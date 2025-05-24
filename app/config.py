# app/config.py
import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

# Carregar variáveis do .env
load_dotenv()


class Settings(BaseSettings):
    # API Settings
    api_v1_str: str = "/api/v1"
    project_name: str = "Sistema Educacional Gamificado"
    version: str = "1.0.0"
    description: str = "API para sistema de direcionamento educacional personalizado"

    # Security
    secret_key: str = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Firebase/Firestore
    google_application_credentials: Optional[str] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    firebase_project_id: Optional[str] = os.getenv("FIREBASE_PROJECT_ID")

    # OpenAI
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    openai_model: str = "gpt-4o"
    openai_model_fast: str = "gpt-3.5-turbo"

    # CORS
    backend_cors_origins: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8080",
        "https://localhost",
        "https://localhost:3000",
        "https://localhost:8080",
    ]

    # Gamification Settings
    xp_thresholds: list[int] = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500]

    # Cache Settings
    cache_ttl: int = 24 * 60 * 60  # 24 hours in seconds

    # Teaching Styles
    teaching_styles: dict = {
        "didático": "Explanações claras e estruturadas com exemplos práticos",
        "socrático": "Guiando através de perguntas para desenvolver o raciocínio crítico",
        "storytelling": "Ensinando através de narrativas e casos contextualizados",
        "visual": "Utilizando descrições de imagens, diagramas e representações visuais",
        "gamificado": "Incorporando elementos de jogos, desafios e recompensas",
        "projeto": "Aprendizado baseado em projetos práticos aplicáveis"
    }

    # Default Values
    default_user_age: int = 14
    default_teaching_style: str = "didático"
    default_level: str = "iniciante"

    model_config = {
        "case_sensitive": True,
        "env_file": ".env",
        "extra": "ignore"  # Ignora campos extras do .env
    }


@lru_cache()
def get_settings():
    """
    Cria uma instância única das configurações (singleton)
    """
    return Settings()


# Constantes do sistema
LEVEL_ORDER = ["iniciante", "básico", "basico", "intermediário", "intermediario", "avançado", "avancado"]

TRACK_DESCRIPTIONS = {
    "Ciências Exatas": "Foco em Matemática, Física, Química, Astronomia e Engenharia.",
    "Artes e Cultura": "Explora artes visuais, design, teatro, fotografia e expressão criativa.",
    "Esportes e Atividades Físicas": "Modalidades esportivas individuais e coletivas, artes marciais e bem-estar físico.",
    "Tecnologia e Computação": "Programação, desenvolvimento de software, hardware, robótica e jogos digitais.",
    "Ciências Biológicas e Saúde": "Biologia, medicina, saúde, psicologia, veterinária e meio ambiente.",
    "Ciências Humanas e Sociais": "Filosofia, história, antropologia, sociologia, política e direito.",
    "Literatura e Linguagem": "Leitura, escrita criativa, linguística, tradução e idiomas.",
    "Negócios e Empreendedorismo": "Administração, marketing, finanças, empreendedorismo e inovação.",
    "Comunicação Profissional": "Jornalismo, oratória, comunicação empresarial e expressão verbal."
}

# Mapeamento de abreviações
ABBREVIATION_MAP = {
    "vc": "voce", "vcs": "voces", "td": "tudo", "tds": "todos", "tbm": "tambem",
    "tb": "tambem", "blz": "beleza", "flw": "falou", "vlw": "valeu", "tmj": "tamo junto",
    "pdp": "pode pa", "pprt": "papo reto", "btf": "boto fe", "slc": "se e louco",
    "mds": "meu deus", "pfv": "por favor", "pfvr": "por favor", "obg": "obrigado",
    "add": "adicionar", "msg": "mensagem", "wpp": "whatsapp", "zap": "whatsapp",
    "insta": "instagram", "face": "facebook", "tt": "twitter", "yt": "youtube",
    "vdd": "verdade", "msm": "mesmo", "cmg": "comigo", "dnv": "de novo",
    "prog": "programacao", "dev": "desenvolvimento", "ia": "inteligencia artificial",
    "ml": "machine learning", "bd": "banco de dados", "sql": "sql", "html": "html",
    "css": "css", "js": "javascript", "py": "python", "pc": "computador",
    "pc gamer": "pc gamer", "hw": "hardware", "sw": "software", "app": "aplicativo",
    "tec": "tecnologia", "robo": "robotica", "drone": "drone", "3d": "3d",
}