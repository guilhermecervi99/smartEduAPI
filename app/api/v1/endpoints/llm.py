# ===== ARQUIVO: app/api/v1/endpoints/llm.py =====

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
import time
import logging

# ✅ CONFIGURAR LOGGER
logger = logging.getLogger(__name__)

from app.core.security import get_current_user
from app.database import get_db
from app.schemas.llm import (
    TeacherQuestionRequest,
    TeacherQuestionResponse,
    LessonGenerationRequest,
    LessonGenerationResponse,
    AssessmentGenerationRequest,
    AssessmentGenerationResponse,
    LearningPathRequest,
    LearningPathResponse,
    ContentAnalysisRequest,
    ContentAnalysisResponse,
    ContentSimplificationRequest,
    ContentEnrichmentRequest
)
from app.utils.gamification import add_user_xp
from app.utils.llm_integration import (
    call_teacher_llm,
    generate_complete_lesson,
    generate_assessment,
    generate_learning_pathway,
    analyze_content_difficulty,
    simplify_content,
    enrich_content_with_context,  # ✅ FUNÇÃO CORRETA
    TEACHING_STYLES
)

router = APIRouter()

@router.post("/ask-teacher", response_model=TeacherQuestionResponse)
async def ask_teacher_question(
        request: TeacherQuestionRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Permite ao usuário fazer perguntas ao professor virtual
    """
    user_id = current_user["id"]

    # Obter contexto do usuário
    current_track = current_user.get("current_track", "")
    progress = current_user.get("progress", {})
    current_subarea = progress.get("current", {}).get("subarea", "")
    current_level = progress.get("current", {}).get("level", "iniciante")

    # Determinar contexto
    context = request.context or f"área de {current_track}"
    if current_subarea:
        context += f", subárea de {current_subarea}, nível {current_level}"

    # Obter preferências do usuário
    user_age = current_user.get("age", 14)
    learning_style = current_user.get("learning_style", "didático")

    # Gerar resposta do professor
    try:
        answer = call_teacher_llm(
            f"O aluno está estudando {context} e pergunta: '{request.question}'. "
            f"Responda de forma adequada para um estudante de {user_age} anos, "
            f"usando linguagem clara e exemplos relevantes.",
            student_age=user_age,
            subject_area=current_track,
            teaching_style=learning_style,
            max_tokens=1500
        )

        # Adicionar XP por fazer pergunta
        xp_result = add_user_xp(db, user_id, 2, "Fez pergunta ao professor virtual")

        return TeacherQuestionResponse(
            question=request.question,
            answer=answer,
            context=context,
            teaching_style=learning_style,
            xp_earned=xp_result["xp_added"]
        )

    except Exception as e:
        logger.error(f"Erro ao perguntar ao professor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating response: {str(e)}"
        )


@router.post("/generate-lesson", response_model=LessonGenerationResponse)
async def generate_lesson(
        request: LessonGenerationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera uma aula completa sobre um tópico específico
    """
    user_id = current_user["id"]

    # Usar preferências do usuário se não especificadas
    user_age = current_user.get("age", 14)
    teaching_style = request.teaching_style or current_user.get("learning_style", "didático")

    # Validar estilo de ensino
    if teaching_style not in TEACHING_STYLES:
        teaching_style = "didático"

    try:
        # Gerar aula
        lesson = generate_complete_lesson(
            topic=request.topic,
            subject_area=request.subject_area,
            age_range=user_age,
            knowledge_level=request.knowledge_level,
            teaching_style=teaching_style,
            lesson_duration_min=request.duration_minutes
        )

        # Adicionar XP
        xp_result = add_user_xp(db, user_id, 5, f"Gerou aula sobre: {request.topic}")

        return LessonGenerationResponse(
            lesson_content=lesson.to_dict(),
            topic=request.topic,
            subject_area=request.subject_area,
            knowledge_level=request.knowledge_level,
            teaching_style=teaching_style,
            duration_minutes=request.duration_minutes,
            xp_earned=xp_result["xp_added"]
        )

    except Exception as e:
        logger.error(f"Erro ao gerar lição: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating lesson: {str(e)}"
        )


@router.post("/generate-assessment", response_model=AssessmentGenerationResponse)
async def generate_assessment_endpoint(
        request: AssessmentGenerationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Gera uma avaliação com questões sobre um tópico
    """
    user_id = current_user["id"]

    # Validar tipos de questões
    valid_types = ["múltipla escolha", "verdadeiro/falso", "dissertativa"]
    question_types = [qt for qt in request.question_types if qt in valid_types]

    if not question_types:
        question_types = ["múltipla escolha", "verdadeiro/falso"]

    try:
        # Gerar avaliação
        assessment = generate_assessment(
            topic=request.topic,
            difficulty=request.difficulty,
            num_questions=request.num_questions,
            question_types=question_types
        )

        # Adicionar XP
        xp_result = add_user_xp(db, user_id, 3, f"Gerou avaliação sobre: {request.topic}")

        return AssessmentGenerationResponse(
            assessment=assessment,
            topic=request.topic,
            difficulty=request.difficulty,
            num_questions=request.num_questions,
            question_types=question_types,
            xp_earned=xp_result["xp_added"]
        )

    except Exception as e:
        logger.error(f"Erro ao gerar avaliação: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating assessment: {str(e)}"
        )


@router.post("/analyze-content", response_model=ContentAnalysisResponse)
async def analyze_content(
        request: ContentAnalysisRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Analisa a dificuldade e adequação de um conteúdo
    """
    user_id = current_user["id"]

    try:
        # Analisar conteúdo
        analysis = analyze_content_difficulty(request.content)

        # Gerar recomendações baseadas na análise
        recommendations = []

        user_age = current_user.get("age", 14)
        age_key = f"adequação_{user_age}_{user_age + 1}_anos"

        # Verificar adequação para a idade do usuário
        adequacy = analysis.get(age_key, 0.5)

        if adequacy < 0.7:
            recommendations.append("Considere simplificar o conteúdo para melhor compreensão")

        if analysis.get("vocabulário_complexidade") == "alto":
            recommendations.append("Adicione um glossário de termos técnicos")

        if analysis.get("explicações_visuais") == "baixo":
            recommendations.append("Inclua mais diagramas e exemplos visuais")

        # Adicionar XP
        xp_result = add_user_xp(db, user_id, 2, "Analisou conteúdo educacional")

        return ContentAnalysisResponse(
            content_preview=request.content[:200] + "..." if len(request.content) > 200 else request.content,
            analysis=analysis,
            recommendations=recommendations,
            xp_earned=xp_result["xp_added"]
        )

    except Exception as e:
        logger.error(f"Erro ao analisar conteúdo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error analyzing content: {str(e)}"
        )


@router.post("/enrich-content")
async def enrich_content_endpoint(
        request: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Enriquece conteúdo educacional com elementos adicionais contextualizados.
    """
    try:
        # Extrair dados do request
        content = request.get("content", "")
        enrichment_type = request.get("enrichment_type", "exemplos")
        context = request.get("context", {})
        user_context = request.get("user_context", {})

        # Validar conteúdo
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Conteúdo não pode estar vazio"
            )

        # Preparar informações de contexto
        area = context.get("area", "")
        subarea = context.get("subarea", "")
        level = context.get("level", "iniciante")
        title = context.get("title", "")

        # Idade e estilo do usuário
        user_age = user_context.get("age", current_user.get("age", 14))
        learning_style = user_context.get("learning_style", current_user.get("learning_style", "didático"))

        logger.info(f"Enriquecendo conteúdo - Tipo: {enrichment_type}, Área: {area}, Usuário: {current_user['id']}")

        # ✅ CHAMAR FUNÇÃO CORRIGIDA
        enriched_content = enrich_content_with_context(
            text=content,
            enrichment_type=enrichment_type,
            title=title,
            area=area,
            subarea=subarea,
            level=level,
            user_age=user_age,
            learning_style=learning_style
        )

        # Adicionar XP por usar ferramentas de enriquecimento
        xp_result = add_user_xp(db, current_user["id"], 3, f"Usou ferramenta: {enrichment_type}")

        return {
            "enriched_content": enriched_content,
            "type": enrichment_type,
            "context_used": {
                "area": area,
                "subarea": subarea,
                "level": level,
                "title": title
            },
            "xp_earned": xp_result.get("xp_added", 3)
        }

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Erro ao enriquecer conteúdo: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao gerar {enrichment_type}: {str(e)}"
        )


@router.post("/simplify-content")
async def simplify_content_endpoint(
        request: ContentSimplificationRequest,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Simplifica um conteúdo para melhor compreensão
    """
    user_id = current_user["id"]

    # Usar idade do usuário se não especificada
    target_age = request.target_age or current_user.get("age", 14)

    try:
        # Simplificar conteúdo
        simplified = simplify_content(request.content, target_age)

        # Adicionar XP
        add_user_xp(db, user_id, 3, "Simplificou conteúdo educacional")

        return {
            "original_content": request.content[:200] + "..." if len(request.content) > 200 else request.content,
            "simplified_content": simplified,
            "target_age": target_age,
            "message": "Conteúdo simplificado com sucesso"
        }

    except Exception as e:
        logger.error(f"Erro ao simplificar conteúdo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error simplifying content: {str(e)}"
        )


@router.post("/apply-assessment")
async def apply_assessment(
        assessment_data: Dict[str, Any],
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Aplica uma avaliação e retorna o resultado
    """
    user_id = current_user["id"]
    user_age = current_user.get("age", 14)
    teaching_style = current_user.get("learning_style", "didático")

    questions = assessment_data.get("questions", [])
    user_answers = assessment_data.get("answers", [])

    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No questions provided"
        )

    correct_answers = 0
    total_questions = len(questions)
    feedback_list = []

    for i, question in enumerate(questions):
        if i >= len(user_answers):
            feedback_list.append({
                "question_id": i,
                "correct": False,
                "feedback": "Questão não respondida"
            })
            continue

        user_answer = user_answers[i]
        question_type = question.get("type", "")

        if question_type == "múltipla escolha":
            correct_idx = question.get("correct_answer", 0)
            is_correct = user_answer == correct_idx

            if is_correct:
                correct_answers += 1

            feedback_list.append({
                "question_id": i,
                "correct": is_correct,
                "feedback": question.get("explanation", "")
            })

        elif question_type == "verdadeiro/falso":
            correct_answer = question.get("correct_answer", False)
            is_correct = user_answer == correct_answer

            if is_correct:
                correct_answers += 1

            feedback_list.append({
                "question_id": i,
                "correct": is_correct,
                "feedback": question.get("explanation", "")
            })

        elif question_type == "dissertativa":
            # Para questões dissertativas, usar LLM para avaliar
            key_points = question.get("key_points", [])

            prompt = (
                f"Avalie a resposta de um aluno de {user_age} anos:\n"
                f"Questão: {question.get('text', '')}\n"
                f"Resposta do aluno: {user_answer}\n"
                f"Pontos-chave esperados: {', '.join(key_points)}\n"
                f"Decida se é satisfatória (70%+ dos pontos) e forneça feedback construtivo."
            )

            try:
                evaluation = call_teacher_llm(
                    prompt,
                    student_age=user_age,
                    teaching_style=teaching_style,
                    max_tokens=500
                )

                # Simplificado: considerar aprovado se contém palavras-chave positivas
                is_correct = any(word in evaluation.lower() for word in ["satisfatória", "aprovado", "correto", "bom"])

                if is_correct:
                    correct_answers += 1

                feedback_list.append({
                    "question_id": i,
                    "correct": is_correct,
                    "feedback": evaluation
                })
            except:
                feedback_list.append({
                    "question_id": i,
                    "correct": False,
                    "feedback": "Erro ao avaliar resposta dissertativa"
                })

    # Calcular pontuação
    score = (correct_answers / total_questions) * 100 if total_questions > 0 else 0

    # Adicionar XP baseado na pontuação
    xp_amount = 5 + int(score / 10)  # 5 XP base + 1 XP para cada 10%
    add_user_xp(db, user_id, xp_amount, f"Completou avaliação com {score:.1f}%")

    return {
        "score": score,
        "correct_answers": correct_answers,
        "total_questions": total_questions,
        "passed": score >= 70,
        "feedback": feedback_list,
        "xp_earned": xp_amount
    }


@router.get("/teaching-styles")
async def get_teaching_styles() -> Any:
    """
    Lista os estilos de ensino disponíveis
    """
    return {
        "styles": [
            {
                "key": key,
                "name": key.capitalize(),
                "description": description
            }
            for key, description in TEACHING_STYLES.items()
        ]
    }