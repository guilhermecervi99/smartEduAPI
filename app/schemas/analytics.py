# app/schemas/analytics.py
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime


# Request Models
class AssessmentGenerationRequest(BaseModel):
    area: Optional[str] = None
    subarea: Optional[str] = None
    level: Optional[str] = None
    focus_area: Optional[str] = None
    difficulty: Optional[str] = "adaptive"  # easy, medium, hard, adaptive
    question_count: int = 10


class StudySessionGenerationRequest(BaseModel):
    topic: Optional[str] = None
    duration_minutes: int = 30
    session_type: str = "mixed"  # theory, practice, mixed
    difficulty: Optional[str] = None
    include_practice: bool = True


class LearningPathGenerationRequest(BaseModel):
    duration_weeks: int = 4
    goals: Optional[List[str]] = None
    focus_areas: Optional[List[str]] = None
    time_available: str = "flexible"  # flexible, limited, intensive
    include_projects: bool = True
    include_assessments: bool = True


# Response Models
class SmartAssessmentResponse(BaseModel):
    assessment_id: str
    assessment: Dict[str, Any]
    metadata: Dict[str, Any]


class FocusedSessionResponse(BaseModel):
    session_id: str
    session: Dict[str, Any]
    personalization: Dict[str, Any]


class AdaptiveLearningPathResponse(BaseModel):
    path_id: str
    learning_path: Dict[str, Any]
    personalization: Dict[str, Any]
    estimated_completion_date: str


# Dashboard Models
class DashboardMetrics(BaseModel):
    current_level: int
    current_xp: int
    total_badges: int
    current_streak: int
    completed_lessons: int
    completed_modules: int
    active_projects: int
    current_area: str
    current_subarea: str
    progress_percentage: float
    today_stats: Optional[Dict[str, Any]] = None
    week_stats: Optional[Dict[str, Any]] = None