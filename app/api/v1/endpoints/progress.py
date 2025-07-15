# app/api/v1/endpoints/progress.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion
import time

from app.core.security import get_current_user, get_current_user_id_required
from app.database import get_db, Collections
from app.schemas.progress import (
    ProgressResponse,
    LessonCompletionRequest,
    ModuleCompletionRequest,
    LevelCompletionRequest,
    ProjectStartRequest,
    ProjectCompletionRequest,
    AssessmentCompletionRequest,
    CertificationRequest,
    ProgressStatistics,
    UserProgressPath,
    NextStepResponse,
    TrackSwitchRequest,
    SpecializationStartRequest,
    InitializeProgressRequest
)
from app.utils.gamification import add_user_xp, grant_badge, XP_REWARDS, calculate_study_streak
from app.utils.llm_integration import generate_complete_lesson, call_teacher_llm
from app.utils.progress_utils import (
    get_user_progress,
    advance_user_progress,
    calculate_progress_percentage,
    get_next_recommendations
)

router = APIRouter()


# Adicionar estas funções auxiliares ao início do arquivo progress.py

def ensure_navigation_context(user_data: dict, db) -> Dict[str, Any]:
    """
    Garante que sempre temos um contexto válido de navegação
    """
    progress = user_data.get("progress", {})

    # Valores padrão
    default_area = "Negócios e Empreendedorismo"
    default_subarea = "Finanças"
    default_level = "iniciante"

    # Extrair valores do progresso
    area = progress.get("area", "")
    current = progress.get("current", {})
    subarea = current.get("subarea", "")
    level = current.get("level", default_level)

    # Garantir que os índices nunca sejam None - SEMPRE começar do 0
    module_index = current.get("module_index", 0)
    lesson_index = current.get("lesson_index", 0)
    step_index = current.get("step_index", 0)

    # Converter None para 0 se necessário
    if module_index is None:
        module_index = 0
    if lesson_index is None:
        lesson_index = 0
    if step_index is None:
        step_index = 0

    # Se não tem área, buscar de outras fontes
    if not area:
        # Tentar current_track
        area = user_data.get("current_track", "")

        # Se ainda não tem, buscar da primeira área com progresso salvo
        if not area and user_data.get("saved_progress"):
            saved_areas = list(user_data.get("saved_progress", {}).keys())
            if saved_areas:
                area = saved_areas[0]
                saved_progress = user_data["saved_progress"][area]
                if "current" in saved_progress:
                    subarea = saved_progress["current"].get("subarea", "")
                    level = saved_progress["current"].get("level", default_level)
                    module_index = saved_progress["current"].get("module_index", 0) or 0
                    lesson_index = saved_progress["current"].get("lesson_index", 0) or 0
                    step_index = saved_progress["current"].get("step_index", 0) or 0

        # Se ainda não tem, usar padrão
        if not area:
            area = default_area

    # Se não tem subárea, buscar da estrutura da área
    if not subarea:
        try:
            area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
            area_doc = area_ref.get()

            if area_doc.exists:
                area_data = area_doc.to_dict()
                subareas = list(area_data.get("subareas", {}).keys())
                if subareas:
                    # Preferir subárea da ordem de progresso se existir
                    subareas_order = progress.get("subareas_order", [])
                    if subareas_order:
                        subarea = subareas_order[0]
                    else:
                        subarea = subareas[0]
        except:
            pass

        # Se ainda não tem, usar padrão
        if not subarea:
            subarea = default_subarea

    return {
        "area": area,
        "subarea": subarea,
        "level": level,
        "module_index": module_index,
        "lesson_index": lesson_index,
        "step_index": step_index
    }

def get_next_available_content(area_data: dict, current_context: dict, db) -> Dict[str, Any]:
    """
    Encontra o próximo conteúdo disponível quando o atual está completo
    """
    area = current_context["area"]
    subarea = current_context["subarea"]
    level = current_context["level"]

    levels_order = ["iniciante", "intermediário", "avançado"]
    subareas = list(area_data.get("subareas", {}).keys())

    # Verificar próximo nível na mesma subárea
    if level in levels_order:
        current_level_idx = levels_order.index(level)
        if current_level_idx < len(levels_order) - 1:
            next_level = levels_order[current_level_idx + 1]
            subarea_data = area_data.get("subareas", {}).get(subarea, {})
            if next_level in subarea_data.get("levels", {}):
                return {
                    "type": "next_level",
                    "area": area,
                    "subarea": subarea,
                    "level": next_level,
                    "module_index": 0,
                    "lesson_index": 0,
                    "step_index": 0
                }

    # Verificar próxima subárea
    if subarea in subareas:
        current_subarea_idx = subareas.index(subarea)
        if current_subarea_idx < len(subareas) - 1:
            next_subarea = subareas[current_subarea_idx + 1]
            return {
                "type": "next_subarea",
                "area": area,
                "subarea": next_subarea,
                "level": "iniciante",
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            }

    # Verificar outras áreas disponíveis
    try:
        areas_ref = db.collection(Collections.LEARNING_PATHS).stream()
        other_areas = []
        for area_doc in areas_ref:
            if area_doc.id != area:
                other_areas.append(area_doc.id)

        if other_areas:
            # Buscar primeira subárea da nova área
            new_area = other_areas[0]
            new_area_ref = db.collection(Collections.LEARNING_PATHS).document(new_area)
            new_area_doc = new_area_ref.get()

            if new_area_doc.exists:
                new_area_data = new_area_doc.to_dict()
                new_subareas = list(new_area_data.get("subareas", {}).keys())
                if new_subareas:
                    return {
                        "type": "new_area",
                        "area": new_area,
                        "subarea": new_subareas[0],
                        "level": "iniciante",
                        "module_index": 0,
                        "lesson_index": 0,
                        "step_index": 0
                    }
    except:
        pass

    # Se não encontrou nada, retornar sugestão de especialização
    return {
        "type": "specialization",
        "area": area,
        "subarea": subarea,
        "message": "Você completou todo o conteúdo básico! Que tal iniciar uma especialização?"
    }


# Substitua a função get_current_progress no arquivo progress.py por esta versão corrigida:

