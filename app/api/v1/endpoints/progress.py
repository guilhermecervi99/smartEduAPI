# app/api/v1/endpoints/progress.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion
import time
from datetime import datetime, timedelta, date
import logging
from app.core.security import get_current_user, get_current_user_id_required
from app.database import get_db, Collections
from app.schemas.progress import (
    ProgressResponse,
    LessonCompletionRequest,
    ModuleCompletionRequest,
    LevelCompletionRequest,
    ProjectStartRequest,
    ProjectCompletionRequest,
    AssessmentCompletionRequest,
    CertificationRequest,
    ProgressStatistics,
    UserProgressPath,
    NextStepResponse,
    TrackSwitchRequest,
    SpecializationStartRequest,
    InitializeProgressRequest
)
from app.utils.gamification import add_user_xp, grant_badge, XP_REWARDS, calculate_study_streak
from app.utils.llm_integration import generate_complete_lesson, call_teacher_llm
from app.utils.progress_utils import (
    get_user_progress,
    advance_user_progress,
    calculate_progress_percentage,
    get_next_recommendations
)

# IMPORTAR O SERVIÇO DE EVENTOS
from app.services.event_service import event_service, EventTypes

router = APIRouter()
logger = logging.getLogger(__name__)
# Adicionar estas funções auxiliares ao início do arquivo progress.py

def ensure_navigation_context(user_data: dict, db) -> Dict[str, Any]:
    """
    Garante que sempre temos um contexto válido de navegação
    """
    progress = user_data.get("progress", {})

    # Valores padrão
    default_area = "Negócios e Empreendedorismo"
    default_subarea = "Finanças"
    default_level = "iniciante"

    # Extrair valores do progresso
    area = progress.get("area", "")
    current = progress.get("current", {})
    subarea = current.get("subarea", "")
    level = current.get("level", default_level)

    # Garantir que os índices nunca sejam None - SEMPRE começar do 0
    module_index = current.get("module_index", 0)
    lesson_index = current.get("lesson_index", 0)
    step_index = current.get("step_index", 0)

    # Converter None para 0 se necessário
    if module_index is None:
        module_index = 0
    if lesson_index is None:
        lesson_index = 0
    if step_index is None:
        step_index = 0

    # Se não tem área, buscar de outras fontes
    if not area:
        # Tentar current_track
        area = user_data.get("current_track", "")

        # Se ainda não tem, buscar da primeira área com progresso salvo
        if not area and user_data.get("saved_progress"):
            saved_areas = list(user_data.get("saved_progress", {}).keys())
            if saved_areas:
                area = saved_areas[0]
                saved_progress = user_data["saved_progress"][area]
                if "current" in saved_progress:
                    subarea = saved_progress["current"].get("subarea", "")
                    level = saved_progress["current"].get("level", default_level)
                    module_index = saved_progress["current"].get("module_index", 0) or 0
                    lesson_index = saved_progress["current"].get("lesson_index", 0) or 0
                    step_index = saved_progress["current"].get("step_index", 0) or 0

        # Se ainda não tem, usar padrão
        if not area:
            area = default_area

    # Se não tem subárea, buscar da estrutura da área
    if not subarea:
        try:
            area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
            area_doc = area_ref.get()

            if area_doc.exists:
                area_data = area_doc.to_dict()
                subareas = list(area_data.get("subareas", {}).keys())
                if subareas:
                    # Preferir subárea da ordem de progresso se existir
                    subareas_order = progress.get("subareas_order", [])
                    if subareas_order:
                        subarea = subareas_order[0]
                    else:
                        subarea = subareas[0]
        except:
            pass

        # Se ainda não tem, usar padrão
        if not subarea:
            subarea = default_subarea

    return {
        "area": area,
        "subarea": subarea,
        "level": level,
        "module_index": module_index,
        "lesson_index": lesson_index,
        "step_index": step_index
    }


def get_next_available_content(area_data: dict, current_context: dict, db) -> Dict[str, Any]:
    """
    Encontra o próximo conteúdo disponível quando o atual está completo
    """
    area = current_context["area"]
    subarea = current_context["subarea"]
    level = current_context["level"]

    levels_order = ["iniciante", "intermediário", "avançado"]
    subareas = list(area_data.get("subareas", {}).keys())

    # Verificar próximo nível na mesma subárea
    if level in levels_order:
        current_level_idx = levels_order.index(level)
        if current_level_idx < len(levels_order) - 1:
            next_level = levels_order[current_level_idx + 1]
            subarea_data = area_data.get("subareas", {}).get(subarea, {})
            if next_level in subarea_data.get("levels", {}):
                return {
                    "type": "next_level",
                    "area": area,
                    "subarea": subarea,
                    "level": next_level,
                    "module_index": 0,
                    "lesson_index": 0,
                    "step_index": 0
                }

    # Verificar próxima subárea
    if subarea in subareas:
        current_subarea_idx = subareas.index(subarea)
        if current_subarea_idx < len(subareas) - 1:
            next_subarea = subareas[current_subarea_idx + 1]
            return {
                "type": "next_subarea",
                "area": area,
                "subarea": next_subarea,
                "level": "iniciante",
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            }

    # Verificar outras áreas disponíveis
    try:
        areas_ref = db.collection(Collections.LEARNING_PATHS).stream()
        other_areas = []
        for area_doc in areas_ref:
            if area_doc.id != area:
                other_areas.append(area_doc.id)

        if other_areas:
            # Buscar primeira subárea da nova área
            new_area = other_areas[0]
            new_area_ref = db.collection(Collections.LEARNING_PATHS).document(new_area)
            new_area_doc = new_area_ref.get()

            if new_area_doc.exists:
                new_area_data = new_area_doc.to_dict()
                new_subareas = list(new_area_data.get("subareas", {}).keys())
                if new_subareas:
                    return {
                        "type": "new_area",
                        "area": new_area,
                        "subarea": new_subareas[0],
                        "level": "iniciante",
                        "module_index": 0,
                        "lesson_index": 0,
                        "step_index": 0
                    }
    except:
        pass

    # Se não encontrou nada, retornar sugestão de especialização
    return {
        "type": "specialization",
        "area": area,
        "subarea": subarea,
        "message": "Você completou todo o conteúdo básico! Que tal iniciar uma especialização?"
    }


