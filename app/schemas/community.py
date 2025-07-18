from typing import List, Optional
from pydantic import BaseModel, Field

class TeamResponse(BaseModel):
    id: str
    name: str
    description: str
    area: str
    is_private: bool
    max_members: int
    members: List[str]
    member_count: int
    leader_id: str
    created_at: float
    chat_enabled: bool
    projects: List[str]

class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    description: str = Field(..., min_length=10, max_length=200)
    area: str
    is_private: bool = False
    max_members: Optional[int] = Field(10, ge=2, le=20)

class TeamJoinRequest(BaseModel):
    team_id: str

class MentorshipRequest(BaseModel):
    mentor_id: str
    message: str = Field(..., min_length=10, max_length=500)
    area: Optional[str] = None

class TeamListResponse(BaseModel):
    teams: List[TeamResponse]
    total: int
    user_teams: List[TeamResponse]

class MentorResponse(BaseModel):
    user_id: str
    display_name: str
    areas: List[str]
    bio: str
    is_available: bool
    rating: float
    mentees_count: int
    level: Optional[int] = None
    badges_count: Optional[int] = None

class MentorListResponse(BaseModel):
    mentors: List[MentorResponse]
    total: int