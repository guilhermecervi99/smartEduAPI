# app/api/v1/endpoints/resources.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion
import time

from app.core.security import get_current_user, get_current_user_id_required
from app.database import get_db, Collections
from app.schemas.resources import (
    ResourceResponse,
    ResourceCategory,
    ResourceAccessRequest,
    ResourceFeedbackRequest,
    CareerExplorationResponse,
    CareerPathway,
    SpecializationResponse,
    StudyPlanResponse,
    ResourceSearchRequest
)
from app.utils.gamification import add_user_xp

router = APIRouter()


@router.get("/learning/{area}", response_model=List[ResourceResponse])
async def get_learning_resources(
        area: str,
        subarea: Optional[str] = Query(None, description="Specific subarea"),
        level: Optional[str] = Query(None, description="Learning level filter"),
        category: Optional[str] = Query(None, description="Resource category filter"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém recursos de aprendizado para uma área específica
    """
    user_id = current_user["id"]

    # Buscar dados da área no Firestore
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Area not found"
        )

    area_data = area_doc.to_dict()

    # Determinar fonte de recursos
    resources = {}

    # Recursos da área geral
    area_resources = area_data.get("resources", {})

    # Recursos específicos da subárea, se especificada
    if subarea and subarea in area_data.get("subareas", {}):
        subarea_data = area_data["subareas"][subarea]
        subarea_resources = subarea_data.get("resources", {})
        # Combinar recursos (priorizar recursos da subárea)
        resources = {**area_resources, **subarea_resources}
    else:
        resources = area_resources

    if not resources:
        return []

    # Converter recursos para formato de resposta
    resource_list = []

    # Mapear categorias disponíveis
    category_mapping = {
        "beginner_friendly": "Iniciante",
        "intermediate": "Intermediário",
        "advanced": "Avançado",
        "books": "Livros",
        "online_courses": "Cursos Online",
        "tools": "Ferramentas",
        "videos": "Vídeos",
        "youtube_channels": "Canais YouTube",
        "datasets": "Conjuntos de Dados"
    }

    for resource_key, resource_category_name in category_mapping.items():
        if resource_key in resources:
            category_resources = resources[resource_key]

            # Filtrar por categoria se especificada
            if category and category != resource_key:
                continue

            for resource_item in category_resources:
                if isinstance(resource_item, dict):
                    resource_level = resource_item.get("level", "")

                    # Filtrar por nível se especificado
                    if level and level != resource_level and resource_level:
                        continue

                    resource_list.append(ResourceResponse(
                        id=f"{area}_{resource_key}_{len(resource_list)}",
                        title=resource_item.get("title", "Sem título"),
                        description=resource_item.get("description", ""),
                        type=resource_item.get("type", resource_category_name),
                        category=ResourceCategory(
                            key=resource_key,
                            name=resource_category_name
                        ),
                        url=resource_item.get("url", ""),
                        author=resource_item.get("author", ""),
                        language=resource_item.get("language", "pt-BR"),
                        level=resource_level or "geral",
                        tags=resource_item.get("tags", []),
                        rating=resource_item.get("rating", 0.0),
                        estimated_duration=resource_item.get("estimated_duration", "")
                    ))
                else:
                    # Se for apenas uma string
                    resource_list.append(ResourceResponse(
                        id=f"{area}_{resource_key}_{len(resource_list)}",
                        title=str(resource_item),
                        description="",
                        type=resource_category_name,
                        category=ResourceCategory(
                            key=resource_key,
                            name=resource_category_name
                        ),
                        url="",
                        author="",
                        language="pt-BR",
                        level="geral",
                        tags=[],
                        rating=0.0,
                        estimated_duration=""
                    ))

    # Registrar acesso aos recursos para XP
    if resource_list:
        add_user_xp(db, user_id, 3, f"Acessou recursos de aprendizado: {area}")

    return resource_list


@router.post("/access")
async def register_resource_access(
        request: ResourceAccessRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra o acesso a um recurso específico
    """
    user_id = current_user["id"]

    # Registrar acesso
    access_data = {
        "resource_id": request.resource_id,
        "title": request.title,
        "type": request.resource_type,
        "area": request.area,
        "access_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time()
    }

    # Adicionar à lista de recursos acessados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "accessed_resources": ArrayUnion([access_data])
    })

    # Adicionar XP
    add_user_xp(db, user_id, 2, f"Acessou recurso: {request.title}")

    return {
        "message": "Resource access registered successfully",
        "xp_earned": 2
    }


