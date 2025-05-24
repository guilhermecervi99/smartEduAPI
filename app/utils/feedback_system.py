# app/utils/feedback_system.py
import time
from typing import Dict, List, Any, Optional
from app.utils.llm_integration import call_teacher_llm
import json
import logging

logger = logging.getLogger(__name__)


def collect_user_feedback(db: Any, user_id: str, content_type: str,
                          rating: int, comments: str = "",
                          context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Coleta e armazena feedback do usuário.

    Args:
        db: Referência do Firestore
        user_id: ID do usuário
        content_type: Tipo de conteúdo
        rating: Avaliação (1-5)
        comments: Comentários opcionais
        context: Contexto adicional

    Returns:
        True se o feedback foi salvo com sucesso
    """
    try:
        feedback_data = {
            "user_id": user_id,
            "content_type": content_type,
            "rating": rating,
            "comments": comments,
            "context": context or {},
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d")
        }

        db.collection("user_feedback").add(feedback_data)
        return True

    except Exception as e:
        logger.error(f"Erro ao coletar feedback: {e}")
        return False


def analyze_user_engagement(db: Any, user_id: str, days: int = 30) -> Dict[str, Any]:
    """
    Analisa o engajamento do usuário com base em múltiplas métricas.

    Args:
        db: Referência do Firestore
        user_id: ID do usuário
        days: Período de análise em dias

    Returns:
        Dicionário com análise de engajamento
    """
    cutoff_time = time.time() - (days * 24 * 60 * 60)

    # Buscar dados do usuário
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return {"has_data": False}

    user_data = user_doc.to_dict()

    # Buscar feedback recente
    feedback_query = db.collection("user_feedback") \
        .where("user_id", "==", user_id) \
        .where("timestamp", ">=", cutoff_time) \
        .stream()

    feedback_list = []
    for doc in feedback_query:
        feedback_list.append(doc.to_dict())

    # Buscar histórico de XP recente
    xp_history = user_data.get("xp_history", [])
    recent_xp = [xp for xp in xp_history if xp.get("timestamp", 0) >= cutoff_time]

    # Calcular métricas
    if not feedback_list and not recent_xp:
        return {"has_data": False}

    # Análise de ratings
    ratings_by_type = {}
    for feedback in feedback_list:
        session_type = feedback.get("session_type", "general")
        rating = feedback.get("rating", 0)

        if session_type not in ratings_by_type:
            ratings_by_type[session_type] = []
        ratings_by_type[session_type].append(rating)

    # Calcular médias
    average_ratings = {}
    for session_type, ratings in ratings_by_type.items():
        if ratings:
            average_ratings[session_type] = sum(ratings) / len(ratings)

    # Análise de engajamento baseada em XP
    xp_by_day = {}
    for xp_entry in recent_xp:
        timestamp = xp_entry.get("timestamp", 0)
        day_key = time.strftime("%Y-%m-%d", time.localtime(timestamp))

        if day_key not in xp_by_day:
            xp_by_day[day_key] = 0
        xp_by_day[day_key] += xp_entry.get("amount", 0)

    # Calcular frequência de estudo
    study_days = len(xp_by_day)
    avg_daily_xp = sum(xp_by_day.values()) / max(study_days, 1)

    # Determinar nível de satisfação
    overall_rating = sum(average_ratings.values()) / len(average_ratings) if average_ratings else 0
    satisfaction_level = _determine_satisfaction_level(overall_rating)

    # Analisar comentários de texto se houver
    text_analysis = {}
    all_comments = " ".join([f.get("comments", "") for f in feedback_list if f.get("comments")])

    if all_comments:
        text_analysis = _analyze_feedback_text(all_comments)

    return {
        "has_data": True,
        "feedback_count": len(feedback_list),
        "average_ratings": average_ratings,
        "satisfaction_level": satisfaction_level,
        "engagement_metrics": {
            "study_days": study_days,
            "avg_daily_xp": avg_daily_xp,
            "total_xp_earned": sum(xp_by_day.values()),
            "consistency_score": study_days / days if days > 0 else 0
        },
        "main_themes": text_analysis.get("main_themes", []),
        "improvement_areas": text_analysis.get("improvement_areas", []),
        "missing_interests": text_analysis.get("missing_interests", [])
    }


def adapt_user_recommendations(db: Any, user_id: str,
                               analysis: Dict[str, Any],
                               force: bool = False) -> Dict[str, Any]:
    """
    Adapta as recomendações do usuário com base na análise.

    Args:
        db: Referência do Firestore
        user_id: ID do usuário
        analysis: Resultado da análise de engajamento
        force: Forçar adaptação mesmo sem mudanças significativas

    Returns:
        Dicionário com as adaptações realizadas
    """
    if not analysis.get("has_data") and not force:
        return {
            "adapted": False,
            "reason": "Dados insuficientes para adaptação"
        }

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return {
            "adapted": False,
            "reason": "Usuário não encontrado"
        }

    user_data = user_doc.to_dict()
    adaptations = []

    # 1. Adaptar baseado na satisfação
    satisfaction = analysis.get("satisfaction_level", "")
    if satisfaction in ["Insatisfatório", "Precisa Melhorar"] or force:
        # Verificar se há áreas alternativas com boa pontuação
        track_scores = user_data.get("track_scores", {})
        current_track = user_data.get("current_track", "")

        if track_scores and current_track:
            sorted_tracks = sorted(track_scores.items(),
                                   key=lambda x: x[1], reverse=True)

            # Se há uma segunda opção próxima
            if len(sorted_tracks) >= 2:
                if sorted_tracks[1][1] >= sorted_tracks[0][1] * 0.8:
                    adaptations.append({
                        "type": "alternative_track_suggestion",
                        "description": f"Considerar mudar para {sorted_tracks[1][0]}",
                        "reason": "Baixa satisfação com trilha atual",
                        "impact": "Pode aumentar engajamento"
                    })

    # 2. Adaptar baseado em interesses ausentes
    missing_interests = analysis.get("missing_interests", [])
    if missing_interests:
        # Ajustar pontuações de interesse
        adaptations.append({
            "type": "interest_adjustment",
            "description": f"Incluir tópicos: {', '.join(missing_interests[:3])}",
            "reason": "Interesses mencionados não cobertos",
            "impact": "Melhor alinhamento com expectativas"
        })

    # 3. Adaptar baseado em padrões de engajamento
    engagement = analysis.get("engagement_metrics", {})
    consistency = engagement.get("consistency_score", 0)

    if consistency < 0.3:  # Menos de 30% dos dias
        adaptations.append({
            "type": "engagement_boost",
            "description": "Implementar lembretes e metas diárias menores",
            "reason": "Baixa consistência de estudo",
            "impact": "Aumentar frequência de estudo"
        })

    # Salvar adaptações se houver
    if adaptations:
        adaptation_record = {
            "user_id": user_id,
            "timestamp": time.time(),
            "adaptations": adaptations,
            "analysis_summary": {
                "satisfaction_level": satisfaction,
                "feedback_count": analysis.get("feedback_count", 0),
                "consistency_score": consistency
            }
        }

        db.collection("user_adaptations").add(adaptation_record)

    return {
        "adapted": len(adaptations) > 0,
        "adaptations": adaptations,
        "reason": "Adaptações aplicadas com sucesso" if adaptations else "Nenhuma adaptação necessária"
    }


def generate_personalized_suggestions(db: Any, user_id: str) -> List[Dict[str, str]]:
    """
    Gera sugestões personalizadas para o usuário.

    Args:
        db: Referência do Firestore
        user_id: ID do usuário

    Returns:
        Lista de sugestões personalizadas
    """
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return []

    user_data = user_doc.to_dict()

    # Analisar dados do usuário
    age = user_data.get("age", 14)
    learning_style = user_data.get("learning_style", "didático")
    current_track = user_data.get("current_track", "")
    completed_lessons = len(user_data.get("completed_lessons", []))
    completed_projects = len(user_data.get("completed_projects", []))

    # Análise recente
    analysis = analyze_user_engagement(db, user_id, 30)

    # Construir prompt para sugestões
    prompt = f"""
    Gere 3-5 sugestões personalizadas para melhorar a experiência de aprendizado:

    Perfil do usuário:
    - Idade: {age} anos
    - Estilo de aprendizado: {learning_style}
    - Área atual: {current_track}
    - Lições completadas: {completed_lessons}
    - Projetos completados: {completed_projects}
    - Nível de satisfação: {analysis.get('satisfaction_level', 'Desconhecido')}

    As sugestões devem ser:
    1. Específicas e acionáveis
    2. Adequadas para a idade
    3. Alinhadas com o estilo de aprendizado
    4. Focadas em aumentar engajamento

    Responda em formato JSON com esta estrutura:
    [
        {
    "title": "Título da sugestão",
            "description": "Descrição detalhada",
            "benefit": "Benefício esperado",
            "priority": "alta/média/baixa"
        }
    ]
    """

    try:
        response = call_teacher_llm(
            prompt,
            student_age=age,
            teaching_style=learning_style,
            temperature=0.7
        )

        # Extrair JSON da resposta
        if "```json" in response:
            json_text = response.split("```json")[1].split("```")[0]
        else:
            json_text = response

        suggestions = json.loads(json_text)

        # Validar e formatar sugestões
        formatted_suggestions = []
        for sugg in suggestions[:5]:  # Limitar a 5
            if all(key in sugg for key in ["title", "description", "benefit"]):
                formatted_suggestions.append({
                    "title": sugg["title"],
                    "description": sugg["description"],
                    "benefit": sugg["benefit"],
                    "priority": sugg.get("priority", "média")
                })

        return formatted_suggestions

    except Exception as e:
        logger.error(f"Erro ao gerar sugestões: {e}")

        # Sugestões padrão de fallback
        return [
            {
                "title": "Experimente projetos práticos",
                "description": "Aplique o que aprendeu em projetos reais",
                "benefit": "Aumenta retenção e motivação",
                "priority": "alta"
            },
            {
                "title": "Estabeleça metas diárias pequenas",
                "description": "15-20 minutos por dia são suficientes",
                "benefit": "Cria consistência no aprendizado",
                "priority": "média"
            }
        ]


def _determine_satisfaction_level(rating: float) -> str:
    """Determina o nível de satisfação baseado na média de ratings."""
    if rating >= 4.5:
        return "Excelente"
    elif rating >= 4.0:
        return "Muito Bom"
    elif rating >= 3.5:
        return "Bom"
    elif rating >= 3.0:
        return "Satisfatório"
    elif rating >= 2.0:
        return "Precisa Melhorar"
    else:
        return "Insatisfatório"


def _analyze_feedback_text(text: str) -> Dict[str, List[str]]:
    """Analisa texto de feedback usando LLM."""
    if not text.strip():
        return {}

    prompt = f"""
    Analise este feedback de usuário e identifique:
    1. Principais temas/preocupações (máximo 3)
    2. Áreas que precisam melhorar (máximo 3)
    3. Interesses não atendidos (máximo 3)

    Feedback: "{text}"

    Responda em JSON com as chaves:
    - main_themes (lista)
    - improvement_areas (lista)
    - missing_interests (lista)
    """

    try:
        response = call_teacher_llm(prompt, temperature=0.3)

        if "```json" in response:
            json_text = response.split("```json")[1].split("```")[0]
        else:
            json_text = response

        return json.loads(json_text)

    except Exception as e:
        logger.error(f"Erro ao analisar texto: {e}")
        return {
            "main_themes": [],
            "improvement_areas": [],
            "missing_interests": []
        }