@router.get("/current", response_model=ProgressResponse)
async def get_current_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o progresso atual detalhado do usuário
    SEMPRE retorna campos completos mesmo que sejam valores padrão
    """
    user_id = current_user["id"]

    # CORREÇÃO: Sempre garantir contexto válido
    nav_context = ensure_navigation_context(current_user, db)

    # Buscar progresso do usuário
    progress = get_user_progress(db, user_id)

    # Se não tem progresso ou está incompleto, criar/corrigir
    if not progress or not progress.get("area") or not progress.get("current", {}).get("subarea"):
        # Criar progresso padrão baseado no contexto
        progress = {
            "area": nav_context["area"],
            "current": {
                "subarea": nav_context["subarea"],
                "level": nav_context["level"],
                "module_index": nav_context["module_index"],
                "lesson_index": nav_context["lesson_index"],
                "step_index": nav_context["step_index"]
            },
            "subareas_order": []
        }

        # Salvar progresso padrão
        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({"progress": progress})

    # IMPORTANTE: Garantir que SEMPRE retornamos valores válidos
    return ProgressResponse(
        user_id=user_id,
        area=progress.get("area") or nav_context["area"],
        subarea=progress.get("current", {}).get("subarea") or nav_context["subarea"],
        level=progress.get("current", {}).get("level") or nav_context["level"],
        module_index=progress.get("current", {}).get("module_index", 0),
        lesson_index=progress.get("current", {}).get("lesson_index", 0),
        step_index=progress.get("current", {}).get("step_index", 0),
        progress_percentage=calculate_progress_percentage(db, user_id, progress) or 0.0,
        subareas_order=progress.get("subareas_order", []),
        last_updated=time.time()
    )


@router.post("/lesson/complete")
async def complete_lesson(
        request: LessonCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de uma lição com validação anti-duplicata
    """
    user_id = current_user["id"]

    # Criar ID único para a lição
    lesson_id = f"{request.area_name}_{request.subarea_name}_{request.level_name}_{request.module_title}_{request.lesson_title}"

    # Verificar se já foi completada
    completed_lessons = current_user.get("completed_lessons", [])
    if any(lesson.get("lesson_id") == lesson_id for lesson in completed_lessons):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta lição já foi completada anteriormente"
        )

    # Registrar conclusão
    lesson_data = {
        "lesson_id": lesson_id,
        "title": request.lesson_title,
        "completion_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "area": request.area_name or "",
        "subarea": request.subarea_name or "",
        "level": request.level_name or "",
        "module": request.module_title or ""
    }

    # Adicionar à lista de lições completadas
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_lessons": ArrayUnion([lesson_data])
    })

    # Adicionar XP
    xp_earned = add_user_xp(db, user_id, XP_REWARDS.get("complete_lesson", 10),
                            f"Completou lição: {request.lesson_title}")

    # PUBLICAR EVENTO DE LIÇÃO COMPLETADA
    await event_service.publish_event(
        event_type=EventTypes.LESSON_COMPLETED,
        user_id=user_id,
        data={
            "lesson_id": lesson_id,
            "lesson_title": request.lesson_title,
            "area": request.area_name,
            "subarea": request.subarea_name,
            "level": request.level_name,
            "module": request.module_title,
            "xp_earned": xp_earned["xp_added"],
            "total_lessons_completed": len(completed_lessons) + 1
        }
    )

    # Se houve level up, publicar evento
    if xp_earned.get("level_up"):
        await event_service.publish_event(
            event_type=EventTypes.LEVEL_UP,
            user_id=user_id,
            data={
                "new_level": xp_earned["new_level"],
                "previous_level": xp_earned["new_level"] - 1,
                "current_xp": xp_earned["new_total"]
            }
        )

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "lesson")

        # PUBLICAR EVENTO DE PROGRESSO ATUALIZADO
        await event_service.publish_event(
            event_type=EventTypes.PROGRESS_UPDATED,
            user_id=user_id,
            data={
                "update_type": "lesson_advance",
                "area": request.area_name,
                "subarea": request.subarea_name,
                "level": request.level_name
            }
        )

    return {
        "message": "Lesson completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/module/complete")
async def complete_module(
        request: ModuleCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de um módulo com validação anti-duplicata
    """
    user_id = current_user["id"]

    # Criar ID único para o módulo
    module_id = f"{request.area_name}_{request.subarea_name}_{request.level_name}_{request.module_title}"

    # Verificar se já foi completado
    completed_modules = current_user.get("completed_modules", [])
    if any(module.get("module_id") == module_id for module in completed_modules):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este módulo já foi completado anteriormente"
        )

    # Registrar conclusão
    module_data = {
        "module_id": module_id,
        "title": request.module_title,
        "completion_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "area": request.area_name or "",
        "subarea": request.subarea_name or "",
        "level": request.level_name or ""
    }

    # Adicionar à lista de módulos completados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_modules": ArrayUnion([module_data])
    })

    # Adicionar XP e badge
    xp_earned = add_user_xp(db, user_id, XP_REWARDS.get("complete_module", 15),
                            f"Completou módulo: {request.module_title}")

    badge_granted = grant_badge(db, user_id, f"Módulo: {request.module_title[:20]}")

    # PUBLICAR EVENTO DE MÓDULO COMPLETADO
    await event_service.publish_event(
        event_type=EventTypes.MODULE_COMPLETED,
        user_id=user_id,
        data={
            "module_id": module_id,
            "module_title": request.module_title,
            "area": request.area_name,
            "subarea": request.subarea_name,
            "level": request.level_name,
            "xp_earned": xp_earned["xp_added"],
            "total_modules_completed": len(completed_modules) + 1,
            "badge_earned": badge_granted
        }
    )

    # Se houve level up, publicar evento
    if xp_earned.get("level_up"):
        await event_service.publish_event(
            event_type=EventTypes.LEVEL_UP,
            user_id=user_id,
            data={
                "new_level": xp_earned["new_level"],
                "previous_level": xp_earned["new_level"] - 1,
                "current_xp": xp_earned["new_total"]
            }
        )

    # Se ganhou badge, publicar evento
    if badge_granted:
        await event_service.publish_event(
            event_type=EventTypes.BADGE_EARNED,
            user_id=user_id,
            data={
                "badge_name": f"Módulo: {request.module_title[:20]}",
                "badge_type": "module_completion",
                "module_title": request.module_title
            }
        )

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "module")

        # PUBLICAR EVENTO DE PROGRESSO ATUALIZADO
        await event_service.publish_event(
            event_type=EventTypes.PROGRESS_UPDATED,
            user_id=user_id,
            data={
                "update_type": "module_advance",
                "area": request.area_name,
                "subarea": request.subarea_name,
                "level": request.level_name
            }
        )

    return {
        "message": "Module completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Módulo: {request.module_title[:20]}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/level/complete")
async def complete_level(
        request: LevelCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de um nível
    """
    user_id = current_user["id"]

    # Registrar conclusão
    level_data = {
        "area": request.area_name,
        "subarea": request.subarea_name,
        "level": request.level_name,
        "completion_date": time.strftime("%Y-%m-%d")
    }

    # Adicionar à lista de níveis completados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_levels": ArrayUnion([level_data])
    })

    # Calcular XP baseado no nível
    xp_amount = 30
    if request.level_name in ["avançado", "avancado"]:
        xp_amount = 50
    elif request.level_name in ["intermediário", "intermediario"]:
        xp_amount = 40

    # Adicionar XP e badge
    xp_earned = add_user_xp(db, user_id, xp_amount,
                            f"Completou nível {request.level_name} em {request.subarea_name}")

    badge_granted = grant_badge(db, user_id,
                                f"Nível {request.level_name.capitalize()}: {request.subarea_name}")

    # PUBLICAR EVENTO DE NÍVEL COMPLETADO
    await event_service.publish_event(
        event_type=EventTypes.LEVEL_COMPLETED,
        user_id=user_id,
        data={
            "area": request.area_name,
            "subarea": request.subarea_name,
            "level": request.level_name,
            "xp_earned": xp_earned["xp_added"],
            "badge_earned": badge_granted
        }
    )

    # Se houve level up, publicar evento
    if xp_earned.get("level_up"):
        await event_service.publish_event(
            event_type=EventTypes.LEVEL_UP,
            user_id=user_id,
            data={
                "new_level": xp_earned["new_level"],
                "previous_level": xp_earned["new_level"] - 1,
                "current_xp": xp_earned["new_total"]
            }
        )

    # Se ganhou badge, publicar evento
    if badge_granted:
        await event_service.publish_event(
            event_type=EventTypes.BADGE_EARNED,
            user_id=user_id,
            data={
                "badge_name": f"Nível {request.level_name.capitalize()}: {request.subarea_name}",
                "badge_type": "level_completion",
                "level": request.level_name,
                "subarea": request.subarea_name
            }
        )

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "level")

        # PUBLICAR EVENTO DE PROGRESSO ATUALIZADO
        await event_service.publish_event(
            event_type=EventTypes.PROGRESS_UPDATED,
            user_id=user_id,
            data={
                "update_type": "level_advance",
                "area": request.area_name,
                "subarea": request.subarea_name,
                "completed_level": request.level_name
            }
        )

    return {
        "message": "Level completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Nível {request.level_name.capitalize()}: {request.subarea_name}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/project/start")