@router.post("/feedback")
async def submit_resource_feedback(
        request: ResourceFeedbackRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Permite ao usuário fornecer feedback sobre um recurso
    """
    user_id = current_user["id"]

    # Criar registro de feedback
    feedback_data = {
        "user_id": user_id,
        "resource_id": request.resource_id,
        "rating": request.rating,
        "usefulness_rating": request.usefulness_rating,
        "difficulty_rating": request.difficulty_rating,
        "comments": request.comments or "",
        "would_recommend": request.would_recommend,
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d")
    }

    # Salvar feedback
    db.collection("resource_feedback").add(feedback_data)

    # Adicionar XP por feedback
    add_user_xp(db, user_id, 3, "Forneceu feedback sobre recurso")

    return {
        "message": "Feedback submitted successfully",
        "xp_earned": 3
    }


@router.get("/careers/{area}", response_model=CareerExplorationResponse)
async def get_career_exploration(
        area: str,
        subarea: Optional[str] = Query(None, description="Specific subarea"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém informações sobre carreiras relacionadas a uma área
    """
    user_id = current_user["id"]

    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Area not found"
        )

    area_data = area_doc.to_dict()

    # Determinar fonte de dados de carreira
    career_data = None

    if subarea and subarea in area_data.get("subareas", {}):
        subarea_data = area_data["subareas"][subarea]
        career_data = subarea_data.get("career_exploration")

    # Se não encontrou na subárea, buscar na área geral
    if not career_data:
        career_data = area_data.get("career_exploration")

    if not career_data:
        # Gerar dados básicos se não existir
        career_data = {
            "overview": f"Explore as diversas oportunidades de carreira em {area}.",
            "related_careers": [
                f"Especialista em {area}",
                f"Consultor de {area}",
                f"Pesquisador em {area}"
            ]
        }

    # Converter carreiras relacionadas
    related_careers = []
    careers_list = career_data.get("related_careers", [])

    for career in careers_list:
        if isinstance(career, dict):
            related_careers.append(career)
        else:
            related_careers.append({
                "title": str(career),
                "description": "",
                "education_required": "",
                "key_skills": []
            })

    # Converter caminhos de carreira
    career_pathways = []
    pathways_list = career_data.get("career_pathways", [])

    for pathway in pathways_list:
        if isinstance(pathway, dict):
            career_pathways.append(CareerPathway(
                path_name=pathway.get("path_name", ""),
                description=pathway.get("description", ""),
                steps=pathway.get("steps", []),
                duration=pathway.get("duration", ""),
                requirements=pathway.get("requirements", [])
            ))

    # Adicionar XP por explorar carreiras
    add_user_xp(db, user_id, 5, f"Explorou carreiras em {area}")

    return CareerExplorationResponse(
        area=area,
        subarea=subarea,
        overview=career_data.get("overview", ""),
        related_careers=related_careers,
        career_pathways=career_pathways,
        educational_paths=career_data.get("educational_paths", []),
        market_trends=career_data.get("market_trends", ""),
        day_in_life=career_data.get("day_in_life", []),
        industry_connections=career_data.get("industry_connections", []),
        additional_resources=career_data.get("additional_resources", [])
    )


