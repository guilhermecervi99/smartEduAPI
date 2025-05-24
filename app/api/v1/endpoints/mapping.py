# app/api/v1/endpoints/mapping.py
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
import time
import uuid
from collections import defaultdict

from app.core.security import get_current_user, get_current_user_id_required, get_current_user_id
from app.database import get_db, Collections
from app.schemas.mapping import (
    MappingStartResponse,
    MappingQuestion,
    QuestionOption,
    QuestionnaireSubmission,
    TextAnalysisRequest,
    MappingResult,
    AreaScore,
    SubareaRecommendation,
    MappingHistory
)
from app.utils.gamification import add_user_xp, grant_badge, XP_REWARDS
from app.utils.text_analysis import analyze_text_interests, normalize_text
from app.utils.interest_mappings import INTEREST_MAPPINGS
from app.config import TRACK_DESCRIPTIONS

router = APIRouter()

# Cache de sessões de mapeamento (em produção, usar Redis)
_mapping_sessions = {}


def generate_balanced_questions() -> List[MappingQuestion]:
    """Gera as perguntas balanceadas para o mapeamento"""
    questions = [
        {
            "id": 1,
            "question": "Quais das seguintes atividades você mais gosta de fazer no seu tempo livre?",
            "options": {
                "1": {"text": "Programar ou criar conteúdo digital", "area": "Tecnologia e Computação", "weight": 1.0},
                "2": {"text": "Resolver problemas matemáticos ou científicos", "area": "Ciências Exatas",
                      "weight": 1.0},
                "3": {"text": "Praticar esportes ou atividades físicas", "area": "Esportes e Atividades Físicas",
                      "weight": 1.0},
                "4": {"text": "Desenhar, pintar ou criar obras visuais", "area": "Artes e Cultura", "weight": 1.0},
                "5": {"text": "Ler livros, escrever ou aprender idiomas", "area": "Literatura e Linguagem",
                      "weight": 1.0},
                "6": {"text": "Cuidar de plantas, animais ou do meio ambiente", "area": "Ciências Biológicas e Saúde",
                      "weight": 1.0},
                "7": {"text": "Debater, analisar sociedade ou política", "area": "Ciências Humanas e Sociais",
                      "weight": 1.0},
                "8": {"text": "Planejar negócios ou gerenciar recursos", "area": "Negócios e Empreendedorismo",
                      "weight": 1.0},
                "9": {"text": "Aprimorar a comunicação e expressão verbal", "area": "Comunicação Profissional",
                      "weight": 1.0},
            }
        },
        {
            "id": 2,
            "question": "Qual tipo de conteúdo você mais gosta de consumir na internet?",
            "options": {
                "1": {"text": "Tutoriais de tecnologia, jogos ou programação", "area": "Tecnologia e Computação",
                      "weight": 0.8},
                "2": {"text": "Vídeos educativos sobre ciências exatas", "area": "Ciências Exatas", "weight": 0.8},
                "3": {"text": "Conteúdos sobre esportes e saúde física", "area": "Esportes e Atividades Físicas",
                      "weight": 0.8},
                "4": {"text": "Canais de arte, música ou cultura", "area": "Artes e Cultura", "weight": 0.8},
                "5": {"text": "Blogs literários ou canais sobre idiomas", "area": "Literatura e Linguagem",
                      "weight": 0.8},
                "6": {"text": "Canais sobre biologia, saúde ou natureza", "area": "Ciências Biológicas e Saúde",
                      "weight": 0.8},
                "7": {"text": "Conteúdos de história, filosofia ou sociologia", "area": "Ciências Humanas e Sociais",
                      "weight": 0.8},
                "8": {"text": "Vídeos sobre empreendedorismo e negócios", "area": "Negócios e Empreendedorismo",
                      "weight": 0.8},
                "9": {"text": "Podcasts, debates ou conteúdos de comunicação", "area": "Comunicação Profissional",
                      "weight": 0.8},
            }
        },
        {
            "id": 3,
            "question": "Em um projeto em grupo, que papel você geralmente prefere assumir?",
            "options": {
                "1": {"text": "Responsável pela parte técnica/tecnológica", "area": "Tecnologia e Computação",
                      "weight": 0.9},
                "2": {"text": "Resolver problemas lógicos e fazer cálculos", "area": "Ciências Exatas", "weight": 0.9},
                "3": {"text": "Organizar atividades práticas e dinâmicas", "area": "Esportes e Atividades Físicas",
                      "weight": 0.9},
                "4": {"text": "Cuidar do design ou aspecto visual", "area": "Artes e Cultura", "weight": 0.9},
                "5": {"text": "Redação e revisão textual", "area": "Literatura e Linguagem", "weight": 0.9},
                "6": {"text": "Pesquisar e cuidar do bem-estar do grupo", "area": "Ciências Biológicas e Saúde",
                      "weight": 0.9},
                "7": {"text": "Contextualizar, analisar impactos sociais", "area": "Ciências Humanas e Sociais",
                      "weight": 0.9},
                "8": {"text": "Coordenar, organizar recursos e prazos", "area": "Negócios e Empreendedorismo",
                      "weight": 0.9},
                "9": {"text": "Apresentar o trabalho e comunicar ideias", "area": "Comunicação Profissional",
                      "weight": 0.9},
            }
        },
        {
            "id": 4,
            "question": "Qual dessas matérias ou temas você mais gostaria de se aprofundar?",
            "options": {
                "1": {"text": "Programação, robótica ou informática", "area": "Tecnologia e Computação", "weight": 1.1},
                "2": {"text": "Matemática, física ou química", "area": "Ciências Exatas", "weight": 1.1},
                "3": {"text": "Educação física, técnicas esportivas", "area": "Esportes e Atividades Físicas",
                      "weight": 1.1},
                "4": {"text": "Artes visuais, música ou expressão cultural", "area": "Artes e Cultura", "weight": 1.1},
                "5": {"text": "Literatura, redação ou idiomas", "area": "Literatura e Linguagem", "weight": 1.1},
                "6": {"text": "Biologia, meio ambiente ou saúde", "area": "Ciências Biológicas e Saúde", "weight": 1.1},
                "7": {"text": "História, filosofia, sociologia ou direito", "area": "Ciências Humanas e Sociais",
                      "weight": 1.1},
                "8": {"text": "Administração, economia ou marketing", "area": "Negócios e Empreendedorismo",
                      "weight": 1.1},
                "9": {"text": "Jornalismo, oratória ou comunicação", "area": "Comunicação Profissional", "weight": 1.1},
            }
        },
        {
            "id": 5,
            "question": "Se pudesse escolher uma profissão agora, qual dessas áreas mais te atrairia?",
            "options": {
                "1": {"text": "Desenvolvedor de software, analista de TI", "area": "Tecnologia e Computação",
                      "weight": 1.2},
                "2": {"text": "Engenheiro, físico ou matemático", "area": "Ciências Exatas", "weight": 1.2},
                "3": {"text": "Atleta, personal trainer ou educador físico", "area": "Esportes e Atividades Físicas",
                      "weight": 1.2},
                "4": {"text": "Artista, músico, designer ou produtor cultural", "area": "Artes e Cultura",
                      "weight": 1.2},
                "5": {"text": "Escritor, tradutor ou professor de idiomas", "area": "Literatura e Linguagem",
                      "weight": 1.2},
                "6": {"text": "Médico, biólogo, veterinário ou nutricionista", "area": "Ciências Biológicas e Saúde",
                      "weight": 1.2},
                "7": {"text": "Professor, advogado, historiador ou psicólogo", "area": "Ciências Humanas e Sociais",
                      "weight": 1.2},
                "8": {"text": "Empresário, administrador ou consultor", "area": "Negócios e Empreendedorismo",
                      "weight": 1.2},
                "9": {"text": "Jornalista, relações públicas ou influenciador", "area": "Comunicação Profissional",
                      "weight": 1.2},
            }
        }
    ]

    # Converter para objetos Pydantic
    mapping_questions = []
    for q in questions:
        options = {}
        for key, opt in q["options"].items():
            options[key] = QuestionOption(**opt)

        mapping_questions.append(MappingQuestion(
            id=q["id"],
            question=q["question"],
            options=options
        ))

    return mapping_questions


