# app/api/v1/endpoints/mapping.py
# Sistema final integrado com modelo PKL

from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
import time
import uuid
from collections import defaultdict
import os

from app.core.security import get_current_user
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
from app.utils.hybrid_interest_mapper import HybridInterestMapper
from app.config import TRACK_DESCRIPTIONS

router = APIRouter()

# Cache de sessões
_mapping_sessions = {}

# Instância global do mapeador híbrido
_hybrid_mapper = None


# Substitua a função get_hybrid_mapper() no arquivo mapping.py por esta:

def get_hybrid_mapper():
    """Obtém instância singleton do mapeador híbrido"""
    global _hybrid_mapper
    if _hybrid_mapper is None:
        # Construir caminho relativo ao arquivo atual
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Navegar para app/utils/ultimate_classifier.pkl
        pkl_path = os.path.join(current_dir, '..', '..', '..', 'utils', 'ultimate_classifier.pkl')

        # Normalizar o caminho
        pkl_path = os.path.normpath(pkl_path)

        print(f"📁 Tentando carregar PKL de: {pkl_path}")
        print(f"📁 Arquivo existe? {os.path.exists(pkl_path)}")

        try:
            _hybrid_mapper = HybridInterestMapper(pkl_path)
            print("✅ Mapeador híbrido inicializado com sucesso!")
        except Exception as e:
            print(f"❌ Erro ao inicializar mapeador híbrido: {e}")
            # Tentar caminho alternativo se o primeiro falhar
            alt_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'utils', 'ultimate_classifier.pkl')
            alt_path = os.path.abspath(alt_path)
            print(f"📁 Tentando caminho alternativo: {alt_path}")

            if os.path.exists(alt_path):
                try:
                    _hybrid_mapper = HybridInterestMapper(alt_path)
                    print("✅ Mapeador híbrido inicializado com caminho alternativo!")
                except Exception as e2:
                    print(f"❌ Falhou também com caminho alternativo: {e2}")
                    _hybrid_mapper = None
            else:
                _hybrid_mapper = None

    return _hybrid_mapper

