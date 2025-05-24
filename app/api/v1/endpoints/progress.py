# app/api/v1/endpoints/progress.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from google.cloud.firestore import ArrayUnion
import time

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
    NextStepResponse
)
from app.utils.gamification import add_user_xp, grant_badge, XP_REWARDS
from app.utils.progress_utils import (
    get_user_progress,
    advance_user_progress,
    calculate_progress_percentage,
    get_next_recommendations
)

router = APIRouter()


@router.get("/current", response_model=ProgressResponse)
async def get_current_progress(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o progresso atual detalhado do usuário
    """
    user_id = current_user["id"]
    progress = get_user_progress(db, user_id)

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress found. Complete interest mapping first."
        )

    # Calcular estatísticas de progresso
    progress_percentage = calculate_progress_percentage(db, user_id, progress)

    return ProgressResponse(
        user_id=user_id,
        area=progress.get("area", ""),
        subarea=progress.get("current", {}).get("subarea", ""),
        level=progress.get("current", {}).get("level", "iniciante"),
        module_index=progress.get("current", {}).get("module_index", 0),
        lesson_index=progress.get("current", {}).get("lesson_index", 0),
        step_index=progress.get("current", {}).get("step_index", 0),
        progress_percentage=progress_percentage,
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
    Registra a conclusão de uma lição
    """
    user_id = current_user["id"]

    # Registrar conclusão
    lesson_data = {
        "title": request.lesson_title,
        "completion_date": time.strftime("%Y-%m-%d"),
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

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "lesson")

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
    Registra a conclusão de um módulo
    """
    user_id = current_user["id"]

    # Registrar conclusão
    module_data = {
        "title": request.module_title,
        "completion_date": time.strftime("%Y-%m-%d"),
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

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "module")

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

    # Avançar progresso se aplicável
    if request.advance_progress:
        advance_user_progress(db, user_id, "level")

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
    Registra a conclusão de um projeto
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

    # Encontrar e atualizar o projeto
    updated_projects = []
    project_found = False

    for project in started_projects:
        if project["title"] == request.title and project["type"] == request.project_type:
            project_found = True
            updated_project = project.copy()
            updated_project["status"] = "completed"
            updated_projects.append(updated_project)
        else:
            updated_projects.append(project)

    # Estrutura do projeto concluído
    completed_project = {
        "title": request.title,
        "type": request.project_type,
        "start_date": time.strftime("%Y-%m-%d"),
        "completion_date": time.strftime("%Y-%m-%d"),
        "description": request.description or ""
    }

    if request.outcomes:
        completed_project["outcomes"] = request.outcomes

    if request.evidence_urls:
        completed_project["evidence_urls"] = request.evidence_urls

    # Atualizar no banco
    user_ref.update({
        "started_projects": updated_projects,
        "completed_projects": ArrayUnion([completed_project])
    })

    # Adicionar XP e possível badge
    xp_amount = XP_REWARDS.get("complete_project", 25)
    if request.project_type == "final":
        xp_amount = XP_REWARDS.get("complete_final_project", 50)
        grant_badge(db, user_id, f"Projeto Final: {request.title[:20]}")

    xp_earned = add_user_xp(db, user_id, xp_amount, f"Completou projeto: {request.title}")

    return {
        "message": "Project completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/assessment/complete")
async def complete_assessment(
        request: AssessmentCompletionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de uma avaliação
    """
    user_id = current_user["id"]

    # Registrar avaliação
    assessment_data = {
        "module": request.module_title or request.level_name,
        "score": request.score,
        "date": time.strftime("%Y-%m-%d"),
        "type": request.assessment_type
    }

    collection_name = "passed_final_assessments" if request.assessment_type == "final" else "passed_assessments"

    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        collection_name: ArrayUnion([assessment_data])
    })

    # Calcular XP baseado na pontuação
    base_xp = XP_REWARDS.get("pass_final_assessment", 20) if request.assessment_type == "final" else XP_REWARDS.get(
        "pass_assessment", 10)
    bonus_xp = int((request.score - 70) / 10) * 2 if request.score > 70 else 0
    total_xp = base_xp + max(0, bonus_xp)

    xp_earned = add_user_xp(db, user_id, total_xp,
                            f"Passou avaliação com {request.score}%")

    # Badge para avaliação final
    badge_granted = False
    if request.assessment_type == "final":
        badge_granted = grant_badge(db, user_id, f"Avaliação Final {request.level_name}")

    return {
        "message": "Assessment completed successfully",
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Avaliação Final {request.level_name}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.post("/certification/award")
async def award_certification(
        request: CertificationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Emite uma certificação para o usuário
    """
    user_id = current_user["id"]

    cert_data = {
        "title": request.title,
        "date": time.strftime("%Y-%m-%d"),
        "id": f"CERT-{int(time.time())}",
        "area": request.area_name or "",
        "subarea": request.subarea_name or ""
    }

    # Adicionar certificação
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "certifications": ArrayUnion([cert_data])
    })

    # Adicionar XP e badge
    xp_earned = add_user_xp(db, user_id, XP_REWARDS.get("get_certification", 75),
                            f"Certificação: {request.title}")

    badge_granted = grant_badge(db, user_id, f"Certificado: {request.title[:20]}")

    return {
        "message": "Certification awarded successfully",
        "certification_id": cert_data["id"],
        "xp_earned": xp_earned["xp_added"],
        "badge_earned": f"Certificado: {request.title[:20]}" if badge_granted else None,
        "new_level": xp_earned["new_level"] if xp_earned["level_up"] else None
    }


@router.get("/statistics", response_model=ProgressStatistics)
async def get_progress_statistics(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém estatísticas detalhadas de progresso do usuário
    """
    user_id = current_user["id"]

    # Calcular estatísticas
    completed_lessons = len(current_user.get("completed_lessons", []))
    completed_modules = len(current_user.get("completed_modules", []))
    completed_levels = len(current_user.get("completed_levels", []))
    completed_projects = len(current_user.get("completed_projects", []))
    certifications = len(current_user.get("certifications", []))

    # Projetos ativos
    started_projects = current_user.get("started_projects", [])
    completed_project_titles = [p.get("title") for p in current_user.get("completed_projects", [])]
    active_projects = len([p for p in started_projects if p.get("title") not in completed_project_titles])

    # Streak de estudo (simplificado)
    current_streak = 0
    last_activity = current_user.get("last_login", 0)
    if last_activity and (time.time() - last_activity) < 48 * 60 * 60:  # 48 horas
        current_streak = current_user.get("study_streak", 0) + 1

    # Área mais forte
    strongest_area = None
    track_scores = current_user.get("track_scores", {})
    if track_scores:
        strongest_area = max(track_scores.items(), key=lambda x: x[1])[0]

    # Tempo total estudado (estimativa baseada em atividades)
    total_study_time = (completed_lessons * 30) + (completed_modules * 60) + (completed_projects * 120)  # em minutos

    return ProgressStatistics(
        completed_lessons=completed_lessons,
        completed_modules=completed_modules,
        completed_levels=completed_levels,
        completed_projects=completed_projects,
        active_projects=active_projects,
        certifications=certifications,
        current_streak=current_streak,
        total_study_time_minutes=total_study_time,
        strongest_area=strongest_area,
        last_activity=last_activity
    )


@router.get("/path", response_model=UserProgressPath)
async def get_user_progress_path(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o caminho completo de progresso do usuário
    """
    user_id = current_user["id"]
    progress = get_user_progress(db, user_id)

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress path found"
        )

    # Buscar dados da área atual
    area_name = progress.get("area", "")
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area_name)
    area_doc = area_ref.get()

    available_subareas = []
    if area_doc.exists:
        area_data = area_doc.to_dict()
        available_subareas = list(area_data.get("subareas", {}).keys())

    current = progress.get("current", {})

    return UserProgressPath(
        area=area_name,
        available_subareas=available_subareas,
        current_subarea=current.get("subarea", ""),
        current_level=current.get("level", "iniciante"),
        subareas_order=progress.get("subareas_order", []),
        progress_percentage=calculate_progress_percentage(db, user_id, progress)
    )


@router.get("/next-steps", response_model=NextStepResponse)
async def get_next_steps(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém sugestões de próximos passos para o usuário
    """
    user_id = current_user["id"]
    recommendations = get_next_recommendations(db, user_id, current_user)

    return NextStepResponse(
        user_id=user_id,
        recommendations=recommendations,
        generated_at=time.time()
    )


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

    return {
        "message": f"Progress advanced to next {step_type}",
        "current_progress": result
    }


# Adicione estes endpoints ao arquivo app/api/v1/endpoints/progress.py

@router.post("/switch-track")
async def switch_learning_track(
        new_track: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Troca a trilha de aprendizado ativa do usuário

    - Preserva o progresso da trilha anterior
    - Restaura progresso se já estudou a nova trilha antes
    """
    user_id = current_user["id"]
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
    add_user_xp(db, user_id, 5, f"Mudou para trilha: {new_track}")

    return {
        "message": "Track switched successfully",
        "old_track": old_track,
        "new_track": new_track,
        "progress_restored": new_track in saved_progress
    }


@router.get("/current-content")
async def get_current_content(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém o conteúdo atual baseado no progresso do usuário

    - Retorna o passo/lição atual
    - Inclui contexto do módulo e nível
    - Gera conteúdo dinamicamente se necessário
    """
    user_id = current_user["id"]
    progress = current_user.get("progress", {})

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress found"
        )

    area = progress.get("area", "")
    current = progress.get("current", {})
    subarea = current.get("subarea", "")
    level = current.get("level", "iniciante")
    module_idx = current.get("module_index", 0)
    lesson_idx = current.get("lesson_index", 0)
    step_idx = current.get("step_index", 0)

    # Buscar dados do currículo
    area_ref = db.collection(Collections.LEARNING_PATHS).document(area)
    area_doc = area_ref.get()

    if not area_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found"
        )

    area_data = area_doc.to_dict()

    # Navegar até o conteúdo atual
    try:
        subarea_data = area_data["subareas"][subarea]
        level_data = subarea_data["levels"][level]
        module_data = level_data["modules"][module_idx]
        lesson_data = module_data["lessons"][lesson_idx]

        # Se a lição tem passos
        if "steps" in lesson_data and lesson_data["steps"]:
            if step_idx < len(lesson_data["steps"]):
                step_content = lesson_data["steps"][step_idx]

                # Gerar conteúdo expandido para o passo
                user_age = current_user.get("age", 14)
                teaching_style = current_user.get("learning_style", "didático")

                context = f"Área: {area}, Subárea: {subarea}, Nível: {level}"

                # Usar LLM para expandir o conteúdo do passo
                expanded_content = call_teacher_llm(
                    f"Explique de forma didática para um estudante de {user_age} anos: {step_content}. "
                    f"Contexto: {context}. Use exemplos práticos e linguagem acessível.",
                    student_age=user_age,
                    subject_area=area,
                    teaching_style=teaching_style
                )

                return {
                    "content_type": "step",
                    "title": lesson_data.get("lesson_title", ""),
                    "content": expanded_content,
                    "original_step": step_content,
                    "context": {
                        "area": area,
                        "subarea": subarea,
                        "level": level,
                        "module": module_data.get("module_title", ""),
                        "lesson": lesson_data.get("lesson_title", ""),
                        "step": f"{step_idx + 1}/{len(lesson_data['steps'])}"
                    },
                    "navigation": {
                        "has_previous": step_idx > 0 or lesson_idx > 0 or module_idx > 0,
                        "has_next": True
                    }
                }
        else:
            # Lição sem passos - gerar conteúdo completo
            lesson_title = lesson_data.get("lesson_title", "")
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

            return {
                "content_type": "lesson",
                "title": lesson_title,
                "content": lesson.to_text(),
                "objectives": objectives,
                "context": {
                    "area": area,
                    "subarea": subarea,
                    "level": level,
                    "module": module_data.get("module_title", ""),
                    "lesson": lesson_title
                },
                "navigation": {
                    "has_previous": lesson_idx > 0 or module_idx > 0,
                    "has_next": True
                }
            }

    except (KeyError, IndexError) as e:
        # Conteúdo não encontrado na posição atual
        return {
            "content_type": "error",
            "message": "Content not found at current position",
            "error": str(e),
            "current_position": {
                "module_index": module_idx,
                "lesson_index": lesson_idx,
                "step_index": step_idx
            }
        }


@router.post("/register-specialization-completion")
async def register_specialization_completion(
        spec_name: str,
        area_name: str,
        subarea_name: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Registra a conclusão de uma especialização
    """
    user_id = current_user["id"]

    spec_data = {
        "name": spec_name,
        "area": area_name,
        "subarea": subarea_name,
        "completion_date": time.strftime("%Y-%m-%d")
    }

    # Adicionar à lista de especializações completadas
    user_ref = db.collection(Collections.USERS).document(user_id)
    user_ref.update({
        "completed_specializations": ArrayUnion([spec_data])
    })

    # Adicionar XP e badges
    xp_result = add_user_xp(db, user_id, 100, f"Completou especialização: {spec_name}")
    grant_badge(db, user_id, f"Especialista Master em {spec_name}")

    # Emitir certificação
    cert_data = {
        "title": f"Especialização em {spec_name}",
        "date": time.strftime("%Y-%m-%d"),
        "id": f"CERT-SPEC-{int(time.time())}",
        "area": area_name,
        "subarea": subarea_name
    }

    user_ref.update({
        "certifications": ArrayUnion([cert_data])
    })

    return {
        "message": "Specialization completed successfully",
        "xp_earned": xp_result["xp_added"],
        "badge_earned": f"Especialista Master em {spec_name}",
        "certification_id": cert_data["id"],
        "new_level": xp_result["new_level"] if xp_result["level_up"] else None
    }