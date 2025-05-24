# app/api/v1/api.py
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    users,
    mapping,
    progress,
    resources,
    achievements,
    projects,
    llm
)

api_router = APIRouter()

# Incluir todos os endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(mapping.router, prefix="/mapping", tags=["mapping"])
api_router.include_router(progress.router, prefix="/progress", tags=["progress"])
api_router.include_router(resources.router, prefix="/resources", tags=["resources"])
api_router.include_router(achievements.router, prefix="/achievements", tags=["achievements"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(llm.router, prefix="/llm", tags=["llm"])