@router.post("/start", response_model=MappingStartResponse)
async def start_mapping(
        db=Depends(get_db),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Inicia uma nova sessão de mapeamento de interesses

    - Gera um ID de sessão único
    - Retorna as perguntas do questionário
    - Salva a sessão para posterior processamento
    """
    # Gerar ID de sessão
    session_id = str(uuid.uuid4())

    # Gerar perguntas
    questions = generate_balanced_questions()

    # Salvar sessão
    _mapping_sessions[session_id] = {
        "user_id": current_user["id"],
        "started_at": time.time(),
        "questions": questions,
        "status": "in_progress"
    }

    return MappingStartResponse(
        session_id=session_id,
        questions=questions,
        total_questions=len(questions),
        instructions="Responda às perguntas abaixo para mapearmos seus interesses. Você pode selecionar múltiplas opções em cada pergunta."
    )


@router.post("/submit", response_model=MappingResult)
async def submit_mapping(
        submission: QuestionnaireSubmission,
        db=Depends(get_db),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Processa a submissão completa do questionário

    - Calcula pontuações para cada área
    - Analisa o texto de interesses (se fornecido)
    - Determina a trilha e subárea recomendadas
    - Atualiza o perfil do usuário
    - Concede XP e badges
    """
    # Verificar sessão
    if submission.session_id not in _mapping_sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired"
        )

    session = _mapping_sessions[submission.session_id]
    if session["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this user"
        )

    # Inicializar pontuações
    area_scores = defaultdict(float)
    all_areas = list(TRACK_DESCRIPTIONS.keys())

    # Processar respostas do questionário
    questions = {q.id: q for q in session["questions"]}

    for response in submission.responses:
        if response.question_id not in questions:
            continue

        question = questions[response.question_id]

        for option_id in response.selected_options:
            if option_id in question.options:
                option = question.options[option_id]
                if option.area:
                    area_scores[option.area] += option.weight

    # Analisar texto se fornecido
    text_contribution = 0.0
    if submission.text_response:
        text_analysis = analyze_text_interests(
            submission.text_response,
            INTEREST_MAPPINGS
        )

        # Integrar pontuações do texto
        text_weight = 1.5
        for area, score in text_analysis["area_scores"].items():
            if area in area_scores:
                area_scores[area] += score * text_weight
                text_contribution += score * text_weight

    # Normalizar pontuações
    if area_scores:
        max_score = max(area_scores.values())
        if max_score > 0:
            normalized_scores = {area: score / max_score for area, score in area_scores.items()}
        else:
            normalized_scores = {area: 1.0 / len(all_areas) for area in all_areas}
    else:
        normalized_scores = {area: 1.0 / len(all_areas) for area in all_areas}

    # Garantir que todas as áreas tenham uma pontuação
    for area in all_areas:
        if area not in normalized_scores:
            normalized_scores[area] = 0.0

    # Ordenar áreas por pontuação
    sorted_areas = sorted(normalized_scores.items(), key=lambda x: x[1], reverse=True)

    # Criar lista de AreaScore
    area_score_list = []
    for rank, (area, score) in enumerate(sorted_areas, 1):
        area_score_list.append(AreaScore(
            area=area,
            score=score,
            percentage=score * 100,
            rank=rank
        ))

    # Determinar trilha principal
    recommended_track = sorted_areas[0][0]

    # Determinar subáreas recomendadas
    top_subareas = []
    if submission.text_response:
        # Usar análise de texto para subáreas
        text_analysis = analyze_text_interests(
            submission.text_response,
            INTEREST_MAPPINGS
        )

        subarea_scores = text_analysis.get("subarea_scores", {})
        # Filtrar apenas subáreas da área recomendada
        relevant_subareas = {
            k: v for k, v in subarea_scores.items()
            if isinstance(k, tuple) and k[0] == recommended_track
        }

        sorted_subareas = sorted(relevant_subareas.items(), key=lambda x: x[1], reverse=True)

        for (area, subarea), score in sorted_subareas[:3]:
            top_subareas.append(SubareaRecommendation(
                subarea=subarea,
                score=score,
                reason=f"Mencionado em seus interesses"
            ))

    # Se não houver subáreas da análise de texto, usar subáreas padrão
    if not top_subareas:
        # Buscar subáreas disponíveis no Firestore
        area_doc = db.collection(Collections.LEARNING_PATHS).document(recommended_track).get()
        if area_doc.exists:
            area_data = area_doc.to_dict()
            subareas = list(area_data.get("subareas", {}).keys())
            if subareas:
                top_subareas.append(SubareaRecommendation(
                    subarea=subareas[0],
                    score=1.0,
                    reason="Subárea principal da trilha"
                ))

    recommended_subarea = top_subareas[0].subarea if top_subareas else None

    # Atualizar dados do usuário
    user_ref = db.collection(Collections.USERS).document(current_user["id"])

    # Criar registro de mapeamento
    mapping_record = {
        "date": time.strftime("%Y-%m-%d"),
        "track": recommended_track,
        "score": normalized_scores.get(recommended_track, 0.0),
        "top_interests": dict(sorted_areas[:3])
    }

    # Preparar atualizações
    updates = {
        "current_track": recommended_track,
        "recommended_track": recommended_track,
        "track_scores": normalized_scores,
        "mapping_history": current_user.get("mapping_history", []) + [mapping_record]
    }

    # Se houver subárea recomendada, configurar progresso
    if recommended_subarea:
        # Buscar ordem de subáreas
        area_doc = db.collection(Collections.LEARNING_PATHS).document(recommended_track).get()
        subareas_order = []
        if area_doc.exists:
            area_data = area_doc.to_dict()
            all_subareas = list(area_data.get("subareas", {}).keys())

            # Colocar a subárea recomendada primeiro
            subareas_order = [recommended_subarea]
            for sub in all_subareas:
                if sub != recommended_subarea:
                    subareas_order.append(sub)

        updates["progress"] = {
            "area": recommended_track,
            "subareas_order": subareas_order,
            "current": {
                "subarea": recommended_subarea,
                "level": "iniciante",
                "module_index": 0,
                "lesson_index": 0,
                "step_index": 0
            }
        }

    # Atualizar no banco
    user_ref.update(updates)

    # Adicionar XP e badges
    xp_earned = XP_REWARDS.get("complete_mapping", 25)
    add_user_xp(db, current_user["id"], xp_earned, f"Completou mapeamento de interesses")

    badges_earned = []

    # Badge de explorador da área
    explorer_badge = f"Explorador de {recommended_track}"
    if grant_badge(db, current_user["id"], explorer_badge):
        badges_earned.append(explorer_badge)

    # Badge de autoconhecimento (primeiro mapeamento)
    if len(current_user.get("mapping_history", [])) == 0:
        if grant_badge(db, current_user["id"], "Autoconhecimento"):
            badges_earned.append("Autoconhecimento")

    # Limpar sessão
    del _mapping_sessions[submission.session_id]

    return MappingResult(
        user_id=current_user["id"],
        session_id=submission.session_id,
        recommended_track=recommended_track,
        recommended_subarea=recommended_subarea,
        area_scores=area_score_list,
        top_subareas=top_subareas,
        text_analysis_contribution=text_contribution if submission.text_response else None,
        badges_earned=badges_earned,
        xp_earned=xp_earned
    )


