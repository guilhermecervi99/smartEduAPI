# app/schemas/projects.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ProjectResponse(BaseModel):
    """Resposta com dados de um projeto"""
    id: str
    title: str
    description: str
    type: str
    status: str
    start_date: str
    completion_date: Optional[str] = None
    outcomes: List[str] = []
    evidence_urls: List[str] = []


class ProjectCreateRequest(BaseModel):
    """Requisição para criar um projeto"""
    title: str
    type: str
    description: Optional[str] = None
    area: Optional[str] = None
    subarea: Optional[str] = None
    level: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    """Requisição para atualizar um projeto"""
    description: Optional[str] = None
    outcomes: Optional[List[str]] = None
    evidence_urls: Optional[List[str]] = None


class ProjectSubmissionRequest(BaseModel):
    """Requisição para submeter um projeto concluído"""
    final_outcomes: Optional[List[str]] = None
    evidence_urls: Optional[List[str]] = None
    reflection: Optional[str] = None


class ProjectFeedbackRequest(BaseModel):
    """Requisição para feedback de projeto"""
    difficulty_rating: int = Field(..., ge=1, le=5)
    engagement_rating: int = Field(..., ge=1, le=5)
    relevance_rating: int = Field(..., ge=1, le=5)
    comments: Optional[str] = None
    suggestions: Optional[str] = None


class ProjectSearchRequest(BaseModel):
    """Requisição para busca de projetos"""
    query: str
    project_type: Optional[str] = None
    status: Optional[str] = None


class ProjectListResponse(BaseModel):
    """Resposta com lista de projetos"""
    projects: List[ProjectResponse]
    total: int
    active_count: int
    completed_count: int


class ProjectDetailResponse(ProjectResponse):
    """Resposta detalhada de um projeto"""
    area: Optional[str] = None
    subarea: Optional[str] = None
    level: Optional[str] = None
    curriculum_requirements: List[str] = []
    curriculum_deliverables: List[str] = []