async def start_project(
        request: ProjectStartRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra o início de um projeto
    """
    user_id = current_user["id"]

    # Estrutura do projeto iniciado
    project_data = {
        "title": request.title,
        "type": request.project_type,
        "start_date": time.strftime("%Y-%m-%d"),
        "status": "in_progress",
        "description": request.description or ""
    }

    # Adicionar à lista de projetos iniciados
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "started_projects": ArrayUnion([project_data])
    })

    # Adicionar XP por iniciar projeto
    xp_amount = XP_REWARDS.get("start_project", 10)
    if request.project_type == "final":
        xp_amount = 15

    xp_earned = add_user_xp(db, user_id, xp_amount, f"Iniciou projeto: {request.title}")

    # PUBLICAR EVENTO DE PROJETO INICIADO
    await event_service.publish_event(
        event_type=EventTypes.PROJECT_STARTED,
        user_id=user_id,
        data={
            "project_title": request.title,
            "project_type": request.project_type,
            "description": request.description or "",
            "xp_earned": xp_earned["xp_added"]
        }
    )

    # Publicar evento de XP ganho
    await event_service.publish_event(
        event_type=EventTypes.XP_EARNED,
        user_id=user_id,
        data={
            "amount": xp_earned["xp_added"],
            "reason": f"Iniciou projeto: {request.title}",
            "total_xp": xp_earned["new_total"]
        }
    )

    return {
        "message": "Project started successfully",
        "project_id": f"{user_id}_{int(time.time())}",
        "xp_earned": xp_earned["xp_added"]
    }


@router.post("/project/complete")
async def complete_project(
        request: ProjectCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de um projeto com lógica corrigida de atualização
    """
    user_id = current_user["id"]
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    started_projects = user_data.get("started_projects", [])

    # Verificar se o projeto foi iniciado
    project_found = False
    for project in started_projects:
        if project["title"] == request.title and project["type"] == request.project_type:
            project_found = True
            break

    if not project_found:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Projeto não foi encontrado na lista de projetos iniciados"
        )

    # Filtrar projetos iniciados para remover o que foi completado
    updated_started_projects = [
        p for p in started_projects
        if not (p["title"] == request.title and p["type"] == request.project_type)
    ]

    # Estrutura do projeto concluído
    completed_project = {
        "title": request.title,
        "type": request.project_type,
        "start_date": next((p["start_date"] for p in started_projects
                            if p["title"] == request.title and p["type"] == request.project_type),
                           time.strftime("%Y-%m-%d")),
        "completion_date": time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "description": request.description or ""
    }

    if request.outcomes:
        completed_project["outcomes"] = request.outcomes

    if request.evidence_urls:
        completed_project["evidence_urls"] = request.evidence_urls

    # Atualizar no banco
    user_ref.update({
        "started_projects": updated_started_projects,
        "completed_projects": ArrayUnion([completed_project])
    })

    # Adicionar XP e possível badge
    xp_amount = XP_REWARDS.get("complete_project", 25)
    badge_granted = False

    if request.project_type == "final":
        xp_amount = XP_REWARDS.get("complete_final_project", 50)
        badge_granted = grant_badge(db, user_id, f"Projeto Final: {request.title[:20]}")

    xp_earned = add_user_xp(db, user_id, xp_amount, f"Completou projeto: {request.title}")

    # PUBLICAR EVENTO DE PROJETO COMPLETADO
    await event_service.publish_event(
        event_type=EventTypes.PROJECT_COMPLETED,
        user_id=user_id,
        data={
            "project_title": request.title,
            "project_type": request.project_type,
            "outcomes": request.outcomes,
            "evidence_urls": request.evidence_urls,
            "xp_earned": xp_earned["xp_added"],
            "badge_earned": badge_granted,
            "duration_days": (time.time() - time.mktime(time.strptime(completed_project["start_date"], "%Y-%m-%d"))) / (
                        24 * 60 * 60)
        }
    )

    # Publicar evento de XP ganho
    await event_service.publish_event(
        event_type=EventTypes.XP_EARNED,
        user_id=user_id,
        data={
            "amount": xp_earned["xp_added"],
            "reason": f"Completou projeto: {request.title}",
            "total_xp": xp_earned["new_total"]
        }
    )

    # Se ganhou badge, publicar evento
    if badge_granted:
        await event_service.publish_event(
            event_type=EventTypes.BADGE_EARNED,
            user_id=user_id,
            data={
                "badge_name": f"Projeto Final: {request.title[:20]}",
                "badge_type": "project_completion",
                "project_title": request.title
            }
        )

    return {
        "message": "Project completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


# Em app/api/v1/endpoints/progress.py
# Adicione os imports necessários no topo do arquivo:

from app.api.deps import get_user_service
from app.services.user_service import UserService


# Corrija a função complete_assessment:

# Em app/api/v1/endpoints/progress.py
# Versão limpa sem dependências desnecessárias:

@router.post("/assessment/complete")
async def complete_assessment(
        assessment_data: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """Registra a conclusão de uma avaliação"""
    try:
        user_id = current_user["id"]

        # Extrair dados da avaliação
        assessment_id = assessment_data.get("assessment_id")
        assessment_type = assessment_data.get("assessment_type", "regular")
        score = assessment_data.get("score", 0)
        questions_correct = assessment_data.get("questions_correct", 0)
        total_questions = assessment_data.get("total_questions", 1)
        time_taken_minutes = assessment_data.get("time_taken_minutes", 0)
        area_name = assessment_data.get("area_name")
        subarea_name = assessment_data.get("subarea_name")
        level_name = assessment_data.get("level_name", "iniciante")
        module_title = assessment_data.get("module_title", "Avaliação")

        # Calcular XP baseado no desempenho
        base_xp = 20  # XP base por completar
        performance_bonus = int(score / 10)  # Bônus baseado na pontuação
        xp_earned = base_xp + performance_bonus

        # Se passou, dar bônus adicional
        if score >= 70:
            xp_earned += 10

        # Registrar no histórico
        assessment_record = {
            "user_id": user_id,
            "assessment_id": assessment_id,
            "assessment_type": assessment_type,
            "score": score,
            "passed": score >= 70,
            "questions_correct": questions_correct,
            "total_questions": total_questions,
            "time_taken_minutes": time_taken_minutes,
            "area": area_name,
            "subarea": subarea_name,
            "level": level_name,
            "module": module_title,
            "xp_earned": xp_earned,
            "completed_at": datetime.utcnow()
        }

        # Salvar no Firestore
        doc_ref = db.collection("assessment_history").add(assessment_record)

        # Atualizar XP do usuário diretamente
        new_total_xp = current_user.get("profile_xp", 0)

        try:
            # Buscar e atualizar usuário no Firestore
            user_doc_ref = db.collection("users").document(user_id)
            user_doc = user_doc_ref.get()

            if user_doc.exists:
                current_data = user_doc.to_dict()
                current_xp = current_data.get("profile_xp", 0)
                current_level = current_data.get("profile_level", 1)

                # Calcular novo XP e nível
                new_total_xp = current_xp + xp_earned
                new_level = (new_total_xp // 100) + 1

                # Atualizar usuário
                user_doc_ref.update({
                    "profile_xp": new_total_xp,
                    "profile_level": new_level,
                    "updated_at": datetime.utcnow()
                })

                # Registrar transação de XP
                xp_transaction = {
                    "user_id": user_id,
                    "amount": xp_earned,
                    "reason": f"Avaliação concluída: {module_title}",
                    "old_xp": current_xp,
                    "new_xp": new_total_xp,
                    "old_level": current_level,
                    "new_level": new_level,
                    "assessment_id": assessment_id,
                    "score": score,
                    "created_at": datetime.utcnow()
                }
                db.collection("xp_transactions").add(xp_transaction)

                logger.info(f"XP atualizado para usuário {user_id}: {current_xp} -> {new_total_xp}")

        except Exception as e:
            logger.error(f"Erro ao atualizar XP: {str(e)}")
            # Continuar sem falhar - pelo menos salvamos o histórico da avaliação

        # Publicar evento para processamento assíncrono
        try:
            await event_service.publish_event(
                event_type=EventTypes.ASSESSMENT_COMPLETED,
                user_id=user_id,
                data={
                    "assessment_id": assessment_id,
                    "score": score,
                    "passed": score >= 70,
                    "xp_earned": xp_earned,
                    "area": area_name,
                    "subarea": subarea_name,
                    "level": level_name,
                    "questions_correct": questions_correct,
                    "total_questions": total_questions,
                    "time_taken_minutes": time_taken_minutes,
                    "detailed_results": assessment_data.get("detailed_results", [])
                }
            )
        except Exception as e:
            logger.error(f"Erro ao publicar evento: {str(e)}")
            # Não falhar se o evento não for publicado

        # Retornar resultado
        return {
            "success": True,
            "score": score,
            "passed": score >= 70,
            "xp_earned": xp_earned,
            "total_xp": new_total_xp,
            "message": "Avaliação registrada com sucesso!",
            "assessment_record_id": doc_ref[1].id if doc_ref else None
        }

    except Exception as e:
        logger.error(f"Erro ao completar avaliação: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/advance")
async def advance_progress(
        step_type: str = Query(..., description="Type of step to advance: lesson, module, level"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Avança o progresso do usuário para o próximo passo
    """
    user_id = current_user["id"]

    if step_type not in ["lesson", "module", "level"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid step type. Must be: lesson, module, or level"
        )

    result = advance_user_progress(db, user_id, step_type)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to advance progress"
        )

    # PUBLICAR EVENTO DE AVANÇO DE PASSO
    await event_service.publish_event(
        event_type=EventTypes.STEP_ADVANCED,
        user_id=user_id,
        data={
            "advance_type": step_type,
            "new_position": result
        }
    )

    return {
        "message": f"Progress advanced to next {step_type}",
        "current_progress": result
    }


@router.get("/next-steps")
async def get_next_steps_recommendations(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém recomendações de próximos passos baseadas no progresso atual
    """
    user_id = current_user["id"]
    progress = current_user.get("progress", {})

    recommendations = []

    # Se não tem progresso, recomendar começar
    if not progress or not progress.get("area"):
        recommendations.append("Complete o mapeamento de interesses para começar sua jornada")
        return {"recommendations": recommendations}

    current = progress.get("current", {})
    area = progress.get("area")
    subarea = current.get("subarea")
    level = current.get("level", "iniciante")

    # Buscar dados da área atual
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        return {"recommendations": ["Continue seus estudos atuais"]}

    area_data = area_doc.to_dict()

    # 1. Recomendação baseada em progresso
    module_idx = current.get("module_index", 0)
    lesson_idx = current.get("lesson_index", 0)

    try:
        modules = area_data["subareas"][subarea]["levels"][level]["modules"]
        current_module = modules[module_idx] if module_idx < len(modules) else None

        if current_module:
            # Recomendar próxima lição
            lessons = current_module.get("lessons", [])
            if lesson_idx < len(lessons) - 1:
                next_lesson = lessons[lesson_idx + 1]
                recommendations.append(f"Continue com: {next_lesson.get('lesson_title', 'Próxima lição')}")
            elif module_idx < len(modules) - 1:
                # Próximo módulo
                next_module = modules[module_idx + 1]
                recommendations.append(
                    f"Prepare-se para o próximo módulo: {next_module.get('module_title', 'Próximo módulo')}")
            else:
                # Completou o nível
                recommendations.append(f"Parabéns! Você está próximo de completar o nível {level}")

                # Sugerir próximo nível
                levels_order = ["iniciante", "intermediário", "avançado"]
                if level in levels_order:
                    current_idx = levels_order.index(level)
                    if current_idx < len(levels_order) - 1:
                        next_level = levels_order[current_idx + 1]
                        recommendations.append(f"Prepare-se para avançar para o nível {next_level}")
    except (KeyError, IndexError):
        pass

    # 2. Recomendações baseadas em performance
    completed_lessons = len(current_user.get("completed_lessons", []))
    completed_modules = len(current_user.get("completed_modules", []))

    # Se completou muitas lições mas poucos módulos
    if completed_lessons > 10 and completed_modules < 2:
        recommendations.append("Considere revisar os módulos anteriores antes de prosseguir")

    # 3. Recomendações de projetos
    started_projects = current_user.get("started_projects", [])
    completed_projects = current_user.get("completed_projects", [])

    if len(started_projects) > len(completed_projects):
        recommendations.append("Você tem projetos em andamento. Que tal finalizá-los?")
    elif completed_modules >= 2 and len(completed_projects) == 0:
        recommendations.append("Aplique seus conhecimentos em um projeto prático!")

    # 4. Recomendações de avaliação
    assessments = current_user.get("passed_assessments", []) + current_user.get("failed_assessments", [])
    recent_assessment = None

    for assessment in assessments:
        if assessment.get("timestamp"):
            if not recent_assessment or assessment["timestamp"] > recent_assessment["timestamp"]:
                recent_assessment = assessment

    # Se não fez avaliação recentemente (30 dias)
    if not recent_assessment or (time.time() - recent_assessment.get("timestamp", 0)) > 30 * 24 * 60 * 60:
        recommendations.append("Teste seus conhecimentos com uma avaliação personalizada")

    # 5. Recomendações de consistência
    streak = calculate_study_streak(current_user)
    if streak == 0:
        recommendations.append("Retome seus estudos hoje para manter a consistência")
    elif streak >= 7:
        recommendations.append(f"Excelente! Mantenha sua sequência de {streak} dias!")

    # 6. Recomendações de especialização
    if level == "avançado" and completed_modules >= 3:
        recommendations.append("Considere iniciar uma especialização na sua área")

    # Limitar a 5 recomendações
    return {"recommendations": recommendations[:5]}


@router.get("/today")
async def get_today_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém o progresso do dia atual
    """
    user_id = current_user["id"]
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    # Contar atividades de hoje
    lessons_today = 0
    modules_today = 0
    projects_today = 0
    xp_today = 0

    # Verificar lições completadas hoje
    for lesson in current_user.get("completed_lessons", []):
        if lesson.get("completion_date") == today_str:
            lessons_today += 1

    # Verificar módulos completados hoje
    for module in current_user.get("completed_modules", []):
        if module.get("completion_date") == today_str:
            modules_today += 1

    # Verificar projetos iniciados/completados hoje
    for project in current_user.get("started_projects", []):
        if project.get("start_date") == today_str:
            projects_today += 1

    for project in current_user.get("completed_projects", []):
        if project.get("completion_date") == today_str:
            projects_today += 1

    # Estimar XP ganho hoje (simplificado)
    xp_today = (lessons_today * 10) + (modules_today * 15) + (projects_today * 25)

    # Calcular tempo de estudo estimado
    estimated_time = (lessons_today * 30) + (modules_today * 45) + (projects_today * 60)

    # Verificar se está em sequência
    streak = calculate_study_streak(current_user)

    return {
        "date": today_str,
        "lessons_completed": lessons_today,
        "modules_completed": modules_today,
        "projects_worked": projects_today,
        "xp_earned": xp_today,
        "study_time_minutes": estimated_time,
        "current_streak": streak,
        "daily_goal": {
            "target_lessons": 2,
            "completed": lessons_today >= 2
        }
    }


@router.get("/weekly")
async def get_weekly_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém o progresso semanal
    """
    user_id = current_user["id"]

    # Calcular início da semana (segunda-feira)
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    # Contadores semanais
    weekly_lessons = 0
    weekly_modules = 0
    weekly_projects = 0
    weekly_xp = 0
    daily_activity = {}

    # Inicializar dias da semana
    for i in range(7):
        day = start_of_week + timedelta(days=i)
        daily_activity[day.strftime("%Y-%m-%d")] = {
            "lessons": 0,
            "modules": 0,
            "projects": 0,
            "xp": 0
        }

    # Contar lições da semana
    for lesson in current_user.get("completed_lessons", []):
        completion_date = lesson.get("completion_date")
        if completion_date:
            try:
                lesson_date = datetime.strptime(completion_date, "%Y-%m-%d").date()
                if start_of_week <= lesson_date <= end_of_week:
                    weekly_lessons += 1
                    if completion_date in daily_activity:
                        daily_activity[completion_date]["lessons"] += 1
                        daily_activity[completion_date]["xp"] += 10
            except:
                pass

    # Contar módulos da semana
    for module in current_user.get("completed_modules", []):
        completion_date = module.get("completion_date")
        if completion_date:
            try:
                module_date = datetime.strptime(completion_date, "%Y-%m-%d").date()
                if start_of_week <= module_date <= end_of_week:
                    weekly_modules += 1
                    if completion_date in daily_activity:
                        daily_activity[completion_date]["modules"] += 1
                        daily_activity[completion_date]["xp"] += 15
            except:
                pass

    # Contar projetos da semana
    for project in current_user.get("started_projects", []):
        start_date = project.get("start_date")
        if start_date:
            try:
                project_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                if start_of_week <= project_date <= end_of_week:
                    weekly_projects += 1
                    if start_date in daily_activity:
                        daily_activity[start_date]["projects"] += 1
                        daily_activity[start_date]["xp"] += 10
            except:
                pass

    # XP total da semana
    weekly_xp = (weekly_lessons * 10) + (weekly_modules * 15) + (weekly_projects * 10)

    # Calcular dias ativos
    active_days = sum(1 for day_data in daily_activity.values()
                      if day_data["lessons"] > 0 or day_data["modules"] > 0 or day_data["projects"] > 0)

    # Meta semanal
    weekly_goal = {
        "target": 5,  # 5 lições por semana
        "completed": weekly_lessons
    }

    # Melhor dia da semana
    best_day = None
    max_xp = 0
    for day, data in daily_activity.items():
        if data["xp"] > max_xp:
            max_xp = data["xp"]
            best_day = day

    return {
        "week_start": start_of_week.strftime("%Y-%m-%d"),
        "week_end": end_of_week.strftime("%Y-%m-%d"),
        "total_lessons": weekly_lessons,
        "total_modules": weekly_modules,
        "total_projects": weekly_projects,
        "total_xp": weekly_xp,
        "active_days": active_days,
        "daily_breakdown": daily_activity,
        "weekly_goal": weekly_goal,
        "best_day": best_day,
        "average_lessons_per_day": round(weekly_lessons / 7, 1) if weekly_lessons > 0 else 0,
        "on_track": weekly_lessons >= (weekly_goal["target"] * (today.weekday() + 1) / 7)
    }


@router.get("/area-subarea")
async def get_progress_for_area_subarea(
        area: str = Query(..., description="Area name"),
        subarea: str = Query(..., description="Subarea name"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém progresso específico para uma combinação área/subárea
    """
    user_id = current_user["id"]

    # Verificar no progresso atual
    current_progress = current_user.get("progress", {})
    if (current_progress.get("area") == area and
            current_progress.get("current", {}).get("subarea") == subarea):
        return {
            "has_progress": True,
            "is_current": True,
            "area": area,
            "subarea": subarea,
            "level": current_progress["current"].get("level", "iniciante"),
            "module_index": current_progress["current"].get("module_index", 0),
            "lesson_index": current_progress["current"].get("lesson_index", 0),
            "step_index": current_progress["current"].get("step_index", 0),
            "completed_lessons": count_completed_in_area_subarea(current_user, area, subarea)
        }

    # Verificar no progresso salvo
    saved_progress = current_user.get("saved_progress", {})
    if area in saved_progress:
        area_progress = saved_progress[area]
        if area_progress.get("current", {}).get("subarea") == subarea:
            return {
                "has_progress": True,
                "is_current": False,
                "area": area,
                "subarea": subarea,
                "level": area_progress["current"].get("level", "iniciante"),
                "module_index": area_progress["current"].get("module_index", 0),
                "lesson_index": area_progress["current"].get("lesson_index", 0),
                "step_index": area_progress["current"].get("step_index", 0),
                "completed_lessons": count_completed_in_area_subarea(current_user, area, subarea)
            }

    # Verificar se tem lições completadas nesta área/subárea
    completed_count = count_completed_in_area_subarea(current_user, area, subarea)

    return {
        "has_progress": completed_count > 0,
        "is_current": False,
        "area": area,
        "subarea": subarea,
        "level": "iniciante",
        "module_index": 0,
        "lesson_index": 0,
        "step_index": 0,
        "completed_lessons": completed_count
    }


def count_completed_in_area_subarea(user_data: dict, area: str, subarea: str) -> int:
    """Conta lições completadas em uma área/subárea específica"""
    count = 0
    for lesson in user_data.get("completed_lessons", []):
        if lesson.get("area") == area and lesson.get("subarea") == subarea:
            count += 1
    return count

@router.post("/switch-track")
async def switch_learning_track(
        payload: TrackSwitchRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Troca a trilha de aprendizado ativa do usuário

    - Preserva o progresso da trilha anterior
    - Restaura progresso se já estudou a nova trilha antes
    """
    user_id = current_user["id"]
    new_track = payload.new_track
    old_track = current_user.get("current_track", "")

    if old_track == new_track:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already in this track"
        )

    # Verificar se a nova trilha existe
    track_ref = db.collection(Collections.LEARNING_PATHS).document(new_track)
    track_doc = track_ref.get()

    if not track_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    # Salvar progresso atual
    saved_progress = current_user.get("saved_progress", {})
    if old_track and "progress" in current_user:
        saved_progress[old_track] = current_user["progress"]

    # Restaurar ou criar novo progresso
    if new_track in saved_progress:
        new_progress = saved_progress[new_track]
    else:
        # Criar novo progresso
        track_data = track_doc.to_dict()
        subareas = list(track_data.get("subareas", {}).keys())

        new_progress = {
            "area": new_track,
            "subareas_order": subareas,
            "current": {
                "subarea": subareas[0] if subareas else "",
                "level": "iniciante",
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            }
        }

    # Atualizar usuário
    updates = {
        "current_track": new_track,
        "progress": new_progress,
        "saved_progress": saved_progress
    }

    db.collection(Collections.USERS).document(user_id).update(updates)

    # Adicionar XP
    xp_result = add_user_xp(db, user_id, 5, f"Mudou para trilha: {new_track}")

    # PUBLICAR EVENTO DE SELEÇÃO DE TRILHA
    await event_service.publish_event(
        event_type=EventTypes.TRACK_SELECTED,
        user_id=user_id,
        data={
            "old_track": old_track,
            "new_track": new_track,
            "progress_restored": new_track in saved_progress,
            "xp_earned": xp_result["xp_added"]
        }
    )

    # PUBLICAR EVENTO DE MUDANÇA DE ÁREA
    await event_service.publish_event(
        event_type=EventTypes.AREA_CHANGED,
        user_id=user_id,
        data={
            "from_area": old_track,
            "to_area": new_track,
            "has_previous_progress": new_track in saved_progress
        }
    )

    return {
        "message": "Track switched successfully",
        "old_track": old_track,
        "new_track": new_track,
        "progress_restored": new_track in saved_progress
    }


@router.post("/specialization/start")
async def start_specialization(
        request: SpecializationStartRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Inicia uma especialização
    """
    user_id = current_user["id"]

    # Verificar se a especialização existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(request.area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{request.area}' não encontrada"
        )

    area_data = area_doc.to_dict()
    subareas = area_data.get("subareas", {})

    if request.subarea not in subareas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subárea '{request.subarea}' não encontrada"
        )

    subarea_data = subareas[request.subarea]
    specializations = subarea_data.get("specializations", [])

    # Encontrar a especialização
    spec_found = None
    for spec in specializations:
        if spec.get("name") == request.specialization_name:
            spec_found = spec
            break

    if not spec_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Especialização '{request.specialization_name}' não encontrada"
        )

    # Verificar pré-requisitos
    prerequisites = spec_found.get("prerequisites", [])
    if prerequisites and request.force_start is False:
        completed_levels = current_user.get("completed_levels", [])
        completed_level_names = [
            f"{l.get('level', '')} em {l.get('subarea', '')}"
            for l in completed_levels
        ]

        missing_prereqs = [p for p in prerequisites if p not in completed_level_names]
        if missing_prereqs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pré-requisitos faltando: {', '.join(missing_prereqs)}"
            )

    # Verificar se já foi iniciada
    specializations_started = current_user.get("specializations_started", [])
    already_started = any(
        s.get("name") == request.specialization_name
        for s in specializations_started
    )

    if already_started:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Especialização já foi iniciada"
        )

    # Criar registro de especialização
    spec_record = {
        "name": request.specialization_name,
        "area": request.area,
        "subarea": request.subarea,
        "start_date": time.strftime("%Y-%m-%d"),
        "estimated_duration": spec_found.get("estimated_time", ""),
        "modules_total": len(spec_found.get("modules", [])),
        "modules_completed": 0,
        "current_module_index": 0,
        "status": "in_progress"
    }

    # Adicionar ao banco
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "specializations_started": ArrayUnion([spec_record])
    })

    # Adicionar XP e badge
    xp_result = add_user_xp(
        db, user_id,
        XP_REWARDS.get("start_specialization", 20),
        f"Iniciou especialização: {request.specialization_name}"
    )

    badge_name = f"Iniciou: {request.specialization_name}"
    badge_earned = grant_badge(db, user_id, badge_name)

    # PUBLICAR EVENTO - Especialização iniciada
    await event_service.publish_event(
        event_type=EventTypes.PROJECT_STARTED,  # Usando PROJECT_STARTED pois não temos evento específico
        user_id=user_id,
        data={
            "project_type": "specialization",
            "specialization_name": request.specialization_name,
            "area": request.area,
            "subarea": request.subarea,
            "modules_total": len(spec_found.get("modules", [])),
            "prerequisites_met": not missing_prereqs if prerequisites else True,
            "xp_earned": xp_result["xp_added"],
            "badge_earned": badge_earned
        }
    )

    return {
        "message": "Especialização iniciada com sucesso",
        "specialization": spec_record,
        "total_modules": len(spec_found.get("modules", [])),
        "learning_outcomes": spec_found.get("learning_outcomes", []),
        "xp_earned": xp_result["xp_added"],
        "badge_earned": badge_name if badge_earned else None
    }


@router.post("/navigate-to")
async def navigate_to_content(
        request: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Navega diretamente para um conteúdo específico
    """
    user_id = current_user["id"]
    user_ref = db.collection(Collections.USERS).document(user_id)

    # Extrair parâmetros do request body
    area = request.get("area")
    subarea = request.get("subarea")
    level = request.get("level")
    specialization = request.get("specialization")
    module_index = request.get("module_index", 0)
    lesson_index = request.get("lesson_index", 0)
    step_index = request.get("step_index", 0)

    # Validar campos obrigatórios
    if not all([area, subarea, level, module_index is not None]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campos obrigatórios: area, subarea, level, module_index"
        )

    # Verificar se o conteúdo existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{area}' não encontrada"
        )

    area_data = area_doc.to_dict()

    # Validar caminho completo
    try:
        subarea_data = area_data["subareas"][subarea]

        if level == "especialização" and specialization:
            # Lógica para especialização...
            pass
        else:
            # IMPORTANTE: Verificar se o nível existe exatamente como está
            if level not in subarea_data.get("levels", {}):
                # Tentar encontrar o nível independente de acentuação
                available_levels = list(subarea_data.get("levels", {}).keys())

                # Procurar match case-insensitive
                level_found = None
                for available_level in available_levels:
                    if available_level.lower() == level.lower():
                        level_found = available_level
                        break

                if not level_found:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Nível '{level}' não encontrado. Níveis disponíveis: {available_levels}"
                    )

                # Usar o nível encontrado
                level = level_found

            level_data = subarea_data["levels"][level]
            modules = level_data.get("modules", [])

            if module_index >= len(modules):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Índice de módulo inválido: {module_index}"
                )

    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho inválido: {str(e)}"
        )

    # Buscar progresso atual
    current_progress = current_user.get("progress", {})
    old_progress = current_progress.copy()

    # Preservar progresso anterior se mudando de área
    if current_progress.get("area") != area and current_progress.get("area"):
        saved_progress = current_user.get("saved_progress", {})
        saved_progress[current_progress["area"]] = current_progress.copy()
        user_ref.update({"saved_progress": saved_progress})

    # Criar estrutura de progresso atualizada
    updated_progress = {
        "area": area,
        "subareas_order": current_progress.get("subareas_order", list(area_data.get("subareas", {}).keys())),
        "current": {
            "subarea": subarea,
            "level": level,
            "module_index": module_index,
            "lesson_index": lesson_index,
            "step_index": step_index
        }
    }

    # Atualizar no banco
    user_ref.update({
        "progress": updated_progress,
        "current_track": area
    })

    # Adicionar XP por navegação
    xp_result = add_user_xp(db, user_id, 2, f"Navegou para: {level} - Módulo {module_index + 1}")

    # PUBLICAR EVENTO DE NAVEGAÇÃO
    await event_service.publish_event(
        event_type=EventTypes.NAVIGATION_OCCURRED,
        user_id=user_id,
        data={
            "from": {
                "area": old_progress.get("area"),
                "subarea": old_progress.get("current", {}).get("subarea"),
                "level": old_progress.get("current", {}).get("level"),
                "module": old_progress.get("current", {}).get("module_index"),
                "lesson": old_progress.get("current", {}).get("lesson_index"),
                "step": old_progress.get("current", {}).get("step_index")
            },
            "to": {
                "area": area,
                "subarea": subarea,
                "level": level,
                "module": module_index,
                "lesson": lesson_index,
                "step": step_index
            },
            "xp_earned": xp_result["xp_added"]
        }
    )

    return {
        "message": "Navegação atualizada com sucesso",
        "current_position": updated_progress["current"]
    }


@router.post("/initialize")
async def initialize_progress(
        request: InitializeProgressRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Inicializa progresso para uma nova área/subárea
    """
    user_id = current_user["id"]

    # Validar que a área/subárea existe
    area_ref = db.collection(Collections.LEARNING_PATHS).document(request.area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Área '{request.area}' não encontrada"
        )

    area_data = area_doc.to_dict()
    subareas = area_data.get("subareas", {})

    if request.subarea not in subareas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subárea '{request.subarea}' não encontrada"
        )

    # Verificar se já existe progresso
    current_progress = current_user.get("progress", {})
    saved_progress = current_user.get("saved_progress", {})

    # Se já é a área/subárea atual
    if (current_progress.get("area") == request.area and
            current_progress.get("current", {}).get("subarea") == request.subarea):
        return {
            "message": "Progresso já existe para esta área/subárea",
            "already_current": True,
            "progress": current_progress
        }

    # Se já existe em progresso salvo
    if request.area in saved_progress:
        area_progress = saved_progress[request.area]
        if area_progress.get("current", {}).get("subarea") == request.subarea:
            return {
                "message": "Progresso já existe para esta área/subárea (salvo)",
                "already_saved": True,
                "progress": area_progress
            }

    # Criar novo progresso
    new_progress = {
        "area": request.area,
        "subareas_order": list(subareas.keys()),
        "current": {
            "subarea": request.subarea,
            "level": request.level,
            "module_index": request.module_index,
            "lesson_index": request.lesson_index,
            "step_index": request.step_index
        },
        "initialized_at": time.time()
    }

    # Se quiser tornar esta a área atual
    if request.set_as_current:
        # Salvar progresso atual se existir
        if current_progress and current_progress.get("area"):
            saved_progress[current_progress["area"]] = current_progress

        # Atualizar progresso atual
        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({
            "progress": new_progress,
            "current_track": request.area,
            "saved_progress": saved_progress
        })

        # Adicionar XP
        xp_result = add_user_xp(db, user_id, 5, f"Iniciou estudos em: {request.subarea}")

        # PUBLICAR EVENTO DE PROGRESSO INICIALIZADO
        await event_service.publish_event(
            event_type=EventTypes.PROGRESS_INITIALIZED,
            user_id=user_id,
            data={
                "area": request.area,
                "subarea": request.subarea,
                "level": request.level,
                "is_first_progress": len(saved_progress) == 0,
                "set_as_current": True,
                "xp_earned": xp_result["xp_added"]
            }
        )

        return {
            "message": "Progresso inicializado e definido como atual",
            "progress": new_progress,
            "set_as_current": True
        }
    else:
        # Apenas salvar para uso futuro
        saved_progress[request.area] = new_progress

        user_ref = db.collection(Collections.USERS).document(user_id)
        user_ref.update({
            "saved_progress": saved_progress
        })

        # PUBLICAR EVENTO DE PROGRESSO INICIALIZADO
        await event_service.publish_event(
            event_type=EventTypes.PROGRESS_INITIALIZED,
            user_id=user_id,
            data={
                "area": request.area,
                "subarea": request.subarea,
                "level": request.level,
                "is_first_progress": len(saved_progress) == 1,
                "set_as_current": False
            }
        )

        return {
            "message": "Progresso inicializado e salvo",
            "progress": new_progress,
            "set_as_current": False
        }


@router.get("/current-content")
async def get_current_content(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o conteúdo atual baseado no progresso do usuário
    SEMPRE retorna contexto completo de navegação
    """
    user_id = current_user["id"]

    # Garantir contexto válido
    nav_context = ensure_navigation_context(current_user, db)
    area = nav_context["area"]
    subarea = nav_context["subarea"]
    level = nav_context["level"]
    module_idx = nav_context["module_index"]
    lesson_idx = nav_context["lesson_index"]
    step_idx = nav_context["step_index"]

    # Buscar dados da área
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        # Mesmo sem área, retornar contexto válido
        return {
            "content_type": "no_content",
            "message": "Área de aprendizado não encontrada",
            "current_area": area,
            "current_subarea": subarea,
            "current_level": level,
            "navigation_context": {
                "area": area,
                "subarea": subarea,
                "level": level,
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            },
            "suggestions": {
                "explore_areas": True,
                "available_areas_url": "/api/v1/content/areas"
            }
        }

    area_data = area_doc.to_dict()

    try:
        # Verificar se subárea existe
        if subarea not in area_data.get("subareas", {}):
            # Pegar primeira subárea disponível
            available_subareas = list(area_data.get("subareas", {}).keys())
            if available_subareas:
                subarea = available_subareas[0]
            else:
                return {
                    "content_type": "no_subareas",
                    "message": "Nenhuma subárea disponível nesta área",
                    "current_area": area,
                    "current_subarea": subarea,
                    "current_level": level,
                    "navigation_context": nav_context
                }

        subarea_data = area_data["subareas"][subarea]

        # Verificar se nível existe
        if level not in subarea_data.get("levels", {}):
            available_levels = list(subarea_data.get("levels", {}).keys())
            if available_levels:
                level = available_levels[0]
            else:
                return {
                    "content_type": "no_levels",
                    "message": "Nenhum nível disponível nesta subárea",
                    "current_area": area,
                    "current_subarea": subarea,
                    "current_level": level,
                    "navigation_context": nav_context
                }

        level_data = subarea_data["levels"][level]
        modules = level_data.get("modules", [])

        # Se não há módulos
        if not modules:
            return {
                "content_type": "no_modules",
                "message": "Nenhum módulo disponível neste nível",
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": nav_context,
                "next_content": get_next_available_content(area_data, nav_context, db)
            }

        # Verificar se ultrapassou todos os módulos
        if module_idx >= len(modules):
            next_content = get_next_available_content(area_data, nav_context, db)

            # PUBLICAR EVENTO DE NÍVEL COMPLETADO
            await event_service.publish_event(
                event_type=EventTypes.LEVEL_COMPLETED,
                user_id=user_id,
                data={
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "auto_detected": True
                }
            )

            return {
                "content_type": "level_completed",
                "title": "Nível Concluído!",
                "message": f"Parabéns! Você completou o nível {level} em {subarea}!",
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module_index": len(modules) - 1,
                    "lesson_index": 0,
                    "step_index": 0
                },
                "completed": True,
                "next_content": next_content,
                "achievements": {
                    "modules_completed": len(modules),
                    "level_completed": True
                }
            }

        # Processar módulo atual
        module_data = modules[module_idx]
        lessons = module_data.get("lessons", [])

        # Se não há lições no módulo
        if not lessons:
            return {
                "content_type": "empty_module",
                "message": "Este módulo não possui lições",
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": nav_context,
                "module_info": {
                    "title": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "index": module_idx
                }
            }

        # Verificar se ultrapassou todas as lições
        if lesson_idx >= len(lessons):
            # Avançar para o próximo módulo automaticamente
            new_module_idx = module_idx + 1

            if new_module_idx < len(modules):
                # Atualizar para o próximo módulo
                user_ref = db.collection(Collections.USERS).document(user_id)
                user_ref.update({
                    "progress.current.module_index": new_module_idx,
                    "progress.current.lesson_index": 0,
                    "progress.current.step_index": 0
                })

                # PUBLICAR EVENTO DE MÓDULO COMPLETADO
                await event_service.publish_event(
                    event_type=EventTypes.MODULE_COMPLETED,
                    user_id=user_id,
                    data={
                        "module_title": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                        "area": area,
                        "subarea": subarea,
                        "level": level,
                        "auto_detected": True
                    }
                )

                # Recursivamente chamar a função com os novos índices
                nav_context["module_index"] = new_module_idx
                nav_context["lesson_index"] = 0
                nav_context["step_index"] = 0
                return await get_current_content(current_user, db)
            else:
                # Completou todos os módulos
                return {
                    "content_type": "level_completed",
                    "title": "Nível Concluído!",
                    "message": f"Parabéns! Você completou o nível {level} em {subarea}!",
                    "current_area": area,
                    "current_subarea": subarea,
                    "current_level": level,
                    "navigation_context": nav_context,
                    "completed": True,
                    "next_content": get_next_available_content(area_data, nav_context, db)
                }

        # Processar lição atual
        lesson_data = lessons[lesson_idx]

        # Se a lição tem passos
        if "steps" in lesson_data and lesson_data["steps"]:
            steps = lesson_data["steps"]
            total_steps = len(steps)

            # Se ultrapassou os passos
            if step_idx >= total_steps:
                # Avançar para a próxima lição
                new_lesson_idx = lesson_idx + 1

                if new_lesson_idx < len(lessons):
                    # Atualizar para a próxima lição
                    user_ref = db.collection(Collections.USERS).document(user_id)
                    user_ref.update({
                        "progress.current.lesson_index": new_lesson_idx,
                        "progress.current.step_index": 0
                    })

                    # PUBLICAR EVENTO DE LIÇÃO COMPLETADA
                    await event_service.publish_event(
                        event_type=EventTypes.LESSON_COMPLETED,
                        user_id=user_id,
                        data={
                            "lesson_title": lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}"),
                            "area": area,
                            "subarea": subarea,
                            "level": level,
                            "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                            "auto_detected": True
                        }
                    )

                    # Recursivamente chamar a função
                    nav_context["lesson_index"] = new_lesson_idx
                    nav_context["step_index"] = 0
                    return await get_current_content(current_user, db)
                else:
                    # Avançar para o próximo módulo
                    new_module_idx = module_idx + 1

                    if new_module_idx < len(modules):
                        user_ref = db.collection(Collections.USERS).document(user_id)
                        user_ref.update({
                            "progress.current.module_index": new_module_idx,
                            "progress.current.lesson_index": 0,
                            "progress.current.step_index": 0
                        })

                        nav_context["module_index"] = new_module_idx
                        nav_context["lesson_index"] = 0
                        nav_context["step_index"] = 0
                        return await get_current_content(current_user, db)
                    else:
                        # Completou o nível
                        return {
                            "content_type": "level_completed",
                            "title": "Nível Concluído!",
                            "message": f"Parabéns! Você completou o nível {level} em {subarea}!",
                            "current_area": area,
                            "current_subarea": subarea,
                            "current_level": level,
                            "navigation_context": nav_context,
                            "completed": True,
                            "next_content": get_next_available_content(area_data, nav_context, db)
                        }

            # Retornar passo atual
            step_content = steps[step_idx]

            # Expandir conteúdo
            user_age = current_user.get("age", 14)
            teaching_style = current_user.get("learning_style", "didático")

            expanded_content = call_teacher_llm(
                f"Explique de forma didática para um estudante de {user_age} anos: {step_content}. "
                f"Contexto: Área: {area}, Subárea: {subarea}, Nível: {level}. "
                f"Use exemplos práticos e linguagem acessível.",
                student_age=user_age,
                subject_area=area,
                teaching_style=teaching_style
            )

            # PUBLICAR EVENTO DE LIÇÃO INICIADA (se for o primeiro passo)
            if step_idx == 0:
                await event_service.publish_event(
                    event_type=EventTypes.LESSON_STARTED,
                    user_id=user_id,
                    data={
                        "lesson_title": lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}"),
                        "area": area,
                        "subarea": subarea,
                        "level": level,
                        "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                        "total_steps": total_steps
                    }
                )

            return {
                "content_type": "step",
                "title": lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}"),
                "content": expanded_content,
                "original_step": step_content,
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module_index": module_idx,
                    "lesson_index": lesson_idx,
                    "step_index": step_idx
                },
                "context": {
                    "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "lesson": lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}"),
                    "step": f"{step_idx + 1}/{total_steps}"
                },
                "navigation": {
                    "has_previous": step_idx > 0 or lesson_idx > 0 or module_idx > 0,
                    "has_next": step_idx < total_steps - 1 or lesson_idx < len(lessons) - 1 or module_idx < len(
                        modules) - 1
                },
                "progress": {
                    "step": (step_idx + 1) / total_steps * 100,
                    "lesson": (lesson_idx + (step_idx + 1) / total_steps) / len(lessons) * 100,
                    "module": (module_idx + (lesson_idx + 1) / len(lessons)) / len(modules) * 100
                }
            }
        else:
            # Lição sem passos - gerar conteúdo completo
            lesson_title = lesson_data.get("lesson_title", f"Lição {lesson_idx + 1}")
            objectives = lesson_data.get("objectives", "")

            user_age = current_user.get("age", 14)
            teaching_style = current_user.get("learning_style", "didático")

            lesson = generate_complete_lesson(
                topic=lesson_title,
                subject_area=f"{area} - {subarea}",
                age_range=user_age,
                knowledge_level=level,
                teaching_style=teaching_style,
                lesson_duration_min=30
            )

            # PUBLICAR EVENTO DE LIÇÃO INICIADA
            await event_service.publish_event(
                event_type=EventTypes.LESSON_STARTED,
                user_id=user_id,
                data={
                    "lesson_title": lesson_title,
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "has_steps": False
                }
            )

            return {
                "content_type": "lesson",
                "title": lesson_title,
                "content": lesson.to_text(),
                "objectives": objectives,
                "current_area": area,
                "current_subarea": subarea,
                "current_level": level,
                "navigation_context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module_index": module_idx,
                    "lesson_index": lesson_idx,
                    "step_index": 0
                },
                "context": {
                    "module": module_data.get("module_title", f"Módulo {module_idx + 1}"),
                    "lesson": lesson_title
                },
                "navigation": {
                    "has_previous": lesson_idx > 0 or module_idx > 0,
                    "has_next": lesson_idx < len(lessons) - 1 or module_idx < len(modules) - 1
                }
            }

    except Exception as e:
        # Em caso de qualquer erro, retornar contexto seguro
        import traceback
        error_details = traceback.format_exc()

        return {
            "content_type": "error",
            "message": "Erro ao carregar conteúdo",
            "error": str(e),
            "current_area": area,
            "current_subarea": subarea,
            "current_level": level,
            "navigation_context": nav_context,
            "recovery": {
                "reset_to_start": {
                    "area": area,
                    "subarea": subarea,
                    "level": "iniciante",
                    "module_index": 0,
                    "lesson_index": 0,
                    "step_index": 0
                }
            }
        }


