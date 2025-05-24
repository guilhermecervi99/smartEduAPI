# app/api/v1/endpoints/feedback.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
import time

from app.core.security import get_current_user
from app.database import get_db, Collections
from app.schemas.feedback import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackAnalysisResponse,
    AdaptationResponse,
    ImprovementSuggestionsResponse
)
from app.utils.feedback_system import (
    collect_user_feedback,
    analyze_user_engagement,
    adapt_user_recommendations,
    generate_personalized_suggestions
)

router = APIRouter()


@router.post("/collect", response_model=FeedbackResponse)
async def collect_feedback(
        request: FeedbackRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Coleta feedback do usuário sobre conteúdo ou experiência.

    - Tipos: study, assessment, general, content
    - Ratings de 1-5 em múltiplas dimensões
    - Comentários e sugestões opcionais
    """
    user_id = current_user["id"]

    # Preparar dados de feedback
    feedback_data = {
        "user_id": user_id,
        "session_type": request.session_type,
        "content_id": request.content_id,
        "content_type": request.content_type,
        "ratings": request.ratings.dict() if request.ratings else {},
        "missing_topics": request.missing_topics,
        "suggestions": request.suggestions,
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d"),
        "context": request.context or {}
    }

    # Salvar feedback
    feedback_ref = db.collection("user_feedback").add(feedback_data)
    feedback_id = feedback_ref[1].id

    # Adicionar XP por fornecer feedback
    from app.utils.gamification import add_user_xp
    xp_result = add_user_xp(db, user_id, 3, "Forneceu feedback valioso")

    return FeedbackResponse(
        feedback_id=feedback_id,
        message="Feedback recebido com sucesso!",
        xp_earned=xp_result["xp_added"],
        timestamp=feedback_data["timestamp"]
    )


@router.get("/analysis", response_model=FeedbackAnalysisResponse)
async def get_feedback_analysis(
        days: int = Query(30, ge=1, le=365, description="Período de análise em dias"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Analisa o feedback do usuário para identificar padrões e áreas de melhoria.

    - Análise de ratings médios por tipo de conteúdo
    - Identificação de temas recorrentes
    - Sugestões de adaptação
    """
    user_id = current_user["id"]

    # Analisar engajamento do usuário
    analysis = analyze_user_engagement(db, user_id, days)

    if not analysis["has_data"]:
        return FeedbackAnalysisResponse(
            has_feedback=False,
            message="Dados insuficientes para análise",
            period_days=days,
            average_ratings={},
            satisfaction_level="Sem dados",
            main_themes=[],
            improvement_areas=[],
            engagement_metrics={}
        )

    return FeedbackAnalysisResponse(
        has_feedback=True,
        feedback_count=analysis["feedback_count"],
        period_days=days,
        average_ratings=analysis["average_ratings"],
        satisfaction_level=analysis["satisfaction_level"],
        main_themes=analysis.get("main_themes", []),
        improvement_areas=analysis.get("improvement_areas", []),
        missing_interests=analysis.get("missing_interests", []),
        engagement_metrics=analysis.get("engagement_metrics", {})
    )


@router.post("/adapt", response_model=AdaptationResponse)
async def adapt_recommendations(
        force: bool = Query(False, description="Forçar adaptação mesmo sem mudanças significativas"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Adapta as recomendações com base no feedback e comportamento do usuário.

    - Ajusta pontuações de interesses
    - Modifica preferências de conteúdo
    - Sugere mudanças de trilha se necessário
    """
    user_id = current_user["id"]

    # Primeiro, analisar feedback recente
    analysis = analyze_user_engagement(db, user_id, 30)

    if not analysis["has_data"] and not force:
        return AdaptationResponse(
            adapted=False,
            reason="Dados insuficientes para adaptação",
            adaptations=[]
        )

    # Executar adaptações
    adaptation_result = adapt_user_recommendations(db, user_id, analysis, force)

    # Se houve adaptações significativas, adicionar XP
    if adaptation_result["adapted"] and len(adaptation_result["adaptations"]) > 0:
        from app.utils.gamification import add_user_xp
        add_user_xp(db, user_id, 10, "Sistema adaptado às suas preferências")

    return AdaptationResponse(
        adapted=adaptation_result["adapted"],
        reason=adaptation_result.get("reason", ""),
        adaptations=adaptation_result["adaptations"],
        timestamp=time.time()
    )


@router.get("/suggestions", response_model=ImprovementSuggestionsResponse)
async def get_improvement_suggestions(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera sugestões personalizadas para melhorar a experiência de aprendizado.

    - Baseado em padrões de uso
    - Considera personalidade e preferências
    - Sugere novos formatos e abordagens
    """
    user_id = current_user["id"]

    # Gerar sugestões personalizadas
    suggestions = generate_personalized_suggestions(db, user_id)

    return ImprovementSuggestionsResponse(
        suggestions=suggestions,
        generated_at=time.time()
    )


@router.get("/history")
async def get_feedback_history(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session_type: Optional[str] = Query(None, description="Filtrar por tipo de sessão"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o histórico de feedback do usuário.

    - Paginação com limit/offset
    - Filtros por tipo de sessão
    - Ordenação por data decrescente
    """
    user_id = current_user["id"]

    # Query base
    query = db.collection("user_feedback").where("user_id", "==", user_id)

    # Aplicar filtro de tipo se especificado
    if session_type:
        query = query.where("session_type", "==", session_type)

    # Ordenar por timestamp decrescente
    query = query.order_by("timestamp", direction="DESCENDING")

    # Aplicar paginação
    query = query.limit(limit).offset(offset)

    # Executar query
    feedback_list = []
    for doc in query.stream():
        feedback_data = doc.to_dict()
        feedback_data["id"] = doc.id
        feedback_list.append(feedback_data)

    return {
        "feedback": feedback_list,
        "total": len(feedback_list),
        "limit": limit,
        "offset": offset
    }