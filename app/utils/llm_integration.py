# app/utils/llm_integration.py
import os
import json
import time
import hashlib
from typing import Dict, List, Optional, Union, Any
from collections import OrderedDict
from openai import OpenAI
import logging

# Configure o logger no início do arquivo, após os imports:
logger = logging.getLogger(__name__)
# Configuração da API
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Modelos disponíveis
MODELS = {
    "default": "gpt-4o",
    "fast": "gpt-3.5-turbo",
    "advanced": "gpt-4o"
}

# Estilos de ensino disponíveis
TEACHING_STYLES = {
    "didático": "Explanações claras e estruturadas com exemplos práticos",
    "socrático": "Guiando através de perguntas para desenvolver o raciocínio crítico",
    "storytelling": "Ensinando através de narrativas e casos contextualizados",
    "visual": "Utilizando descrições de imagens, diagramas e representações visuais",
    "gamificado": "Incorporando elementos de jogos, desafios e recompensas",
    "projeto": "Aprendizado baseado em projetos práticos aplicáveis"
}


# Sistema de cache com limite de tamanho
class LRUCache:
    """Cache LRU (Least Recently Used) com limite de tamanho."""

    def __init__(self, max_size=1000):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key):
        if key in self.cache:
            # Mover para o fim (mais recentemente usado)
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        return None

    def set(self, key, value):
        if key in self.cache:
            # Remover para atualizar a posição
            self.cache.pop(key)
        elif len(self.cache) >= self.max_size:
            # Remover o item menos recentemente usado
            self.cache.popitem(last=False)

        # Adicionar ao final (mais recentemente usado)
        self.cache[key] = value


# Cache para respostas de LLM
# Chave: hash do prompt e parâmetros, Valor: (resposta, timestamp)
_response_cache = LRUCache(max_size=1000)

# Tempo máximo de cache (24 horas)
CACHE_TTL = 24 * 60 * 60  # em segundos


class LessonContent:
    """Classe para estruturar o conteúdo de uma aula"""

    def __init__(self,
                 title: str,
                 introduction: str,
                 main_content: List[Dict[str, str]],
                 examples: List[Dict[str, str]],
                 activities: List[Dict[str, str]],
                 summary: str):
        self.title = title
        self.introduction = introduction
        self.main_content = main_content
        self.examples = examples
        self.activities = activities
        self.summary = summary

    def to_dict(self) -> Dict[str, Any]:
        """Converte a aula para dicionário"""
        return {
            "title": self.title,
            "introduction": self.introduction,
            "main_content": self.main_content,
            "examples": self.examples,
            "activities": self.activities,
            "summary": self.summary
        }

    def to_text(self) -> str:
        """Converte a aula para texto formatado"""
        text = f"# {self.title}\n\n"
        text += f"{self.introduction}\n\n"

        for section in self.main_content:
            text += f"## {section['subtitle']}\n{section['content']}\n\n"

        if self.examples:
            text += "## Exemplos\n"
            for i, example in enumerate(self.examples, 1):
                text += f"### Exemplo {i}: {example['title']}\n{example['content']}\n\n"

        if self.activities:
            text += "## Atividades Práticas\n"
            for i, activity in enumerate(self.activities, 1):
                text += f"### Atividade {i}: {activity['title']}\n{activity['description']}\n\n"

        text += f"## Resumo\n{self.summary}"
        return text

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LessonContent':
        """Cria uma instância a partir de um dicionário"""
        return cls(
            title=data.get("title", ""),
            introduction=data.get("introduction", ""),
            main_content=data.get("main_content", []),
            examples=data.get("examples", []),
            activities=data.get("activities", []),
            summary=data.get("summary", "")
        )


def get_cache_key(content: str, **kwargs) -> str:
    """
    Gera uma chave de cache única baseada no conteúdo e parâmetros.
    """
    # Criar uma representação estável dos parâmetros
    params_str = json.dumps(
        {k: v for k, v in sorted(kwargs.items()) if k not in ['user_id', 'use_cache']}
    )

    # Concatenar conteúdo e parâmetros
    combined = f"{content}::{params_str}"

    # Gerar hash
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


