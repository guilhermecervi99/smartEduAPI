# app/schemas/user.py
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime

from app.config import get_settings

settings = get_settings()


# Request Schemas
class UserCreate(BaseModel):
    """Schema para criação de usuário"""
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    age: int = Field(default=14, ge=10, le=100)
    learning_style: Optional[str] = "didático"

    @field_validator('learning_style')
    @classmethod
    def validate_learning_style(cls, v):
        if v and v not in settings.teaching_styles:
            raise ValueError(f"Invalid learning style. Must be one of: {list(settings.teaching_styles.keys())}")
        return v


class UserUpdate(BaseModel):
    """Schema para atualização de usuário"""
    email: Optional[EmailStr] = None
    age: Optional[int] = Field(None, ge=10, le=100)
    learning_style: Optional[str] = None
    current_track: Optional[str] = None

    @field_validator('learning_style')
    @classmethod
    def validate_learning_style(cls, v):
        if v and v not in settings.teaching_styles:
            raise ValueError(f"Invalid learning style. Must be one of: {list(settings.teaching_styles.keys())}")
        return v


class UserLogin(BaseModel):
    """Schema para login"""
    username: str  # Pode ser email ou user_id
    password: Optional[str] = None


class PreferencesUpdate(BaseModel):
    """Schema para atualizar preferências"""
    age: Optional[int] = Field(None, ge=10, le=100)
    learning_style: Optional[str] = None
    current_track: Optional[str] = None
    current_subarea: Optional[str] = None


# Response Schemas
class UserBase(BaseModel):
    """Schema base de usuário para respostas"""
    id: str
    email: Optional[str] = None
    age: int
    learning_style: str
    current_track: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserPublic(UserBase):
    """Schema público do usuário (sem dados sensíveis)"""
    profile_level: int
    profile_xp: int
    badges: List[str] = []


class UserProfile(UserPublic):
    """Schema completo do perfil do usuário"""
    recommended_track: Optional[str] = None
    track_scores: Optional[Dict[str, float]] = None
    completed_lessons_count: int = 0
    completed_modules_count: int = 0
    completed_projects_count: int = 0
    active_projects_count: int = 0
    certifications_count: int = 0


class UserProgress(BaseModel):
    """Schema de progresso do usuário"""
    area: str
    subarea: str
    level: str
    module_index: int
    lesson_index: int
    step_index: int
    progress_percentage: float = 0.0


class UserStatistics(BaseModel):
    """Schema de estatísticas do usuário"""
    profile_level: int
    profile_xp: int
    total_badges: int
    completed_lessons: int
    completed_modules: int
    completed_projects: int
    active_projects: int
    certifications: int
    days_active: int
    last_activity: Optional[float] = None
    strongest_area: Optional[str] = None
    current_streak: int = 0


# Token Schemas
class Token(BaseModel):
    """Schema de token de autenticação"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str  # Adicionar user_id ao schema


class TokenPayload(BaseModel):
    """Payload do token JWT"""
    sub: Optional[str] = None
    exp: Optional[int] = None