def generate_balanced_questions() -> List[MappingQuestion]:
    """Gera as perguntas do questionário"""
    questions = [
        {
            "id": 1,
            "question": "Quais das seguintes atividades você mais gosta de fazer no seu tempo livre?",
            "options": {
                "1": {
                    "text": "Programar ou criar conteúdo digital",
                    "area": "Tecnologia e Computação",
                    "weight": 0.6
                },
                "2": {
                    "text": "Resolver problemas matemáticos ou científicos",
                    "area": "Ciências Exatas",
                    "weight": 0.8
                },
                "3": {
                    "text": "Praticar esportes ou atividades físicas",
                    "area": "Esportes e Atividades Físicas",
                    "weight": 0.4
                },
                "4": {
                    "text": "Desenhar, pintar ou criar obras visuais",
                    "area": "Artes e Cultura",
                    "weight": 0.6
                },
                "5": {
                    "text": "Ler livros, escrever ou aprender idiomas",
                    "area": "Literatura e Linguagem",
                    "weight": 0.8
                },
                "6": {
                    "text": "Cuidar de plantas, animais ou do meio ambiente",
                    "area": "Ciências Biológicas e Saúde",
                    "weight": 0.7
                },
                "7": {
                    "text": "Debater, analisar sociedade ou política",
                    "area": "Ciências Humanas e Sociais",
                    "weight": 0.8
                },
                "8": {
                    "text": "Planejar negócios ou gerenciar recursos",
                    "area": "Negócios e Empreendedorismo",
                    "weight": 0.7
                },
                "9": {
                    "text": "Aprimorar a comunicação e expressão verbal",
                    "area": "Comunicação Profissional",
                    "weight": 0.7
                }
            }
        },
        {
            "id": 2,
            "question": "Qual tipo de conteúdo você mais gosta de consumir na internet?",
            "options": {
                "1": {
                    "text": "Tutoriais de tecnologia, jogos ou programação",
                    "area": "Tecnologia e Computação",
                    "weight": 0.9
                },
                "2": {
                    "text": "Vídeos educativos sobre ciências exatas",
                    "area": "Ciências Exatas",
                    "weight": 1.0
                },
                "3": {
                    "text": "Conteúdos sobre esportes e saúde física",
                    "area": "Esportes e Atividades Físicas",
                    "weight": 0.7
                },
                "4": {
                    "text": "Canais de arte, música ou cultura",
                    "area": "Artes e Cultura",
                    "weight": 0.9
                },
                "5": {
                    "text": "Blogs literários ou canais sobre idiomas",
                    "area": "Literatura e Linguagem",
                    "weight": 1.0
                },
                "6": {
                    "text": "Canais sobre biologia, saúde ou natureza",
                    "area": "Ciências Biológicas e Saúde",
                    "weight": 1.0
                },
                "7": {
                    "text": "Conteúdos de história, filosofia ou sociologia",
                    "area": "Ciências Humanas e Sociais",
                    "weight": 1.0
                },
                "8": {
                    "text": "Vídeos sobre empreendedorismo e negócios",
                    "area": "Negócios e Empreendedorismo",
                    "weight": 1.0
                },
                "9": {
                    "text": "Podcasts, debates ou conteúdos de comunicação",
                    "area": "Comunicação Profissional",
                    "weight": 1.0
                }
            }
        },
        {
            "id": 3,
            "question": "Em um projeto em grupo, que papel você geralmente prefere assumir?",
            "options": {
                "1": {
                    "text": "Responsável pela parte técnica/tecnológica",
                    "area": "Tecnologia e Computação",
                    "weight": 1.2
                },
                "2": {
                    "text": "Resolver problemas lógicos e fazer cálculos",
                    "area": "Ciências Exatas",
                    "weight": 1.2
                },
                "3": {
                    "text": "Organizar atividades práticas e dinâmicas",
                    "area": "Esportes e Atividades Físicas",
                    "weight": 0.9
                },
                "4": {
                    "text": "Cuidar do design ou aspecto visual",
                    "area": "Artes e Cultura",
                    "weight": 1.1
                },
                "5": {
                    "text": "Redação e revisão textual",
                    "area": "Literatura e Linguagem",
                    "weight": 1.2
                },
                "6": {
                    "text": "Pesquisar e cuidar do bem-estar do grupo",
                    "area": "Ciências Biológicas e Saúde",
                    "weight": 1.1
                },
                "7": {
                    "text": "Contextualizar, analisar impactos sociais",
                    "area": "Ciências Humanas e Sociais",
                    "weight": 1.2
                },
                "8": {
                    "text": "Coordenar, organizar recursos e prazos",
                    "area": "Negócios e Empreendedorismo",
                    "weight": 1.2
                },
                "9": {
                    "text": "Apresentar o trabalho e comunicar ideias",
                    "area": "Comunicação Profissional",
                    "weight": 1.2
                }
            }
        },
        {
            "id": 4,
            "question": "Qual dessas matérias ou temas você mais gostaria de se aprofundar?",
            "options": {
                "1": {
                    "text": "Programação, robótica ou informática",
                    "area": "Tecnologia e Computação",
                    "weight": 1.5
                },
                "2": {
                    "text": "Matemática, física ou química",
                    "area": "Ciências Exatas",
                    "weight": 1.5
                },
                "3": {
                    "text": "Educação física, técnicas esportivas",
                    "area": "Esportes e Atividades Físicas",
                    "weight": 1.2
                },
                "4": {
                    "text": "Artes visuais, música ou expressão cultural",
                    "area": "Artes e Cultura",
                    "weight": 1.4
                },
                "5": {
                    "text": "Literatura, redação ou idiomas",
                    "area": "Literatura e Linguagem",
                    "weight": 1.5
                },
                "6": {
                    "text": "Biologia, meio ambiente ou saúde",
                    "area": "Ciências Biológicas e Saúde",
                    "weight": 1.5
                },
                "7": {
                    "text": "História, filosofia, sociologia ou direito",
                    "area": "Ciências Humanas e Sociais",
                    "weight": 1.5
                },
                "8": {
                    "text": "Administração, economia ou marketing",
                    "area": "Negócios e Empreendedorismo",
                    "weight": 1.5
                },
                "9": {
                    "text": "Jornalismo, oratória ou comunicação",
                    "area": "Comunicação Profissional",
                    "weight": 1.5
                }
            }
        },
        {
            "id": 5,
            "question": "Se pudesse escolher uma profissão agora, qual dessas áreas mais te atrairia?",
            "options": {
                "1": {
                    "text": "Desenvolvedor de software, analista de TI",
                    "area": "Tecnologia e Computação",
                    "weight": 2.0
                },
                "2": {
                    "text": "Engenheiro, físico ou matemático",
                    "area": "Ciências Exatas",
                    "weight": 2.0
                },
                "3": {
                    "text": "Atleta, personal trainer ou educador físico",
                    "area": "Esportes e Atividades Físicas",
                    "weight": 2.0
                },
                "4": {
                    "text": "Artista, músico, designer ou produtor cultural",
                    "area": "Artes e Cultura",
                    "weight": 2.0
                },
                "5": {
                    "text": "Escritor, tradutor ou professor de idiomas",
                    "area": "Literatura e Linguagem",
                    "weight": 2.0
                },
                "6": {
                    "text": "Médico, biólogo, veterinário ou nutricionista",
                    "area": "Ciências Biológicas e Saúde",
                    "weight": 2.0
                },
                "7": {
                    "text": "Professor, advogado, historiador ou psicólogo",
                    "area": "Ciências Humanas e Sociais",
                    "weight": 2.0
                },
                "8": {
                    "text": "Empresário, administrador ou consultor",
                    "area": "Negócios e Empreendedorismo",
                    "weight": 2.0
                },
                "9": {
                    "text": "Jornalista, relações públicas ou influenciador",
                    "area": "Comunicação Profissional",
                    "weight": 2.0
                }
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
    """Inicia uma nova sessão de mapeamento"""
    session_id = str(uuid.uuid4())
    questions = generate_balanced_questions()

    _mapping_sessions[session_id] = {
        "user_id": current_user["id"],
        "started_at": time.time(),
        "questions": questions,
        "status": "in_progress"
    }

    # Verificar se o modelo PKL está disponível
    mapper = get_hybrid_mapper()
    has_ml_model = mapper is not None

    instructions = (
        "Responda às perguntas abaixo para mapearmos seus interesses de forma precisa. "
        "Suas escolhas profissionais e acadêmicas têm maior peso que hobbies. "
        "Você pode selecionar múltiplas opções em cada pergunta."
    )

    if has_ml_model:
        instructions += (
            "\n\n💡 Dica: No campo de texto livre, seja específico sobre seus interesses, "
            "sonhos e o que realmente te motiva. Nossa IA analisará seu texto para "
            "uma recomendação ainda mais precisa!"
        )

    return MappingStartResponse(
        session_id=session_id,
        questions=questions,
        total_questions=len(questions),
        instructions=instructions
    )


# Substitua a função submit_mapping no arquivo mapping.py por esta versão corrigida:

@router.post("/submit", response_model=MappingResult)
async def submit_mapping(
        submission: QuestionnaireSubmission,
        db=Depends(get_db),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """Processa a submissão com o sistema híbrido"""

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

    # Preparar dados para o mapeador híbrido
    questions = {q.id: q for q in session["questions"]}

    # Converter respostas para formato esperado
    questionnaire_responses = {
        r.question_id: r.selected_options
        for r in submission.responses
    }

    # Converter opções para formato esperado
    question_options = {}
    for q_id, question in questions.items():
        question_options[q_id] = {}
        for opt_id, option in question.options.items():
            question_options[q_id][opt_id] = {
                "area": option.area,
                "weight": option.weight
            }

    # Usar mapeador híbrido se disponível
    mapper = get_hybrid_mapper()
    text_contribution = 0.0

    # CORREÇÃO: Sempre calcular scores do questionário primeiro
    # Calcular scores manualmente se o mapper não está disponível
    if mapper:
        if submission.text_response:
            # Usar sistema híbrido com PKL
            results = mapper.map_interests(
                questionnaire_responses,
                question_options,
                submission.text_response
            )
            normalized_scores = results['combined_scores']
            text_contribution = results['text_quality'] * 0.4  # 40% máximo

            # Log para debug
            print(f"📊 Usando sistema híbrido:")
            print(f"   - Qualidade do texto: {results['text_quality']:.1%}")
            print(f"   - Concordância: {results['analysis_details']['agreement_score']:.1%}")
        else:
            # Usar apenas questionário através do mapper
            normalized_scores = mapper.calculate_questionnaire_scores(
                questionnaire_responses,
                question_options
            )
    else:
        # CORREÇÃO: Implementar cálculo manual quando não há mapper
        print("⚠️ Mapper não disponível, usando cálculo manual")

        # Sistema de pesos do questionário
        question_weights = {
            1: 0.15,  # Tempo livre
            2: 0.20,  # Conteúdo internet
            3: 0.30,  # Papel no grupo
            4: 0.35,  # Matérias
            5: 0.40  # Profissão
        }

        # Calcular scores manualmente
        area_scores = defaultdict(float)
        area_appearances = defaultdict(set)

        for question_id, selected_options in questionnaire_responses.items():
            if question_id not in question_options:
                continue

            question_weight = question_weights.get(question_id, 0.2)
            num_selected = len(selected_options)

            if num_selected == 0:
                continue

            for option_id in selected_options:
                if option_id in question_options[question_id]:
                    option = question_options[question_id][option_id]
                    area = option.get('area')
                    weight = option.get('weight', 1.0)

                    if area:
                        score = (question_weight * weight) / num_selected
                        area_scores[area] += score
                        area_appearances[area].add(question_id)

        # Normalizar scores
        normalized_scores = {}
        if area_scores:
            max_score = max(area_scores.values())
            if max_score > 0:
                normalized_scores = {area: score / max_score for area, score in area_scores.items()}
        else:
            # Se não há scores, criar distribuição uniforme
            all_areas = list(TRACK_DESCRIPTIONS.keys())
            normalized_scores = {area: 0.1 for area in all_areas}

    # Garantir que todas as áreas tenham pontuação
    all_areas = list(TRACK_DESCRIPTIONS.keys())
    for area in all_areas:
        if area not in normalized_scores:
            normalized_scores[area] = 0.0

    # Ordenar áreas
    sorted_areas = sorted(normalized_scores.items(), key=lambda x: x[1], reverse=True)

    # CORREÇÃO: Verificar se há scores válidos
    if not sorted_areas or all(score == 0 for _, score in sorted_areas):
        # Se todos os scores são zero, usar primeira área como fallback
        print("⚠️ Nenhum score válido encontrado, usando área padrão")
        sorted_areas = [(all_areas[0], 1.0)] + [(area, 0.0) for area in all_areas[1:]]

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

    # CORREÇÃO: Não definir subárea automaticamente
    # Remover toda a lógica de subárea recomendada
    top_subareas = []
    recommended_subarea = None

    # Atualizar dados do usuário - SEM definir current_track ainda
    user_ref = db.collection(Collections.USERS).document(current_user["id"])

    # Criar registro de mapeamento
    mapping_record = {
        "date": time.strftime("%Y-%m-%d"),
        "track": recommended_track,
        "score": normalized_scores.get(recommended_track, 0.0),
        "top_interests": dict(sorted_areas[:3]),
        "method": "hybrid_pkl" if mapper and submission.text_response else "questionnaire_only"
    }

    # Preparar atualizações - APENAS recommended_track, NÃO current_track
    updates = {
        "recommended_track": recommended_track,
        "track_scores": normalized_scores,
        "mapping_history": current_user.get("mapping_history", []) + [mapping_record]
    }

    # NÃO configurar progresso ainda - isso será feito quando escolher subárea

    # Atualizar no banco
    user_ref.update(updates)

    # Adicionar XP e badges
    xp_earned = XP_REWARDS.get("complete_mapping", 25)

    # Bonus de XP se usou texto
    if submission.text_response and len(submission.text_response) > 50:
        xp_earned += 10
        add_user_xp(db, current_user["id"], xp_earned, "Completou mapeamento detalhado com análise de texto")
    else:
        add_user_xp(db, current_user["id"], xp_earned, "Completou mapeamento de interesses")

    badges_earned = []

    # Badge de explorador
    explorer_badge = f"Explorador de {recommended_track}"
    if grant_badge(db, current_user["id"], explorer_badge):
        badges_earned.append(explorer_badge)

    # Badge de autoconhecimento
    if len(current_user.get("mapping_history", [])) == 0:
        if grant_badge(db, current_user["id"], "Autoconhecimento"):
            badges_earned.append("Autoconhecimento")

    # Badge especial por usar IA
    if mapper and submission.text_response and len(submission.text_response) > 100:
        if grant_badge(db, current_user["id"], "Explorador Detalhista"):
            badges_earned.append("Explorador Detalhista")

    # Limpar sessão
    del _mapping_sessions[submission.session_id]

    return MappingResult(
        user_id=current_user["id"],
        session_id=submission.session_id,
        recommended_track=recommended_track,
        recommended_subarea=None,  # SEMPRE None agora
        area_scores=area_score_list,
        top_subareas=[],  # SEMPRE vazio agora
        text_analysis_contribution=text_contribution,
        badges_earned=badges_earned,
        xp_earned=xp_earned
    )
@router.post("/analyze-text")
async def analyze_text(
        request: TextAnalysisRequest,
        current_user: dict = Depends(get_current_user)
) -> Any:
    """Analisa texto usando o modelo PKL"""
    mapper = get_hybrid_mapper()

    if not mapper:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML model not available"
        )

    # Analisar texto
    text_scores = mapper.analyze_text_with_pkl(request.text)

    # Formatar resposta
    area_scores = [
        {
            "area": area,
            "score": score,
            "percentage": score * 100
        }
        for area, score in sorted(
            text_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
    ]

    # Qualidade do texto
    text_quality = mapper.calculate_text_quality(request.text)

    return {
        "area_scores": area_scores,
        "top_area": area_scores[0]["area"] if area_scores else None,
        "text_quality": text_quality,
        "text_analyzed": request.text[:100] + "..." if len(request.text) > 100 else request.text,
        "method": "ml_classifier"
    }


@router.post("/upload-pkl")
async def upload_classifier_model(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Endpoint para fazer upload de um novo modelo PKL
    (Apenas para admins)
    """
    # Verificar se é admin
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can upload models"
        )

    # Verificar extensão
    if not file.filename.endswith('.pkl'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .pkl file"
        )

    # Salvar arquivo
    try:
        contents = await file.read()
        with open("ultimate_classifier_new.pkl", "wb") as f:
            f.write(contents)

        # Recarregar o mapeador
        global _hybrid_mapper
        _hybrid_mapper = HybridInterestMapper("ultimate_classifier_new.pkl")

        # Mover arquivo
        os.rename("ultimate_classifier_new.pkl", "ultimate_classifier.pkl")

        return {
            "message": "Model uploaded successfully",
            "filename": file.filename,
            "size": len(contents)
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload model: {str(e)}"
        )


@router.get("/model-status")
async def get_model_status(
        current_user: dict = Depends(get_current_user)
) -> Any:
    """Verifica o status do modelo ML"""
    mapper = get_hybrid_mapper()

    if mapper:
        return {
            "status": "active",
            "model_type": "hybrid_pkl",
            "categories_available": list(mapper.label_encoder.classes_) if hasattr(mapper, 'label_encoder') else [],
            "embedder_loaded": hasattr(mapper, 'embedder'),
            "features": {
                "questionnaire": True,
                "text_analysis": True,
                "hybrid_scoring": True
            }
        }
    else:
        return {
            "status": "inactive",
            "model_type": "questionnaire_only",
            "message": "ML model not loaded, using questionnaire-only system"
        }


@router.get("/history", response_model=MappingHistory)
async def get_mapping_history(
        db=Depends(get_db),
        current_user: dict = Depends(get_current_user)
) -> Any:
    """Obtém o histórico de mapeamentos do usuário"""
    mapping_history = current_user.get("mapping_history", [])

    # Análise do histórico
    area_frequencies = defaultdict(int)
    methods_used = defaultdict(int)

    for mapping in mapping_history:
        track = mapping.get("track")
        method = mapping.get("method", "questionnaire_only")

        if track:
            area_frequencies[track] += 1
        methods_used[method] += 1

    strongest_area = None
    if area_frequencies:
        strongest_area = max(area_frequencies.items(), key=lambda x: x[1])[0]

    return MappingHistory(
        mappings=mapping_history,
        total_mappings=len(mapping_history),
        current_track=current_user.get("current_track"),
        strongest_area=strongest_area,
        analysis_methods=dict(methods_used)
    )


@router.get("/areas")
async def get_available_areas() -> Any:
    """Lista todas as áreas disponíveis"""
    mapper = get_hybrid_mapper()

    areas = []
    for area, description in TRACK_DESCRIPTIONS.items():
        area_info = {
            "name": area,
            "description": description
        }

        # Adicionar informações do modelo ML se disponível
        if mapper and hasattr(mapper, 'label_encoder'):
            if area in mapper.label_encoder.classes_:
                area_info["ml_supported"] = True

        areas.append(area_info)

    return {
        "areas": areas,
        "total": len(areas),
        "ml_model_available": mapper is not None
    }