@router.post("/analyze-text")
async def analyze_text(
        request: TextAnalysisRequest,
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Analisa um texto para identificar interesses

    - Útil para análise rápida sem passar pelo questionário completo
    - Retorna áreas e subáreas identificadas
    """
    # Analisar texto
    analysis = analyze_text_interests(
        request.text,
        INTEREST_MAPPINGS
    )

    # Formatar resposta
    area_scores = [
        {
            "area": area,
            "score": score,
            "percentage": score * 100
        }
        for area, score in sorted(
            analysis["area_scores"].items(),
            key=lambda x: x[1],
            reverse=True
        )
    ]

    subarea_scores = [
        {
            "area": area,
            "subarea": subarea,
            "score": score,
            "percentage": score * 100
        }
        for (area, subarea), score in sorted(
            analysis["subarea_scores"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]  # Top 10 subáreas
    ]

    return {
        "area_scores": area_scores,
        "subarea_scores": subarea_scores,
        "top_area": area_scores[0]["area"] if area_scores else None,
        "text_analyzed": request.text[:100] + "..." if len(request.text) > 100 else request.text
    }


@router.get("/history", response_model=MappingHistory)
async def get_mapping_history(
        db=Depends(get_db),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Obtém o histórico de mapeamentos do usuário

    - Lista todos os mapeamentos realizados
    - Mostra a evolução dos interesses
    """
    mapping_history = current_user.get("mapping_history", [])

    # Determinar área mais forte ao longo do tempo
    area_frequencies = defaultdict(int)
    for mapping in mapping_history:
        track = mapping.get("track")
        if track:
            area_frequencies[track] += 1

    strongest_area = None
    if area_frequencies:
        strongest_area = max(area_frequencies.items(), key=lambda x: x[1])[0]

    return MappingHistory(
        mappings=mapping_history,
        total_mappings=len(mapping_history),
        current_track=current_user.get("current_track"),
        strongest_area=strongest_area
    )


@router.get("/areas")
async def get_available_areas() -> Any:
    """
    Lista todas as áreas disponíveis no sistema

    - Retorna áreas com suas descrições
    - Útil para UI de seleção manual
    """
    areas = []
    for area, description in TRACK_DESCRIPTIONS.items():
        areas.append({
            "name": area,
            "description": description
        })

    return {
        "areas": areas,
        "total": len(areas)
    }