def call_teacher_llm(user_content: str,
                     student_age: Union[int, List[int]] = None,
                     subject_area: str = None,
                     teaching_style: str = "didático",
                     knowledge_level: str = "iniciante",
                     temperature: float = 0.7,
                     model: str = "default",
                     max_tokens: int = 1500,
                     user_id: str = None,
                     use_cache: bool = True) -> str:
    """
    Chama a API da OpenAI para gerar conteúdo pedagógico adaptado.

    Args:
        user_content: O conteúdo/pergunta do usuário
        student_age: Idade(s) do(s) aluno(s) alvo
        subject_area: Área de conhecimento (ex: matemática, ciências)
        teaching_style: Estilo de ensino (didático, socrático, storytelling, etc)
        knowledge_level: Nível de conhecimento (iniciante, intermediário, avançado)
        temperature: Controle de criatividade (0.0 a 1.0)
        model: Modelo a ser usado (default, fast, advanced)
        max_tokens: Limite máximo de tokens na resposta
        user_id: ID do usuário para personalização contínua
        use_cache: Se deve usar cache para respostas anteriores

    Returns:
        Conteúdo educacional gerado
    """
    # Normaliza a idade para string
    if isinstance(student_age, list):
        age_range = f"{min(student_age)}-{max(student_age)}"
    elif isinstance(student_age, int):
        age_range = str(student_age)
    else:
        age_range = "11-17"  # Padrão

    # Verificar cache se habilitado
    if use_cache:
        cache_key = get_cache_key(
            user_content,
            student_age=age_range,
            subject_area=subject_area,
            teaching_style=teaching_style,
            knowledge_level=knowledge_level,
            model=model
        )
        cached = _response_cache.get(cache_key)

        if cached:
            response, timestamp = cached
            # Verificar se o cache ainda é válido
            if time.time() - timestamp < CACHE_TTL:
                return response

    # Construir o prompt do sistema
    system_prompt = (
        f"Você é um professor experiente especializado em {subject_area or 'diversas áreas'}. "
        f"Seu público são alunos de {age_range} anos. "
        f"Seu estilo de ensino é {teaching_style}, e você está ensinando conteúdo de nível {knowledge_level}. "
        "\n\nGuidelines de ensino:\n"
        "- IMPORTANTE: Vá direto ao conteúdo, sem introduções como 'Claro!', 'Vamos lá!', 'Com certeza!' ou similares\n"
        "- Não use cumprimentos ou frases de cortesia no início da resposta\n"
        "- Comece imediatamente com o conteúdo educacional solicitado\n"
        "- Explique conceitos de forma clara, gradual e com linguagem adequada à idade\n"
        "- Use exemplos concretos relacionados ao dia-a-dia dos alunos\n"
        "- Incentive a curiosidade, pensamento crítico e prática\n"
        "- Forneça contexto histórico e aplicações práticas quando relevante\n"
        "- Inclua perguntas reflexivas e desafios apropriados\n"
        "- Adapte o vocabulário e complexidade ao nível de conhecimento informado\n"
        "- Ofereça analogias e metáforas para conceitos abstratos\n"
        "- Incorpore elementos visuais (descrições de imagens/diagramas) quando útil\n"
    )

    # Adicionar elementos específicos para cada estilo de ensino
    if teaching_style == "socrático":
        system_prompt += (
            "- Guie através de perguntas que estimulem reflexão\n"
            "- Ajude o aluno a chegar às próprias conclusões\n"
            "- Evite fornecer respostas diretas imediatamente\n"
        )
    elif teaching_style == "storytelling":
        system_prompt += (
            "- Use narrativas envolventes para transmitir conceitos\n"
            "- Crie histórias com personagens e situações cativantes\n"
            "- Relacione a história com o conceito sendo ensinado\n"
        )
    elif teaching_style == "visual":
        system_prompt += (
            "- Descreva em detalhes como visualizar conceitos\n"
            "- Explique como seriam diagramas e imagens relacionadas\n"
            "- Use linguagem espacial e visual em suas explicações\n"
        )
    elif teaching_style == "gamificado":
        system_prompt += (
            "- Estruture o conteúdo como missões ou desafios\n"
            "- Incorpore elementos de progressão e recompensa\n"
            "- Use linguagem de jogos para tornar o aprendizado divertido\n"
        )
    elif teaching_style == "projeto":
        system_prompt += (
            "- Proponha projetos práticos aplicáveis\n"
            "- Ensine habilidades no contexto de um objetivo concreto\n"
            "- Forneça passos claros para implementação\n"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    # Selecionar o modelo apropriado
    selected_model = MODELS.get(model, MODELS["default"])

    # Realizar a chamada à API
    try:
        response = client.chat.completions.create(
            model=selected_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        content = response.choices[0].message.content

        # Guardar no cache se habilitado
        if use_cache:
            _response_cache.set(cache_key, (content, time.time()))

        return content
    except Exception as e:
        print(f"Erro ao chamar a API: {e}")
        return f"Ocorreu um erro ao gerar o conteúdo. Por favor, tente novamente mais tarde. Detalhes: {str(e)[:100]}..."


def generate_complete_lesson(topic: str,
                             subject_area: str,
                             age_range: Union[int, List[int]] = None,
                             knowledge_level: str = "iniciante",
                             teaching_style: str = "didático",
                             lesson_duration_min: int = 30) -> LessonContent:
    """
    Gera uma aula completa sobre um tópico específico.

    Args:
        topic: Tópico específico da aula
        subject_area: Área/disciplina geral
        age_range: Idade(s) do público-alvo
        knowledge_level: Nível de conhecimento (iniciante, intermediário, avançado)
        teaching_style: Estilo de ensino preferido
        lesson_duration_min: Duração aproximada da aula em minutos

    Returns:
        Um objeto LessonContent com a aula estruturada
    """
    # Converter duração da aula em complexidade aproximada
    complexity = "básica"
    if lesson_duration_min > 45:
        complexity = "detalhada"
    if lesson_duration_min > 90:
        complexity = "aprofundada"

    # Gerar a estrutura da aula
    prompt = f"""
    Crie uma aula {complexity} sobre "{topic}" na área de {subject_area}, para nível {knowledge_level}.

    A aula deve seguir a estrutura JSON abaixo:
    {{
        "title": "Título envolvente da aula",
        "introduction": "Introdução que desperte interesse (2-3 parágrafos)",
        "main_content": [
            {{"subtitle": "Subtítulo da primeira seção", "content": "Conteúdo detalhado desta seção (2-5 parágrafos)"}},
            {{"subtitle": "Subtítulo da segunda seção", "content": "Conteúdo detalhado desta seção (2-5 parágrafos)"}},
            {{"subtitle": "Subtítulo da terceira seção", "content": "Conteúdo detalhado desta seção (2-5 parágrafos)"}}
        ],
        "examples": [
            {{"title": "Título do exemplo 1", "content": "Descrição detalhada do exemplo"}},
            {{"title": "Título do exemplo 2", "content": "Descrição detalhada do exemplo"}}
        ],
        "activities": [
            {{"title": "Nome da atividade 1", "description": "Instruções detalhadas para realizar a atividade"}},
            {{"title": "Nome da atividade 2", "description": "Instruções detalhadas para realizar a atividade"}}
        ],
        "summary": "Resumo conciso dos principais pontos da aula (1-2 parágrafos)"
    }}

    Responda APENAS com o JSON válido, sem explicações adicionais.
    """

    try:
        # Gerar o conteúdo
        json_content = call_teacher_llm(
            prompt,
            student_age=age_range,
            subject_area=subject_area,
            teaching_style=teaching_style,
            knowledge_level=knowledge_level,
            temperature=0.7,
            max_tokens=4000  # Aumento do limite para aulas completas
        )

        # Extrair apenas o JSON da resposta
        json_match = json_content
        if "```json" in json_content:
            json_match = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_match = json_content.split("```")[1].strip()

        # Carregar o JSON
        lesson_data = json.loads(json_match)
        return LessonContent.from_dict(lesson_data)

    except Exception as e:
        print(f"Erro ao gerar a aula completa: {e}")
        # Criar uma aula básica em caso de erro
        return LessonContent(
            title=f"Aula sobre {topic}",
            introduction=f"Esta é uma introdução sobre {topic} na área de {subject_area}.",
            main_content=[{"subtitle": "Conceitos básicos", "content": "Conteúdo não disponível devido a um erro."}],
            examples=[],
            activities=[],
            summary=f"Não foi possível gerar o resumo para {topic}."
        )


def generate_assessment(topic: str,
                        difficulty: str = "médio",
                        num_questions: int = 5,
                        question_types: List[str] = ["múltipla escolha", "verdadeiro/falso", "dissertativa"]) -> Dict:
    """
    Gera uma avaliação com questões sobre o tópico específico.

    Args:
        topic: Tópico a ser avaliado
        difficulty: Nível de dificuldade (fácil, médio, difícil)
        num_questions: Quantidade de questões
        question_types: Tipos de questões desejados

    Returns:
        Dicionário com as questões, alternativas e respostas
    """
    prompt = f"""
    Crie uma avaliação sobre "{topic}" com {num_questions} questões de dificuldade {difficulty}.

    Inclua os seguintes tipos de questões: {', '.join(question_types)}.

    Forneça o resultado no seguinte formato JSON:
    {{
        "title": "Título da avaliação",
        "questions": [
            {{
                "type": "múltipla escolha",
                "text": "Texto da pergunta",
                "options": ["Alternativa A", "Alternativa B", "Alternativa C", "Alternativa D"],
                "correct_answer": 0,
                "explanation": "Explicação da resposta correta"
            }},
            {{
                "type": "verdadeiro/falso",
                "text": "Afirmação a ser julgada",
                "correct_answer": true,
                "explanation": "Explicação da resposta correta"
            }},
            {{
                "type": "dissertativa",
                "text": "Pergunta dissertativa",
                "sample_answer": "Exemplo de resposta adequada",
                "key_points": ["Ponto chave 1", "Ponto chave 2", "Ponto chave 3"]
            }}
        ]
    }}

    Responda APENAS com o JSON válido, sem explicações adicionais.
    """

    try:
        json_content = call_teacher_llm(
            prompt,
            teaching_style="didático",  # Estilo didático é melhor para avaliações
            temperature=0.7,
            max_tokens=3000
        )

        # Extrair apenas o JSON da resposta
        json_match = json_content
        if "```json" in json_content:
            json_match = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_match = json_content.split("```")[1].strip()

        # Carregar o JSON
        assessment_data = json.loads(json_match)
        return assessment_data

    except Exception as e:
        print(f"Erro ao gerar a avaliação: {e}")
        return {
            "title": f"Avaliação sobre {topic}",
            "questions": [
                {
                    "type": "múltipla escolha",
                    "text": "Não foi possível gerar questões devido a um erro.",
                    "options": ["Opção A", "Opção B", "Opção C", "Opção D"],
                    "correct_answer": 0,
                    "explanation": "Não disponível"
                }
            ]
        }


def generate_learning_pathway(topic: str,
                              duration_weeks: int = 8,
                              hours_per_week: int = 3,
                              initial_level: str = "iniciante",
                              target_level: str = "intermediário") -> Dict:
    """
    Gera um roteiro de aprendizado progressivo para um tópico.

    Args:
        topic: Tópico principal a ser aprendido
        duration_weeks: Duração do roteiro em semanas
        hours_per_week: Horas semanais de estudo
        initial_level: Nível de conhecimento inicial
        target_level: Nível de conhecimento alvo

    Returns:
        Dicionário com o roteiro estruturado de aprendizado
    """
    prompt = f"""
    Crie um roteiro de aprendizado sobre "{topic}" para {duration_weeks} semanas, 
    considerando {hours_per_week} horas de estudo por semana.

    O aluno começa no nível {initial_level} e deseja atingir o nível {target_level}.

    Forneça o resultado no seguinte formato JSON:
    {{
        "title": "Título do roteiro de aprendizado",
        "description": "Descrição do objetivo geral",
        "weekly_plan": [
            {{
                "week": 1,
                "focus": "Foco principal da semana",
                "objectives": ["Objetivo 1", "Objetivo 2", "Objetivo 3"],
                "activities": [
                    {{
                        "title": "Título da atividade",
                        "description": "Descrição detalhada",
                        "duration_minutes": 45,
                        "resources": ["Recurso 1", "Recurso 2"]
                    }}
                ],
                "assessment": "Como avaliar o progresso da semana"
            }}
        ],
        "final_project": "Descrição do projeto final que demonstra o aprendizado",
        "additional_resources": ["Recurso adicional 1", "Recurso adicional 2"]
    }}

    Responda APENAS com o JSON válido, sem explicações adicionais.
    """

    try:
        json_content = call_teacher_llm(
            prompt,
            teaching_style="projeto",  # Estilo baseado em projetos para roteiro
            temperature=0.7,
            max_tokens=4000
        )

        # Extrair apenas o JSON da resposta
        json_match = json_content
        if "```json" in json_content:
            json_match = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_match = json_content.split("```")[1].strip()

        # Carregar o JSON
        pathway_data = json.loads(json_match)
        return pathway_data

    except Exception as e:
        print(f"Erro ao gerar o roteiro de aprendizado: {e}")
        return {
            "title": f"Roteiro para aprender {topic}",
            "description": "Não foi possível gerar o roteiro completo devido a um erro.",
            "weekly_plan": [
                {
                    "week": 1,
                    "focus": "Introdução",
                    "objectives": ["Entender conceitos básicos"],
                    "activities": []
                }
            ]
        }


def analyze_content_difficulty(text: str) -> Dict[str, Any]:
    """
    Analisa a dificuldade de um conteúdo para diferentes faixas etárias.

    Args:
        text: Texto a ser analisado

    Returns:
        Dicionário com scores de adequação para diferentes idades
    """
    prompt = f"""
    Analise o seguinte texto e determine quão adequado ele é para diferentes faixas etárias
    em termos de complexidade, vocabulário e conceitos. Considere:

    Texto para análise:
    ---
    {text}
    ---

    Forneça o resultado como um JSON válido no seguinte formato:
    {{
        "adequação_11_12_anos": 0.8,
        "adequação_13_14_anos": 0.9,
        "adequação_15_17_anos": 0.95,
        "vocabulário_complexidade": "médio",
        "conceitos_abstratos": "médio",
        "explicações_visuais": "alto",
        "sugestões_adaptação": ["Sugestão 1", "Sugestão 2"]
    }}

    Responda APENAS com o JSON válido, sem explicações adicionais.
    """

    try:
        json_content = call_teacher_llm(
            prompt,
            teaching_style="didático",
            temperature=0.3,  # Temperatura mais baixa para análise objetiva
            max_tokens=1000
        )

        # Extrair apenas o JSON da resposta
        json_match = json_content
        if "```json" in json_content:
            json_match = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_match = json_content.split("```")[1].strip()

        # Carregar o JSON
        analysis_data = json.loads(json_match)
        return analysis_data

    except Exception as e:
        print(f"Erro ao analisar dificuldade: {e}")
        # Implementação fallback simplificada
        word_count = len(text.split())

        if word_count < 100:
            complexity = "baixo"
            adequacy_scores = {
                "adequação_11_12_anos": 0.9,
                "adequação_13_14_anos": 0.95,
                "adequação_15_17_anos": 1.0
            }
        elif word_count < 300:
            complexity = "médio"
            adequacy_scores = {
                "adequação_11_12_anos": 0.7,
                "adequação_13_14_anos": 0.85,
                "adequação_15_17_anos": 0.9
            }
        else:
            complexity = "alto"
            adequacy_scores = {
                "adequação_11_12_anos": 0.5,
                "adequação_13_14_anos": 0.7,
                "adequação_15_17_anos": 0.8
            }

        return {
            **adequacy_scores,
            "vocabulário_complexidade": complexity,
            "conceitos_abstratos": complexity,
            "explicações_visuais": "médio",
            "sugestões_adaptação": [
                "Adicionar mais exemplos práticos",
                "Simplificar vocabulário técnico",
                "Incluir elementos visuais"
            ]
        }


def simplify_content(text: str, target_age: int) -> str:
    """
    Simplifica um conteúdo para torná-lo mais adequado para uma determinada idade.

    Args:
        text: Texto original
        target_age: Idade alvo

    Returns:
        Texto simplificado e adaptado
    """
    prompt = f"""
    Simplifique o seguinte texto para que seja adequado e compreensível para um aluno de {target_age} anos.
    Mantenha todos os conceitos importantes, mas adapte o vocabulário, comprimento das frases e explicações.

    Texto original:
    ---
    {text}
    ---

    Texto simplificado:
    """

    try:
        simplified_text = call_teacher_llm(
            prompt,
            student_age=target_age,
            teaching_style="didático",
            temperature=0.7
        )
        return simplified_text
    except Exception as e:
        print(f"Erro ao simplificar conteúdo: {e}")
        # Implementação fallback simplificada
        words = text.split()

        if target_age <= 12:
            # Simplificação mais agressiva
            simplified_words = []
            for word in words:
                if len(word) > 10:
                    simplified_words.append(f"[termo técnico: {word[:7]}...]")
                else:
                    simplified_words.append(word)

            simplified_text = " ".join(simplified_words)
            return f"Versão simplificada para {target_age} anos:\n\n{simplified_text}\n\n[Nota: Este conteúdo foi automaticamente simplificado.]"

        return f"Conteúdo adaptado para {target_age} anos:\n\n{text}\n\n[Nota: Use a função de LLM para adaptação mais precisa.]"


# Substitua a função enrich_content no arquivo llm_integration.py por esta versão melhorada:

def enrich_content(text: str, enrichment_type: str = "exemplos") -> str:
    """
    Enriquece um conteúdo com elementos adicionais específicos.

    Args:
        text: Texto original
        enrichment_type: Tipo de enriquecimento (exemplos, analogias, perguntas, aplicações)

    Returns:
        Texto enriquecido com o tipo específico de conteúdo
    """

    # Prompts específicos para cada tipo de enriquecimento
    prompts = {
        "exemplos": """
        Adicione 3-5 exemplos práticos e concretos para o conteúdo abaixo.
        Os exemplos devem:
        - Ser do cotidiano dos alunos
        - Ilustrar claramente os conceitos
        - Variar em complexidade (do simples ao mais elaborado)
        - Incluir situações reais e aplicáveis

        Formato desejado:
        ## Exemplos Práticos

        ### Exemplo 1: [Título descritivo]
        [Descrição detalhada do exemplo]

        ### Exemplo 2: [Título descritivo]
        [Descrição detalhada do exemplo]

        (continue com mais exemplos)
        """,

        "analogias": """
        Crie 3-4 analogias criativas e esclarecedoras para o conteúdo abaixo.
        As analogias devem:
        - Comparar conceitos complexos com situações familiares
        - Usar metáforas visuais quando possível
        - Explicar o paralelo entre a analogia e o conceito
        - Ser apropriadas para a idade do público

        Formato desejado:
        ## Analogias para Melhor Compreensão

        ### 🔄 [Conceito] é como [Analogia]
        [Explicação detalhada da comparação]

        ### 🎯 Imagine que [Conceito] funciona como [Analogia]
        [Explicação detalhada]

        (continue com mais analogias)
        """,

        "perguntas": """
        Formule 5-7 perguntas reflexivas e desafiadoras sobre o conteúdo abaixo.
        As perguntas devem:
        - Estimular o pensamento crítico
        - Ter diferentes níveis de complexidade
        - Conectar o conteúdo com a vida real
        - Incluir perguntas abertas e fechadas
        - Promover a aplicação do conhecimento

        Formato desejado:
        ## Perguntas para Reflexão e Prática

        ### 🤔 Perguntas de Compreensão:
        1. [Pergunta básica sobre o conceito]
        2. [Pergunta sobre detalhes importantes]

        ### 💭 Perguntas de Análise:
        3. [Pergunta que exige comparação ou análise]
        4. [Pergunta sobre causa e efeito]

        ### 🚀 Perguntas de Aplicação:
        5. [Como você aplicaria isso em...]
        6. [O que aconteceria se...]

        ### 🎯 Desafio:
        7. [Pergunta complexa que integra vários conceitos]
        """,

        "aplicações": """
        Descreva 4-6 aplicações práticas e reais do conteúdo abaixo.
        As aplicações devem:
        - Mostrar usos no mundo real
        - Incluir diferentes áreas (tecnologia, ciência, cotidiano, profissões)
        - Explicar como o conceito é usado na prática
        - Inspirar o aluno sobre a importância do aprendizado

        Formato desejado:
        ## Aplicações no Mundo Real

        ### 🏭 Na Indústria
        [Como esse conceito é usado em fábricas/empresas]

        ### 💻 Na Tecnologia
        [Aplicações em computadores/internet/apps]

        ### 🏠 No Dia a Dia
        [Como usamos isso em casa/escola]

        ### 🔬 Na Ciência e Pesquisa
        [Aplicações científicas e descobertas]

        ### 💼 Nas Profissões
        [Quais profissionais usam esse conhecimento e como]
        """
    }

    # Selecionar o prompt apropriado
    specific_prompt = prompts.get(enrichment_type, prompts["exemplos"])

    prompt = f"""
    {specific_prompt}

    Conteúdo original para enriquecer:
    ---
    {text}
    ---

    Gere APENAS o conteúdo de enriquecimento solicitado, sem repetir o conteúdo original.
    Use linguagem clara, apropriada para adolescentes e mantenha um tom educativo e envolvente.
    """

    try:
        enriched_text = call_teacher_llm(
            prompt,
            teaching_style="didático",
            temperature=0.8,  # Um pouco mais criativo para gerar conteúdo variado
            max_tokens=2000
        )
        return enriched_text
    except Exception as e:
        print(f"Erro ao enriquecer conteúdo: {e}")

        # Implementação fallback mais elaborada
        fallback_content = {
            "exemplos": f"""
## Exemplos Práticos

### Exemplo 1: Aplicação Básica
Imagine que você está aprendendo este conceito pela primeira vez. Um exemplo simples seria...

### Exemplo 2: Situação Cotidiana
No seu dia a dia, você pode observar isso quando...

### Exemplo 3: Caso Avançado
Para quem já domina o básico, considere esta situação mais complexa...

[Nota: Exemplos genéricos - use a função com LLM para exemplos específicos do conteúdo]
""",

            "analogias": f"""
## Analogias para Melhor Compreensão

### 🔄 Este conceito é como uma receita de bolo
Assim como seguir uma receita garante um bolo perfeito, entender este conceito...

### 🎯 Imagine que funciona como um quebra-cabeça
Cada peça do conhecimento se encaixa para formar o quadro completo...

[Nota: Analogias genéricas - use a função com LLM para analogias específicas do conteúdo]
""",

            "perguntas": f"""
## Perguntas para Reflexão e Prática

### 🤔 Perguntas de Compreensão:
1. O que você entendeu sobre o conceito principal?
2. Quais são os pontos mais importantes?

### 💭 Perguntas de Análise:
3. Como isso se relaciona com outros conceitos que você conhece?
4. Quais são as possíveis consequências disso?

### 🚀 Perguntas de Aplicação:
5. Como você usaria esse conhecimento em um projeto pessoal?
6. Que problemas do dia a dia isso poderia resolver?

[Nota: Perguntas genéricas - use a função com LLM para perguntas específicas do conteúdo]
""",

            "aplicações": f"""
## Aplicações no Mundo Real

### 🏭 Na Indústria
Este conhecimento é fundamental para processos de produção e otimização...

### 💻 Na Tecnologia
Desenvolvedores e engenheiros usam esses conceitos para criar...

### 🏠 No Dia a Dia
Você pode aplicar isso quando precisa...

### 💼 Nas Profissões
Profissionais de diversas áreas utilizam esse conhecimento para...

[Nota: Aplicações genéricas - use a função com LLM para aplicações específicas do conteúdo]
"""
        }

        return fallback_content.get(enrichment_type, fallback_content["exemplos"])

# Adicione esta função melhorada em llm_integration.py

def enrich_content_with_context(
        text: str,
        enrichment_type: str = "exemplos",
        title: str = "",
        area: str = "",
        subarea: str = "",
        level: str = "iniciante",
        user_age: int = 14,
        learning_style: str = "didático"
) -> str:
    """
    Versão melhorada de enrich_content que usa todo o contexto disponível.
    """

    # Verificar se o texto não está vazio
    if not text.strip():
        return f"Erro: Conteúdo vazio para gerar {enrichment_type}"

    # Construir contexto adicional para o prompt
    context_info = f"""
    Contexto da Lição:
    - Título: {title or 'Conteúdo Educacional'}
    - Área: {area or 'Geral'}
    - Subárea: {subarea or 'Geral'}
    - Nível: {level}
    - Idade do aluno: {user_age} anos
    - Estilo de aprendizagem: {learning_style}
    """

    # Prompts específicos aprimorados com contexto
    prompts = {
        "exemplos": f"""
        {context_info}

        Crie 3-4 exemplos práticos e concretos sobre o conteúdo fornecido.
        Os exemplos devem ser:
        - Apropriados para alunos de {user_age} anos
        - Relacionados à área de {area or 'conhecimento geral'}
        - Progressivos em dificuldade
        - Conectados com o cotidiano brasileiro

        Formato:
        ## 📚 Exemplos Práticos

        ### Exemplo 1: [Título descritivo]
        [Descrição detalhada do exemplo]

        ### Exemplo 2: [Título descritivo]
        [Situação prática que ilustra o conceito]

        ### Exemplo 3: [Título descritivo]
        [Exemplo mais avançado]
        """,

        "analogias": f"""
        {context_info}

        Crie 3-4 analogias criativas para explicar os conceitos do conteúdo.
        As analogias devem:
        - Ser adequadas para {user_age} anos
        - Usar referências familiares aos estudantes
        - Tornar conceitos abstratos em concretos

        Formato:
        ## 🔄 Analogias Esclarecedoras

        ### 💡 [Conceito] é como...
        [Analogia detalhada explicando a comparação]

        ### 🎯 Pense em [conceito] como se fosse...
        [Analogia visual e descritiva]
        """,

        "perguntas": f"""
        {context_info}

        Formule 5-6 perguntas reflexivas sobre o conteúdo.
        As perguntas devem:
        - Ser adequadas para nível {level}
        - Estimular pensamento crítico
        - Ter progressão de dificuldade
        - Conectar com a realidade dos jovens

        Formato:
        ## 🤔 Perguntas para Reflexão

        ### Compreensão:
        1. [Pergunta básica sobre o conceito]
        2. [Pergunta sobre detalhes importantes]

        ### Análise:
        3. [Como isso se relaciona com...]
        4. [Por que você acha que...]

        ### Aplicação:
        5. [Como você usaria isso para...]
        6. [Crie um exemplo onde...]
        """,

        "aplicações": f"""
        {context_info}

        Descreva 4-5 aplicações práticas do conteúdo no mundo real.
        As aplicações devem:
        - Mostrar usos reais em {area or 'diversas áreas'}
        - Ser relevantes para jovens de {user_age} anos
        - Incluir tecnologias atuais
        - Inspirar sobre possibilidades futuras

        Formato:
        ## 🚀 Aplicações no Mundo Real

        ### 💻 Na Tecnologia
        [Como esse conhecimento é usado em tecnologia]

        ### 🏢 No Trabalho
        [Profissões que usam esse conhecimento]

        ### 🌍 No Cotidiano
        [Situações do dia a dia onde isso aparece]

        ### 🔬 Em Inovações
        [Pesquisas e projetos que usam esses conceitos]
        """
    }

    # Selecionar o prompt apropriado
    specific_prompt = prompts.get(enrichment_type, prompts["exemplos"])

    prompt = f"""
    {specific_prompt}

    Conteúdo da lição para enriquecer:
    ---
    {text[:1500]}...
    ---

    Gere conteúdo ESPECÍFICO sobre o que foi apresentado na lição.
    Use linguagem clara e apropriada para {user_age} anos.
    """

    try:
        enriched_text = call_teacher_llm(
            prompt,
            student_age=user_age,
            subject_area=f"{area} - {subarea}" if area and subarea else area or "Geral",
            teaching_style=learning_style,
            knowledge_level=level,
            temperature=0.8,
            max_tokens=2000
        )
        return enriched_text
    except Exception as e:
        logger.error(f"Erro ao enriquecer conteúdo com LLM: {e}")

        # Fallback simples
        fallback_content = {
            "exemplos": f"## 📚 Exemplos Práticos\n\n### Exemplo 1\nEste conceito pode ser observado quando...\n\n### Exemplo 2\nOutra situação onde isso aparece é...\n\n[Erro na geração de exemplos específicos]",
            "analogias": f"## 🔄 Analogias\n\n### 💡 Comparação\nEste conceito é como...\n\n[Erro na geração de analogias específicas]",
            "perguntas": f"## 🤔 Perguntas para Reflexão\n\n1. O que você entendeu sobre este conceito?\n2. Como isso se aplica na sua vida?\n3. Que dúvidas você ainda tem?\n\n[Erro na geração de perguntas específicas]",
            "aplicações": f"## 🚀 Aplicações\n\n### No cotidiano\nEsse conhecimento é usado para...\n\n### Na tecnologia\nDesenvolvemos soluções que...\n\n[Erro na geração de aplicações específicas]"
        }

        return fallback_content.get(enrichment_type, "Erro ao gerar conteúdo enriquecido.")

def get_personalized_content(prompt: str,
                             user_id: str = None,
                             subject_area: str = None,
                             age_range: Union[int, List[int]] = None) -> str:
    """
    Mantém compatibilidade com o nome usado no código (gera conteúdo).
    Internamente, chama call_teacher_llm para que as respostas
    tenham tom de professor didático.

    Args:
        prompt: Prompt do usuário
        user_id: ID do usuário para personalização
        subject_area: Área do conhecimento
        age_range: Idade do estudante

    Returns:
        Conteúdo personalizado gerado
    """
    return call_teacher_llm(
        prompt,
        student_age=age_range,
        subject_area=subject_area,
        teaching_style="didático",
        temperature=0.7,
        user_id=user_id
    )