# app/schemas/resources.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ResourceCategory(BaseModel):
    """Categoria de recurso"""
    key: str
    name: str


class ResourceResponse(BaseModel):
    """Resposta com dados de um recurso"""
    id: str
    title: str
    description: str
    type: str
    category: ResourceCategory
    url: str
    author: str
    language: str
    level: str
    tags: List[str] = []
    rating: float = 0.0
    estimated_duration: str


class ResourceAccessRequest(BaseModel):
    """Requisição para registrar acesso a recurso"""
    resource_id: str
    title: str
    resource_type: str
    area: str


class ResourceFeedbackRequest(BaseModel):
    """Requisição para feedback de recurso"""
    resource_id: str
    rating: int = Field(..., ge=1, le=5)
    usefulness_rating: int = Field(..., ge=1, le=5)
    difficulty_rating: int = Field(..., ge=1, le=5)
    comments: Optional[str] = None
    would_recommend: bool


class CareerPathway(BaseModel):
    """Caminho de carreira"""
    path_name: str
    description: str
    steps: List[str]
    duration: str
    requirements: List[str]


class CareerExplorationResponse(BaseModel):
    """Resposta com exploração de carreiras"""
    area: str
    subarea: Optional[str] = None
    overview: str
    related_careers: List[Dict[str, Any]]
    career_pathways: List[CareerPathway]
    educational_paths: List[str]
    market_trends: str
    day_in_life: List[str]
    industry_connections: List[str]
    additional_resources: List[str]


class SpecializationResponse(BaseModel):
    """Resposta com dados de especialização"""
    id: str
    name: str
    description: str
    age_range: str
    prerequisites: List[str]
    modules: List[Any]
    learning_outcomes: List[str]
    skills_developed: List[str]
    related_careers: List[str]
    estimated_time: str
    final_project: Dict[str, Any]
    meets_prerequisites: bool
    is_started: bool
    is_completed: bool


class StudyPlanResponse(BaseModel):
    """Resposta com plano de estudos"""
    user_id: str
    current_area: str
    current_subarea: str
    current_level: str
    progress_summary: Dict[str, int]
    current_objectives: List[str]
    recommendations: List[str]
    next_areas: List[Dict[str, Any]]
    study_schedule: Dict[str, Any]


class ResourceSearchRequest(BaseModel):
    """Requisição para busca de recursos"""
    query: str
    area: Optional[str] = None
    resource_type: Optional[str] = None
    level: Optional[str] = None