# app/schemas/achievements.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BadgeResponse(BaseModel):
    """Resposta com dados de uma badge"""
    id: str
    name: str
    description: str
    earned_date: Optional[str] = None
    rarity: str  # common, rare, epic, legendary
    icon_url: str


class BadgeCategory(BaseModel):
    """Categoria de badges"""
    name: str
    key: str
    badges: List[BadgeResponse]
    total_count: int


class AchievementProgress(BaseModel):
    """Progresso em uma conquista"""
    badge_name: str
    description: str
    current_progress: int
    target_progress: int
    progress_percentage: float


class UserAchievementsResponse(BaseModel):
    """Resposta com conquistas do usuário"""
    user_id: str
    total_badges: int
    profile_level: int
    profile_xp: int
    next_level_xp_needed: int
    xp_progress_percentage: float
    current_streak: int
    badge_categories: List[BadgeCategory]
    achievement_progress: List[AchievementProgress]


class LeaderboardResponse(BaseModel):
    """Resposta com leaderboard"""
    category: str
    entries: List[Dict[str, Any]]
    current_user_position: Optional[int] = None
    total_users: int
    last_updated: float


class StreakResponse(BaseModel):
    """Resposta com dados de streak"""
    current_streak: int
    longest_streak: int
    total_study_days: int
    last_activity_date: float
    next_milestone: Optional[int] = None
    days_until_milestone: int
    streak_level: str


class XPHistoryResponse(BaseModel):
    """Resposta com histórico de XP"""
    period_days: int
    total_xp_gained: int
    avg_daily_xp: float
    daily_breakdown: Dict[str, int]
    source_breakdown: Dict[str, int]
    recent_activities: List[Dict[str, Any]]
    current_total_xp: int


class AchievementResponse(BaseModel):
    """Resposta com dados de uma conquista"""
    id: str
    name: str
    description: str
    category: str
    requirements: List[str]
    reward_xp: int
    is_unlocked: bool
    progress_percentage: float