@router.get("/specializations/{area}/{subarea}", response_model=List[SpecializationResponse])
async def get_specializations(
        area: str,
        subarea: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém especializações disponíveis para uma subárea
    """
    user_id = current_user["id"]

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
    specializations = subarea_data.get("specializations", [])

    if not specializations:
        return []

    # Verificar pré-requisitos do usuário
    completed_levels = current_user.get("completed_levels", [])
    completed_level_names = [level.get("level") for level in completed_levels]

    specialization_list = []

    for spec in specializations:
        # Verificar pré-requisitos
        prereqs = spec.get("prerequisites", [])
        meets_prereqs = all(prereq in completed_level_names for prereq in prereqs)

        # Verificar se já foi iniciada
        specializations_started = current_user.get("specializations_started", [])
        is_started = any(s.get("name") == spec.get("name") for s in specializations_started)

        # Verificar se foi concluída
        completed_specializations = current_user.get("completed_specializations", [])
        is_completed = any(s.get("name") == spec.get("name") for s in completed_specializations)

        specialization_list.append(SpecializationResponse(
            id=f"{area}_{subarea}_{spec.get('name', '')}",
            name=spec.get("name", ""),
            description=spec.get("description", ""),
            age_range=spec.get("age_range", ""),
            prerequisites=prereqs,
            modules=spec.get("modules", []),
            learning_outcomes=spec.get("learning_outcomes", []),
            skills_developed=spec.get("skills_developed", []),
            related_careers=spec.get("related_careers", []),
            estimated_time=spec.get("estimated_time", ""),
            final_project=spec.get("final_project", {}),
            meets_prerequisites=meets_prereqs,
            is_started=is_started,
            is_completed=is_completed
        ))

    # Adicionar XP por explorar especializações
    if specialization_list:
        add_user_xp(db, user_id, 3, f"Explorou especializações em {subarea}")

    return specialization_list


@router.get("/study-plan", response_model=StudyPlanResponse)
async def get_study_plan(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera um plano de estudos personalizado baseado no progresso atual
    """
    user_id = current_user["id"]
    current_track = current_user.get("current_track", "")

    if not current_track:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must have an active learning track"
        )

    # Buscar dados da área atual
    area_ref = db.collection(Collections.LEARNING_PATHS).document(current_track)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning track data not found"
        )

    area_data = area_doc.to_dict()

    # Obter progresso atual
    progress = current_user.get("progress", {})
    current = progress.get("current", {})
    current_subarea = current.get("subarea", "")
    current_level = current.get("level", "iniciante")

    # Calcular estatísticas de progresso
    completed_lessons = len(current_user.get("completed_lessons", []))
    completed_modules = len(current_user.get("completed_modules", []))
    completed_projects = len(current_user.get("completed_projects", []))

    # Estimar tempo de estudo
    estimated_study_time = (completed_lessons * 30) + (completed_modules * 60) + (completed_projects * 120)

    # Gerar recomendações
    recommendations = []

    if current_subarea:
        subareas = area_data.get("subareas", {})
        if current_subarea in subareas:
            subarea_data = subareas[current_subarea]

            # Verificar próximos passos no nível atual
            levels = subarea_data.get("levels", {})
            if current_level in levels:
                level_data = levels[current_level]
                modules = level_data.get("modules", [])

                module_index = current.get("module_index", 0)
                if module_index < len(modules):
                    current_module = modules[module_index]
                    recommendations.append(f"Continuar módulo: {current_module.get('module_title', 'Módulo atual')}")

                # Verificar projetos disponíveis
                if level_data.get("final_project"):
                    recommendations.append("Considerar projeto final do nível")

                # Verificar especializações disponíveis
                specializations = subarea_data.get("specializations", [])
                if specializations:
                    recommendations.append("Explorar especializações disponíveis")

    # Sugestões gerais
    if completed_lessons < 5:
        recommendations.append("Focar em completar mais lições básicas")

    if completed_projects == 0:
        recommendations.append("Iniciar primeiro projeto prático")

    # Próximas áreas recomendadas
    track_scores = current_user.get("track_scores", {})
    next_areas = []
    if track_scores:
        sorted_tracks = sorted(track_scores.items(), key=lambda x: x[1], reverse=True)
        for track, score in sorted_tracks[1:4]:  # Pular a área atual
            next_areas.append({
                "area": track,
                "score": score,
                "reason": f"Alta compatibilidade com seus interesses ({score:.2f})"
            })

    # Adicionar XP por visualizar plano de estudos
    add_user_xp(db, user_id, 2, "Visualizou plano de estudos")

    return StudyPlanResponse(
        user_id=user_id,
        current_area=current_track,
        current_subarea=current_subarea,
        current_level=current_level,
        progress_summary={
            "completed_lessons": completed_lessons,
            "completed_modules": completed_modules,
            "completed_projects": completed_projects,
            "estimated_study_time_hours": estimated_study_time // 60
        },
        current_objectives=[
            "Avançar no nível atual",
            "Completar projetos práticos",
            "Explorar recursos adicionais"
        ],
        recommendations=recommendations,
        next_areas=next_areas,
        study_schedule={
            "recommended_hours_per_week": 3,
            "suggested_session_duration": 45,
            "optimal_study_times": ["Manhã", "Final da tarde"]
        }
    )


