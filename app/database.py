# app/database.py
from google.cloud import firestore
from typing import Optional
import logging
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class FirestoreClient:
    """Gerenciador de conexão com Firestore"""

    def __init__(self):
        self._client: Optional[firestore.Client] = None

    def get_client(self) -> firestore.Client:
        """
        Retorna o cliente Firestore, criando um se não existir
        """
        if self._client is None:
            try:
                if settings.firebase_project_id:
                    self._client = firestore.Client(project=settings.firebase_project_id)
                else:
                    self._client = firestore.Client()
                logger.info("Firestore client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Firestore client: {e}")
                raise

        return self._client

    def close(self):
        """Fecha a conexão com o Firestore"""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Firestore client closed")


# Instância global do cliente
firestore_client = FirestoreClient()


def get_db() -> firestore.Client:
    """
    Dependência para obter o cliente Firestore nas rotas
    """
    return firestore_client.get_client()


# Collections names
class Collections:
    """Nomes das coleções no Firestore"""
    USERS = "users"
    LEARNING_PATHS = "learning_paths"
    PROJECTS = "projects"
    ACHIEVEMENTS = "achievements"
    ASSESSMENTS = "assessments"
    RESOURCES = "resources"


# Índices compostos sugeridos para Firestore
FIRESTORE_INDEXES = [
    {
        "collection": Collections.USERS,
        "fields": [
            {"fieldPath": "current_track", "order": "ASCENDING"},
            {"fieldPath": "profile_level", "order": "DESCENDING"}
        ]
    },
    {
        "collection": Collections.USERS,
        "fields": [
            {"fieldPath": "created_at", "order": "DESCENDING"},
            {"fieldPath": "profile_xp", "order": "DESCENDING"}
        ]
    }
]