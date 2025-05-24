# app/api/v1/endpoints/projects.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion
import time

from app.core.security import get_current_user, get_current_user_id_required
from app.database import get_db, Collections
from app.schemas.projects import (
    ProjectResponse,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectSubmissionRequest,
    ProjectFeedbackRequest,
    ProjectSearchRequest,
    ProjectListResponse,
    ProjectDetailResponse
)
from app.utils.gamification import add_user_xp, grant_badge, XP_REWARDS

router = APIRouter()


@router.get("/", response_model=ProjectListResponse)
async def list_user_projects(
        status_filter: Optional[str] = Query(None, description="Filter by status: in_progress, completed, all"),
        project_type: Optional[str] = Query(None, description="Filter by type: final, module, lesson, personal"),
        limit: int = Query(20, ge=1, le=50),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Lista os projetos do usuário com filtros opcionais
    """
    started_projects = current_user.get("started_projects", [])
    completed_projects = current_user.get("completed_projects", [])

    # Criar lista de títulos de projetos concluídos para filtragem
    completed_titles = {p.get("title") for p in completed_projects}

    # Filtrar projetos ativos
    active_projects = [
        {**p, "status": "in_progress"}
        for p in started_projects
        if p.get("title") not in completed_titles
    ]

    # Adicionar projetos concluídos
    all_projects = active_projects + [{**p, "status": "completed"} for p in completed_projects]

    # Aplicar filtros
    filtered_projects = all_projects

    if status_filter and status_filter != "all":
        filtered_projects = [p for p in filtered_projects if p.get("status") == status_filter]

    if project_type:
        filtered_projects = [p for p in filtered_projects if p.get("type") == project_type]

    # Limitar resultados
    filtered_projects = filtered_projects[:limit]

    # Converter para resposta
    projects = []
    for project in filtered_projects:
        projects.append(ProjectResponse(
            id=f"{current_user['id']}_{project.get('title', '')}_{int(time.time())}",
            title=project.get("title", ""),
            description=project.get("description", ""),
            type=project.get("type", "personal"),
            status=project.get("status", "in_progress"),
            start_date=project.get("start_date", ""),
            completion_date=project.get("completion_date"),
            outcomes=project.get("outcomes", []),
            evidence_urls=project.get("evidence_urls", [])
        ))

    return ProjectListResponse(
        projects=projects,
        total=len(filtered_projects),
        active_count=len(active_projects),
        completed_count=len(completed_projects)
    )


@router.post("/", response_model=ProjectResponse)
async def create_project(
        request: ProjectCreateRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Cria um novo projeto para o usuário
    """
    user_id = current_user["id"]

    # Verificar se já existe um projeto com o mesmo título
    started_projects = current_user.get("started_projects", [])
    completed_projects = current_user.get("completed_projects", [])

    all_titles = [p.get("title") for p in started_projects + completed_projects]
    if request.title in all_titles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A project with this title already exists"
        )

    # Criar estrutura do projeto
    project_data = {
        "title": request.title,
        "type": request.type,
        "description": request.description or "",
        "start_date": time.strftime("%Y-%m-%d"),
        "status": "in_progress",
        "area": request.area,
        "subarea": request.subarea,
        "level": request.level
    }

    # Adicionar à lista de projetos iniciados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "started_projects": ArrayUnion([project_data])
    })

    # Adicionar XP baseado no tipo do projeto
    xp_amount = XP_REWARDS.get("start_project", 10)
    if request.type == "final":
        xp_amount = 15
    elif request.type == "module":
        xp_amount = 12

    add_user_xp(db, user_id, xp_amount, f"Iniciou projeto: {request.title}")

    return ProjectResponse(
        id=f"{user_id}_{request.title}_{int(time.time())}",
        title=request.title,
        description=request.description or "",
        type=request.type,
        status="in_progress",
        start_date=project_data["start_date"],
        completion_date=None,
        outcomes=[],
        evidence_urls=[]
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project_details(
        project_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém detalhes completos de um projeto específico
    """
    # Extrair título do project_id (simplificado)
    try:
        project_title = project_id.split("_")[1]
    except IndexError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project ID format"
        )

    # Buscar projeto
    started_projects = current_user.get("started_projects", [])
    completed_projects = current_user.get("completed_projects", [])

    project = None
    project_status = "not_found"

    # Buscar em projetos iniciados
    for p in started_projects:
        if p.get("title") == project_title:
            project = p
            project_status = "in_progress"
            break

    # Se não encontrou, buscar em projetos concluídos
    if not project:
        for p in completed_projects:
            if p.get("title") == project_title:
                project = p
                project_status = "completed"
                break

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Buscar informações adicionais do currículo se disponível
    curriculum_info = None
    if project.get("area"):
        area_ref = db.collection(Collections.LEARNING_PATHS).document(project["area"])
        area_doc = area_ref.get()

        if area_doc.exists and project.get("subarea"):
            area_data = area_doc.to_dict()
            subareas = area_data.get("subareas", {})

            if project["subarea"] in subareas:
                subarea_data = subareas[project["subarea"]]
                levels = subarea_data.get("levels", {})

                if project.get("level") and project["level"] in levels:
                    level_data = levels[project["level"]]

                    # Buscar projeto relacionado no currículo
                    for module in level_data.get("modules", []):
                        if module.get("module_project", {}).get("title") == project_title:
                            curriculum_info = module.get("module_project")
                            break

                    # Buscar projeto final se não encontrou nos módulos
                    if not curriculum_info:
                        final_project = level_data.get("final_project", {})
                        if final_project.get("title") == project_title:
                            curriculum_info = final_project

    return ProjectDetailResponse(
        id=project_id,
        title=project.get("title", ""),
        description=project.get("description", ""),
        type=project.get("type", "personal"),
        status=project_status,
        start_date=project.get("start_date", ""),
        completion_date=project.get("completion_date"),
        outcomes=project.get("outcomes", []),
        evidence_urls=project.get("evidence_urls", []),
        area=project.get("area"),
        subarea=project.get("subarea"),
        level=project.get("level"),
        curriculum_requirements=curriculum_info.get("requirements", []) if curriculum_info else [],
        curriculum_deliverables=curriculum_info.get("deliverables", []) if curriculum_info else []
    )


@router.put("/{project_id}")
async def update_project(
        project_id: str,
        request: ProjectUpdateRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Atualiza informações de um projeto
    """
    user_id = current_user["id"]

    # Extrair título do project_id
    try:
        project_title = project_id.split("_")[1]
    except IndexError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project ID format"
        )

    # Buscar e atualizar projeto
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    started_projects = user_data.get("started_projects", [])

    # Encontrar e atualizar o projeto
    updated_projects = []
    project_found = False

    for project in started_projects:
        if project.get("title") == project_title:
            project_found = True
            updated_project = project.copy()

            # Atualizar campos fornecidos
            if request.description is not None:
                updated_project["description"] = request.description

            if request.outcomes is not None:
                updated_project["outcomes"] = request.outcomes

            if request.evidence_urls is not None:
                updated_project["evidence_urls"] = request.evidence_urls

            updated_project["last_updated"] = time.strftime("%Y-%m-%d")
            updated_projects.append(updated_project)
        else:
            updated_projects.append(project)

    if not project_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Atualizar no banco
    user_ref.update({"started_projects": updated_projects})

    return {"message": "Project updated successfully"}


@router.post("/{project_id}/complete")
async def complete_project(
        project_id: str,
        request: ProjectSubmissionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Marca um projeto como concluído
    """
    user_id = current_user["id"]

    # Extrair título do project_id
    try:
        project_title = project_id.split("_")[1]
    except IndexError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project ID format"
        )

    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    started_projects = user_data.get("started_projects", [])

    # Encontrar o projeto
    project_to_complete = None
    updated_started_projects = []

    for project in started_projects:
        if project.get("title") == project_title:
            project_to_complete = project.copy()
        else:
            updated_started_projects.append(project)

    if not project_to_complete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Criar projeto concluído
    completed_project = project_to_complete.copy()
    completed_project["completion_date"] = time.strftime("%Y-%m-%d")
    completed_project["status"] = "completed"

    if request.final_outcomes:
        completed_project["outcomes"] = request.final_outcomes

    if request.evidence_urls:
        completed_project["evidence_urls"] = request.evidence_urls

    if request.reflection:
        completed_project["reflection"] = request.reflection

    # Atualizar no banco
    user_ref.update({
        "started_projects": updated_started_projects,
        "completed_projects": ArrayUnion([completed_project])
    })

    # Adicionar XP e badges
    xp_amount = XP_REWARDS.get("complete_project", 25)
    if project_to_complete.get("type") == "final":
        xp_amount = XP_REWARDS.get("complete_final_project", 50)
        grant_badge(db, user_id, f"Projeto Final: {project_title[:20]}")
    elif project_to_complete.get("type") == "module":
        xp_amount = 35

    xp_result = add_user_xp(db, user_id, xp_amount, f"Completou projeto: {project_title}")

    return {
        "message": "Project completed successfully",
        "xp_earned": xp_result["xp_added"],
        "new_level": xp_result["new_level"] if xp_result["level_up"] else None,
        "completion_date": completed_project["completion_date"]
    }


@router.post("/{project_id}/feedback")
async def submit_project_feedback(
        project_id: str,
        request: ProjectFeedbackRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Permite ao usuário fornecer feedback sobre um projeto
    """
    user_id = current_user["id"]

    # Extrair título do project_id
    try:
        project_title = project_id.split("_")[1]
    except IndexError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project ID format"
        )

    # Criar registro de feedback
    feedback_data = {
        "project_id": project_id,
        "project_title": project_title,
        "user_id": user_id,
        "difficulty_rating": request.difficulty_rating,
        "engagement_rating": request.engagement_rating,
        "relevance_rating": request.relevance_rating,
        "comments": request.comments or "",
        "suggestions": request.suggestions or "",
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d")
    }

    # Salvar feedback
    db.collection("project_feedback").add(feedback_data)

    # Adicionar XP por fornecer feedback
    add_user_xp(db, user_id, 5, f"Forneceu feedback para projeto: {project_title}")

    return {
        "message": "Feedback submitted successfully",
        "xp_earned": 5
    }


@router.get("/available/{area}/{subarea}")
async def get_available_projects(
        area: str,
        subarea: str,
        level: Optional[str] = Query("iniciante", description="Learning level"),
        db=Depends(get_db),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Obtém projetos disponíveis para uma área/subárea específica
    """
    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Area not found"
        )

    area_data = area_doc.to_dict()
    subareas = area_data.get("subareas", {})

    if subarea not in subareas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subarea not found"
        )

    subarea_data = subareas[subarea]
    levels = subarea_data.get("levels", {})

    if level not in levels:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Level not found"
        )

    level_data = levels[level]

    # Coletar todos os projetos disponíveis
    available_projects = []

    # Projeto final do nível
    final_project = level_data.get("final_project", {})
    if final_project:
        available_projects.append({
            "title": final_project.get("title", "Projeto Final"),
            "description": final_project.get("description", ""),
            "type": "final",
            "source": "Nível",
            "requirements": final_project.get("requirements", []),
            "deliverables": final_project.get("deliverables", []),
            "estimated_duration": final_project.get("estimated_duration", "")
        })

    # Projetos dos módulos
    for module in level_data.get("modules", []):
        module_title = module.get("module_title", "")

        # Projeto do módulo
        module_project = module.get("module_project", {})
        if module_project:
            available_projects.append({
                "title": module_project.get("title", f"Projeto do Módulo: {module_title}"),
                "description": module_project.get("description", ""),
                "type": "module",
                "source": f"Módulo: {module_title}",
                "requirements": module_project.get("requirements", []),
                "deliverables": module_project.get("deliverables", []),
                "estimated_duration": module_project.get("estimated_duration", "")
            })

        # Projetos das lições
        for lesson in module.get("lessons", []):
            lesson_title = lesson.get("lesson_title", "")
            lesson_project = lesson.get("project", {})

            if lesson_project:
                available_projects.append({
                    "title": lesson_project.get("title", f"Projeto da Lição: {lesson_title}"),
                    "description": lesson_project.get("description", ""),
                    "type": "lesson",
                    "source": f"Lição: {lesson_title} (Módulo: {module_title})",
                    "requirements": lesson_project.get("requirements", []),
                    "deliverables": lesson_project.get("deliverables", []),
                    "estimated_duration": lesson_project.get("estimated_duration", "")
                })

    # Projetos de descoberta
    discovery_projects = level_data.get("discovery_projects", [])
    for project in discovery_projects:
        available_projects.append({
            "title": project.get("title", "Projeto de Descoberta"),
            "description": project.get("description", ""),
            "type": "discovery",
            "source": "Projetos de Descoberta",
            "requirements": project.get("requirements", []),
            "deliverables": project.get("deliverables", []),
            "estimated_duration": project.get("estimated_duration", "")
        })

    return {
        "area": area,
        "subarea": subarea,
        "level": level,
        "available_projects": available_projects,
        "total_count": len(available_projects)
    }


@router.get("/search")
async def search_projects(
        query: str = Query(..., description="Search query"),
        project_type: Optional[str] = Query(None, description="Filter by type"),
        status: Optional[str] = Query(None, description="Filter by status"),
        limit: int = Query(10, ge=1, le=50),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Busca projetos do usuário por termo
    """
    started_projects = current_user.get("started_projects", [])
    completed_projects = current_user.get("completed_projects", [])

    # Combinar todos os projetos
    all_projects = []

    # Projetos ativos
    completed_titles = {p.get("title") for p in completed_projects}
    for project in started_projects:
        if project.get("title") not in completed_titles:
            all_projects.append({**project, "status": "in_progress"})

    # Projetos concluídos
    for project in completed_projects:
        all_projects.append({**project, "status": "completed"})

    # Filtrar por busca textual
    query_lower = query.lower()
    filtered_projects = []

    for project in all_projects:
        title = project.get("title", "").lower()
        description = project.get("description", "").lower()

        if query_lower in title or query_lower in description:
            filtered_projects.append(project)

    # Aplicar filtros adicionais
    if project_type:
        filtered_projects = [p for p in filtered_projects if p.get("type") == project_type]

    if status:
        filtered_projects = [p for p in filtered_projects if p.get("status") == status]

    # Limitar resultados
    filtered_projects = filtered_projects[:limit]

    return {
        "query": query,
        "results": filtered_projects,
        "total_found": len(filtered_projects)
    }