@router.get("/current", response_model=ProgressResponse)
async def get_current_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o progresso atual detalhado do usuário
    SEMPRE retorna campos completos mesmo que sejam valores padrão
    """
    user_id = current_user["id"]

    # CORREÇÃO: Sempre garantir contexto válido
    nav_context = ensure_navigation_context(current_user, db)

    # Buscar progresso do usuário
    progress = get_user_progress(db, user_id)

    # Se não tem progresso ou está incompleto, criar/corrigir
    if not progress or not progress.get("area") or not progress.get("current", {}).get("subarea"):
        # Criar progresso padrão baseado no contexto
        progress = {
            "area": nav_context["area"],
            "current": {
                "subarea": nav_context["subarea"],
                "level": nav_context["level"],
                "module_index": nav_context["module_index"],
                "lesson_index": nav_context["lesson_index"],
                "step_index": nav_context["step_index"]
            },
            "subareas_order": []
        }

        # Salvar progresso padrão
        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({"progress": progress})

    # IMPORTANTE: Garantir que SEMPRE retornamos valores válidos
    return ProgressResponse(
        user_id=user_id,
        area=progress.get("area") or nav_context["area"],
        subarea=progress.get("current", {}).get("subarea") or nav_context["subarea"],
        level=progress.get("current", {}).get("level") or nav_context["level"],
        module_index=progress.get("current", {}).get("module_index", 0),
        lesson_index=progress.get("current", {}).get("lesson_index", 0),
        step_index=progress.get("current", {}).get("step_index", 0),
        progress_percentage=calculate_progress_percentage(db, user_id, progress) or 0.0,
        subareas_order=progress.get("subareas_order", []),
        last_updated=time.time()
    )
@router.post("/lesson/complete")
async def complete_lesson(
        request: LessonCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de uma lição com validação anti-duplicata
    """
    user_id = current_user["id"]

    # Criar ID único para a lição
    lesson_id = f"{request.area_name}_{request.subarea_name}_{request.level_name}_{request.module_title}_{request.lesson_title}"

    # Verificar se já foi completada
    completed_lessons = current_user.get("completed_lessons", [])
    if any(lesson.get("lesson_id") == lesson_id for lesson in completed_lessons):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta lição já foi completada anteriormente"
        )

    # Registrar conclusão
    lesson_data = {
        "lesson_id": lesson_id,
        "title": request.lesson_title,
        "completion_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "area": request.area_name or "",
        "subarea": request.subarea_name or "",
        "level": request.level_name or "",
        "module": request.module_title or ""
    }

    # Adicionar à lista de lições completadas
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_lessons": ArrayUnion([lesson_data])
    })

    # Adicionar XP
    xp_earned = add_user_xp(db, user_id, XP_REWARDS.get("complete_lesson", 10),
                            f"Completou lição: {request.lesson_title}")

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "lesson")

    return {
        "message": "Lesson completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/module/complete")
async def complete_module(
        request: ModuleCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de um módulo com validação anti-duplicata
    """
    user_id = current_user["id"]

    # Criar ID único para o módulo
    module_id = f"{request.area_name}_{request.subarea_name}_{request.level_name}_{request.module_title}"

    # Verificar se já foi completado
    completed_modules = current_user.get("completed_modules", [])
    if any(module.get("module_id") == module_id for module in completed_modules):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este módulo já foi completado anteriormente"
        )

    # Registrar conclusão
    module_data = {
        "module_id": module_id,
        "title": request.module_title,
        "completion_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "area": request.area_name or "",
        "subarea": request.subarea_name or "",
        "level": request.level_name or ""
    }

    # Adicionar à lista de módulos completados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_modules": ArrayUnion([module_data])
    })

    # Adicionar XP e badge
    xp_earned = add_user_xp(db, user_id, XP_REWARDS.get("complete_module", 15),
                            f"Completou módulo: {request.module_title}")

    badge_granted = grant_badge(db, user_id, f"Módulo: {request.module_title[:20]}")

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "module")

    return {
        "message": "Module completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Módulo: {request.module_title[:20]}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/level/complete")
async def complete_level(
        request: LevelCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de um nível
    """
    user_id = current_user["id"]

    # Registrar conclusão
    level_data = {
        "area": request.area_name,
        "subarea": request.subarea_name,
        "level": request.level_name,
        "completion_date": time.strftime("%Y-%m-%d")
    }

    # Adicionar à lista de níveis completados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_levels": ArrayUnion([level_data])
    })

    # Calcular XP baseado no nível
    xp_amount = 30
    if request.level_name in ["avançado", "avancado"]:
        xp_amount = 50
    elif request.level_name in ["intermediário", "intermediario"]:
        xp_amount = 40

    # Adicionar XP e badge
    xp_earned = add_user_xp(db, user_id, xp_amount,
                            f"Completou nível {request.level_name} em {request.subarea_name}")

    badge_granted = grant_badge(db, user_id,
                                f"Nível {request.level_name.capitalize()}: {request.subarea_name}")

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "level")

    return {
        "message": "Level completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Nível {request.level_name.capitalize()}: {request.subarea_name}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/project/start")
async def start_project(
        request: ProjectStartRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra o início de um projeto
    """
    user_id = current_user["id"]

    # Estrutura do projeto iniciado
    project_data = {
        "title": request.title,
        "type": request.project_type,
        "start_date": time.strftime("%Y-%m-%d"),
        "status": "in_progress",
        "description": request.description or ""
    }

    # Adicionar à lista de projetos iniciados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "started_projects": ArrayUnion([project_data])
    })

    # Adicionar XP por iniciar projeto
    xp_amount = XP_REWARDS.get("start_project", 10)
    if request.project_type == "final":
        xp_amount = 15

    xp_earned = add_user_xp(db, user_id, xp_amount, f"Iniciou projeto: {request.title}")

    return {
        "message": "Project started successfully",
        "project_id": f"{user_id}_{int(time.time())}",
        "xp_earned": xp_earned["xp_added"]
    }


@router.post("/project/complete")
async def complete_project(
        request: ProjectCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de um projeto com lógica corrigida de atualização
    """
    user_id = current_user["id"]
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    started_projects = user_data.get("started_projects", [])

    # Verificar se o projeto foi iniciado
    project_found = False
    for project in started_projects:
        if project["title"] == request.title and project["type"] == request.project_type:
            project_found = True
            break

    if not project_found:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Projeto não foi encontrado na lista de projetos iniciados"
        )

    # Filtrar projetos iniciados para remover o que foi completado
    updated_started_projects = [
        p for p in started_projects
        if not (p["title"] == request.title and p["type"] == request.project_type)
    ]

    # Estrutura do projeto concluído
    completed_project = {
        "title": request.title,
        "type": request.project_type,
        "start_date": next((p["start_date"] for p in started_projects
                            if p["title"] == request.title and p["type"] == request.project_type),
                           time.strftime("%Y-%m-%d")),
        "completion_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "description": request.description or ""
    }

    if request.outcomes:
        completed_project["outcomes"] = request.outcomes

    if request.evidence_urls:
        completed_project["evidence_urls"] = request.evidence_urls

    # Atualizar no banco
    user_ref.update({
        "started_projects": updated_started_projects,
        "completed_projects": ArrayUnion([completed_project])
    })

    # Adicionar XP e possível badge
    xp_amount = XP_REWARDS.get("complete_project", 25)
    if request.project_type == "final":
        xp_amount = XP_REWARDS.get("complete_final_project", 50)
        grant_badge(db, user_id, f"Projeto Final: {request.title[:20]}")

    xp_earned = add_user_xp(db, user_id, xp_amount, f"Completou projeto: {request.title}")

    return {
        "message": "Project completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/assessment/complete")
