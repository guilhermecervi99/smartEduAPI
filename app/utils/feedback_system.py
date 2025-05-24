# app/utils/feedback_system.py (novo arquivo)
import time
from typing import Dict, List, Any, Optional


def collect_user_feedback(db, user_id: str, content_type: str, rating: int,
                          comments: str = "", context: Dict[str, Any] = None) -> bool:
    """
    Coleta feedback do usuário sobre conteúdo ou experiência
    """
    feedback_data = {
        "user_id": user_id,
        "content_type": content_type,
        "rating": rating,
        "comments": comments,
        "context": context or {},
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d")
    }

    try:
        db.collection("user_feedback").add(feedback_data)
        return True
    except Exception as e:
        print(f"Erro ao salvar feedback: {e}")
        return False


def analyze_user_engagement(db, user_id: str, days: int = 30) -> Dict[str, Any]:
    """
    Analisa o engajamento do usuário nos últimos dias
    """
    cutoff_time = time.time() - (days * 24 * 60 * 60)

    try:
        # Buscar atividades recentes
        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            return {"engagement_level": "unknown", "recommendations": []}

        user_data = user_doc.to_dict()

        # Calcular métricas de engajamento
        xp_history = user_data.get("xp_history", [])
        recent_xp = sum(
            entry.get("amount", 0)
            for entry in xp_history
            if entry.get("timestamp", 0) >= cutoff_time
        )

        completed_lessons = len([
            lesson for lesson in user_data.get("completed_lessons", [])
            if time.mktime(time.strptime(lesson.get("completion_date", "1970-01-01"), "%Y-%m-%d")) >= cutoff_time
        ])

        # Determinar nível de engajamento
        if recent_xp >= 100 and completed_lessons >= 5:
            engagement_level = "alto"
        elif recent_xp >= 50 and completed_lessons >= 2:
            engagement_level = "médio"
        elif recent_xp > 0 or completed_lessons > 0:
            engagement_level = "baixo"
        else:
            engagement_level = "inativo"

        # Gerar recomendações baseadas no engajamento
        recommendations = []
        if engagement_level == "inativo":
            recommendations = [
                "Que tal voltar com uma lição rápida?",
                "Explore novos tópicos em sua área de interesse",
                "Defina uma meta pequena para hoje"
            ]
        elif engagement_level == "baixo":
            recommendations = [
                "Tente completar mais uma lição hoje",
                "Considere iniciar um projeto prático",
                "Explore recursos de aprendizado disponíveis"
            ]
        elif engagement_level == "médio":
            recommendations = [
                "Você está indo bem! Continue assim",
                "Que tal tentar um projeto mais desafiador?",
                "Explore especializações em sua área"
            ]
        else:  # alto
            recommendations = [
                "Excelente progresso! Mantenha o ritmo",
                "Considere ajudar outros usuários",
                "Explore áreas complementares"
            ]

        return {
            "engagement_level": engagement_level,
            "recent_xp": recent_xp,
            "recent_lessons": completed_lessons,
            "recommendations": recommendations,
            "period_days": days
        }

    except Exception as e:
        print(f"Erro ao analisar engajamento: {e}")
        return {"engagement_level": "error", "recommendations": []}


def generate_personalized_suggestions(db, user_id: str) -> List[str]:
    """
    Gera sugestões personalizadas baseadas no perfil do usuário
    """
    try:
        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            return ["Complete seu perfil para receber sugestões personalizadas"]

        user_data = user_doc.to_dict()
        suggestions = []

        # Sugestões baseadas na área atual
        current_track = user_data.get("current_track", "")
        if current_track:
            suggestions.append(f"Explore recursos avançados em {current_track}")

        # Sugestões baseadas no progresso
        progress = user_data.get("progress", {})
        current = progress.get("current", {})

        if current.get("level") == "iniciante":
            suggestions.append("Foque em completar o nível iniciante antes de avançar")
        elif current.get("level") == "intermediario":
            suggestions.append("Considere iniciar projetos mais complexos")

        # Sugestões baseadas em projetos
        completed_projects = len(user_data.get("completed_projects", []))
        if completed_projects == 0:
            suggestions.append("Inicie seu primeiro projeto prático")
        elif completed_projects < 3:
            suggestions.append("Desenvolva mais projetos para fortalecer seu portfolio")

        # Sugestões baseadas em badges
        badges = user_data.get("badges", [])
        if len(badges) < 5:
            suggestions.append("Complete mais atividades para desbloquear conquistas")

        return suggestions[:5]  # Limitar a 5 sugestões

    except Exception as e:
        print(f"Erro ao gerar sugestões: {e}")
        return ["Erro ao gerar sugestões personalizadas"]