# Funções auxiliares restantes

def get_assessment_feedback(score: float, passed: bool) -> str:
    """Gera feedback baseado na pontuação da avaliação"""
    if score == 100:
        return "Perfeito! Você demonstrou domínio completo do conteúdo!"
    elif score >= 90:
        return "Excelente! Você tem um ótimo entendimento do material."
    elif score >= 80:
        return "Muito bom! Continue assim!"
    elif score >= 70:
        return "Bom trabalho! Você passou, mas ainda há espaço para melhorar."
    elif score >= 60:
        return "Quase lá! Revise o conteúdo e tente novamente."
    elif score >= 50:
        return "Você está no caminho certo. Continue estudando!"
    else:
        return "Não desista! Revise o material e tente novamente quando estiver pronto."


def get_last_activity_for_subarea(user_data: dict, area: str, subarea: str) -> Optional[float]:
    """Obtém timestamp da última atividade em uma subárea específica"""
    last_activity = None

    # Verificar lições
    for lesson in user_data.get("completed_lessons", []):
        if lesson.get("area") == area and lesson.get("subarea") == subarea:
            lesson_date = lesson.get("completion_date")
            if lesson_date:
                try:
                    timestamp = time.mktime(time.strptime(lesson_date, "%Y-%m-%d"))
                    if not last_activity or timestamp > last_activity:
                        last_activity = timestamp
                except:
                    pass

    # Verificar módulos
    for module in user_data.get("completed_modules", []):
        if module.get("area") == area and module.get("subarea") == subarea:
            module_date = module.get("completion_date")
            if module_date:
                try:
                    timestamp = time.mktime(time.strptime(module_date, "%Y-%m-%d"))
                    if not last_activity or timestamp > last_activity:
                        last_activity = timestamp
                except:
                    pass

    return last_activity