async def complete_assessment(
        request: AssessmentCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de uma avaliação
    """
    user_id = current_user["id"]

    # Validar score
    if not 0 <= request.score <= 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score deve estar entre 0 e 100"
        )

    # Determinar se passou (70% ou mais)
    passed = request.score >= 70

    # Registrar avaliação
    assessment_data = {
        "assessment_id": request.assessment_id,
        "module": request.module_title or request.level_name,
        "score": request.score,
        "passed": passed,
        "date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "type": request.assessment_type,
        "time_taken_minutes": request.time_taken_minutes,
        "questions_correct": request.questions_correct,
        "total_questions": request.total_questions
    }

    # Adicionar contexto se fornecido
    if request.area_name:
        assessment_data["area"] = request.area_name
    if request.subarea_name:
        assessment_data["subarea"] = request.subarea_name

    # Determinar coleção baseada no tipo
    if request.assessment_type == "final":
        collection_key = "passed_final_assessments" if passed else "failed_final_assessments"
    else:
        collection_key = "passed_assessments" if passed else "failed_assessments"

    # Atualizar no banco
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        collection_key: ArrayUnion([assessment_data])
    })

    # Calcular XP baseado na pontuação
    if passed:
        base_xp = XP_REWARDS.get("pass_final_assessment", 20) if request.assessment_type == "final" else XP_REWARDS.get(
            "pass_assessment", 10)
        bonus_xp = int((request.score - 70) / 10) * 2  # 2 XP extra para cada 10% acima de 70
        total_xp = base_xp + bonus_xp
    else:
        # Mesmo falhando, ganha XP por tentar
        total_xp = 5

    xp_result = add_user_xp(
        db, user_id, total_xp,
        f"{'Passou' if passed else 'Tentou'} avaliação com {request.score}%"
    )

    # Badge para avaliação final com score alto
    badge_earned = None
    if passed:
        if request.assessment_type == "final" and request.score >= 90:
            badge_name = f"Mestre em {request.level_name or 'Avaliação'}"
            if grant_badge(db, user_id, badge_name):
                badge_earned = badge_name
        elif request.score == 100:
            badge_name = "Perfeição"
            if grant_badge(db, user_id, badge_name):
                badge_earned = badge_name

    return {
        "message": "Avaliação registrada com sucesso",
        "passed": passed,
        "score": request.score,
        "xp_earned": xp_result["xp_added"],
        "badge_earned": badge_earned,
        "new_level": xp_result["new_level"] if xp_result["level_up"] else None,
        "feedback": get_assessment_feedback(request.score, passed)
    }


@router.post("/certification/award")
async def award_certification(
        request: CertificationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Emite uma certificação para o usuário
    """
    user_id = current_user["id"]

    cert_data = {
        "title": request.title,
        "date": time.strftime("%Y-%m-%d"),
        "id": f"CERT-{int(time.time())}",
        "area": request.area_name or "",
        "subarea": request.subarea_name or ""
    }

    # Adicionar certificação
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "certifications": ArrayUnion([cert_data])
    })

    # Adicionar XP e badge
    xp_earned = add_user_xp(db, user_id, XP_REWARDS.get("get_certification", 75),
                            f"Certificação: {request.title}")

    badge_granted = grant_badge(db, user_id, f"Certificado: {request.title[:20]}")

    return {
        "message": "Certification awarded successfully",
        "certification_id": cert_data["id"],
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Certificado: {request.title[:20]}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.get("/statistics", response_model=ProgressStatistics)
async def get_progress_statistics(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém estatísticas detalhadas de progresso do usuário
    """
    user_id = current_user["id"]

    # Calcular estatísticas
    completed_lessons = len(current_user.get("completed_lessons", []))
    completed_modules = len(current_user.get("completed_modules", []))
    completed_levels = len(current_user.get("completed_levels", []))
    completed_projects = len(current_user.get("completed_projects", []))
    certifications = len(current_user.get("certifications", []))

    # Projetos ativos
    started_projects = current_user.get("started_projects", [])
    completed_project_titles = [p.get("title") for p in current_user.get("completed_projects", [])]
    active_projects = len([p for p in started_projects if p.get("title") not in completed_project_titles])

    # Streak de estudo (simplificado)
    current_streak = 0
    last_activity = current_user.get("last_login", 0)
    if last_activity and (time.time() - last_activity) < 48 * 60 * 60:  # 48 horas
        current_streak = current_user.get("study_streak", 0) + 1

    # Área mais forte
    strongest_area = None
    track_scores = current_user.get("track_scores", {})
    if track_scores:
        strongest_area = max(track_scores.items(), key=lambda x: x[1])[0]

    # Tempo total estudado (estimativa baseada em atividades)
    total_study_time = (completed_lessons * 30) + (completed_modules * 60) + (completed_projects * 120)  # em minutos

    return ProgressStatistics(
        completed_lessons=completed_lessons,
        completed_modules=completed_modules,
        completed_levels=completed_levels,
        completed_projects=completed_projects,
        active_projects=active_projects,
        certifications=certifications,
        current_streak=current_streak,
        total_study_time_minutes=total_study_time,
        strongest_area=strongest_area,
        last_activity=last_activity
    )


@router.get("/path", response_model=UserProgressPath)
async def get_user_progress_path(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o caminho completo de progresso do usuário
    """
    user_id = current_user["id"]
    progress = get_user_progress(db, user_id)

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress path found"
        )

    # Buscar dados da área atual
    area_name = progress.get("area", "")
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
    area_doc = area_ref.get()

    available_subareas = []
    if area_doc.exists:
        area_data = area_doc.to_dict()
        available_subareas = list(area_data.get("subareas", {}).keys())

    current = progress.get("current", {})

    return UserProgressPath(
        area=area_name,
        available_subareas=available_subareas,
        current_subarea=current.get("subarea", ""),
        current_level=current.get("level", "iniciante"),
        subareas_order=progress.get("subareas_order", []),
        progress_percentage=calculate_progress_percentage(db, user_id, progress)
    )


@router.get("/next-steps", response_model=NextStepResponse)
async def get_next_steps(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém sugestões de próximos passos para o usuário
    """
    user_id = current_user["id"]
    recommendations = get_next_recommendations(db, user_id, current_user)

    return NextStepResponse(
        user_id=user_id,
        recommendations=recommendations,
        generated_at=time.time()
    )


@router.post("/navigate/previous")
async def navigate_previous(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Navega para o conteúdo anterior (passo, lição ou módulo)
    """
    user_id = current_user["id"]
    progress = current_user.get("progress", {})

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum progresso encontrado"
        )

    area = progress.get("area", "")
    current = progress.get("current", {})
    current_module_idx = current.get("module_index", 0)
    current_lesson_idx = current.get("lesson_index", 0)
    current_step_idx = current.get("step_index", 0)

    # Buscar estrutura do curso
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trilha de aprendizado não encontrada"
        )

    area_data = area_doc.to_dict()

    try:
        subarea = current.get("subarea", "")
        level = current.get("level", "iniciante")

        subarea_data = area_data["subareas"][subarea]
        level_data = subarea_data["levels"][level]
        modules = level_data["modules"]

        # Determinar posição anterior
        new_module_idx = current_module_idx
        new_lesson_idx = current_lesson_idx
        new_step_idx = current_step_idx - 1

        # Se for o primeiro passo, voltar para lição anterior
        if new_step_idx < 0:
            new_lesson_idx -= 1

            # Se for a primeira lição, voltar para módulo anterior
            if new_lesson_idx < 0:
                new_module_idx -= 1

                # Se for o primeiro módulo, não pode voltar mais
                if new_module_idx < 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Já está no início do curso"
                    )

                # Definir última lição do módulo anterior
                prev_module = modules[new_module_idx]
                new_lesson_idx = len(prev_module.get("lessons", [])) - 1

            # Definir último passo da lição
            module = modules[new_module_idx]
            lesson = module["lessons"][new_lesson_idx]
            steps = lesson.get("steps", [])
            new_step_idx = len(steps) - 1 if steps else 0

        # Atualizar progresso
        updated_progress = {
            "area": area,
            "subareas_order": progress.get("subareas_order", []),
            "current": {
                "subarea": subarea,
                "level": level,
                "module_index": new_module_idx,
                "lesson_index": new_lesson_idx,
                "step_index": new_step_idx
            }
        }

        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({"progress": updated_progress})

        return {
            "message": "Navegação atualizada com sucesso",
            "current_position": updated_progress["current"]
        }

    except (KeyError, IndexError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao navegar: {str(e)}"
        )


