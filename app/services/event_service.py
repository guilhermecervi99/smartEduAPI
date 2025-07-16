# app/services/event_service.py
import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from google.cloud import pubsub_v1
import logging

from app.services.event_types import EventTypes

logger = logging.getLogger(__name__)


class EventService:
    """Serviço unificado para publicar eventos"""

    def __init__(self):
        self.project_id = os.getenv("FIREBASE_PROJECT_ID", "axiomatic-robot-417213")
        self.topic_name = "app-events"

        # Verificar se está em desenvolvimento
        if os.getenv("PUBSUB_EMULATOR_HOST"):
            logger.info(f"Usando emulador Pub/Sub: {os.getenv('PUBSUB_EMULATOR_HOST')}")

        try:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)
            logger.info(f"EventService inicializado para tópico: {self.topic_path}")
        except Exception as e:
            logger.error(f"Erro ao inicializar Pub/Sub client: {e}")
            self.publisher = None

    async def publish_event(
            self,
            event_type: EventTypes,
            user_id: str,
            data: Dict[str, Any],
            context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Publica evento de forma assíncrona
        """
        if not self.publisher:
            logger.warning("Publisher não inicializado, pulando evento")
            return None

        try:
            # Criar evento com estrutura padrão
            event = {
                "event_id": f"{event_type}_{user_id}_{int(datetime.utcnow().timestamp() * 1000)}",
                "event_type": event_type,
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": data,
                "context": context or {},
                "metadata": {
                    "app_version": os.getenv("APP_VERSION", "1.0.0"),
                    "environment": os.getenv("ENVIRONMENT", "production"),
                    "source": "backend_api"
                }
            }

            # Log do evento
            logger.info(f"Publicando evento: {event_type} para usuário: {user_id}")

            # Serializar
            message_bytes = json.dumps(event).encode("utf-8")

            # Publicar
            future = self.publisher.publish(
                self.topic_path,
                message_bytes,
                event_type=event_type,
                user_id=user_id
            )

            # Log assíncrono
            asyncio.create_task(self._log_publish_result(future, event_type))

            return event.get("event_id")

        except Exception as e:
            logger.error(f"Erro ao publicar evento {event_type}: {e}")
            return None

    async def _log_publish_result(self, future, event_type):
        """Log do resultado da publicação"""
        try:
            message_id = await asyncio.get_event_loop().run_in_executor(
                None, future.result, 5.0
            )
            logger.debug(f"Evento {event_type} publicado com ID: {message_id}")
        except Exception as e:
            logger.error(f"Falha ao publicar {event_type}: {e}")


# Instância global
event_service = EventService()