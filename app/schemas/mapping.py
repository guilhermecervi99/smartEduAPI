# app/schemas/mapping.py
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


class QuestionOption(BaseModel):
    """Opção de resposta para uma pergunta"""
    text: str
    area: Optional[str] = None
    weight: float = 1.0


class MappingQuestion(BaseModel):
    """Pergunta do questionário de mapeamento"""
    id: int
    question: str
    options: Dict[str, QuestionOption]


class QuestionResponse(BaseModel):
    """Resposta do usuário para uma pergunta"""
    question_id: int
    selected_options: List[str] = Field(..., min_length=1)

    @field_validator('selected_options')
    @classmethod
    def validate_options(cls, v):
        # Remove duplicatas
        return list(set(v))


class TextAnalysisRequest(BaseModel):
    """Requisição para análise de texto de interesses"""
    text: str = Field(..., min_length=10, max_length=5000)

    @field_validator('text')
    @classmethod
    def validate_text(cls, v):
        # Remove espaços extras
        return ' '.join(v.split())


class MappingStartResponse(BaseModel):
    """Resposta ao iniciar o mapeamento"""
    session_id: str
    questions: List[MappingQuestion]
    total_questions: int
    instructions: str


class QuestionnaireSubmission(BaseModel):
    """Submissão completa do questionário"""
    session_id: str
    responses: List[QuestionResponse]
    text_response: Optional[str] = Field(None, min_length=10, max_length=5000)

    @field_validator('responses')
    @classmethod
    def validate_responses(cls, v):
        # Verificar se todas as respostas são únicas por question_id
        question_ids = [r.question_id for r in v]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Duplicate responses for the same question")
        return v


class AreaScore(BaseModel):
    """Pontuação de uma área"""
    area: str
    score: float = Field(..., ge=0.0, le=1.0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    rank: int


class SubareaRecommendation(BaseModel):
    """Recomendação de subárea"""
    subarea: str
    score: float = Field(..., ge=0.0, le=1.0)
    reason: Optional[str] = None


class MappingResult(BaseModel):
    """Resultado completo do mapeamento"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "user_123",
                "session_id": "session_456",
                "recommended_track": "Tecnologia e Computação",
                "recommended_subarea": "Desenvolvimento de Software",
                "area_scores": [
                    {
                        "area": "Tecnologia e Computação",
                        "score": 0.85,
                        "percentage": 85.0,
                        "rank": 1
                    },
                    {
                        "area": "Ciências Exatas",
                        "score": 0.65,
                        "percentage": 65.0,
                        "rank": 2
                    }
                ],
                "top_subareas": [
                    {
                        "subarea": "Desenvolvimento de Software",
                        "score": 0.9,
                        "reason": "Forte interesse em programação"
                    }
                ],
                "text_analysis_contribution": 0.3,
                "badges_earned": ["Explorador de Tecnologia e Computação"],
                "xp_earned": 25
            }
        }
    )

    user_id: str
    session_id: str
    recommended_track: str
    recommended_subarea: Optional[str] = None
    area_scores: List[AreaScore]
    top_subareas: List[SubareaRecommendation]
    text_analysis_contribution: Optional[float] = None
    badges_earned: List[str] = []
    xp_earned: int = 0


class MappingHistory(BaseModel):
    """Histórico de mapeamentos do usuário"""
    mappings: List[Dict[str, Any]]
    total_mappings: int
    current_track: Optional[str] = None
    strongest_area: Optional[str] = None