@router.post("/advance")
async def advance_progress(
        step_type: str = Query(..., description="Type of step to advance: lesson, module, level"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Avança o progresso do usuário para o próximo passo
    """
    user_id = current_user["id"]

    if step_type not in ["lesson", "module", "level"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid step type. Must be: lesson, module, or level"
        )

    result = advance_user_progress(db, user_id, step_type)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to advance progress"
        )

    return {
        "message": f"Progress advanced to next {step_type}",
        "current_progress": result
    }


@router.post("/switch-track")
async def switch_learning_track(
        payload: TrackSwitchRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Troca a trilha de aprendizado ativa do usuário

    - Preserva o progresso da trilha anterior
    - Restaura progresso se já estudou a nova trilha antes
    """
    user_id = current_user["id"]
    new_track = payload.new_track
    old_track = current_user.get("current_track", "")

    if old_track == new_track:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already in this track"
        )

    # Verificar se a nova trilha existe
    track_ref = db.collection(Collections.LEARNING_PATHS).document(new_track)
    track_doc = track_ref.get()

    if not track_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    # Salvar progresso atual
    saved_progress = current_user.get("saved_progress", {})
    if old_track and "progress" in current_user:
        saved_progress[old_track] = current_user["progress"]

    # Restaurar ou criar novo progresso
    if new_track in saved_progress:
        new_progress = saved_progress[new_track]
    else:
        # Criar novo progresso
        track_data = track_doc.to_dict()
        subareas = list(track_data.get("subareas", {}).keys())

        new_progress = {
            "area": new_track,
            "subareas_order": subareas,
            "current": {
                "subarea": subareas[0] if subareas else "",
                "level": "iniciante",
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            }
        }

    # Atualizar usuário
    updates = {
        "current_track": new_track,
        "progress": new_progress,
        "saved_progress": saved_progress
    }

    db.collection(Collections.USERS).document(user_id).update(updates)

    # Adicionar XP
    add_user_xp(db, user_id, 5, f"Mudou para trilha: {new_track}")

    return {
        "message": "Track switched successfully",
        "old_track": old_track,
        "new_track": new_track,
        "progress_restored": new_track in saved_progress
    }

@router.post("/specialization/start")
async def start_specialization(
        request: SpecializationStartRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Inicia uma especialização
    """
    user_id = current_user["id"]

    # Verificar se a especialização existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(request.area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{request.area}' não encontrada"
        )

    area_data = area_doc.to_dict()
    subareas = area_data.get("subareas", {})

    if request.subarea not in subareas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subárea '{request.subarea}' não encontrada"
        )

    subarea_data = subareas[request.subarea]
    specializations = subarea_data.get("specializations", [])

    # Encontrar a especialização
    spec_found = None
    for spec in specializations:
        if spec.get("name") == request.specialization_name:
            spec_found = spec
            break

    if not spec_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Especialização '{request.specialization_name}' não encontrada"
        )

    # Verificar pré-requisitos
    prerequisites = spec_found.get("prerequisites", [])
    if prerequisites and request.force_start is False:
        completed_levels = current_user.get("completed_levels", [])
        completed_level_names = [
            f"{l.get('level', '')} em {l.get('subarea', '')}"
            for l in completed_levels
        ]

        missing_prereqs = [p for p in prerequisites if p not in completed_level_names]
        if missing_prereqs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pré-requisitos faltando: {', '.join(missing_prereqs)}"
            )

    # Verificar se já foi iniciada
    specializations_started = current_user.get("specializations_started", [])
    already_started = any(
        s.get("name") == request.specialization_name
        for s in specializations_started
    )

    if already_started:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Especialização já foi iniciada"
        )

    # Criar registro de especialização
    spec_record = {
        "name": request.specialization_name,
        "area": request.area,
        "subarea": request.subarea,
        "start_date": time.strftime("%Y-%m-%d"),
        "estimated_duration": spec_found.get("estimated_time", ""),
        "modules_total": len(spec_found.get("modules", [])),
        "modules_completed": 0,
        "current_module_index": 0,
        "status": "in_progress"
    }

    # Adicionar ao banco
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "specializations_started": ArrayUnion([spec_record])
    })

    # Adicionar XP e badge
    xp_result = add_user_xp(
        db, user_id,
        XP_REWARDS.get("start_specialization", 20),
        f"Iniciou especialização: {request.specialization_name}"
    )

    badge_name = f"Iniciou: {request.specialization_name}"
    badge_earned = grant_badge(db, user_id, badge_name)

    return {
        "message": "Especialização iniciada com sucesso",
        "specialization": spec_record,
        "total_modules": len(spec_found.get("modules", [])),
        "learning_outcomes": spec_found.get("learning_outcomes", []),
        "xp_earned": xp_result["xp_added"],
        "badge_earned": badge_name if badge_earned else None
    }


@router.post("/specialization/complete")
async def register_specialization_completion(
        spec_name: str,
        area_name: str,
        subarea_name: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de uma especialização
    """
    user_id = current_user["id"]

    spec_data = {
        "name": spec_name,
        "area": area_name,
        "subarea": subarea_name,
        "completion_date": time.strftime("%Y-%m-%d")
    }

    # Adicionar à lista de especializações completadas
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_specializations": ArrayUnion([spec_data])
    })

    # Adicionar XP e badges
    xp_result = add_user_xp(db, user_id, 100, f"Completou especialização: {spec_name}")
    grant_badge(db, user_id, f"Especialista Master em {spec_name}")

    # Emitir certificação
    cert_data = {
        "title": f"Especialização em {spec_name}",
        "date": time.strftime("%Y-%m-%d"),
        "id": f"CERT-SPEC-{int(time.time())}",
        "area": area_name,
        "subarea": subarea_name
    }

    user_ref.update({
        "certifications": ArrayUnion([cert_data])
    })

    return {
        "message": "Specialization completed successfully",
        "xp_earned": xp_result["xp_added"],
        "badge_earned": f"Especialista Master em {spec_name}",
        "certification_id": cert_data["id"],
        "new_level": xp_result["new_level"] if xp_result["level_up"] else None
    }


