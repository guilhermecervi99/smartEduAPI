# app/schemas/content.py
from pydantic import BaseModel
from typing import Dict, List, Optional, Any


class AreaInfo(BaseModel):
    name: str
    description: str
    subarea_count: int
    is_current: bool
    metadata: Optional[Dict[str, Any]] = None
    resource_count: Optional[int] = None


class AreaListResponse(BaseModel):
    areas: List[AreaInfo]
    total_count: int
    user_current_area: Optional[str] = None


class SubareaInfo(BaseModel):
    name: str
    description: str
    estimated_time: str
    level_count: int
    specialization_count: int
    has_career_info: bool


class AreaDetailResponse(BaseModel):
    name: str
    description: str
    subareas: List[SubareaInfo]
    metadata: Dict[str, Any]
    resources: Dict[str, Any]
    total_subareas: int


class LevelInfo(BaseModel):
    name: str
    description: str
    module_count: int
    has_final_project: bool
    has_final_assessment: bool
    prerequisites: List[str]


class SpecializationInfo(BaseModel):
    name: str
    description: str
    age_range: str
    prerequisites: List[str]
    module_count: int
    estimated_time: str


class SubareaDetailResponse(BaseModel):
    area_name: str
    name: str
    description: str
    estimated_time: str
    levels: List[LevelInfo]
    specializations: List[SpecializationInfo]
    resources: Dict[str, Any]
    career_exploration: Dict[str, Any]
    metadata: Dict[str, Any]


class LevelDetailResponse(BaseModel):
    area_name: str
    subarea_name: str
    name: str
    description: str
    modules: List[Dict[str, Any]]
    prerequisites: List[str]
    learning_outcomes: List[str]
    has_final_project: bool
    has_final_assessment: bool


class ModuleDetailResponse(BaseModel):
    title: str
    description: str
    lessons: List[Dict[str, Any]]
    has_project: bool
    has_assessment: bool
    resources: List[Dict[str, Any]]


class ContentMetadataResponse(BaseModel):
    age_appropriate: bool
    prerequisite_subjects: List[str]
    cross_curricular: List[str]
    school_aligned: bool
    difficulty_level: str
    estimated_duration: str