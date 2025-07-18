from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion, ArrayRemove
import time

from app.core.security import get_current_user
from app.database import get_db, Collections
from app.schemas.community import (
    TeamResponse,
    TeamCreateRequest,
    TeamJoinRequest,
    MentorshipRequest,
    TeamListResponse,
    MentorListResponse
)
from app.utils.gamification import add_user_xp, grant_badge

router = APIRouter()


@router.get("/teams", response_model=TeamListResponse)
async def get_teams(
        area: Optional[str] = Query(None),
        is_private: Optional[bool] = Query(None),
        has_space: bool = Query(False),
        limit: int = Query(20, ge=1, le=50),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Lista times disponíveis com filtros
    """
    teams_ref = db.collection("teams")

    # Aplicar filtros
    query = teams_ref

    if area:
        query = query.where("area", "==", area)

    if is_private is not None:
        query = query.where("is_private", "==", is_private)

    # Limitar resultados
    query = query.limit(limit)

    teams = []
    for doc in query.stream():
        team_data = doc.to_dict()
        team_data["id"] = doc.id

        # Filtrar por espaço disponível
        if has_space and team_data.get("member_count", 0) >= team_data.get("max_members", 10):
            continue

        teams.append(TeamResponse(**team_data))

    return TeamListResponse(
        teams=teams,
        total=len(teams),
        user_teams=[t for t in teams if current_user["id"] in t.get("members", [])]
    )


@router.post("/teams", response_model=TeamResponse)
async def create_team(
        request: TeamCreateRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Cria um novo time
    """
    # Criar time
    team_data = {
        "name": request.name,
        "description": request.description,
        "area": request.area,
        "is_private": request.is_private,
        "max_members": request.max_members or 10,
        "members": [current_user["id"]],
        "member_count": 1,
        "leader_id": current_user["id"],
        "created_at": time.time(),
        "chat_enabled": True,
        "projects": []
    }

    # Salvar no Firestore
    team_ref = db.collection("teams").add(team_data)
    team_id = team_ref[1].id

    # Adicionar XP e badge
    add_user_xp(db, current_user["id"], 20, f"Criou o time: {request.name}")
    grant_badge(db, current_user["id"], "Líder de Equipe")

    return TeamResponse(id=team_id, **team_data)


@router.post("/teams/{team_id}/join")
async def join_team(
        team_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Entrar em um time
    """
    team_ref = db.collection("teams").document(team_id)
    team_doc = team_ref.get()

    if not team_doc.exists:
        raise HTTPException(status_code=404, detail="Time não encontrado")

    team_data = team_doc.to_dict()

    # Verificar se já é membro
    if current_user["id"] in team_data.get("members", []):
        raise HTTPException(status_code=400, detail="Você já é membro deste time")

    # Verificar se há espaço
    if team_data.get("member_count", 0) >= team_data.get("max_members", 10):
        raise HTTPException(status_code=400, detail="Time está cheio")

    # Adicionar membro
    team_ref.update({
        "members": ArrayUnion([current_user["id"]]),
        "member_count": team_data.get("member_count", 0) + 1
    })

    # Adicionar XP
    add_user_xp(db, current_user["id"], 10, f"Entrou no time: {team_data['name']}")

    # Se for o primeiro time, dar badge
    user_teams = db.collection("teams").where("members", "array_contains", current_user["id"]).get()
    if len(list(user_teams)) == 1:
        grant_badge(db, current_user["id"], "Trabalho em Equipe")

    return {"message": "Entrou no time com sucesso", "team_id": team_id}


@router.get("/mentors", response_model=MentorListResponse)
async def get_mentors(
        area: Optional[str] = Query(None),
        is_available: bool = Query(True),
        limit: int = Query(20, ge=1, le=50),
        db=Depends(get_db)
) -> Any:
    """
    Lista mentores disponíveis
    """
    mentors_ref = db.collection("mentors")

    # Aplicar filtros
    query = mentors_ref

    if is_available:
        query = query.where("is_available", "==", True)

    query = query.limit(limit)

    mentors = []
    for doc in query.stream():
        mentor_data = doc.to_dict()

        # Filtrar por área se especificado
        if area and area not in mentor_data.get("areas", []):
            continue

        # Buscar dados do usuário mentor
        user_doc = db.collection(Collections.USERS).document(mentor_data["user_id"]).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            mentor_data["display_name"] = user_data.get("email", "").split("@")[0]
            mentor_data["level"] = user_data.get("profile_level", 1)
            mentor_data["badges_count"] = len(user_data.get("badges", []))

        mentors.append(mentor_data)

    return MentorListResponse(
        mentors=mentors,
        total=len(mentors)
    )


@router.post("/mentorship/request")
async def request_mentorship(
        request: MentorshipRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Solicitar mentoria
    """
    # Verificar se mentor existe
    mentor_doc = db.collection("mentors").where("user_id", "==", request.mentor_id).get()
    if not list(mentor_doc):
        raise HTTPException(status_code=404, detail="Mentor não encontrado")

    mentor_data = list(mentor_doc)[0].to_dict()

    if not mentor_data.get("is_available"):
        raise HTTPException(status_code=400, detail="Mentor não está disponível")

    # Criar solicitação
    mentorship_data = {
        "mentor_id": request.mentor_id,
        "mentee_id": current_user["id"],
        "message": request.message,
        "status": "pending",
        "created_at": time.time(),
        "area": request.area or current_user.get("current_track")
    }

    db.collection("mentorship_requests").add(mentorship_data)

    # Adicionar XP
    add_user_xp(db, current_user["id"], 5, "Solicitou mentoria")

    return {"message": "Solicitação enviada com sucesso"}


@router.post("/become-mentor")
async def become_mentor(
        areas: List[str],
        bio: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Tornar-se um mentor
    """
    # Verificar nível mínimo
    if current_user.get("profile_level", 1) < 10:
        raise HTTPException(
            status_code=400,
            detail="Você precisa ser pelo menos nível 10 para ser mentor"
        )

    # Verificar se já é mentor
    existing = db.collection("mentors").where("user_id", "==", current_user["id"]).get()
    if list(existing):
        raise HTTPException(status_code=400, detail="Você já é um mentor")

    # Criar perfil de mentor
    mentor_data = {
        "user_id": current_user["id"],
        "areas": areas,
        "bio": bio,
        "is_available": True,
        "rating": 0.0,
        "mentees_count": 0,
        "created_at": time.time()
    }

    db.collection("mentors").add(mentor_data)

    # Adicionar badge e XP
    grant_badge(db, current_user["id"], "Mentor")
    add_user_xp(db, current_user["id"], 50, "Tornou-se mentor")

    return {"message": "Você agora é um mentor!"}   