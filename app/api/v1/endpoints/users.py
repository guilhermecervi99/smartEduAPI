# app/api/v1/endpoints/users.py
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import FieldFilter
import time

from app.core.security import get_current_user, get_current_user_id_required
from app.database import get_db, Collections
from app.schemas.user import (
    UserProfile,
    UserUpdate,
    PreferencesUpdate,
    UserStatistics,
    UserProgress as UserProgressSchema
)
from app.models.user import UserProgress
from app.utils.gamification import (
    get_next_level_info,
    calculate_study_streak,
    check_achievement_criteria,
    grant_badge,
    add_user_xp,
    XP_REWARDS
)

router = APIRouter()


@router.get("/{user_id}", response_model=UserProfile)
async def get_user_profile(
        user_id: str,
        db=Depends(get_db),
        current_user_id: Optional[str] = Depends(get_current_user_id_required)
) -> Any:
    """
    Obtém o perfil completo de um usuário

    - Apenas o próprio usuário pode ver seu perfil completo
    - Outros usuários verão informações públicas
    """
    # Verificar se é o próprio usuário
    is_own_profile = current_user_id == user_id

    # Buscar usuário
    user_doc = db.collection(Collections.USERS).document(user_id).get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    user_data["id"] = user_id

    # Se não for o próprio perfil, limitar informações
    if not is_own_profile:
        # Retornar apenas informações públicas
        public_data = {
            "id": user_id,
            "profile_level": user_data.get("profile_level", 1),
            "profile_xp": user_data.get("profile_xp", 0),
            "badges": user_data.get("badges", []),
            "current_track": user_data.get("current_track"),
            "completed_lessons_count": len(user_data.get("completed_lessons", [])),
            "completed_modules_count": len(user_data.get("completed_modules", [])),
            "completed_projects_count": len(user_data.get("completed_projects", [])),
            "certifications_count": len(user_data.get("certifications", []))
        }
        return UserProfile(**public_data)

    # Calcular contagens
    user_data["completed_lessons_count"] = len(user_data.get("completed_lessons", []))
    user_data["completed_modules_count"] = len(user_data.get("completed_modules", []))
    user_data["completed_projects_count"] = len(user_data.get("completed_projects", []))
    user_data["certifications_count"] = len(user_data.get("certifications", []))

    # Calcular projetos ativos
    started = user_data.get("started_projects", [])
    completed = user_data.get("completed_projects", [])
    completed_titles = [p.get("title") for p in completed]
    user_data["active_projects_count"] = len([p for p in started if p.get("title") not in completed_titles])

    return UserProfile(**user_data)


@router.put("/{user_id}", response_model=UserProfile)
async def update_user(
        user_id: str,
        user_update: UserUpdate,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Atualiza dados do usuário

    - Apenas o próprio usuário pode atualizar seus dados
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own profile"
        )

    # Buscar usuário
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Preparar dados para atualização
    update_data = user_update.dict(exclude_unset=True)

    # Atualizar no banco
    user_ref.update(update_data)

    # Retornar perfil atualizado
    return await get_user_profile(user_id, db, current_user_id)


