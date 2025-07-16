# app/api/v1/endpoints/analytics.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta
import asyncio
from app.services.event_service import event_service, EventTypes
import logging
from app.core.security import get_current_user
from app.database import get_db, Collections
from app.schemas.analytics import (
    DashboardMetrics,
    AssessmentGenerationRequest,
    StudySessionGenerationRequest,
    LearningPathGenerationRequest,
    SmartAssessmentResponse,
    FocusedSessionResponse,
    AdaptiveLearningPathResponse
)
from app.utils.llm_integration import call_teacher_llm
from app.utils.gamification import calculate_study_streak
import json

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/dashboard/metrics")
async def get_dashboard_metrics(
        period: str = Query("week", description="Period: today, week, month, all"),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém métricas otimizadas para o dashboard
    Usa apenas Firestore para performance
    """
    user_id = current_user["id"]

    # Calcular métricas básicas
    metrics = {
        "current_level": current_user.get("profile_level", 1),
        "current_xp": current_user.get("profile_xp", 0),
        "total_badges": len(current_user.get("badges", [])),
        "current_streak": calculate_study_streak(current_user),
        "completed_lessons": len(current_user.get("completed_lessons", [])),
        "completed_modules": len(current_user.get("completed_modules", [])),
        "active_projects": count_active_projects(current_user),
        "current_area": current_user.get("current_track", ""),
        "current_subarea": current_user.get("progress", {}).get("current", {}).get("subarea", ""),
        "progress_percentage": calculate_current_progress(current_user)
    }

    # Calcular métricas do período
    if period == "today":
        metrics["today_stats"] = calculate_today_stats(current_user)
    elif period == "week":
        metrics["week_stats"] = calculate_week_stats(current_user)

    return metrics


@router.post("/generate-assessment", response_model=SmartAssessmentResponse)
async def generate_smart_assessment(
        request: AssessmentGenerationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera avaliação inteligente baseada no progresso do usuário
    """
    user_id = current_user["id"]

    # Analisar conhecimento do usuário
    knowledge_analysis = analyze_user_knowledge(current_user, request.focus_area)

    # Determinar tópicos e dificuldade
    if request.difficulty == "adaptive":
        difficulty = determine_adaptive_difficulty(current_user, knowledge_analysis)
    else:
        difficulty = request.difficulty or "medium"

    # Preparar contexto para o LLM
    context = {
        "user_age": current_user.get("age", 14),
        "learning_style": current_user.get("learning_style", "visual"),
        "current_level": current_user.get("profile_level", 1),
        "area": request.area or current_user.get("current_track"),
        "subarea": request.subarea or current_user.get("progress", {}).get("current", {}).get("subarea"),
        "level": request.level or current_user.get("progress", {}).get("current", {}).get("level", "iniciante"),
        "focus_topics": knowledge_analysis.get("weak_topics", []),
        "avoid_topics": knowledge_analysis.get("strong_topics", []),
        "previous_scores": get_recent_assessment_scores(current_user)
    }

    # Gerar prompt para o LLM
    prompt = f"""
    Crie uma avaliação personalizada com as seguintes características:

    - Área: {context['area']}
    - Subárea: {context['subarea']}
    - Nível: {context['level']}
    - Dificuldade: {difficulty}
    - Número de questões: {request.question_count}
    - Idade do aluno: {context['user_age']} anos
    - Estilo de aprendizagem: {context['learning_style']}

    Foque nos tópicos: {', '.join(context['focus_topics'][:3]) if context['focus_topics'] else 'conteúdo geral'}

    Formato da resposta JSON:
    {{
        "title": "Título da Avaliação",
        "description": "Descrição breve",
        "questions": [
            {{
                "id": 1,
                "question": "Pergunta completa",
                "type": "multiple_choice",
                "options": ["A) Opção 1", "B) Opção 2", "C) Opção 3", "D) Opção 4"],
                "correct_answer": "A",
                "explanation": "Explicação da resposta correta",
                "topic": "Tópico específico",
                "difficulty": "easy|medium|hard"
            }}
        ],
        "estimated_time_minutes": 15,
        "passing_score": 70
    }}

    Importante:
    - Use linguagem apropriada para a idade
    - Varie os tipos de questões se possível
    - Inclua explicações educativas
    - Garanta que as questões sejam progressivas
    """

    # Chamar LLM
    llm_response = call_teacher_llm(
        prompt,
        student_age=context['user_age'],
        subject_area=context['area'],
        teaching_style=context['learning_style']
    )

    # Parse da resposta
    try:
        assessment_data = json.loads(llm_response)
    except:
        # Fallback se o parsing falhar
        assessment_data = {
            "title": f"Avaliação de {context['subarea']}",
            "description": "Teste seus conhecimentos",
            "questions": generate_fallback_questions(context, request.question_count),
            "estimated_time_minutes": request.question_count * 1.5,
            "passing_score": 70
        }

    # Criar resposta
    assessment_id = f"assessment_{user_id}_{int(datetime.utcnow().timestamp())}"

    # Salvar metadados da avaliação
    assessment_metadata = {
        "assessment_id": assessment_id,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat(),
        "area": context['area'],
        "subarea": context['subarea'],
        "difficulty": difficulty,
        "question_count": len(assessment_data['questions']),
        "status": "pending"
    }

    # Armazenar no Firestore
    db.collection("assessments").document(assessment_id).set({
        **assessment_metadata,
        "assessment_data": assessment_data
    })

    # Publicar evento
    await event_service.publish_event(
        event_type=EventTypes.AI_ASSESSMENT_GENERATED,
        user_id=user_id,
        data={
            "assessment_id": assessment_id,
            "area": context['area'],
            "subarea": context['subarea'],
            "difficulty": difficulty,
            "question_count": len(assessment_data['questions']),
            "focus_topics": context['focus_topics'][:3]
        }
    )

    return SmartAssessmentResponse(
        assessment_id=assessment_id,
        assessment=assessment_data,
        metadata={
            "difficulty": difficulty,
            "personalized": True,
            "based_on_gaps": len(context['focus_topics']) > 0,
            "adaptive": request.difficulty == "adaptive",
            "estimated_time": assessment_data['estimated_time_minutes']
        }
    )


@router.post("/generate-study-session", response_model=FocusedSessionResponse)
async def generate_focused_study_session(
        request: StudySessionGenerationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera sessão de estudo focada e personalizada
    """
    user_id = current_user["id"]

    # Analisar contexto atual
    current_context = get_user_learning_context(current_user)

    # Determinar tópico se não especificado
    if not request.topic:
        request.topic = determine_next_topic(current_user, current_context)

    # Analisar energia e melhor tipo de sessão
    user_state = analyze_user_state(current_user)
    session_recommendations = get_session_recommendations(
        user_state,
        request.duration_minutes,
        request.session_type
    )

    # Preparar prompt para o LLM
    prompt = f"""
    Crie uma sessão de estudo focada com as seguintes características:

    - Tópico: {request.topic}
    - Duração: {request.duration_minutes} minutos
    - Tipo: {request.session_type} (theory/practice/mixed)
    - Nível do aluno: {current_user.get('profile_level', 1)}
    - Idade: {current_user.get('age', 14)} anos
    - Área atual: {current_context['area']}
    - Energia estimada: {user_state['energy_level']}

    Estruture a sessão no formato JSON:
    {{
        "title": "Título da Sessão",
        "topic": "{request.topic}",
        "objectives": ["Objetivo 1", "Objetivo 2", "Objetivo 3"],
        "structure": [
            {{
                "phase": "Aquecimento",
                "duration_minutes": 5,
                "activities": [
                    {{
                        "type": "review|explanation|exercise|quiz",
                        "content": "Descrição detalhada da atividade",
                        "materials": ["Material 1", "Material 2"],
                        "tips": ["Dica 1", "Dica 2"]
                    }}
                ]
            }},
            {{
                "phase": "Desenvolvimento",
                "duration_minutes": 20,
                "activities": [...]
            }},
            {{
                "phase": "Conclusão",
                "duration_minutes": 5,
                "activities": [...]
            }}
        ],
        "key_concepts": ["Conceito 1", "Conceito 2"],
        "practice_exercises": [
            {{
                "title": "Exercício 1",
                "description": "Descrição",
                "difficulty": "easy|medium|hard",
                "estimated_time": 5
            }}
        ],
        "breaks": [
            {{
                "after_minutes": 15,
                "duration": 2,
                "suggestion": "Sugestão de pausa"
            }}
        ],
        "success_criteria": ["Critério 1", "Critério 2"],
        "next_steps": ["Próximo passo 1", "Próximo passo 2"]
    }}

    Considere:
    - Incluir pausas se a sessão for maior que 25 minutos
    - Variar atividades para manter engajamento
    - Adaptar linguagem para a idade
    - {session_recommendations}
    """

    # Chamar LLM
    llm_response = call_teacher_llm(
        prompt,
        student_age=current_user.get('age', 14),
        subject_area=current_context['area'],
        teaching_style=current_user.get('learning_style', 'visual')
    )

    # Parse da resposta
    try:
        session_data = json.loads(llm_response)
    except:
        # Fallback
        session_data = generate_fallback_session(
            request.topic,
            request.duration_minutes,
            request.session_type,
            current_context
        )

    # Criar ID da sessão
    session_id = f"session_{user_id}_{int(datetime.utcnow().timestamp())}"

    # Salvar sessão
    session_metadata = {
        "session_id": session_id,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat(),
        "topic": request.topic,
        "duration_minutes": request.duration_minutes,
        "session_type": request.session_type,
        "status": "ready",
        "context": current_context
    }

    db.collection("study_sessions").document(session_id).set({
        **session_metadata,
        "session_data": session_data
    })

    # Publicar evento
    await event_service.publish_event(
        event_type=EventTypes.AI_CONTENT_GENERATED,
        user_id=user_id,
        data={
            "content_type": "study_session",
            "session_id": session_id,
            "topic": request.topic,
            "duration": request.duration_minutes,
            "session_type": request.session_type
        }
    )

    return FocusedSessionResponse(
        session_id=session_id,
        session=session_data,
        personalization={
            "adapted_to_time": True,
            "considers_energy": True,
            "includes_breaks": request.duration_minutes > 25,
            "variety_score": calculate_variety_score(session_data),
            "engagement_optimization": True
        }
    )


@router.post("/generate-learning-path", response_model=AdaptiveLearningPathResponse)
async def generate_adaptive_learning_path(
        request: LearningPathGenerationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera plano de estudos adaptativo personalizado
    """
    user_id = current_user["id"]

    # Analisar progresso e ritmo
    progress_analysis = analyze_learning_progress(current_user)
    pace_analysis = calculate_learning_pace(current_user)

    # Obter conteúdo disponível
    available_content = get_available_content_for_planning(
        db,
        current_user.get("current_track"),
        current_user.get("progress", {}),
        request.duration_weeks
    )

    # Estimar disponibilidade
    availability = estimate_user_availability(current_user, progress_analysis)

    # Preparar contexto
    context = {
        "current_position": current_user.get("progress", {}),
        "learning_pace": pace_analysis,
        "weekly_hours": availability['hours_per_week'],
        "preferred_times": availability['best_times'],
        "learning_style": current_user.get("learning_style", "visual"),
        "age": current_user.get("age", 14),
        "goals": request.goals or ["Completar o nível atual", "Dominar conceitos fundamentais"],
        "strengths": progress_analysis.get("strengths", []),
        "weaknesses": progress_analysis.get("weaknesses", [])
    }

    # Gerar prompt
    prompt = f"""
    Crie um plano de estudos personalizado e adaptativo:

    - Duração: {request.duration_weeks} semanas
    - Posição atual: {context['current_position'].get('area')} - {context['current_position'].get('current', {}).get('subarea')}
    - Nível: {context['current_position'].get('current', {}).get('level', 'iniciante')}
    - Ritmo atual: {pace_analysis['lessons_per_week']} lições/semana
    - Disponibilidade: {availability['hours_per_week']} horas/semana
    - Objetivos: {', '.join(context['goals'])}

    Conteúdo disponível para as próximas semanas:
    {json.dumps(available_content[:10], indent=2)}

    Formato JSON do plano:
    {{
        "title": "Plano de Estudos Personalizado",
        "duration_weeks": {request.duration_weeks},
        "start_date": "{datetime.utcnow().date().isoformat()}",
        "end_date": "{(datetime.utcnow() + timedelta(weeks=request.duration_weeks)).date().isoformat()}",
        "goals": ["Meta 1", "Meta 2", "Meta 3"],
        "weekly_plans": [
            {{
                "week": 1,
                "theme": "Tema da Semana",
                "objectives": ["Objetivo 1", "Objetivo 2"],
                "content": [
                    {{
                        "day": 1,
                        "date": "2024-01-01",
                        "activities": [
                            {{
                                "type": "lesson|practice|project|assessment",
                                "title": "Título",
                                "description": "Descrição",
                                "duration_minutes": 30,
                                "priority": "high|medium|low",
                                "resources": ["Recurso 1"]
                            }}
                        ],
                        "estimated_time": 45,
                        "flexibility": "fixed|flexible|optional"
                    }}
                ],
                "milestones": ["Marco 1", "Marco 2"],
                "assessment": {{
                    "type": "quiz|project|practical",
                    "title": "Avaliação Semanal",
                    "scheduled_day": 5
                }}
            }}
        ],
        "adaptation_rules": [
            {{
                "condition": "se o aluno completar tudo antes do prazo",
                "action": "adicionar conteúdo bônus"
            }},
            {{
                "condition": "se o aluno ficar atrasado",
                "action": "reduzir carga e focar no essencial"
            }}
        ],
        "review_sessions": [
            {{
                "week": 2,
                "day": 3,
                "topics": ["Tópico 1", "Tópico 2"],
                "duration_minutes": 30
            }}
        ],
        "projects": [
            {{
                "title": "Projeto Prático",
                "description": "Descrição",
                "start_week": 2,
                "duration_weeks": 2,
                "deliverables": ["Entregável 1", "Entregável 2"]
            }}
        ],
        "success_metrics": [
            "Completar 80% das atividades",
            "Passar em todas as avaliações com 70%+",
            "Entregar todos os projetos"
        ],
        "flexibility_options": {{
            "can_skip": ["atividades opcionais"],
            "can_reschedule": ["projetos", "avaliações"],
            "buffer_days": 2
        }}
    }}

    Considere:
    - Intercalar teoria e prática
    - Incluir revisões periódicas
    - Adaptar carga baseada no ritmo atual
    - Incluir projetos práticos
    - Manter motivação com marcos alcançáveis
    """

    # Chamar LLM
    llm_response = call_teacher_llm(
        prompt,
        student_age=context['age'],
        subject_area=context['current_position'].get('area', ''),
        teaching_style=context['learning_style']
    )

    # Parse da resposta
    try:
        learning_path = json.loads(llm_response)
    except:
        # Fallback
        learning_path = generate_fallback_learning_path(
            request.duration_weeks,
            context,
            available_content
        )

    # Criar ID do plano
    path_id = f"path_{user_id}_{int(datetime.utcnow().timestamp())}"

    # Salvar plano
    path_metadata = {
        "path_id": path_id,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat(),
        "duration_weeks": request.duration_weeks,
        "status": "active",
        "progress": {
            "completed_activities": 0,
            "total_activities": count_total_activities(learning_path),
            "current_week": 1
        }
    }

    db.collection("learning_paths").document(path_id).set({
        **path_metadata,
        "path_data": learning_path,
        "context": context
    })

    # Publicar evento
    await event_service.publish_event(
        event_type=EventTypes.AI_PATH_GENERATED,
        user_id=user_id,
        data={
            "path_id": path_id,
            "duration_weeks": request.duration_weeks,
            "total_activities": path_metadata['progress']['total_activities'],
            "includes_projects": len(learning_path.get('projects', [])) > 0,
            "personalized": True
        }
    )

    return AdaptiveLearningPathResponse(
        path_id=path_id,
        learning_path=learning_path,
        personalization={
            "based_on_pace": True,
            "considers_availability": True,
            "includes_buffer": True,
            "adaptive_rules": len(learning_path.get('adaptation_rules', [])) > 0,
            "flexibility_score": calculate_flexibility_score(learning_path)
        },
        estimated_completion_date=(datetime.utcnow() + timedelta(weeks=request.duration_weeks)).date().isoformat()
    )


# ====================================
# FUNÇÕES AUXILIARES IMPLEMENTADAS
# ====================================

def count_active_projects(user_data: dict) -> int:
    """Conta projetos ativos"""
    started = user_data.get("started_projects", [])
    completed = user_data.get("completed_projects", [])
    completed_titles = {p.get("title") for p in completed}
    return len([p for p in started if p.get("title") not in completed_titles])


def calculate_current_progress(user_data: dict) -> float:
    """Calcula progresso no nível atual"""
    progress = user_data.get("progress", {})
    current = progress.get("current", {})

    # Estimativa simplificada
    module_weight = 33.33
    lesson_weight = module_weight / 5  # 5 lições por módulo
    step_weight = lesson_weight / 4  # 4 passos por lição

    total = (
            current.get("module_index", 0) * module_weight +
            current.get("lesson_index", 0) * lesson_weight +
            current.get("step_index", 0) * step_weight
    )

    return min(total, 100.0)


def calculate_today_stats(user_data: dict) -> dict:
    """Calcula estatísticas do dia atual"""
    today = datetime.utcnow().date().isoformat()

    lessons_today = 0
    modules_today = 0
    xp_today = 0
    time_spent = 0

    # Contar lições de hoje
    for lesson in user_data.get("completed_lessons", []):
        if lesson.get("completion_date") == today:
            lessons_today += 1
            # Estimar tempo por lição
            time_spent += 30

    # Contar módulos de hoje
    for module in user_data.get("completed_modules", []):
        if module.get("completion_date") == today:
            modules_today += 1
            time_spent += 45

    # Estimar XP ganho hoje
    xp_today = (lessons_today * 10) + (modules_today * 15)

    # Verificar projetos de hoje
    projects_today = 0
    for project in user_data.get("started_projects", []):
        if project.get("start_date") == today:
            projects_today += 1
            xp_today += 10

    for project in user_data.get("completed_projects", []):
        if project.get("completion_date") == today:
            projects_today += 1
            xp_today += 25

    return {
        "date": today,
        "lessons_completed": lessons_today,
        "modules_completed": modules_today,
        "projects_worked": projects_today,
        "xp_earned": xp_today,
        "time_spent_minutes": time_spent,
        "is_active": lessons_today > 0 or modules_today > 0,
        "daily_goal_met": lessons_today >= 1  # Meta diária: pelo menos 1 lição
    }


def calculate_week_stats(user_data: dict) -> dict:
    """Calcula estatísticas da semana atual"""
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    lessons_week = 0
    modules_week = 0
    projects_week = 0
    xp_week = 0
    active_days = set()
    daily_breakdown = {}

    # Inicializar dias da semana
    for i in range(7):
        day = week_start + timedelta(days=i)
        daily_breakdown[day.isoformat()] = {
            "lessons": 0,
            "modules": 0,
            "xp": 0
        }

    # Processar lições da semana
    for lesson in user_data.get("completed_lessons", []):
        completion_date = lesson.get("completion_date")
        if completion_date:
            try:
                lesson_date = datetime.fromisoformat(completion_date).date()
                if week_start <= lesson_date <= week_end:
                    lessons_week += 1
                    active_days.add(lesson_date.isoformat())
                    if lesson_date.isoformat() in daily_breakdown:
                        daily_breakdown[lesson_date.isoformat()]["lessons"] += 1
                        daily_breakdown[lesson_date.isoformat()]["xp"] += 10
            except:
                pass

    # Processar módulos da semana
    for module in user_data.get("completed_modules", []):
        completion_date = module.get("completion_date")
        if completion_date:
            try:
                module_date = datetime.fromisoformat(completion_date).date()
                if week_start <= module_date <= week_end:
                    modules_week += 1
                    active_days.add(module_date.isoformat())
                    if module_date.isoformat() in daily_breakdown:
                        daily_breakdown[module_date.isoformat()]["modules"] += 1
                        daily_breakdown[module_date.isoformat()]["xp"] += 15
            except:
                pass

    # Processar projetos da semana
    for project in user_data.get("started_projects", []):
        start_date = project.get("start_date")
        if start_date:
            try:
                project_date = datetime.fromisoformat(start_date).date()
                if week_start <= project_date <= week_end:
                    projects_week += 1
            except:
                pass

    # XP total da semana
    xp_week = (lessons_week * 10) + (modules_week * 15)

    # Melhor dia da semana
    best_day = None
    max_xp = 0
    for day, stats in daily_breakdown.items():
        if stats["xp"] > max_xp:
            max_xp = stats["xp"]
            best_day = day

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "lessons_completed": lessons_week,
        "modules_completed": modules_week,
        "projects_active": projects_week,
        "xp_earned": xp_week,
        "active_days": len(active_days),
        "daily_breakdown": daily_breakdown,
        "best_day": best_day,
        "weekly_goal_progress": min((lessons_week / 5) * 100, 100),  # Meta: 5 lições/semana
        "on_track": lessons_week >= (today.weekday() + 1) * 0.7  # 70% do esperado até hoje
    }


def analyze_user_knowledge(user_data: dict, focus_area: Optional[str]) -> dict:
    """Analisa conhecimento do usuário para identificar gaps"""
    completed_lessons = user_data.get("completed_lessons", [])
    failed_assessments = user_data.get("failed_assessments", [])
    passed_assessments = user_data.get("passed_assessments", [])

    # Identificar tópicos fracos
    weak_topics = []
    for assessment in failed_assessments:
        if assessment.get("module"):
            weak_topics.append(assessment["module"])

    # Identificar tópicos fortes
    strong_topics = []
    for assessment in passed_assessments:
        if assessment.get("score", 0) >= 90:
            strong_topics.append(assessment.get("module", ""))

    return {
        "weak_topics": list(set(weak_topics)),
        "strong_topics": list(set(strong_topics)),
        "total_lessons_completed": len(completed_lessons),
        "assessment_history": len(passed_assessments) + len(failed_assessments)
    }


def determine_adaptive_difficulty(user_data: dict, knowledge: dict) -> str:
    """Determina dificuldade adaptativa baseada no desempenho"""
    level = user_data.get("profile_level", 1)
    recent_scores = get_recent_assessment_scores(user_data)

    if not recent_scores:
        return "medium"

    avg_score = sum(recent_scores) / len(recent_scores)

    if avg_score >= 85 and level >= 5:
        return "hard"
    elif avg_score >= 70:
        return "medium"
    else:
        return "easy"


def get_recent_assessment_scores(user_data: dict, limit: int = 5) -> List[float]:
    """Obtém scores recentes de avaliações"""
    all_assessments = (
            user_data.get("passed_assessments", []) +
            user_data.get("failed_assessments", [])
    )

    # Ordenar por data
    sorted_assessments = sorted(
        all_assessments,
        key=lambda x: x.get("timestamp", 0),
        reverse=True
    )

    return [a.get("score", 0) for a in sorted_assessments[:limit]]


def get_user_learning_context(user_data: dict) -> dict:
    """Obtém contexto completo de aprendizagem do usuário"""
    progress = user_data.get("progress", {})
    current = progress.get("current", {})

    return {
        "area": progress.get("area", user_data.get("current_track", "")),
        "subarea": current.get("subarea", ""),
        "level": current.get("level", "iniciante"),
        "module_index": current.get("module_index", 0),
        "lesson_index": current.get("lesson_index", 0),
        "completed_lessons": len(user_data.get("completed_lessons", [])),
        "completed_modules": len(user_data.get("completed_modules", [])),
        "learning_style": user_data.get("learning_style", "visual"),
        "age": user_data.get("age", 14),
        "profile_level": user_data.get("profile_level", 1)
    }


def determine_next_topic(user_data: dict, context: dict) -> str:
    """Determina o próximo tópico ideal para estudo"""
    # Baseado no progresso atual
    area = context.get("area", "Tecnologia")
    subarea = context.get("subarea", "Programação")
    level = context.get("level", "iniciante")

    # Simplificado - em produção, isso consultaria o banco de dados
    base_topics = {
        "iniciante": ["Conceitos Básicos", "Introdução", "Fundamentos"],
        "intermediário": ["Aplicações Práticas", "Técnicas Avançadas", "Projetos"],
        "avançado": ["Especialização", "Otimização", "Casos Complexos"]
    }

    topics = base_topics.get(level, base_topics["iniciante"])
    module_idx = context.get("module_index", 0) % len(topics)

    return f"{topics[module_idx]} de {subarea}"


def analyze_user_state(user_data: dict) -> dict:
    """Analisa estado atual do usuário (energia, foco, etc)"""
    today_stats = calculate_today_stats(user_data)
    current_hour = datetime.utcnow().hour

    # Estimar nível de energia baseado no horário e atividade
    if 6 <= current_hour < 12:
        energy_level = "high"
    elif 12 <= current_hour < 15:
        energy_level = "medium"
    elif 15 <= current_hour < 18:
        energy_level = "high"
    elif 18 <= current_hour < 21:
        energy_level = "medium"
    else:
        energy_level = "low"

    # Ajustar baseado em atividade do dia
    if today_stats["lessons_completed"] >= 3:
        energy_level = "low"  # Já estudou muito
    elif today_stats["lessons_completed"] == 0:
        energy_level = "high" if energy_level != "low" else "medium"

    return {
        "energy_level": energy_level,
        "optimal_duration": 45 if energy_level == "high" else 30 if energy_level == "medium" else 15,
        "recommended_type": "practice" if energy_level == "high" else "theory" if energy_level == "medium" else "review",
        "focus_score": 80 if energy_level == "high" else 60 if energy_level == "medium" else 40,
        "break_needed": today_stats["time_spent_minutes"] > 60
    }


def get_session_recommendations(user_state: dict, duration: int, session_type: str) -> str:
    """Gera recomendações para a sessão baseadas no estado do usuário"""
    recommendations = []

    if user_state["energy_level"] == "low":
        recommendations.append("Inclua mais pausas e atividades interativas")

    if user_state["break_needed"]:
        recommendations.append("Comece com uma pausa de 5 minutos para descansar")

    if duration > 45:
        recommendations.append("Divida em blocos menores com pausas entre eles")

    if session_type == "practice" and user_state["energy_level"] != "high":
        recommendations.append("Considere alternar entre teoria e prática")

    return " | ".join(recommendations) if recommendations else "Sessão otimizada para o momento atual"


def generate_fallback_questions(context: dict, count: int) -> List[dict]:
    """Gera questões de fallback caso o LLM falhe"""
    questions = []

    for i in range(count):
        question = {
            "id": i + 1,
            "question": f"Questão {i + 1} sobre {context.get('subarea', 'o conteúdo')}",
            "type": "multiple_choice",
            "options": [
                "A) Opção 1",
                "B) Opção 2",
                "C) Opção 3",
                "D) Opção 4"
            ],
            "correct_answer": "A",
            "explanation": "Explicação padrão da resposta",
            "topic": context.get('subarea', 'Geral'),
            "difficulty": "medium"
        }
        questions.append(question)

    return questions


def generate_fallback_session(topic: str, duration: int, session_type: str, context: dict) -> dict:
    """Gera sessão de fallback caso o LLM falhe"""
    # Estrutura básica de sessão
    warm_up_duration = min(5, duration // 6)
    cool_down_duration = min(5, duration // 6)
    main_duration = duration - warm_up_duration - cool_down_duration

    return {
        "title": f"Sessão de {session_type} - {topic}",
        "topic": topic,
        "objectives": [
            f"Compreender os conceitos de {topic}",
            f"Aplicar o conhecimento em exercícios práticos",
            f"Revisar e consolidar o aprendizado"
        ],
        "structure": [
            {
                "phase": "Aquecimento",
                "duration_minutes": warm_up_duration,
                "activities": [
                    {
                        "type": "review",
                        "content": f"Revisão rápida dos conceitos anteriores relacionados a {topic}",
                        "materials": ["Notas da aula anterior"],
                        "tips": ["Anote suas dúvidas", "Identifique pontos que precisa revisar"]
                    }
                ]
            },
            {
                "phase": "Desenvolvimento",
                "duration_minutes": main_duration,
                "activities": [
                    {
                        "type": session_type,
                        "content": f"Estudo focado em {topic}",
                        "materials": ["Material principal", "Exercícios"],
                        "tips": ["Mantenha o foco", "Faça anotações"]
                    }
                ]
            },
            {
                "phase": "Conclusão",
                "duration_minutes": cool_down_duration,
                "activities": [
                    {
                        "type": "review",
                        "content": "Resumo dos pontos principais aprendidos",
                        "materials": ["Suas anotações"],
                        "tips": ["Identifique o que aprendeu", "Planeje próximos passos"]
                    }
                ]
            }
        ],
        "key_concepts": [f"Conceito 1 de {topic}", f"Conceito 2 de {topic}"],
        "practice_exercises": [],
        "breaks": [{"after_minutes": 25, "duration": 5, "suggestion": "Levante e alongue-se"}] if duration > 25 else [],
        "success_criteria": ["Completar todas as atividades", "Fazer anotações dos pontos principais"],
        "next_steps": ["Revisar anotações", "Praticar com exercícios adicionais"]
    }


def analyze_learning_progress(user_data: dict) -> dict:
    """Analisa progresso de aprendizagem detalhado"""
    completed_lessons = user_data.get("completed_lessons", [])
    completed_modules = user_data.get("completed_modules", [])

    # Agrupar por área
    areas_progress = {}
    for lesson in completed_lessons:
        area = lesson.get("area", "unknown")
        if area not in areas_progress:
            areas_progress[area] = {"lessons": 0, "modules": 0}
        areas_progress[area]["lessons"] += 1

    for module in completed_modules:
        area = module.get("area", "unknown")
        if area not in areas_progress:
            areas_progress[area] = {"lessons": 0, "modules": 0}
        areas_progress[area]["modules"] += 1

    # Identificar pontos fortes e fracos
    strengths = []
    weaknesses = []

    for area, progress in areas_progress.items():
        if progress["modules"] >= 3:
            strengths.append(area)
        elif progress["lessons"] < 5:
            weaknesses.append(area)

    return {
        "areas_progress": areas_progress,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "total_completion": len(completed_lessons) + len(completed_modules) * 5
    }


def calculate_learning_pace(user_data: dict) -> dict:
    """Calcula ritmo de aprendizagem"""
    completed_lessons = user_data.get("completed_lessons", [])

    if not completed_lessons:
        return {
            "lessons_per_week": 3,  # Padrão
            "average_time_per_lesson": 30,
            "consistency": "new_user"
        }

    # Agrupar por semana
    lessons_by_week = {}
    for lesson in completed_lessons:
        if lesson.get("completion_date"):
            try:
                date = datetime.fromisoformat(lesson["completion_date"])
                week = date.isocalendar()[1]
                year = date.year
                key = f"{year}-{week}"

                if key not in lessons_by_week:
                    lessons_by_week[key] = 0
                lessons_by_week[key] += 1
            except:
                pass

    # Calcular média
    if lessons_by_week:
        avg_lessons = sum(lessons_by_week.values()) / len(lessons_by_week)
    else:
        avg_lessons = 3

    return {
        "lessons_per_week": round(avg_lessons, 1),
        "average_time_per_lesson": 30,  # Pode ser calculado com mais dados
        "consistency": "regular" if len(lessons_by_week) >= 4 else "irregular"
    }


def estimate_user_availability(user_data: dict, progress_analysis: dict) -> dict:
    """Estima disponibilidade do usuário baseada em histórico"""
    # Analisar padrão de estudo
    study_patterns = analyze_study_patterns(user_data)

    # Calcular horas por semana baseado em histórico
    avg_lessons_per_week = calculate_average_lessons_per_week(user_data)
    estimated_hours = avg_lessons_per_week * 0.5  # 30 min por lição

    return {
        "hours_per_week": max(estimated_hours, 3),  # Mínimo 3 horas
        "best_times": study_patterns.get("preferred_times", ["evening"]),
        "best_days": study_patterns.get("active_days", ["weekdays"]),
        "consistency": study_patterns.get("consistency", "moderate")
    }


def analyze_study_patterns(user_data: dict) -> dict:
    """Analisa padrões de estudo do usuário"""
    completed_lessons = user_data.get("completed_lessons", [])

    if not completed_lessons:
        return {
            "preferred_times": ["evening"],
            "active_days": ["weekdays"],
            "consistency": "new_user"
        }

    # Simplificado - análise básica
    weekday_count = 0
    weekend_count = 0

    for lesson in completed_lessons[-20:]:  # Últimas 20 lições
        try:
            date = datetime.fromisoformat(lesson.get("completion_date", ""))
            if date.weekday() < 5:
                weekday_count += 1
            else:
                weekend_count += 1
        except:
            pass

    return {
        "preferred_times": ["afternoon", "evening"],
        "active_days": ["weekdays"] if weekday_count > weekend_count else ["weekend"],
        "consistency": "regular" if len(completed_lessons) > 10 else "irregular"
    }


def calculate_average_lessons_per_week(user_data: dict) -> float:
    """Calcula média de lições por semana"""
    completed_lessons = user_data.get("completed_lessons", [])

    if not completed_lessons:
        return 5.0  # Padrão

    # Pegar lições das últimas 4 semanas
    four_weeks_ago = datetime.utcnow().date() - timedelta(weeks=4)
    recent_lessons = []

    for lesson in completed_lessons:
        try:
            date = datetime.fromisoformat(lesson.get("completion_date", "")).date()
            if date >= four_weeks_ago:
                recent_lessons.append(lesson)
        except:
            pass

    if recent_lessons:
        return len(recent_lessons) / 4
    else:
        return 5.0


def get_available_content_for_planning(db, area: str, progress: dict, weeks: int) -> List[dict]:
    """Obtém conteúdo disponível para as próximas semanas"""
    # Simplificado - em produção consultaria o banco
    available_content = []

    current = progress.get("current", {})
    current_module = current.get("module_index", 0)

    # Gerar conteúdo estimado
    for week in range(weeks):
        for day in range(5):  # 5 dias por semana
            content_item = {
                "week": week + 1,
                "day": day + 1,
                "module": current_module + week,
                "lesson": day + 1,
                "title": f"Lição {day + 1} - Módulo {current_module + week}",
                "type": "lesson",
                "estimated_time": 30,
                "difficulty": "progressive"
            }
            available_content.append(content_item)

    return available_content


def generate_fallback_learning_path(weeks: int, context: dict, content: List[dict]) -> dict:
    """Gera plano de estudos de fallback"""
    start_date = datetime.utcnow().date()
    end_date = start_date + timedelta(weeks=weeks)

    weekly_plans = []

    for week in range(weeks):
        week_plan = {
            "week": week + 1,
            "theme": f"Semana {week + 1} - {context['current_position'].get('subarea', 'Estudos')}",
            "objectives": [
                f"Completar módulo {week + 1}",
                "Praticar conceitos aprendidos"
            ],
            "content": [],
            "milestones": [f"Conclusão do módulo {week + 1}"],
            "assessment": {
                "type": "quiz",
                "title": f"Avaliação Semanal {week + 1}",
                "scheduled_day": 5
            }
        }

        # Adicionar atividades diárias
        for day in range(5):
            day_plan = {
                "day": day + 1,
                "date": (start_date + timedelta(weeks=week, days=day)).isoformat(),
                "activities": [
                    {
                        "type": "lesson",
                        "title": f"Lição {day + 1}",
                        "description": "Conteúdo principal do dia",
                        "duration_minutes": 30,
                        "priority": "high",
                        "resources": ["Material de estudo"]
                    }
                ],
                "estimated_time": 45,
                "flexibility": "flexible" if day > 2 else "fixed"
            }
            week_plan["content"].append(day_plan)

        weekly_plans.append(week_plan)

    return {
        "title": "Plano de Estudos Personalizado",
        "duration_weeks": weeks,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "goals": context.get("goals", ["Completar o nível atual"]),
        "weekly_plans": weekly_plans,
        "adaptation_rules": [
            {
                "condition": "se completar tudo antes do prazo",
                "action": "adicionar conteúdo extra"
            },
            {
                "condition": "se ficar atrasado",
                "action": "focar no essencial"
            }
        ],
        "review_sessions": [],
        "projects": [],
        "success_metrics": ["Completar 80% das atividades"],
        "flexibility_options": {
            "can_skip": ["atividades opcionais"],
            "can_reschedule": ["avaliações"],
            "buffer_days": 2
        }
    }


def count_total_activities(learning_path: dict) -> int:
    """Conta total de atividades no plano de estudos"""
    total = 0

    for week in learning_path.get("weekly_plans", []):
        for day in week.get("content", []):
            total += len(day.get("activities", []))

    return total


def calculate_variety_score(session_data: dict) -> float:
    """Calcula score de variedade da sessão"""
    activity_types = set()

    for phase in session_data.get("structure", []):
        for activity in phase.get("activities", []):
            activity_types.add(activity.get("type"))

    # Score baseado na variedade de tipos
    variety = len(activity_types)
    max_variety = 5  # review, explanation, exercise, quiz, practice

    return min((variety / max_variety) * 100, 100)


def calculate_flexibility_score(learning_path: dict) -> float:
    """Calcula score de flexibilidade do plano"""
    total_days = 0
    flexible_days = 0

    for week in learning_path.get("weekly_plans", []):
        for day in week.get("content", []):
            total_days += 1
            if day.get("flexibility") in ["flexible", "optional"]:
                flexible_days += 1

    if total_days == 0:
        return 0

    base_score = (flexible_days / total_days) * 60

    # Bonus por regras de adaptação
    adaptation_bonus = min(len(learning_path.get("adaptation_rules", [])) * 10, 20)

    # Bonus por dias buffer
    buffer_bonus = min(learning_path.get("flexibility_options", {}).get("buffer_days", 0) * 10, 20)

    return min(base_score + adaptation_bonus + buffer_bonus, 100)


# Adicione estes endpoints em app/api/v1/endpoints/analytics.py

@router.get("/assessments/{assessment_id}")
async def get_assessment_details(
        assessment_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém detalhes de uma avaliação específica
    """
    try:
        # Buscar avaliação no Firestore
        assessment_doc = db.collection("assessments").document(assessment_id).get()

        if not assessment_doc.exists:
            raise HTTPException(status_code=404, detail="Avaliação não encontrada")

        assessment_data = assessment_doc.to_dict()

        # Verificar se pertence ao usuário
        if assessment_data.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        return {
            "assessment_id": assessment_id,
            "assessment": assessment_data.get("assessment_data"),
            "metadata": {
                "difficulty": assessment_data.get("difficulty", "adaptive"),
                "area": assessment_data.get("area"),
                "subarea": assessment_data.get("subarea"),
                "level": assessment_data.get("level_name", "iniciante"),
                "personalized": assessment_data.get("personalized", True)
            },
            "created_at": assessment_data.get("created_at"),
            "status": assessment_data.get("status", "pending")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar avaliação: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar avaliação")


@router.post("/assessments/{assessment_id}/submit")
async def submit_assessment_response(
        assessment_id: str,
        submission: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Submete respostas de uma avaliação
    """
    try:
        # Buscar avaliação
        assessment_ref = db.collection("assessments").document(assessment_id)
        assessment_doc = assessment_ref.get()

        if not assessment_doc.exists:
            raise HTTPException(status_code=404, detail="Avaliação não encontrada")

        assessment_data = assessment_doc.to_dict()

        # Verificar se pertence ao usuário
        if assessment_data.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        # Verificar se já foi completada
        if assessment_data.get("status") == "completed":
            raise HTTPException(status_code=400, detail="Avaliação já foi completada")

        # Processar respostas
        answers = submission.get("answers", {})
        questions = assessment_data.get("assessment_data", {}).get("questions", [])

        # Calcular pontuação
        correct_answers = 0
        total_questions = len(questions)

        for idx, question in enumerate(questions):
            user_answer = answers.get(str(idx))
            if user_answer and user_answer == question.get("correct_answer"):
                correct_answers += 1

        score = round((correct_answers / total_questions * 100) if total_questions > 0 else 0)
        passed = score >= assessment_data.get("assessment_data", {}).get("passing_score", 70)

        # Atualizar documento
        update_data = {
            "responses": answers,
            "score": score,
            "passed": passed,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "time_taken_seconds": submission.get("time_taken_seconds", 0),
            "completed_at": submission.get("completed_at", datetime.utcnow().isoformat()),
            "status": "completed"
        }

        assessment_ref.update(update_data)

        # Publicar evento
        await event_service.publish_event(
            event_type=EventTypes.ASSESSMENT_COMPLETED,
            user_id=current_user["id"],
            data={
                "assessment_id": assessment_id,
                "score": score,
                "passed": passed,
                "area": assessment_data.get("area"),
                "subarea": assessment_data.get("subarea")
            }
        )

        return {
            "message": "Avaliação submetida com sucesso",
            "assessment_id": assessment_id,
            "score": score,
            "passed": passed,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "status": "completed"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao submeter avaliação: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao submeter avaliação")


@router.get("/study-sessions/{session_id}")
async def get_study_session_details(
        session_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém detalhes de uma sessão de estudo
    """
    try:
        # Buscar sessão no Firestore
        session_doc = db.collection("study_sessions").document(session_id).get()

        if not session_doc.exists:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")

        session_data = session_doc.to_dict()

        # Verificar se pertence ao usuário
        if session_data.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        return {
            "session_id": session_id,
            "session": session_data.get("session_data"),
            "metadata": session_data.get("context", {}),
            "created_at": session_data.get("created_at"),
            "status": session_data.get("status", "ready")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar sessão: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar sessão")


@router.post("/study-sessions/{session_id}/complete")
async def complete_study_session(
        session_id: str,
        completion_data: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Marca uma sessão de estudo como completa
    """
    try:
        # Buscar sessão
        session_ref = db.collection("study_sessions").document(session_id)
        session_doc = session_ref.get()

        if not session_doc.exists:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")

        session_data = session_doc.to_dict()

        # Verificar se pertence ao usuário
        if session_data.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        # Atualizar sessão
        update_data = {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "completed_activities": completion_data.get("completed_activities", []),
            "notes": completion_data.get("notes", ""),
            "completion_rate": completion_data.get("completion_rate", 0),
            "total_time_minutes": completion_data.get("total_time_minutes", 0)
        }

        session_ref.update(update_data)

        # Publicar evento
        await event_service.publish_event(
            event_type=EventTypes.STUDY_SESSION_COMPLETED,
            user_id=current_user["id"],
            data={
                "session_id": session_id,
                "completion_rate": update_data["completion_rate"],
                "total_time_minutes": update_data["total_time_minutes"]
            }
        )

        return {
            "message": "Sessão concluída com sucesso",
            "session_id": session_id,
            "status": "completed"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao completar sessão: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao completar sessão")


@router.get("/learning-paths/{path_id}")
async def get_learning_path_details(
        path_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Obtém detalhes de um plano de estudos
    """
    try:
        # Buscar plano no Firestore
        path_doc = db.collection("learning_paths").document(path_id).get()

        if not path_doc.exists:
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        path_data = path_doc.to_dict()

        # Verificar se pertence ao usuário
        if path_data.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        return {
            "path_id": path_id,
            "learning_path": path_data.get("path_data"),
            "progress": path_data.get("progress", {}),
            "completed_activities": path_data.get("completed_activities", []),
            "created_at": path_data.get("created_at"),
            "status": path_data.get("status", "active")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar plano: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar plano")


@router.put("/learning-paths/{path_id}/progress")
async def update_learning_path_progress(
        path_id: str,
        progress_data: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Dict[str, Any]:
    """
    Atualiza progresso em um plano de estudos
    """
    try:
        # Buscar plano
        path_ref = db.collection("learning_paths").document(path_id)
        path_doc = path_ref.get()

        if not path_doc.exists:
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        path_data = path_doc.to_dict()

        # Verificar se pertence ao usuário
        if path_data.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        # Atualizar progresso
        current_progress = path_data.get("progress", {})
        completed_activities = set(path_data.get("completed_activities", []))

        # Adicionar novas atividades completadas
        new_activities = progress_data.get("completed_activities", [])
        completed_activities.update(new_activities)

        # Calcular novo progresso
        total_activities = current_progress.get("total_activities", 0)
        completed_count = len(completed_activities)
        percentage = (completed_count / total_activities * 100) if total_activities > 0 else 0

        # Atualizar documento
        update_data = {
            "completed_activities": list(completed_activities),
            "progress.completed_activities": completed_count,
            "progress.percentage": percentage,
            "last_activity": progress_data.get("last_activity"),
            "updated_at": datetime.utcnow().isoformat()
        }

        path_ref.update(update_data)

        return {
            "message": "Progresso atualizado com sucesso",
            "path_id": path_id,
            "completed_activities": completed_count,
            "total_activities": total_activities,
            "percentage": percentage
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar progresso: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar progresso")