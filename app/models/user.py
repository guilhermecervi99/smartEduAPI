# app/models/user.py
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr


class UserProgress(BaseModel):
    """Estrutura de progresso do usuário"""
    area: str = ""
    subareas_order: List[str] = []
    current: Dict[str, Any] = Field(default_factory=lambda: {
        "subarea": "",
        "level": "iniciante",
        "module_index": 0,
        "lesson_index": 0,
        "step_index": 0
    })


class MappingRecord(BaseModel):
    """Registro de mapeamento de interesses"""
    date: str
    track: str
    score: float
    top_interests: Dict[str, float]


class CompletedItem(BaseModel):
    """Item completado genérico"""
    title: str
    completion_date: str
    area: Optional[str] = None
    subarea: Optional[str] = None
    level: Optional[str] = None
    module: Optional[str] = None


class ProjectRecord(BaseModel):
    """Registro de projeto"""
    title: str
    type: str
    start_date: str
    status: str = "in_progress"
    description: Optional[str] = ""
    completion_date: Optional[str] = None
    outcomes: Optional[List[str]] = None
    evidence_urls: Optional[List[str]] = None


class CertificationRecord(BaseModel):
    """Registro de certificação"""
    title: str
    date: str
    id: str
    area: Optional[str] = None
    subarea: Optional[str] = None


class XPHistoryRecord(BaseModel):
    """Registro de histórico de XP"""
    amount: int
    reason: str
    timestamp: float


class User(BaseModel):
    """Modelo completo do usuário"""
    id: Optional[str] = None

    # Informações básicas
    email: Optional[EmailStr] = None
    age: Optional[int] = 14
    created_at: Optional[float] = None
    last_login: Optional[float] = None

    # Preferências de aprendizado
    learning_style: str = "didático"
    current_track: Optional[str] = None
    recommended_track: Optional[str] = None

    # Progresso
    progress: Optional[UserProgress] = None
    saved_progress: Optional[Dict[str, Dict]] = None

    # Gamificação
    profile_xp: int = 0
    profile_level: int = 1
    badges: List[str] = []
    xp_history: List[XPHistoryRecord] = []

    # Mapeamento e scores
    track_scores: Optional[Dict[str, float]] = None
    mapping_history: List[MappingRecord] = []

    # Conclusões
    completed_lessons: List[CompletedItem] = []
    completed_modules: List[CompletedItem] = []
    completed_levels: List[CompletedItem] = []
    completed_subareas: List[str] = []
    completed_specializations: List[Dict[str, Any]] = []

    # Projetos
    started_projects: List[ProjectRecord] = []
    completed_projects: List[ProjectRecord] = []

    # Avaliações
    passed_assessments: List[Dict[str, Any]] = []
    passed_final_assessments: List[Dict[str, Any]] = []

    # Certificações
    certifications: List[CertificationRecord] = []

    # Especializações
    specializations_started: List[Dict[str, Any]] = []

    # Recursos acessados
    accessed_resources: List[Dict[str, Any]] = []

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat(),
        }
    }


class UserInDB(User):
    """Modelo do usuário no banco de dados"""
    hashed_password: Optional[str] = None