# app/schemas/progress.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ProgressResponse(BaseModel):
    """Resposta com progresso atual do usuário"""
    user_id: str
    area: str
    subarea: str
    level: str
    module_index: int
    lesson_index: int
    step_index: int
    progress_percentage: float
    subareas_order: List[str] = []
    last_updated: float


class LessonCompletionRequest(BaseModel):
    """Requisição para completar uma lição"""
    lesson_title: str
    area_name: Optional[str] = None
    subarea_name: Optional[str] = None
    level_name: Optional[str] = None
    module_title: Optional[str] = None
    advance_progress: bool = True


class ModuleCompletionRequest(BaseModel):
    """Requisição para completar um módulo"""
    module_title: str
    area_name: Optional[str] = None
    subarea_name: Optional[str] = None
    level_name: Optional[str] = None
    advance_progress: bool = True


class LevelCompletionRequest(BaseModel):
    """Requisição para completar um nível"""
    area_name: str
    subarea_name: str
    level_name: str
    advance_progress: bool = True


class ProjectStartRequest(BaseModel):
    """Requisição para iniciar um projeto"""
    title: str
    project_type: str
    description: Optional[str] = None


class ProjectCompletionRequest(BaseModel):
    """Requisição para completar um projeto"""
    title: str
    project_type: str
    description: Optional[str] = None
    outcomes: Optional[List[str]] = None
    evidence_urls: Optional[List[str]] = None


class AssessmentCompletionRequest(BaseModel):
    """Requisição para completar uma avaliação"""
    score: float = Field(..., ge=0, le=100)
    assessment_type: str  # "final" ou "module"
    module_title: Optional[str] = None
    level_name: Optional[str] = None


class CertificationRequest(BaseModel):
    """Requisição para emitir uma certificação"""
    title: str
    area_name: Optional[str] = None
    subarea_name: Optional[str] = None


class ProgressStatistics(BaseModel):
    """Estatísticas de progresso do usuário"""
    completed_lessons: int
    completed_modules: int
    completed_levels: int
    completed_projects: int
    active_projects: int
    certifications: int
    current_streak: int
    total_study_time_minutes: int
    strongest_area: Optional[str] = None
    last_activity: Optional[float] = None


class UserProgressPath(BaseModel):
    """Caminho de progresso do usuário"""
    area: str
    available_subareas: List[str]
    current_subarea: str
    current_level: str
    subareas_order: List[str]
    progress_percentage: float


class NextStepResponse(BaseModel):
    """Resposta com próximos passos recomendados"""
    user_id: str
    recommendations: List[str]
    generated_at: float