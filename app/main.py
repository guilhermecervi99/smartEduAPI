# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import get_settings
from app.api.v1.api import api_router
from app.database import firestore_client

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação
    """
    # Startup
    logger.info("Starting up the application...")
    logger.info(f"Project: {settings.project_name}")
    logger.info(f"Version: {settings.version}")

    yield

    # Shutdown
    logger.info("Shutting down the application...")
    firestore_client.close()


# Criar aplicação FastAPI
app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    description=settings.description,
    openapi_url=f"{settings.api_v1_str}/openapi.json",
    docs_url=f"{settings.api_v1_str}/docs",
    redoc_url=f"{settings.api_v1_str}/redoc",
    lifespan=lifespan
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir rotas da API
app.include_router(api_router, prefix=settings.api_v1_str)


# Health check endpoint
@app.get("/", tags=["health"])
async def root():
    """
    Health check endpoint
    """
    return {
        "status": "ok",
        "project": settings.project_name,
        "version": settings.version,
        "message": "Sistema Educacional Gamificado API"
    }


@app.get("/health", tags=["health"])
async def health_check():
    """
    Verifica a saúde da aplicação e suas dependências
    """
    health_status = {
        "status": "healthy",
        "services": {}
    }

    # Verificar Firestore
    try:
        db = firestore_client.get_client()
        # Fazer uma operação simples para verificar conexão
        db.collection("_health_check").document("test").set({"check": True})
        health_status["services"]["firestore"] = "healthy"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["services"]["firestore"] = f"unhealthy: {str(e)}"

    # Verificar OpenAI (se configurado)
    if settings.openai_api_key:
        health_status["services"]["openai"] = "configured"
    else:
        health_status["services"]["openai"] = "not configured"

    return health_status


# Middleware para logging
@app.middleware("http")
async def log_requests(request, call_next):
    """
    Log todas as requisições HTTP
    """
    logger.info(f"{request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Status: {response.status_code}")
    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )