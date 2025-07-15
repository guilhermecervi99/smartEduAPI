# app/utils/progress_utils.py
from typing import Dict, Any, Optional, List
import time
from app.database import Collections


def get_user_progress(db, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Obtém o progresso atual do usuário
    """
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return None

    user_data = user_doc.to_dict()
    return user_data.get("progress", {})


def advance_user_progress(db, user_id: str, step_type: str) -> Optional[Dict[str, Any]]:
    """
    Avança o progresso do usuário baseado no tipo de passo

    Args:
        db: Referência do Firestore
        user_id: ID do usuário
        step_type: Tipo de avanço ("lesson", "module", "level")

    Returns:
        Novo progresso ou None se houver erro
    """
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return None

    user_data = user_doc.to_dict()
    progress = user_data.get("progress", {})
    current = progress.get("current", {})

    # Fazer uma cópia para modificar
    new_current = current.copy()

    if step_type == "lesson":
        new_current["lesson_index"] = current.get("lesson_index", 0) + 1
        new_current["step_index"] = 0
    elif step_type == "module":
        new_current["module_index"] = current.get("module_index", 0) + 1
        new_current["lesson_index"] = 0
        new_current["step_index"] = 0
    elif step_type == "level":
        # Para avanço de nível, precisamos determinar o próximo nível
        current_level = current.get("level", "iniciante")
        next_level = get_next_level(current_level)

        if next_level:
            new_current["level"] = next_level
            new_current["module_index"] = 0
            new_current["lesson_index"] = 0
            new_current["step_index"] = 0
        else:
            # Se não há próximo nível, não avançar
            return current

    # Atualizar no banco
    progress["current"] = new_current
    user_ref.update({"progress": progress})

    return new_current


def calculate_progress_percentage(db, user_id: str, progress: Dict[str, Any]) -> float:
    """
    Calcula a porcentagem de progresso do usuário no nível atual
    """
    current = progress.get("current", {})
    area = progress.get("area", "")
    subarea = current.get("subarea", "")
    level = current.get("level", "iniciante")

    if not area or not subarea:
        return 0.0

    try:
        # Buscar dados do currículo
        area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
        area_doc = area_ref.get()

        if not area_doc.exists:
            return 0.0

        area_data = area_doc.to_dict()
        subareas = area_data.get("subareas", {})

        if subarea not in subareas:
            return 0.0

        subarea_data = subareas[subarea]
        levels = subarea_data.get("levels", {})

        if level not in levels:
            return 0.0

        level_data = levels[level]
        modules = level_data.get("modules", [])

        if not modules:
            return 0.0

        # Calcular progresso baseado na posição atual
        module_index = current.get("module_index", 0)
        lesson_index = current.get("lesson_index", 0)

        total_modules = len(modules)

        # Estimar total de lições
        total_lessons = 0
        for module in modules:
            lessons = module.get("lessons", [])
            total_lessons += len(lessons)

        # Calcular lições completadas
        completed_lessons = 0

        # Módulos anteriores (100% completos)
        for i in range(min(module_index, len(modules))):
            module_lessons = modules[i].get("lessons", [])
            completed_lessons += len(module_lessons)

        # Lições do módulo atual
        if module_index < len(modules):
            completed_lessons += lesson_index

        # Calcular porcentagem
        if total_lessons > 0:
            progress_percentage = (completed_lessons / total_lessons) * 100
            return min(100.0, progress_percentage)

        return 0.0

    except Exception as e:
        print(f"Erro ao calcular progresso: {e}")
        return 0.0


def get_next_recommendations(db, user_id: str, user_data: Dict[str, Any]) -> List[str]:
    """
    Gera recomendações de próximos passos para o usuário
    """
    recommendations = []

    # Verificar progresso atual
    progress = user_data.get("progress", {})
    current = progress.get("current", {})
    area = progress.get("area", "")
    subarea = current.get("subarea", "")
    level = current.get("level", "iniciante")

    if not area:
        recommendations.append("Complete o mapeamento de interesses para definir sua trilha")
        return recommendations

    if not subarea:
        recommendations.append(f"Selecione uma subárea em {area} para começar")
        return recommendations

    # Recomendações baseadas no progresso
    completed_lessons = len(user_data.get("completed_lessons", []))
    completed_modules = len(user_data.get("completed_modules", []))
    completed_projects = len(user_data.get("completed_projects", []))

    # Próximo passo no currículo
    recommendations.append(f"Continuar progresso em {subarea} - {level}")

    # Baseado no número de atividades completadas
    if completed_lessons == 0:
        recommendations.append("Complete sua primeira lição para ganhar XP")
    elif completed_lessons < 5:
        recommendations.append("Continue completando lições para ganhar experiência")

    if completed_projects == 0:
        recommendations.append("Inicie seu primeiro projeto prático")
    elif completed_projects < 3:
        recommendations.append("Desenvolva mais projetos para consolidar o aprendizado")

    # Recomendações baseadas na área atual
    if area == "Tecnologia e Computação":
        recommendations.append("Explore projetos de programação e desenvolvimento")
    elif area == "Artes e Cultura":
        recommendations.append("Crie um portfolio com seus trabalhos artísticos")
    elif area == "Ciências Exatas":
        recommendations.append("Pratique resolução de problemas matemáticos")

    # Recomendações de exploração
    track_scores = user_data.get("track_scores", {})
    if track_scores:
        sorted_tracks = sorted(track_scores.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_tracks) > 1:
            second_area = sorted_tracks[1][0]
            recommendations.append(f"Considere explorar também: {second_area}")

    return recommendations[:5]  # Limitar a 5 recomendações


def get_next_level(current_level: str) -> Optional[str]:
    """
    Determina o próximo nível na sequência
    """
    level_progression = {
        "iniciante": "intermediário",
        "intermediário": "avançado",
        "avançado": None  # Não há próximo nível
    }

    # Normalizar o nível atual
    normalized_current = current_level.lower().strip()

    # Corrigir variações comuns
    if normalized_current == "intermediario":
        normalized_current = "intermediário"
    elif normalized_current == "avancado":
        normalized_current = "avançado"

    return level_progression.get(normalized_current)
