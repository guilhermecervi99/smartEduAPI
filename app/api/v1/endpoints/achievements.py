# app/api/v1/endpoints/achievements.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion
import time

from app.core.security import get_current_user, get_current_user_id_required
from app.database import get_db, Collections
from app.schemas.achievements import (
    AchievementResponse,
    BadgeResponse,
    UserAchievementsResponse,
    LeaderboardResponse,
    StreakResponse,
    XPHistoryResponse,
    BadgeCategory,
    AchievementProgress
)
from app.utils.gamification import (
    add_user_xp,
    grant_badge,
    check_achievement_criteria,
    get_next_level_info,
    calculate_study_streak
)

router = APIRouter()


@router.get("/", response_model=UserAchievementsResponse)
async def get_user_achievements(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém todas as conquistas do usuário organizadas por categoria
    """
    user_id = current_user["id"]
    badges = current_user.get("badges", [])

    # Organizar badges por categorias
    categorized_badges = {
        "trilhas": [],
        "projetos": [],
        "niveis": [],
        "especializacoes": [],
        "participacao": [],
        "outros": []
    }

    for badge in badges:
        if "Explorador" in badge or "Trilha" in badge:
            categorized_badges["trilhas"].append(badge)
        elif "Projeto" in badge:
            categorized_badges["projetos"].append(badge)
        elif "Nível" in badge or "Avançado" in badge or "Intermediário" in badge or "Iniciante" in badge:
            categorized_badges["niveis"].append(badge)
        elif "Especialista" in badge or "Especialização" in badge:
            categorized_badges["especializacoes"].append(badge)
        elif "Participação" in badge or "Autoconhecimento" in badge or any(
                x in badge for x in ["Iniciante", "Estudante", "Mestre"]):
            categorized_badges["participacao"].append(badge)
        else:
            categorized_badges["outros"].append(badge)

    # Converter para objetos BadgeCategory
    badge_categories = []
    category_names = {
        "trilhas": "Exploração de Trilhas",
        "projetos": "Projetos Concluídos",
        "niveis": "Níveis de Aprendizado",
        "especializacoes": "Especializações",
        "participacao": "Participação e Engajamento",
        "outros": "Outras Conquistas"
    }

    for category_key, category_badges in categorized_badges.items():
        if category_badges:  # Só incluir categorias com badges
            badge_responses = [
                BadgeResponse(
                    id=f"{user_id}_{badge}_{badges.index(badge)}",
                    name=badge,
                    description=get_badge_description(badge),
                    earned_date=get_badge_earned_date(current_user, badge),
                    rarity=get_badge_rarity(badge),
                    icon_url=get_badge_icon_url(badge)
                )
                for badge in category_badges
            ]

            badge_categories.append(BadgeCategory(
                name=category_names[category_key],
                key=category_key,
                badges=badge_responses,
                total_count=len(category_badges)
            ))

    # Calcular estatísticas gerais
    profile_level = current_user.get("profile_level", 1)
    profile_xp = current_user.get("profile_xp", 0)

    # Informações sobre próximo nível
    next_level_info = get_next_level_info(profile_xp, profile_level)

    # Streak de estudo
    study_streak = calculate_study_streak(current_user)

    # Progresso em conquistas
    achievement_progress = check_user_achievement_progress(current_user)

    return UserAchievementsResponse(
        user_id=user_id,
        total_badges=len(badges),
        profile_level=profile_level,
        profile_xp=profile_xp,
        next_level_xp_needed=next_level_info.get("xp_needed", 0),
        xp_progress_percentage=next_level_info.get("xp_progress", 0.0),
        current_streak=study_streak,
        badge_categories=badge_categories,
        achievement_progress=achievement_progress
    )


@router.get("/badges", response_model=List[BadgeResponse])
async def get_user_badges(
        category: Optional[str] = Query(None, description="Filter by category"),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Obtém as badges do usuário com filtro opcional por categoria
    """
    user_id = current_user["id"]
    badges = current_user.get("badges", [])

    # Filtrar por categoria se especificada
    if category:
        filtered_badges = []
        for badge in badges:
            badge_category = get_badge_category(badge)
            if badge_category == category:
                filtered_badges.append(badge)
        badges = filtered_badges

    # Converter para resposta
    badge_responses = []
    for badge in badges:
        badge_responses.append(BadgeResponse(
            id=f"{user_id}_{badge}_{badges.index(badge)}",
            name=badge,
            description=get_badge_description(badge),
            earned_date=get_badge_earned_date(current_user, badge),
            rarity=get_badge_rarity(badge),
            icon_url=get_badge_icon_url(badge)
        ))

    return badge_responses


@router.post("/check")
async def check_new_achievements(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Verifica e desbloqueia novas conquistas para o usuário
    """
    user_id = current_user["id"]

    # Verificar critérios de conquistas
    new_badges = check_achievement_criteria(current_user)

    # Conceder novas badges
    granted_badges = []
    for badge in new_badges:
        if grant_badge(db, user_id, badge):
            granted_badges.append(badge)

    # Adicionar XP por verificar conquistas
    if granted_badges:
        add_user_xp(db, user_id, len(granted_badges) * 5, "Desbloqueou novas conquistas")

    return {
        "new_badges": granted_badges,
        "total_new_badges": len(granted_badges),
        "xp_earned": len(granted_badges) * 5 if granted_badges else 0,
        "message": f"Parabéns! Você desbloqueou {len(granted_badges)} nova(s) conquista(s)!" if granted_badges else "Nenhuma nova conquista disponível no momento."
    }


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
        category: str = Query("xp", description="Leaderboard category: xp, badges, projects"),
        limit: int = Query(10, ge=1, le=50),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o leaderboard global de usuários
    """
    # Buscar usuários para o leaderboard
    users_ref = db.collection(Collections.USERS)

    # Ordenar baseado na categoria
    if category == "xp":
        query = users_ref.order_by("profile_xp", direction="DESCENDING").limit(limit)
    elif category == "badges":
        # Para badges, vamos buscar todos e ordenar por tamanho da lista
        query = users_ref.limit(limit * 2)  # Buscar mais para ordenar depois
    elif category == "projects":
        # Similar para projetos
        query = users_ref.limit(limit * 2)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid category. Must be: xp, badges, or projects"
        )

    # Executar query
    users_data = []
    for doc in query.stream():
        user_data = doc.to_dict()
        user_data["id"] = doc.id
        users_data.append(user_data)

    # Ordenar e filtrar baseado na categoria
    if category == "badges":
        users_data.sort(key=lambda x: len(x.get("badges", [])), reverse=True)
    elif category == "projects":
        users_data.sort(key=lambda x: len(x.get("completed_projects", [])), reverse=True)

    users_data = users_data[:limit]

    # Converter para resposta
    leaderboard_entries = []
    current_user_position = None

    for rank, user_data in enumerate(users_data, 1):
        user_id = user_data["id"]

        # Calcular valor baseado na categoria
        if category == "xp":
            value = user_data.get("profile_xp", 0)
        elif category == "badges":
            value = len(user_data.get("badges", []))
        elif category == "projects":
            value = len(user_data.get("completed_projects", []))

        entry = {
            "rank": rank,
            "user_id": user_id,
            "display_name": f"Usuário {user_id[:8]}",  # Anonimizar
            "value": value,
            "profile_level": user_data.get("profile_level", 1),
            "current_track": user_data.get("current_track", "")
        }

        leaderboard_entries.append(entry)

        # Verificar se é o usuário atual
        if user_id == current_user["id"]:
            current_user_position = rank

    return LeaderboardResponse(
        category=category,
        entries=leaderboard_entries,
        current_user_position=current_user_position,
        total_users=len(leaderboard_entries),
        last_updated=time.time()
    )


@router.get("/streak", response_model=StreakResponse)
async def get_study_streak(
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Obtém informações sobre a sequência de estudos do usuário
    """
    current_streak = calculate_study_streak(current_user)

    # Calcular estatísticas da streak
    last_activity = current_user.get("last_login", 0)
    streak_data = current_user.get("streak_data", {})

    longest_streak = streak_data.get("longest_streak", current_streak)
    total_study_days = streak_data.get("total_study_days", current_streak)

    # Determinar próximas metas de streak
    next_milestones = [7, 14, 30, 60, 100, 365]
    next_milestone = None

    for milestone in next_milestones:
        if current_streak < milestone:
            next_milestone = milestone
            break

    return StreakResponse(
        current_streak=current_streak,
        longest_streak=longest_streak,
        total_study_days=total_study_days,
        last_activity_date=last_activity,
        next_milestone=next_milestone,
        days_until_milestone=next_milestone - current_streak if next_milestone else 0,
        streak_level=get_streak_level(current_streak)
    )


@router.get("/xp-history", response_model=XPHistoryResponse)
async def get_xp_history(
        days: int = Query(30, ge=1, le=365, description="Number of days to retrieve"),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Obtém o histórico de XP do usuário
    """
    xp_history = current_user.get("xp_history", [])

    # Filtrar por período
    cutoff_time = time.time() - (days * 24 * 60 * 60)
    filtered_history = [
        entry for entry in xp_history
        if entry.get("timestamp", 0) >= cutoff_time
    ]

    # Calcular estatísticas
    total_xp_gained = sum(entry.get("amount", 0) for entry in filtered_history)

    # Agrupar por dia
    daily_xp = {}
    for entry in filtered_history:
        timestamp = entry.get("timestamp", 0)
        date_key = time.strftime("%Y-%m-%d", time.localtime(timestamp))

        if date_key not in daily_xp:
            daily_xp[date_key] = 0
        daily_xp[date_key] += entry.get("amount", 0)

    # Calcular médias
    avg_daily_xp = total_xp_gained / max(len(daily_xp), 1)

    # Principais fontes de XP
    source_xp = {}
    for entry in filtered_history:
        reason = entry.get("reason", "Outros")
        # Extrair categoria da razão
        if "lição" in reason.lower():
            category = "Lições"
        elif "módulo" in reason.lower():
            category = "Módulos"
        elif "projeto" in reason.lower():
            category = "Projetos"
        elif "avaliação" in reason.lower():
            category = "Avaliações"
        else:
            category = "Outros"

        if category not in source_xp:
            source_xp[category] = 0
        source_xp[category] += entry.get("amount", 0)

    return XPHistoryResponse(
        period_days=days,
        total_xp_gained=total_xp_gained,
        avg_daily_xp=avg_daily_xp,
        daily_breakdown=daily_xp,
        source_breakdown=source_xp,
        recent_activities=filtered_history[-10:],  # 10 mais recentes
        current_total_xp=current_user.get("profile_xp", 0)
    )


@router.get("/available")
async def get_available_achievements(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém conquistas disponíveis que o usuário ainda pode desbloquear
    """
    user_badges = set(current_user.get("badges", []))

    # Definir todas as conquistas possíveis
    all_possible_achievements = get_all_possible_achievements(current_user, db)

    # Filtrar apenas as não conquistadas
    available_achievements = []
    for achievement in all_possible_achievements:
        if achievement["badge_name"] not in user_badges:
            available_achievements.append(achievement)

    return {
        "available_achievements": available_achievements,
        "total_available": len(available_achievements),
        "completion_percentage": (len(user_badges) / len(
            all_possible_achievements)) * 100 if all_possible_achievements else 0
    }


# Funções auxiliares

def get_badge_description(badge_name: str) -> str:
    """Gera descrição para uma badge"""
    descriptions = {
        "Iniciante": "Bem-vindo ao sistema! Primeira badge conquistada.",
        "Autoconhecimento": "Completou o mapeamento de interesses.",
        "Estudante Dedicado": "Completou 10 lições.",
        "Mestre do Conhecimento": "Completou 50 lições.",
        "Construtor": "Completou 5 projetos.",
        "Arquiteto de Projetos": "Completou 20 projetos."
    }

    # Verificar padrões conhecidos
    if "Explorador de" in badge_name:
        area = badge_name.replace("Explorador de ", "")
        return f"Explorou a área de {area}."
    elif "Nível" in badge_name and ":" in badge_name:
        return f"Completou {badge_name.lower()}."
    elif "Projeto Final:" in badge_name:
        return "Completou um projeto final com sucesso."
    elif "Especialista em" in badge_name:
        spec = badge_name.replace("Especialista em ", "")
        return f"Tornou-se especialista em {spec}."

    return descriptions.get(badge_name, "Conquista especial desbloqueada!")


def get_badge_earned_date(user_data: dict, badge_name: str) -> Optional[str]:
    """Tenta determinar quando uma badge foi conquistada"""
    # Simplificado - em um sistema real, você salvaria timestamps das badges
    xp_history = user_data.get("xp_history", [])

    for entry in xp_history:
        reason = entry.get("reason", "")
        if badge_name.lower() in reason.lower():
            timestamp = entry.get("timestamp", 0)
            return time.strftime("%Y-%m-%d", time.localtime(timestamp))

    return None


def get_badge_rarity(badge_name: str) -> str:
    """Determina a raridade de uma badge"""
    if any(keyword in badge_name for keyword in ["Mestre", "Arquiteto", "Especialista", "Final"]):
        return "legendary"
    elif any(keyword in badge_name for keyword in ["Avançado", "Projeto", "Nível"]):
        return "epic"
    elif any(keyword in badge_name for keyword in ["Intermediário", "Construtor", "Explorador"]):
        return "rare"
    else:
        return "common"


def get_badge_icon_url(badge_name: str) -> str:
    """Retorna URL do ícone da badge (placeholder)"""
    # Em um sistema real, você teria ícones reais
    rarity = get_badge_rarity(badge_name)
    return f"/static/badges/{rarity}_badge.png"


def get_badge_category(badge_name: str) -> str:
    """Determina a categoria de uma badge"""
    if "Explorador" in badge_name:
        return "trilhas"
    elif "Projeto" in badge_name:
        return "projetos"
    elif "Nível" in badge_name:
        return "niveis"
    elif "Especialista" in badge_name:
        return "especializacoes"
    else:
        return "participacao"


def get_streak_level(streak_days: int) -> str:
    """Determina o nível da streak"""
    if streak_days >= 365:
        return "Master Streaker"
    elif streak_days >= 100:
        return "Consistent Learner"
    elif streak_days >= 30:
        return "Dedicated Student"
    elif streak_days >= 7:
        return "Regular Learner"
    else:
        return "Getting Started"


def check_user_achievement_progress(user_data: dict) -> List[AchievementProgress]:
    """Verifica o progresso em conquistas não completadas"""
    progress_list = []

    # Progresso em lições
    completed_lessons = len(user_data.get("completed_lessons", []))
    if completed_lessons < 50:
        target = 50 if completed_lessons >= 10 else 10
        badge_name = "Mestre do Conhecimento" if target == 50 else "Estudante Dedicado"

        progress_list.append(AchievementProgress(
            badge_name=badge_name,
            description=f"Complete {target} lições",
            current_progress=completed_lessons,
            target_progress=target,
            progress_percentage=(completed_lessons / target) * 100
        ))

    # Progresso em projetos
    completed_projects = len(user_data.get("completed_projects", []))
    if completed_projects < 20:
        target = 20 if completed_projects >= 5 else 5
        badge_name = "Arquiteto de Projetos" if target == 20 else "Construtor"

        progress_list.append(AchievementProgress(
            badge_name=badge_name,
            description=f"Complete {target} projetos",
            current_progress=completed_projects,
            target_progress=target,
            progress_percentage=(completed_projects / target) * 100
        ))

    return progress_list


def get_all_possible_achievements(user_data: dict, db) -> List[Dict]:
    """Retorna todas as conquistas possíveis no sistema"""
    achievements = [
        {"badge_name": "Iniciante", "description": "Primeira badge", "category": "participacao"},
        {"badge_name": "Autoconhecimento", "description": "Complete o mapeamento", "category": "participacao"},
        {"badge_name": "Estudante Dedicado", "description": "Complete 10 lições", "category": "participacao"},
        {"badge_name": "Mestre do Conhecimento", "description": "Complete 50 lições", "category": "participacao"},
        {"badge_name": "Construtor", "description": "Complete 5 projetos", "category": "projetos"},
        {"badge_name": "Arquiteto de Projetos", "description": "Complete 20 projetos", "category": "projetos"},
    ]

    # Adicionar badges de áreas (baseado nas áreas disponíveis)
    try:
        areas_ref = db.collection(Collections.LEARNING_PATHS).stream()
        for area_doc in areas_ref:
            area_name = area_doc.id
            achievements.append({
                "badge_name": f"Explorador de {area_name}",
                "description": f"Explore a área de {area_name}",
                "category": "trilhas"
            })
    except:
        pass  # Falha silenciosa se não conseguir acessar as áreas

    return achievements