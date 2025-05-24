# app/schemas/feedback.py
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime


class RatingsModel(BaseModel):
    relevance: int = Field(..., ge=1, le=5)
    clarity: int = Field(..., ge=1, le=5)
    usefulness: int = Field(..., ge=1, le=5)
    difficulty: Optional[int] = Field(None, ge=1, le=5)
    engagement: Optional[int] = Field(None, ge=1, le=5)


class FeedbackRequest(BaseModel):
    session_type: str = Field(..., description="Tipo de sessão: study, assessment, general, content")
    content_id: Optional[str] = None
    content_type: Optional[str] = None
    ratings: Optional[RatingsModel] = None
    missing_topics: Optional[str] = None
    suggestions: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class FeedbackResponse(BaseModel):
    feedback_id: str
    message: str
    xp_earned: int
    timestamp: float


class FeedbackAnalysisResponse(BaseModel):
    has_feedback: bool
    feedback_count: Optional[int] = None
    period_days: int
    average_ratings: Dict[str, float]
    satisfaction_level: str
    main_themes: List[str]
    improvement_areas: List[str]
    missing_interests: Optional[List[str]] = None
    engagement_metrics: Optional[Dict[str, Any]] = None


class AdaptationItem(BaseModel):
    type: str
    description: str
    reason: str
    impact: Optional[str] = None


class AdaptationResponse(BaseModel):
    adapted: bool
    reason: str
    adaptations: List[AdaptationItem]
    timestamp: float


class ImprovementSuggestion(BaseModel):
    title: str
    description: str
    benefit: str
    priority: Optional[str] = None


class ImprovementSuggestionsResponse(BaseModel):
    suggestions: List[ImprovementSuggestion]
    generated_at: float


