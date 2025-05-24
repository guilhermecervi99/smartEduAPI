# app/schemas/llm.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TeacherQuestionRequest(BaseModel):
    """Requisição para pergunta ao professor virtual"""
    question: str = Field(..., min_length=3, max_length=1000)
    context: Optional[str] = Field(None, max_length=500)


class TeacherQuestionResponse(BaseModel):
    """Resposta do professor virtual"""
    question: str
    answer: str
    context: str
    teaching_style: str
    xp_earned: int


class LessonGenerationRequest(BaseModel):
    """Requisição para gerar uma aula"""
    topic: str = Field(..., min_length=3, max_length=200)
    subject_area: str
    knowledge_level: str = "iniciante"
    teaching_style: Optional[str] = None
    duration_minutes: int = Field(30, ge=15, le=180)


class LessonGenerationResponse(BaseModel):
    """Resposta com aula gerada"""
    lesson_content: Dict[str, Any]
    topic: str
    subject_area: str
    knowledge_level: str
    teaching_style: str
    duration_minutes: int
    xp_earned: int


class AssessmentGenerationRequest(BaseModel):
    """Requisição para gerar avaliação"""
    topic: str = Field(..., min_length=3, max_length=200)
    difficulty: str = "médio"
    num_questions: int = Field(5, ge=1, le=20)
    question_types: List[str] = ["múltipla escolha", "verdadeiro/falso"]


class AssessmentGenerationResponse(BaseModel):
    """Resposta com avaliação gerada"""
    assessment: Dict[str, Any]
    topic: str
    difficulty: str
    num_questions: int
    question_types: List[str]
    xp_earned: int


class LearningPathRequest(BaseModel):
    """Requisição para gerar roteiro de aprendizado"""
    topic: str = Field(..., min_length=3, max_length=200)
    duration_weeks: int = Field(8, ge=1, le=52)
    hours_per_week: int = Field(3, ge=1, le=40)
    initial_level: str = "iniciante"
    target_level: str = "intermediário"


class LearningPathResponse(BaseModel):
    """Resposta com roteiro de aprendizado"""
    pathway: Dict[str, Any]
    topic: str
    duration_weeks: int
    hours_per_week: int
    initial_level: str
    target_level: str
    xp_earned: int


class ContentAnalysisRequest(BaseModel):
    """Requisição para análise de conteúdo"""
    content: str = Field(..., min_length=10, max_length=5000)


class ContentAnalysisResponse(BaseModel):
    """Resposta com análise de conteúdo"""
    content_preview: str
    analysis: Dict[str, Any]
    recommendations: List[str]
    xp_earned: int


class ContentSimplificationRequest(BaseModel):
    """Requisição para simplificar conteúdo"""
    content: str = Field(..., min_length=10, max_length=5000)
    target_age: Optional[int] = Field(None, ge=10, le=18)


class ContentEnrichmentRequest(BaseModel):
    """Requisição para enriquecer conteúdo"""
    content: str = Field(..., min_length=10, max_length=5000)
    enrichment_type: str = "exemplos"  # exemplos, analogias, perguntas, etc.