@router.post("/navigate-to")
async def navigate_to_content(
        request: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Navega diretamente para um conteúdo específico
    """
    user_id = current_user["id"]
    user_ref = db.collection(Collections.USERS).document(user_id)

    # Extrair parâmetros do request body
    area = request.get("area")
    subarea = request.get("subarea")
    level = request.get("level")
    specialization = request.get("specialization")
    module_index = request.get("module_index", 0)
    lesson_index = request.get("lesson_index", 0)
    step_index = request.get("step_index", 0)

    # Validar campos obrigatórios
    if not all([area, subarea, level, module_index is not None]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campos obrigatórios: area, subarea, level, module_index"
        )

    # Verificar se o conteúdo existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{area}' não encontrada"
        )

    area_data = area_doc.to_dict()

    # Validar caminho completo
    try:
        subarea_data = area_data["subareas"][subarea]

        if level == "especialização" and specialization:
            # Lógica para especialização...
            pass
        else:
            # IMPORTANTE: Verificar se o nível existe exatamente como está
            if level not in subarea_data.get("levels", {}):
                # Tentar encontrar o nível independente de acentuação
                available_levels = list(subarea_data.get("levels", {}).keys())

                # Procurar match case-insensitive
                level_found = None
                for available_level in available_levels:
                    if available_level.lower() == level.lower():
                        level_found = available_level
                        break

                if not level_found:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Nível '{level}' não encontrado. Níveis disponíveis: {available_levels}"
                    )

                # Usar o nível encontrado
                level = level_found

            level_data = subarea_data["levels"][level]
            modules = level_data.get("modules", [])

            if module_index >= len(modules):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Índice de módulo inválido: {module_index}"
                )

    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho inválido: {str(e)}"
        )

    # Buscar progresso atual
    current_progress = current_user.get("progress", {})

    # Preservar progresso anterior se mudando de área
    if current_progress.get("area") != area and current_progress.get("area"):
        saved_progress = current_user.get("saved_progress", {})
        saved_progress[current_progress["area"]] = current_progress.copy()
        user_ref.update({"saved_progress": saved_progress})

    # Criar estrutura de progresso atualizada
    updated_progress = {
        "area": area,
        "subareas_order": current_progress.get("subareas_order", list(area_data.get("subareas", {}).keys())),
        "current": {
            "subarea": subarea,
            "level": level,
            "module_index": module_index,
            "lesson_index": lesson_index,
            "step_index": step_index
        }
    }

    # Atualizar no banco
    user_ref.update({
        "progress": updated_progress,
        "current_track": area
    })

    # Adicionar XP por navegação
    add_user_xp(db, user_id, 2, f"Navegou para: {level} - Módulo {module_index + 1}")

    return {
        "message": "Navegação atualizada com sucesso",
        "current_position": updated_progress["current"]
    }
@router.get("/today")
async def get_today_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o progresso do usuário hoje
    """
    user_id = current_user["id"]
    today = time.strftime("%Y-%m-%d")

    # Contar lições completadas hoje
    completed_lessons = current_user.get("completed_lessons", [])
    lessons_today = len([l for l in completed_lessons if l.get("completion_date") == today])

    # Contar módulos completados hoje
    completed_modules = current_user.get("completed_modules", [])
    modules_today = len([m for m in completed_modules if m.get("completion_date") == today])

    # Contar projetos iniciados/completados hoje
    started_projects = current_user.get("started_projects", [])
    completed_projects = current_user.get("completed_projects", [])

    projects_started_today = len([p for p in started_projects if p.get("start_date") == today])
    projects_completed_today = len([p for p in completed_projects if p.get("completion_date") == today])

    # Buscar XP ganho hoje
    xp_history = current_user.get("xp_history", [])
    today_timestamp = time.mktime(time.strptime(today, "%Y-%m-%d"))
    tomorrow_timestamp = today_timestamp + (24 * 60 * 60)

    xp_today = sum(
        entry.get("amount", 0)
        for entry in xp_history
        if today_timestamp <= entry.get("timestamp", 0) < tomorrow_timestamp
    )

    # Estimar tempo de estudo (30 min por lição, 60 min por módulo, 45 min por projeto)
    study_time = (lessons_today * 30) + (modules_today * 60) + (projects_started_today * 45)

    return {
        "date": today,
        "lessons_completed": lessons_today,
        "modules_completed": modules_today,
        "projects_started": projects_started_today,
        "projects_completed": projects_completed_today,
        "xp_earned": xp_today,
        "study_time_minutes": study_time,
        "is_active": lessons_today > 0 or modules_today > 0,
        "daily_goal_progress": {
            "lessons": min(100, (lessons_today / 2) * 100),  # Meta: 2 lições/dia
            "xp": min(100, (xp_today / 50) * 100)  # Meta: 50 XP/dia
        }
    }


@router.get("/weekly")
async def get_weekly_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o progresso semanal do usuário
    """
    user_id = current_user["id"]

    # Calcular datas da semana
    today = time.time()
    week_start = today - (6 * 24 * 60 * 60)  # 6 dias atrás

    # Dados para os últimos 7 dias
    daily_data = []

    for days_ago in range(6, -1, -1):  # De 6 dias atrás até hoje
        day_timestamp = today - (days_ago * 24 * 60 * 60)
        day_date = time.strftime("%Y-%m-%d", time.localtime(day_timestamp))

        # Contar atividades do dia
        completed_lessons = current_user.get("completed_lessons", [])
        completed_modules = current_user.get("completed_modules", [])

        lessons_count = len([l for l in completed_lessons if l.get("completion_date") == day_date])
        modules_count = len([m for m in completed_modules if m.get("completion_date") == day_date])

        # XP do dia
        xp_history = current_user.get("xp_history", [])
        day_start = time.mktime(time.strptime(day_date, "%Y-%m-%d"))
        day_end = day_start + (24 * 60 * 60)

        xp_earned = sum(
            entry.get("amount", 0)
            for entry in xp_history
            if day_start <= entry.get("timestamp", 0) < day_end
        )

        daily_data.append({
            "date": day_date,
            "day_name": time.strftime("%A", time.localtime(day_timestamp)),
            "lessons": lessons_count,
            "modules": modules_count,
            "xp": xp_earned,
            "was_active": lessons_count > 0 or modules_count > 0
        })

    # Calcular totais e médias
    total_lessons = sum(d["lessons"] for d in daily_data)
    total_modules = sum(d["modules"] for d in daily_data)
    total_xp = sum(d["xp"] for d in daily_data)
    active_days = sum(1 for d in daily_data if d["was_active"])

    # Meta semanal
    weekly_target = 10  # 10 lições por semana

    # Calcular streak atual
    current_streak = calculate_study_streak(current_user)

    return {
        "period_start": time.strftime("%Y-%m-%d", time.localtime(week_start)),
        "period_end": time.strftime("%Y-%m-%d", time.localtime(today)),
        "daily_progress": daily_data,
        "totals": {
            "lessons": total_lessons,
            "modules": total_modules,
            "xp": total_xp,
            "active_days": active_days
        },
        "averages": {
            "lessons_per_day": round(total_lessons / 7, 1),
            "xp_per_day": round(total_xp / 7, 1)
        },
        "target": weekly_target,
        "target_progress": min(100, (total_lessons / weekly_target) * 100),
        "current_streak": current_streak,
        "best_day": max(daily_data, key=lambda d: d["xp"])["date"] if daily_data else None
    }


@router.get("/area-subarea")
async def get_progress_for_area_subarea(
        area: str = Query(...),
        subarea: str = Query(...),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém progresso específico para uma combinação área/subárea
    """
    user_id = current_user["id"]

    # Buscar progresso salvo
    saved_progress = current_user.get("saved_progress", {})

    # Verificar se há progresso salvo para esta área
    if area in saved_progress:
        area_progress = saved_progress[area]
        current = area_progress.get("current", {})

        # Verificar se é a subárea correta
        if current.get("subarea") == subarea:
            # Calcular estatísticas
            completed_lessons = current_user.get("completed_lessons", [])
            area_subarea_lessons = [
                l for l in completed_lessons
                if l.get("area") == area and l.get("subarea") == subarea
            ]

            completed_modules = current_user.get("completed_modules", [])
            area_subarea_modules = [
                m for m in completed_modules
                if m.get("area") == area and m.get("subarea") == subarea
            ]

            return {
                "has_progress": True,
                "area": area,
                "subarea": subarea,
                "level": current.get("level", "iniciante"),
                "module_index": current.get("module_index", 0),
                "lesson_index": current.get("lesson_index", 0),
                "step_index": current.get("step_index", 0),
                "completed_lessons": len(area_subarea_lessons),
                "completed_modules": len(area_subarea_modules),
                "last_activity": get_last_activity_for_subarea(current_user, area, subarea)
            }

    # Verificar se é o progresso atual
    current_progress = current_user.get("progress", {})
    if (current_progress.get("area") == area and
            current_progress.get("current", {}).get("subarea") == subarea):
        current = current_progress.get("current", {})
        completed_lessons = current_user.get("completed_lessons", [])
        area_subarea_lessons = [
            l for l in completed_lessons
            if l.get("area") == area and l.get("subarea") == subarea
        ]

        completed_modules = current_user.get("completed_modules", [])
        area_subarea_modules = [
            m for m in completed_modules
            if m.get("area") == area and m.get("subarea") == subarea
        ]

        return {
            "has_progress": True,
            "area": area,
            "subarea": subarea,
            "level": current.get("level", "iniciante"),
            "module_index": current.get("module_index", 0),
            "lesson_index": current.get("lesson_index", 0),
            "step_index": current.get("step_index", 0),
            "completed_lessons": len(area_subarea_lessons),
            "completed_modules": len(area_subarea_modules),
            "last_activity": get_last_activity_for_subarea(current_user, area, subarea),
            "is_current": True
        }

    # Não há progresso para esta combinação
    return {
        "has_progress": False,
        "area": area,
        "subarea": subarea,
        "message": "Nenhum progresso encontrado para esta área/subárea"
    }


@router.post("/initialize")
async def initialize_progress(
        request: InitializeProgressRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Inicializa progresso para uma nova área/subárea
    """
    user_id = current_user["id"]

    # Validar que a área/subárea existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(request.area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{request.area}' não encontrada"
        )

    area_data = area_doc.to_dict()
    subareas = area_data.get("subareas", {})

    if request.subarea not in subareas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subárea '{request.subarea}' não encontrada"
        )

    # Verificar se já existe progresso
    current_progress = current_user.get("progress", {})
    saved_progress = current_user.get("saved_progress", {})

    # Se já é a área/subárea atual
    if (current_progress.get("area") == request.area and
            current_progress.get("current", {}).get("subarea") == request.subarea):
        return {
            "message": "Progresso já existe para esta área/subárea",
            "already_current": True,
            "progress": current_progress
        }

    # Se já existe em progresso salvo
    if request.area in saved_progress:
        area_progress = saved_progress[request.area]
        if area_progress.get("current", {}).get("subarea") == request.subarea:
            return {
                "message": "Progresso já existe para esta área/subárea (salvo)",
                "already_saved": True,
                "progress": area_progress
            }

    # Criar novo progresso
    new_progress = {
        "area": request.area,
        "subareas_order": list(subareas.keys()),
        "current": {
            "subarea": request.subarea,
            "level": request.level,
            "module_index": request.module_index,
            "lesson_index": request.lesson_index,
            "step_index": request.step_index
        },
        "initialized_at": time.time()
    }

    # Se quiser tornar esta a área atual
    if request.set_as_current:
        # Salvar progresso atual se existir
        if current_progress and current_progress.get("area"):
            saved_progress[current_progress["area"]] = current_progress

        # Atualizar progresso atual
        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({
            "progress": new_progress,
            "current_track": request.area,
            "saved_progress": saved_progress
        })

        # Adicionar XP
        add_user_xp(db, user_id, 5, f"Iniciou estudos em: {request.subarea}")

        return {
            "message": "Progresso inicializado e definido como atual",
            "progress": new_progress,
            "set_as_current": True
        }
    else:
        # Apenas salvar para uso futuro
        saved_progress[request.area] = new_progress

        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({
            "saved_progress": saved_progress
        })

        return {
            "message": "Progresso inicializado e salvo",
            "progress": new_progress,
            "set_as_current": False
        }


# Funções auxiliares

def get_assessment_feedback(score: float, passed: bool) -> str:
    """Gera feedback baseado na pontuação da avaliação"""
    if score == 100:
        return "Perfeito! Você demonstrou domínio completo do conteúdo!"
    elif score >= 90:
        return "Excelente! Você tem um ótimo entendimento do material."
    elif score >= 80:
        return "Muito bom! Continue assim!"
    elif score >= 70:
        return "Bom trabalho! Você passou, mas ainda há espaço para melhorar."
    elif score >= 60:
        return "Quase lá! Revise o conteúdo e tente novamente."
    elif score >= 50:
        return "Você está no caminho certo. Continue estudando!"
    else:
        return "Não desista! Revise o material e tente novamente quando estiver pronto."


def get_last_activity_for_subarea(user_data: dict, area: str, subarea: str) -> Optional[float]:
    """Obtém timestamp da última atividade em uma subárea específica"""
    last_activity = None

    # Verificar lições
    for lesson in user_data.get("completed_lessons", []):
        if lesson.get("area") == area and lesson.get("subarea") == subarea:
            lesson_date = lesson.get("completion_date")
            if lesson_date:
                try:
                    timestamp = time.mktime(time.strptime(lesson_date, "%Y-%m-%d"))
                    if not last_activity or timestamp > last_activity:
                        last_activity = timestamp
                except:
                    pass

    # Verificar módulos
    for module in user_data.get("completed_modules", []):
        if module.get("area") == area and module.get("subarea") == subarea:
            module_date = module.get("completion_date")
            if module_date:
                try:
                    timestamp = time.mktime(time.strptime(module_date, "%Y-%m-%d"))
                    if not last_activity or timestamp > last_activity:
                        last_activity = timestamp
                except:
                    pass

    return last_activity


@router.get("/current-content")
async def get_current_content(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o conteúdo atual baseado no progresso do usuário
    SEMPRE retorna contexto completo de navegação
    """
    user_id = current_user["id"]

    # Garantir contexto válido
    nav_context = ensure_navigation_context(current_user, db)
    area = nav_context["area"]
    subarea = nav_context["subarea"]
    level = nav_context["level"]
    module_idx = nav_context["module_index"]
    lesson_idx = nav_context["lesson_index"]
    step_idx = nav_context["step_index"]

    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        # Mesmo sem área, retornar contexto válido
        return {
            "content_type": "no_content",
            "message": "Área de aprendizado não encontrada",
            "current_area": area,
            "current_subarea": subarea,
            "current_level": level,
            "navigation_context": {
                "area": area,
                "subarea": subarea,
                "level": level,
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            },
            "suggestions": {
                "explore_areas": True,
                "available_areas_url": "/api/v1/content/areas"
            }
        }

    area_data = area_doc.to_dict()

    try:
        # Verificar se subárea existe
        if subarea not in area_data.get("subareas", {}):
            # Pegar primeira subárea disponível
            available_subareas = list(area_data.get("subareas", {}).keys())
            if available_subareas:
                subarea = available_subareas[0]
            else:
                return {
                    "content_type": "no_subareas",
                    "message": "Nenhuma subárea disponível nesta área",
                    "current_area": area,
                    "current_subarea": subarea,
                    "current_level": level,
                    "navigation_context": nav_context
                }

        subarea_data = area_data["subareas"][subarea]

        # Verificar se nível existe
        if level not in subarea_data.get("levels", {}):
            available_levels = list(subarea_data.get("levels", {}).keys())
            if available_levels:
                level = available_levels[0]
            else:
                return {
                    "content_type": "no_levels",
                    "message": "Nenhum nível disponível nesta subárea",
                    "current_area": area,
                    "current_subarea": subarea,
                    "current_level": level,
                    "navigation_context": nav_context
                }

        level_data = subarea_data["levels"][level]
        modules = level_data.get("modules", [])

        # Se não há módulos
        if not modules:
            return {
                "content_type": "no_modules",
                "message": "Nenhum módulo disponível neste nível",
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": nav_context,
                "next_content": get_next_available_content(area_data, nav_context, db)
            }

        # Verificar se ultrapassou todos os módulos
        if module_idx >= len(modules):
            next_content = get_next_available_content(area_data, nav_context, db)

            return {
                "content_type": "level_completed",
                "title": "Nível Concluído!",
                "message": f"Parabéns! Você completou o nível {level} em {subarea}!",
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module_index": len(modules) - 1,
                    "lesson_index": 0,
                    "step_index": 0
                },
                "completed": True,
                "next_content": next_content,
                "achievements": {
                    "modules_completed": len(modules),
                    "level_completed": True
                }
            }

        # Processar módulo atual
        module_data = modules[module_idx]
        lessons = module_data.get("lessons", [])

        # Se não há lições no módulo
        if not lessons:
            return {
                "content_type": "empty_module",
                "message": "Este módulo não possui lições",
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": nav_context,
                "module_info": {
                    "title": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "index": module_idx
                }
            }

        # Verificar se ultrapassou todas as lições
        if lesson_idx >= len(lessons):
            # Avançar para o próximo módulo automaticamente
            new_module_idx = module_idx + 1

            if new_module_idx < len(modules):
                # Atualizar para o próximo módulo
                user_ref = db.collection(Collections.USERS).document(user_id)
                user_ref.update({
                    "progress.current.module_index": new_module_idx,
                    "progress.current.lesson_index": 0,
                    "progress.current.step_index": 0
                })

                # Recursivamente chamar a função com os novos índices
                nav_context["module_index"] = new_module_idx
                nav_context["lesson_index"] = 0
                nav_context["step_index"] = 0
                return await get_current_content(current_user, db)
            else:
                # Completou todos os módulos
                return {
                    "content_type": "level_completed",
                    "title": "Nível Concluído!",
                    "message": f"Parabéns! Você completou o nível {level} em {subarea}!",
                    "current_area": area,
                    "current_subarea": subarea,
                    "current_level": level,
                    "navigation_context": nav_context,
                    "completed": True,
                    "next_content": get_next_available_content(area_data, nav_context, db)
                }

        # Processar lição atual
        lesson_data = lessons[lesson_idx]

        # Se a lição tem passos
        if "steps" in lesson_data and lesson_data["steps"]:
            steps = lesson_data["steps"]
            total_steps = len(steps)

            # Se ultrapassou os passos
            if step_idx >= total_steps:
                # Avançar para a próxima lição
                new_lesson_idx = lesson_idx + 1

                if new_lesson_idx < len(lessons):
                    # Atualizar para a próxima lição
                    user_ref = db.collection(Collections.USERS).document(user_id)
                    user_ref.update({
                        "progress.current.lesson_index": new_lesson_idx,
                        "progress.current.step_index": 0
                    })

                    # Recursivamente chamar a função
                    nav_context["lesson_index"] = new_lesson_idx
                    nav_context["step_index"] = 0
                    return await get_current_content(current_user, db)
                else:
                    # Avançar para o próximo módulo
                    new_module_idx = module_idx + 1

                    if new_module_idx < len(modules):
                        user_ref = db.collection(Collections.USERS).document(user_id)
                        user_ref.update({
                            "progress.current.module_index": new_module_idx,
                            "progress.current.lesson_index": 0,
                            "progress.current.step_index": 0
                        })

                        nav_context["module_index"] = new_module_idx
                        nav_context["lesson_index"] = 0
                        nav_context["step_index"] = 0
                        return await get_current_content(current_user, db)
                    else:
                        # Completou o nível
                        return {
                            "content_type": "level_completed",
                            "title": "Nível Concluído!",
                            "message": f"Parabéns! Você completou o nível {level} em {subarea}!",
                            "current_area": area,
                            "current_subarea": subarea,
                            "current_level": level,
                            "navigation_context": nav_context,
                            "completed": True,
                            "next_content": get_next_available_content(area_data, nav_context, db)
                        }

            # Retornar passo atual
            step_content = steps[step_idx]

            # Expandir conteúdo
            user_age = current_user.get("age", 14)
            teaching_style = current_user.get("learning_style", "didático")

            expanded_content = call_teacher_llm(
                f"Explique de forma didática para um estudante de {user_age} anos: {step_content}. "
                f"Contexto: Área: {area}, Subárea: {subarea}, Nível: {level}. "
                f"Use exemplos práticos e linguagem acessível.",
                student_age=user_age,
                subject_area=area,
                teaching_style=teaching_style
            )

            return {
                "content_type": "step",
                "title": lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}"),
                "content": expanded_content,
                "original_step": step_content,
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module_index": module_idx,
                    "lesson_index": lesson_idx,
                    "step_index": step_idx
                },
                "context": {
                    "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "lesson": lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}"),
                    "step": f"{step_idx + 1}/{total_steps}"
                },
                "navigation": {
                    "has_previous": step_idx > 0 or lesson_idx > 0 or module_idx > 0,
                    "has_next": step_idx < total_steps - 1 or lesson_idx < len(lessons) - 1 or module_idx < len(
                        modules) - 1
                },
                "progress": {
                    "step": (step_idx + 1) / total_steps * 100,
                    "lesson": (lesson_idx + (step_idx + 1) / total_steps) / len(lessons) * 100,
                    "module": (module_idx + (lesson_idx + 1) / len(lessons)) / len(modules) * 100
                }
            }
        else:
            # Lição sem passos - gerar conteúdo completo
            lesson_title = lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}")
            objectives = lesson_data.get("objectives", "")

            user_age = current_user.get("age", 14)
            teaching_style = current_user.get("learning_style", "didático")

            lesson = generate_complete_lesson(
                topic=lesson_title,
                subject_area=f"{area} - {subarea}",
                age_range=user_age,
                knowledge_level=level,
                teaching_style=teaching_style,
                lesson_duration_min=30
            )

            return {
                "content_type": "lesson",
                "title": lesson_title,
                "content": lesson.to_text(),
                "objectives": objectives,
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module_index": module_idx,
                    "lesson_index": lesson_idx,
                    "step_index": 0
                },
                "context": {
                    "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "lesson": lesson_title
                },
                "navigation": {
                    "has_previous": lesson_idx > 0 or module_idx > 0,
                    "has_next": lesson_idx < len(lessons) - 1 or module_idx < len(modules) - 1
                }
            }

    except Exception as e:
        # Em caso de qualquer erro, retornar contexto seguro
        import traceback
        error_details = traceback.format_exc()

        return {
            "content_type": "error",
            "message": "Erro ao carregar conteúdo",
            "error": str(e),
            "current_area": area,
            "current_subarea": subarea,
            "current_level": level,
            "navigation_context": nav_context,
            "recovery": {
                "reset_to_start": {
                    "area": area,
                    "subarea": subarea,
                    "level": "iniciante",
                    "module_index": 0,
                    "lesson_index": 0,
                    "step_index": 0
                }
            }
        }