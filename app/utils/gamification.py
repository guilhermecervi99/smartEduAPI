# app/utils/gamification.py
from typing import Dict, Any, Optional, List
from google.cloud.firestore import ArrayUnion
import time

from app.config import get_settings
from app.database import Collections

settings = get_settings()


def initialize_user_gamification() -> Dict[str, Any]:
    """
    Inicializa dados de gamificação para novo usuário
    """
    return {
        "profile_xp": 0,
        "profile_level": 1,
        "badges": ["Iniciante"],  # Badge inicial
        "xp_history": [{
            "amount": 10,
            "reason": "Criação de conta",
            "timestamp": time.time()
        }],
        "started_projects": [],
        "completed_projects": [],
        "completed_lessons": [],
        "completed_modules": [],
        "completed_levels": [],
        "completed_subareas": [],
        "completed_specializations": [],
        "passed_assessments": [],
        "passed_final_assessments": [],
        "certifications": [],
        "specializations_started": [],
        "accessed_resources": [],
        "mapping_history": [],
        "track_scores": {}
    }


def calculate_user_level(xp: int) -> int:
    """
    Calcula o nível do usuário baseado no XP
    """
    for level, threshold in enumerate(settings.xp_thresholds, 1):
        if xp < threshold:
            return level - 1
    return len(settings.xp_thresholds)


def add_user_xp(db, user_id: str, amount: int, reason: str) -> Dict[str, Any]:
    """
    Adiciona XP ao usuário e atualiza seu nível

    Returns:
        Dict com new_xp, new_level, level_up (bool)
    """
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise ValueError(f"User {user_id} not found")

    user_data = user_doc.to_dict()
    current_xp = user_data.get("profile_xp", 0)
    current_level = user_data.get("profile_level", 1)

    # Adicionar XP
    new_xp = current_xp + amount

    # Calcular novo nível
    new_level = calculate_user_level(new_xp)

    # Verificar se subiu de nível
    level_up = new_level > current_level

    # Preparar atualizações
    updates = {
        "profile_xp": new_xp,
        "profile_level": new_level,
        "xp_history": ArrayUnion([{
            "amount": amount,
            "reason": reason,
            "timestamp": time.time()
        }])
    }

    # Se houve level up, adicionar badge de nível
    if level_up:
        level_badge = f"Nível {new_level}"
        if level_badge not in user_data.get("badges", []):
            updates["badges"] = ArrayUnion([level_badge])

    # Atualizar no banco
    user_ref.update(updates)

    return {
        "new_xp": new_xp,
        "new_level": new_level,
        "level_up": level_up,
        "xp_added": amount
    }


def grant_badge(db, user_id: str, badge_name: str) -> bool:
    """
    Concede uma badge ao usuário

    Returns:
        True se a badge foi concedida, False se já possuía
    """
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise ValueError(f"User {user_id} not found")

    user_data = user_doc.to_dict()
    badges = user_data.get("badges", [])

    # Verificar se já possui a badge
    if badge_name in badges:
        return False

    # Adicionar a badge
    user_ref.update({
        "badges": ArrayUnion([badge_name])
    })

    return True


def check_achievement_criteria(user_data: Dict[str, Any]) -> List[str]:
    """
    Verifica critérios para desbloqueio automático de conquistas

    Returns:
        Lista de badges a serem desbloqueadas
    """
    new_badges = []
    current_badges = user_data.get("badges", [])

    # Conquistas por número de lições
    completed_lessons = len(user_data.get("completed_lessons", []))
    if completed_lessons >= 10 and "Estudante Dedicado" not in current_badges:
        new_badges.append("Estudante Dedicado")
    if completed_lessons >= 50 and "Mestre do Conhecimento" not in current_badges:
        new_badges.append("Mestre do Conhecimento")

    # Conquistas por projetos
    completed_projects = len(user_data.get("completed_projects", []))
    if completed_projects >= 5 and "Construtor" not in current_badges:
        new_badges.append("Construtor")
    if completed_projects >= 20 and "Arquiteto de Projetos" not in current_badges:
        new_badges.append("Arquiteto de Projetos")

    # Conquistas por certificações
    certifications = len(user_data.get("certifications", []))
    if certifications >= 3 and "Colecionador de Certificados" not in current_badges:
        new_badges.append("Colecionador de Certificados")

    # Conquistas por áreas completadas
    completed_subareas = len(user_data.get("completed_subareas", []))
    if completed_subareas >= 3 and "Explorador Multidisciplinar" not in current_badges:
        new_badges.append("Explorador Multidisciplinar")

    # Conquistas por especializações
    completed_specs = len(user_data.get("completed_specializations", []))
    if completed_specs >= 1 and "Especialista" not in current_badges:
        new_badges.append("Especialista")
    if completed_specs >= 5 and "Mestre Especialista" not in current_badges:
        new_badges.append("Mestre Especialista")

    return new_badges