@router.get("/search")
async def search_resources(
        query: str = Query(..., description="Search query"),
        area: Optional[str] = Query(None, description="Filter by area"),
        resource_type: Optional[str] = Query(None, description="Filter by resource type"),
        level: Optional[str] = Query(None, description="Filter by level"),
        limit: int = Query(20, ge=1, le=50),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Busca recursos em todas as áreas disponíveis
    """
    user_id = current_user["id"]

    # Se área específica foi fornecida, buscar apenas nela
    if area:
        areas_to_search = [area]
    else:
        # Buscar em todas as áreas
        areas_ref = db.collection(Collections.LEARNING_PATHS).stream()
        areas_to_search = [doc.id for doc in areas_ref]

    all_results = []
    query_lower = query.lower()

    for area_name in areas_to_search:
        area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
        area_doc = area_ref.get()

        if not area_doc.exists:
            continue

        area_data = area_doc.to_dict()

        # Buscar em recursos da área
        area_resources = area_data.get("resources", {})
        search_in_resources(area_resources, area_name, "", query_lower, resource_type, level, all_results)

        # Buscar em recursos das subáreas
        subareas = area_data.get("subareas", {})
        for subarea_name, subarea_data in subareas.items():
            subarea_resources = subarea_data.get("resources", {})
            search_in_resources(subarea_resources, area_name, subarea_name, query_lower, resource_type, level,
                                all_results)

    # Limitar resultados
    limited_results = all_results[:limit]

    # Registrar busca para XP
    if limited_results:
        add_user_xp(db, user_id, 2, f"Pesquisou recursos: {query}")

    return {
        "query": query,
        "results": limited_results,
        "total_found": len(limited_results),
        "filters_applied": {
            "area": area,
            "resource_type": resource_type,
            "level": level
        }
    }


def search_in_resources(resources: dict, area_name: str, subarea_name: str,
                        query_lower: str, resource_type_filter: Optional[str],
                        level_filter: Optional[str], results_list: list):
    """
    Função auxiliar para buscar em recursos
    """
    for resource_key, resource_list in resources.items():
        for resource_item in resource_list:
            if isinstance(resource_item, dict):
                title = resource_item.get("title", "").lower()
                description = resource_item.get("description", "").lower()
                item_type = resource_item.get("type", resource_key).lower()
                item_level = resource_item.get("level", "").lower()

                # Verificar se corresponde à busca
                if query_lower in title or query_lower in description:
                    # Aplicar filtros
                    if resource_type_filter and resource_type_filter.lower() != item_type:
                        continue

                    if level_filter and level_filter.lower() != item_level:
                        continue

                    results_list.append({
                        "title": resource_item.get("title", ""),
                        "description": resource_item.get("description", ""),
                        "type": resource_item.get("type", resource_key),
                        "url": resource_item.get("url", ""),
                        "area": area_name,
                        "subarea": subarea_name,
                        "level": resource_item.get("level", ""),
                        "author": resource_item.get("author", ""),
                        "language": resource_item.get("language", "pt-BR")
                    })
            else:
                # Se for string simples
                if query_lower in str(resource_item).lower():
                    results_list.append({
                        "title": str(resource_item),
                        "description": "",
                        "type": resource_key,
                        "url": "",
                        "area": area_name,
                        "subarea": subarea_name,
                        "level": "",
                        "author": "",
                        "language": "pt-BR"
                    })