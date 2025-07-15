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

# Adicionar constante no início do arquivo
VALID_LEVELS = ["iniciante", "intermediário", "avançado"]


# Adicionar função de validação
def normalize_level_name(level: str) -> str:
    """Normaliza o nome do nível para o padrão correto"""
    level_lower = level.lower().strip()

    # Mapeamento de variações
    level_map = {
        "intermediario": "intermediário",
        "avancado": "avançado",
        "básico": "iniciante",
        "basico": "iniciante"
    }

    normalized = level_map.get(level_lower, level_lower)

    # Validar se está na lista de níveis válidos
    if normalized not in VALID_LEVELS:
        return "iniciante"  # Padrão seguro

    return normalized

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
    SEMPRE começa do início (índices 0)
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
        # Criar novo progresso - SEMPRE DO INÍCIO
        new_progress = {
            "area": area_name,
            "subareas_order": list(area_data.get("subareas", {}).keys()),
            "current": {
                "subarea": subarea_name or "",
                "level": "iniciante",
                "module_index": 0,  # Primeiro módulo
                "lesson_index": 0,  # Primeira lição
                "step_index": 0     # Primeiro passo
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


# Adicionar estes endpoints ao arquivo content_navigation.py

@router.get("/areas/{area_name}/subareas/{subarea_name:path}/levels/{level_name}",
            response_model=LevelDetailResponse)
async def get_level_details(
        area_name: str,
        subarea_name: str,
        level_name: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém detalhes completos de um nível específico.

    - Módulos disponíveis
    - Pré-requisitos
    - Objetivos de aprendizagem
    - Projetos e avaliações
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
    levels = subarea_data.get("levels", {})

    if level_name not in levels:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nível '{level_name}' não encontrado"
        )

    level_data = levels[level_name]

    # Processar módulos
    modules = []
    for module in level_data.get("modules", []):
        module_info = {
            "title": module.get("module_title", ""),
            "description": module.get("description", ""),
            "lessons": module.get("lessons", []),
            "has_project": "module_project" in module,
            "has_assessment": "assessment" in module,
            "resources": module.get("resources", [])
        }
        modules.append(module_info)

    return LevelDetailResponse(
        area_name=area_name,
        subarea_name=subarea_name,
        name=level_name,
        description=level_data.get("description", ""),
        modules=modules,
        prerequisites=level_data.get("prerequisites", []),
        learning_outcomes=level_data.get("learning_outcomes", []),
        has_final_project="final_project" in level_data,
        has_final_assessment="final_assessment" in level_data
    )


@router.get("/areas/{area_name}/subareas/{subarea_name}/levels/{level_name}/modules/{module_index}",
            response_model=ModuleDetailResponse)
async def get_module_details(
        area_name: str,
        subarea_name: str,
        level_name: str,
        module_index: int,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém detalhes completos de um módulo específico.

    - Lições do módulo
    - Projeto do módulo
    - Avaliação do módulo
    - Recursos adicionais
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

    # Navegar até o módulo
    try:
        subarea_data = area_data["subareas"][subarea_name]
        level_data = subarea_data["levels"][level_name]
        modules = level_data.get("modules", [])

        if module_index >= len(modules):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Módulo com índice {module_index} não encontrado"
            )

        module_data = modules[module_index]

    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Caminho não encontrado: {str(e)}"
        )

    # Adicionar XP por explorar módulo
    add_user_xp(db, current_user["id"], 2, f"Explorou módulo: {module_data.get('module_title', '')}")

    return ModuleDetailResponse(
        title=module_data.get("module_title", ""),
        description=module_data.get("description", ""),
        lessons=module_data.get("lessons", []),
        has_project="module_project" in module_data,
        has_assessment="assessment" in module_data,
        resources=module_data.get("resources", [])
    )


@router.get("/content/{content_id}/metadata", response_model=ContentMetadataResponse)
async def get_content_metadata(
        content_id: str,
        content_type: str = Query(..., description="Tipo: area, subarea, level, module"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém metadados de qualquer conteúdo.

    - Adequação por idade
    - Pré-requisitos
    - Conexões curriculares
    - Nível de dificuldade
    """
    # Parse do content_id (formato: area_name[/subarea_name[/level_name[/module_index]]])
    parts = content_id.split("/")

    if len(parts) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de conteúdo inválido"
        )

    area_name = parts[0]

    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{area_name}' não encontrada"
        )

    area_data = area_doc.to_dict()
    metadata = area_data.get("meta", {})

    # Se for conteúdo mais específico, buscar metadados específicos
    if len(parts) > 1 and content_type == "subarea":
        subarea_name = parts[1]
        subarea_data = area_data.get("subareas", {}).get(subarea_name, {})
        subarea_meta = subarea_data.get("meta", {})
        # Mesclar metadados
        metadata.update(subarea_meta)

    elif len(parts) > 2 and content_type == "level":
        subarea_name = parts[1]
        level_name = parts[2]
        try:
            level_data = area_data["subareas"][subarea_name]["levels"][level_name]
            level_meta = level_data.get("meta", {})
            metadata.update(level_meta)
        except KeyError:
            pass

    # Determinar adequação por idade
    user_age = current_user.get("age", 14)
    age_range = metadata.get("age_range", "11-17")
    min_age, max_age = map(int, age_range.split("-"))
    age_appropriate = min_age <= user_age <= max_age

    # Estimar duração baseada no tipo
    duration_map = {
        "area": "6-12 meses",
        "subarea": "2-3 meses",
        "level": "4-6 semanas",
        "module": "1-2 semanas"
    }

    return ContentMetadataResponse(
        age_appropriate=age_appropriate,
        prerequisite_subjects=metadata.get("prerequisite_subjects", []),
        cross_curricular=metadata.get("cross_curricular", []),
        school_aligned=metadata.get("school_aligned", True),
        difficulty_level=metadata.get("difficulty_level", "médio"),
        estimated_duration=duration_map.get(content_type, "variável")
    )


@router.get("/search/content")
async def search_all_content(
        q: str = Query(..., min_length=3, description="Termo de busca"),
        content_types: List[str] = Query(["all"], description="Tipos: area, subarea, level, module, lesson"),
        limit: int = Query(20, ge=1, le=50),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Busca em todo o conteúdo disponível.

    - Busca em títulos, descrições e palavras-chave
    - Filtra por tipo de conteúdo
    - Retorna resultados ranqueados
    """
    query_lower = q.lower()
    results = []

    # Buscar em todas as áreas
    areas_ref = db.collection(Collections.LEARNING_PATHS).stream()

    for area_doc in areas_ref:
        area_name = area_doc.id
        area_data = area_doc.to_dict()

        # Buscar na área
        if "all" in content_types or "area" in content_types:
            if query_lower in area_name.lower() or query_lower in area_data.get("description", "").lower():
                results.append({
                    "type": "area",
                    "id": area_name,
                    "title": area_name,
                    "description": area_data.get("description", ""),
                    "path": area_name,
                    "score": 1.0 if query_lower in area_name.lower() else 0.8
                })

        # Buscar nas subáreas
        if "all" in content_types or "subarea" in content_types:
            for subarea_name, subarea_data in area_data.get("subareas", {}).items():
                if query_lower in subarea_name.lower() or query_lower in subarea_data.get("description", "").lower():
                    results.append({
                        "type": "subarea",
                        "id": f"{area_name}/{subarea_name}",
                        "title": subarea_name,
                        "description": subarea_data.get("description", ""),
                        "path": f"{area_name} > {subarea_name}",
                        "score": 0.9 if query_lower in subarea_name.lower() else 0.7
                    })

                # Buscar nos níveis
                if "all" in content_types or "level" in content_types:
                    for level_name, level_data in subarea_data.get("levels", {}).items():
                        if query_lower in level_name.lower() or query_lower in level_data.get("description",
                                                                                              "").lower():
                            results.append({
                                "type": "level",
                                "id": f"{area_name}/{subarea_name}/{level_name}",
                                "title": f"Nível {level_name.capitalize()}",
                                "description": level_data.get("description", ""),
                                "path": f"{area_name} > {subarea_name} > {level_name}",
                                "score": 0.8 if query_lower in level_name.lower() else 0.6
                            })

                        # Buscar nos módulos
                        if "all" in content_types or "module" in content_types:
                            for idx, module in enumerate(level_data.get("modules", [])):
                                module_title = module.get("module_title", "")
                                if query_lower in module_title.lower():
                                    results.append({
                                        "type": "module",
                                        "id": f"{area_name}/{subarea_name}/{level_name}/{idx}",
                                        "title": module_title,
                                        "description": module.get("description", ""),
                                        "path": f"{area_name} > {subarea_name} > {level_name} > Módulo {idx + 1}",
                                        "score": 0.7
                                    })

                                # Buscar nas lições
                                if "all" in content_types or "lesson" in content_types:
                                    for lesson_idx, lesson in enumerate(module.get("lessons", [])):
                                        lesson_title = lesson.get("lesson_title", "")
                                        if query_lower in lesson_title.lower():
                                            results.append({
                                                "type": "lesson",
                                                "id": f"{area_name}/{subarea_name}/{level_name}/{idx}/{lesson_idx}",
                                                "title": lesson_title,
                                                "description": lesson.get("objectives", ""),
                                                "path": f"{area_name} > {subarea_name} > {level_name} > {module_title} > Lição {lesson_idx + 1}",
                                                "score": 0.6
                                            })

    # Ordenar por score
    results.sort(key=lambda x: x["score"], reverse=True)

    # Limitar resultados
    results = results[:limit]

    # Adicionar XP por pesquisar
    if results:
        add_user_xp(db, current_user["id"], 1, f"Pesquisou conteúdo: {q}")

    return {
        "query": q,
        "results": results,
        "total_found": len(results),
        "content_types": content_types
    }


@router.get("/navigation/breadcrumb")
async def get_navigation_breadcrumb(
        path: str = Query(..., description="Caminho: area/subarea/level/module"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Retorna a navegação em formato breadcrumb com links para cada nível.
    """
    parts = path.split("/")
    breadcrumb = []

    # Construir breadcrumb progressivamente
    for i, part in enumerate(parts):
        current_path = "/".join(parts[:i + 1])
        level_names = ["area", "subarea", "level", "module"]

        breadcrumb.append({
            "name": part,
            "path": current_path,
            "type": level_names[i] if i < len(level_names) else "item",
            "is_current": i == len(parts) - 1
        })

    return {
        "breadcrumb": breadcrumb,
        "current_path": path
    }