def get_next_level_info(current_xp: int, current_level: int) -> Dict[str, Any]:
    """
    Obtém informações sobre o próximo nível
    """
    if current_level >= len(settings.xp_thresholds):
        return {
            "next_level": current_level + 1,
            "xp_needed": 0,
            "xp_progress": 100.0,
            "is_max_level": True
        }

    current_threshold = settings.xp_thresholds[current_level - 1] if current_level > 1 else 0
    next_threshold = settings.xp_thresholds[current_level] if current_level < len(settings.xp_thresholds) else float(
        'inf')

    xp_in_level = current_xp - current_threshold
    xp_for_level = next_threshold - current_threshold
    xp_progress = (xp_in_level / xp_for_level) * 100 if xp_for_level > 0 else 0

    return {
        "next_level": current_level + 1,
        "xp_needed": next_threshold - current_xp,
        "xp_progress": min(xp_progress, 100.0),
        "is_max_level": False
    }


def calculate_study_streak(user_data: Dict[str, Any]) -> int:
    """
    Calcula a sequência de dias de estudo do usuário
    """
    # Buscar último login
    last_login = user_data.get("last_login", 0)
    if not last_login:
        return 0

    current_time = time.time()
    time_diff = current_time - last_login

    # Se o último login foi há mais de 48 horas, a streak quebra
    if time_diff > 48 * 60 * 60:  # 48 horas
        return 0

    # Buscar histórico de atividades
    completed_lessons = user_data.get("completed_lessons", [])
    completed_modules = user_data.get("completed_modules", [])

    # Criar set de datas únicas de atividade
    activity_dates = set()

    for lesson in completed_lessons:
        date = lesson.get("completion_date")
        if date:
            activity_dates.add(date)

    for module in completed_modules:
        date = module.get("completion_date")
        if date:
            activity_dates.add(date)

    # Ordenar datas
    sorted_dates = sorted(activity_dates, reverse=True)

    if not sorted_dates:
        return 1 if time_diff < 24 * 60 * 60 else 0

    # Contar dias consecutivos
    streak = 1
    today = time.strftime("%Y-%m-%d")

    # Se hoje está nas datas, começar de hoje
    if today in sorted_dates:
        current_date = today
    else:
        # Se não, verificar se ontem está
        yesterday = time.strftime("%Y-%m-%d", time.localtime(current_time - 24 * 60 * 60))
        if yesterday in sorted_dates:
            current_date = yesterday
        else:
            return 0

    # Contar dias consecutivos para trás
    for i in range(1, len(sorted_dates)):
        prev_date = time.strftime("%Y-%m-%d", time.localtime(
            time.mktime(time.strptime(current_date, "%Y-%m-%d")) - 24 * 60 * 60
        ))

        if prev_date in sorted_dates:
            streak += 1
            current_date = prev_date
        else:
            break

    return streak

# Recompensas por tipo de ação
XP_REWARDS = {
    "create_account": 10,
    "complete_mapping": 25,
    "select_track": 5,
    "select_subarea": 5,
    "complete_lesson": 10,
    "complete_module": 15,
    "complete_level": 30,
    "complete_level_intermediate": 40,
    "complete_level_advanced": 50,
    "start_project": 10,
    "complete_project": 25,
    "complete_final_project": 50,
    "pass_assessment": 10,
    "pass_final_assessment": 20,
    "get_certification": 75,
    "start_specialization": 20,
    "complete_specialization": 100,
    "access_resource": 3,
    "ask_teacher": 2,
    "explore_careers": 5,
    "view_achievements": 2,
    "change_teaching_style": 3,
    "daily_login": 5
}