@router.get("/{user_id}/statistics", response_model=UserStatistics)
async def get_user_statistics(
        user_id: str,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Obtém estatísticas detalhadas do usuário

    - XP e níveis
    - Conquistas
    - Atividades completadas
    - Streak de estudo
    """
    # Buscar usuário
    user_doc = db.collection(Collections.USERS).document(user_id).get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()

    # Calcular estatísticas
    stats = {
        "profile_level": user_data.get("profile_level", 1),
        "profile_xp": user_data.get("profile_xp", 0),
        "total_badges": len(user_data.get("badges", [])),
        "completed_lessons": len(user_data.get("completed_lessons", [])),
        "completed_modules": len(user_data.get("completed_modules", [])),
        "completed_projects": len(user_data.get("completed_projects", [])),
        "active_projects": 0,
        "certifications": len(user_data.get("certifications", [])),
        "days_active": 0,
        "last_activity": None,
        "strongest_area": None,
        "current_streak": calculate_study_streak(user_data)
    }

    # Calcular projetos ativos
    started = user_data.get("started_projects", [])
    completed = user_data.get("completed_projects", [])
    completed_titles = [p.get("title") for p in completed]
    stats["active_projects"] = len([p for p in started if p.get("title") not in completed_titles])

    # Calcular dias ativos
    if user_data.get("created_at"):
        days_since_creation = (time.time() - user_data["created_at"]) / (24 * 60 * 60)
        stats["days_active"] = int(days_since_creation)

    # Última atividade
    if user_data.get("last_login"):
        stats["last_activity"] = user_data["last_login"]

    # Área mais forte (baseada em pontuações)
    track_scores = user_data.get("track_scores", {})
    if track_scores:
        strongest = max(track_scores.items(), key=lambda x: x[1])
        stats["strongest_area"] = strongest[0]

    # Adicionar XP por visualizar estatísticas
    if current_user_id == user_id:
        add_user_xp(db, user_id, XP_REWARDS.get("view_achievements", 2), "Visualizou estatísticas")

    return UserStatistics(**stats)


@router.get("/{user_id}/progress", response_model=UserProgressSchema)
async def get_user_progress(
        user_id: str,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Obtém o progresso atual detalhado do usuário
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own progress"
        )

    # Buscar usuário
    user_doc = db.collection(Collections.USERS).document(user_id).get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    progress_data = user_data.get("progress", {})

    if not progress_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress found. Complete the interest mapping first."
        )

    # Criar objeto de progresso
    progress = UserProgress(progress_data)
    current = progress_data.get("current", {})

    # Calcular porcentagem de progresso
    # Estimativa simplificada: assumindo 3 módulos por nível, 5 lições por módulo, 4 passos por lição
    total_steps = 3 * 5 * 4  # 60 passos estimados por nível
    current_steps = (
            (current.get("module_index", 0) * 5 * 4) +
            (current.get("lesson_index", 0) * 4) +
            current.get("step_index", 0)
    )
    progress_percentage = min(100, (current_steps / total_steps) * 100)

    return UserProgressSchema(
        area=progress.area,
        subarea=progress.subarea,
        level=progress.level,
        module_index=progress.module_index,
        lesson_index=progress.lesson_index,
        step_index=progress.step_index,
        progress_percentage=progress_percentage
    )


@router.put("/{user_id}/preferences", response_model=UserProfile)
async def update_preferences(
        user_id: str,
        preferences: PreferencesUpdate,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Atualiza preferências de aprendizado do usuário
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own preferences"
        )

    # Buscar usuário
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    update_data = preferences.dict(exclude_unset=True)

    # Se mudando de subárea, atualizar progresso
    if "current_subarea" in update_data and update_data["current_subarea"]:
        progress = user_data.get("progress", {})
        progress["current"] = {
            "subarea": update_data["current_subarea"],
            "level": "iniciante",
            "module_index": 0,
            "lesson_index": 0,
            "step_index": 0
        }
        update_data["progress"] = progress
        del update_data["current_subarea"]

        # Adicionar XP por escolher nova subárea
        add_user_xp(db, user_id, XP_REWARDS.get("select_subarea", 5),
                    f"Selecionou subárea: {update_data['current_subarea']}")

    # Se mudando estilo de ensino
    if "learning_style" in update_data:
        add_user_xp(db, user_id, XP_REWARDS.get("change_teaching_style", 3),
                    f"Mudou estilo de ensino para: {update_data['learning_style']}")

    # Atualizar no banco
    user_ref.update(update_data)

    # Retornar perfil atualizado
    return await get_user_profile(user_id, db, current_user_id)


@router.get("/{user_id}/next-level-info")
async def get_next_level_information(
        user_id: str,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Obtém informações sobre o próximo nível do usuário
    """
    # Buscar usuário
    user_doc = db.collection(Collections.USERS).document(user_id).get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    current_xp = user_data.get("profile_xp", 0)
    current_level = user_data.get("profile_level", 1)

    return get_next_level_info(current_xp, current_level)


@router.post("/{user_id}/check-achievements")
async def check_user_achievements(
        user_id: str,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Verifica e desbloqueia novas conquistas para o usuário
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only check your own achievements"
        )

    # Buscar usuário
    user_doc = db.collection(Collections.USERS).document(user_id).get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()

    # Verificar conquistas
    new_badges = check_achievement_criteria(user_data)

    # Conceder novas badges
    granted_badges = []
    for badge in new_badges:
        if grant_badge(db, user_id, badge):
            granted_badges.append(badge)

    return {
        "new_badges": granted_badges,
        "total_badges": len(user_data.get("badges", [])) + len(granted_badges)
    }


@router.get("/search", response_model=List[UserProfile])
async def search_users(
        q: Optional[str] = Query(None, description="Search query"),
        track: Optional[str] = Query(None, description="Filter by track"),
        min_level: Optional[int] = Query(None, ge=1, description="Minimum level"),
        limit: int = Query(10, ge=1, le=50),
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Busca usuários com filtros

    - Por email (parcial)
    - Por trilha atual
    - Por nível mínimo
    """
    # Iniciar query
    query = db.collection(Collections.USERS)

    # Aplicar filtros
    if track:
        query = query.where(filter=FieldFilter("current_track", "==", track))

    if min_level:
        query = query.where(filter=FieldFilter("profile_level", ">=", min_level))

    # Limitar resultados
    query = query.limit(limit)

    # Executar query
    users = []
    for doc in query.stream():
        user_data = doc.to_dict()
        user_data["id"] = doc.id

        # Filtrar por email se necessário
        if q and user_data.get("email"):
            if q.lower() not in user_data["email"].lower():
                continue

        # Retornar apenas dados públicos
        public_data = {
            "id": doc.id,
            "email": user_data.get("email") if doc.id == current_user_id else None,
            "profile_level": user_data.get("profile_level", 1),
            "profile_xp": user_data.get("profile_xp", 0),
            "badges": user_data.get("badges", []),
            "current_track": user_data.get("current_track"),
            "completed_lessons_count": len(user_data.get("completed_lessons", [])),
            "completed_modules_count": len(user_data.get("completed_modules", [])),
            "completed_projects_count": len(user_data.get("completed_projects", [])),
            "certifications_count": len(user_data.get("certifications", []))
        }
        users.append(UserProfile(**public_data))

    return users


# Adicione estes endpoints ao arquivo app/api/v1/endpoints/users.py

@router.post("/{user_id}/feedback")
async def submit_feedback(
        user_id: str,
        content_type: str,
        rating: int = Query(..., ge=1, le=5),
        comments: str = "",
        session_type: str = "general",
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Coleta feedback do usuário sobre conteúdo ou experiência
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit feedback for yourself"
        )

    from app.utils.feedback_system import collect_user_feedback

    context = {
        "session_type": session_type,
        "timestamp": time.time()
    }

    success = collect_user_feedback(
        db, user_id, content_type, rating, comments, context
    )

    if success:
        # Adicionar XP por fornecer feedback
        add_user_xp(db, user_id, 3, "Forneceu feedback sobre o sistema")

        return {
            "message": "Feedback submitted successfully",
            "xp_earned": 3
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save feedback"
        )


@router.get("/{user_id}/engagement")
async def get_user_engagement(
        user_id: str,
        days: int = Query(30, ge=1, le=365),
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Analisa o engajamento do usuário
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own engagement"
        )

    from app.utils.feedback_system import analyze_user_engagement

    engagement = analyze_user_engagement(db, user_id, days)

    return engagement


@router.get("/{user_id}/personalized-suggestions")
async def get_personalized_suggestions(
        user_id: str,
        db=Depends(get_db),
        current_user_id: str = Depends(get_current_user_id_required)
) -> Any:
    """
    Gera sugestões personalizadas baseadas no perfil do usuário
    """
    # Verificar se é o próprio usuário
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own suggestions"
        )

    from app.utils.feedback_system import generate_personalized_suggestions

    suggestions = generate_personalized_suggestions(db, user_id)

    return {
        "suggestions": suggestions,
        "generated_at": time.time()
    }