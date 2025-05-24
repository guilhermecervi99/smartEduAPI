# app/api/v1/endpoints/content_navigation.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
import time

from app.core.security import get_current_user
from app.database import get_db, Collections
from app.schemas.content import (
    AreaListResponse,
    AreaDetailResponse,
    SubareaDetailResponse,
    LevelDetailResponse,
    ModuleDetailResponse,
    ContentMetadataResponse
)
from app.utils.gamification import add_user_xp

router = APIRouter()


@router.get("/areas", response_model=AreaListResponse)
async def browse_areas(
        include_metadata: bool = Query(True, description="Incluir metadados das áreas"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Lista todas as áreas de aprendizado disponíveis.

    - Descrições e metadados
    - Contagem de subáreas
    - Indicação de progresso do usuário
    """
    user_id = current_user["id"]
    current_track = current_user.get("current_track", "")

    # Buscar todas as áreas
    areas_ref = db.collection(Collections.LEARNING_PATHS).stream()
    areas = []

    for area_doc in areas_ref:
        area_name = area_doc.id
        area_data = area_doc.to_dict()

        area_info = {
            "name": area_name,
            "description": area_data.get("description", ""),
            "subarea_count": len(area_data.get("subareas", {})),
            "is_current": area_name == current_track
        }

        if include_metadata:
            meta = area_data.get("meta", {})
            area_info["metadata"] = {
                "age_appropriate": meta.get("age_appropriate", True),
                "prerequisite_subjects": meta.get("prerequisite_subjects", []),
                "cross_curricular": meta.get("cross_curricular", []),
                "school_aligned": meta.get("school_aligned", True)
            }

        # Verificar recursos disponíveis
        resources = area_data.get("resources", {})
        area_info["resource_count"] = sum(
            len(resources.get(key, []))
            for key in ["beginner_friendly", "intermediate", "advanced",
                        "books", "online_courses", "tools", "videos"]
        )

        areas.append(area_info)

    # Adicionar XP por explorar áreas
    add_user_xp(db, user_id, 2, "Explorou áreas disponíveis")

    return AreaListResponse(
        areas=areas,
        total_count=len(areas),
        user_current_area=current_track
    )


@router.get("/areas/{area_name}", response_model=AreaDetailResponse)
async def get_area_details(
        area_name: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém detalhes completos de uma área específica.

    - Lista de subáreas com descrições
    - Recursos disponíveis
    - Metadados e pré-requisitos
    """
    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{area_name}' não encontrada"
        )

    area_data = area_doc.to_dict()

    # Processar subáreas
    subareas = []
    for subarea_name, subarea_data in area_data.get("subareas", {}).items():
        subarea_info = {
            "name": subarea_name,
            "description": subarea_data.get("description", ""),
            "estimated_time": subarea_data.get("estimated_time", ""),
            "level_count": len(subarea_data.get("levels", {})),
            "specialization_count": len(subarea_data.get("specializations", [])),
            "has_career_info": "career_exploration" in subarea_data
        }
        subareas.append(subarea_info)

    # Metadados
    meta = area_data.get("meta", {})

    return AreaDetailResponse(
        name=area_name,
        description=area_data.get("description", ""),
        subareas=subareas,
        metadata=meta,
        resources=area_data.get("resources", {}),
        total_subareas=len(subareas)
    )


@router.get("/areas/{area_name}/subareas/{subarea_name}",
            response_model=SubareaDetailResponse)
async def get_subarea_details(
        area_name: str,
        subarea_name: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém detalhes completos de uma subárea.

    - Níveis disponíveis
    - Especializações
    - Recursos específicos
    - Informações de carreira
    """
    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{area_name}' não encontrada"
        )

    area_data = area_doc.to_dict()
    subareas = area_data.get("subareas", {})

    if subarea_name not in subareas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subárea '{subarea_name}' não encontrada"
        )

    subarea_data = subareas[subarea_name]

    # Processar níveis
    levels = []
    for level_name, level_data in subarea_data.get("levels", {}).items():
        level_info = {
            "name": level_name,
            "description": level_data.get("description", ""),
            "module_count": len(level_data.get("modules", [])),
            "has_final_project": "final_project" in level_data,
            "has_final_assessment": "final_assessment" in level_data,
            "prerequisites": level_data.get("prerequisites", [])
        }
        levels.append(level_info)

    # Processar especializações
    specializations = []
    for spec in subarea_data.get("specializations", []):
        spec_info = {
            "name": spec.get("name", ""),
            "description": spec.get("description", ""),
            "age_range": spec.get("age_range", ""),
            "prerequisites": spec.get("prerequisites", []),
            "module_count": len(spec.get("modules", [])),
            "estimated_time": spec.get("estimated_time", "")
        }
        specializations.append(spec_info)

    return SubareaDetailResponse(
        area_name=area_name,
        name=subarea_name,
        description=subarea_data.get("description", ""),
        estimated_time=subarea_data.get("estimated_time", ""),
        levels=levels,
        specializations=specializations,
        resources=subarea_data.get("resources", {}),
        career_exploration=subarea_data.get("career_exploration", {}),
        metadata=subarea_data.get("meta", {})
    )


@router.post("/areas/{area_name}/set-current")
async def set_current_area(
        area_name: str,
        subarea_name: Optional[str] = Query(None, description="Subárea inicial"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Define a área atual do usuário.

    - Preserva progresso anterior
    - Inicializa nova estrutura de progresso
    - Concede XP e badges
    """
    user_id = current_user["id"]
    old_track = current_user.get("current_track", "")

    # Verificar se a área existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{area_name}' não encontrada"
        )

    area_data = area_doc.to_dict()

    # Se não especificou subárea, pegar a primeira disponível
    if not subarea_name:
        subareas = list(area_data.get("subareas", {}).keys())
        if subareas:
            subarea_name = subareas[0]

    # Preservar progresso anterior se houver
    saved_progress = current_user.get("saved_progress", {})
    if old_track and old_track != area_name and "progress" in current_user:
        saved_progress[old_track] = current_user["progress"]

    # Criar ou restaurar progresso
    if area_name in saved_progress:
        # Restaurar progresso salvo
        new_progress = saved_progress[area_name]
    else:
        # Criar novo progresso
        new_progress = {
            "area": area_name,
            "subareas_order": list(area_data.get("subareas", {}).keys()),
            "current": {
                "subarea": subarea_name or "",
                "level": "iniciante",
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            }
        }

    # Atualizar usuário
    updates = {
        "current_track": area_name,
        "progress": new_progress,
        "saved_progress": saved_progress
    }

    db.collection(Collections.USERS).document(user_id).update(updates)

    # Adicionar XP
    from app.utils.gamification import add_user_xp, grant_badge
    add_user_xp(db, user_id, 5, f"Mudou para área: {area_name}")

    # Badge se for primeira vez nesta área
    if area_name not in saved_progress:
        grant_badge(db, user_id, f"Explorador de {area_name}")

    return {
        "message": "Área definida com sucesso",
        "area": area_name,
        "subarea": subarea_name or new_progress["current"]["subarea"],
        "is_new_area": area_name not in saved_progress
    }


@router.get("/explore/dynamic")
async def get_dynamic_exploration_menu(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Retorna opções para exploração dinâmica de conteúdo.

    - Áreas recomendadas baseadas em interesses
    - Conteúdos em destaque
    - Sugestões personalizadas
    """
    user_id = current_user["id"]
    track_scores = current_user.get("track_scores", {})
    current_track = current_user.get("current_track", "")

    # Ordenar áreas por pontuação
    recommended_areas = []
    if track_scores:
        sorted_tracks = sorted(track_scores.items(), key=lambda x: x[1], reverse=True)

        for track, score in sorted_tracks[:5]:  # Top 5
            if track != current_track:  # Excluir área atual
                area_ref = db.collection(Collections.LEARNING_PATHS).document(track)
                area_doc = area_ref.get()

                if area_doc.exists:
                    area_data = area_doc.to_dict()
                    recommended_areas.append({
                        "name": track,
                        "description": area_data.get("description", ""),
                        "compatibility_score": score,
                        "subarea_count": len(area_data.get("subareas", {}))
                    })

    # Buscar conteúdos em destaque (especializações populares)
    featured_content = []

    # Coletar todas as especializações
    areas_ref = db.collection(Collections.LEARNING_PATHS).stream()
    for area_doc in areas_ref:
        area_name = area_doc.id
        area_data = area_doc.to_dict()

        for subarea_name, subarea_data in area_data.get("subareas", {}).items():
            for spec in subarea_data.get("specializations", []):
                if spec.get("featured", False):  # Se marcada como destaque
                    featured_content.append({
                        "type": "specialization",
                        "area": area_name,
                        "subarea": subarea_name,
                        "name": spec.get("name", ""),
                        "description": spec.get("description", "")
                    })

    # Sugestões baseadas no perfil
    suggestions = []

    # Se ainda não tem área definida
    if not current_track:
        suggestions.append({
            "type": "action",
            "title": "Complete o mapeamento de interesses",
            "description": "Descubra sua área ideal de aprendizado",
            "action": "start_mapping"
        })

    # Se tem baixo engajamento recente
    last_activity = current_user.get("last_login", 0)
    if time.time() - last_activity > 7 * 24 * 60 * 60:  # 7 dias
        suggestions.append({
            "type": "motivation",
            "title": "Volte aos estudos!",
            "description": "Que tal continuar de onde parou?",
            "action": "continue_learning"
        })

    return {
        "recommended_areas": recommended_areas,
        "featured_content": featured_content,
        "personalized_suggestions": suggestions,
        "exploration_mode": "dynamic"
    }