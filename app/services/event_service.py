import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from google.cloud import pubsub_v1
import logging
from enum import Enum

from app.database import get_db

logger = logging.getLogger(__name__)


class EventTypes(Enum):
    """Tipos de eventos do sistema"""
    # Progresso
    LESSON_COMPLETED = "lesson_completed"
    MODULE_COMPLETED = "module_completed"
    LEVEL_COMPLETED = "level_completed"

    # Gamificação
    XP_EARNED = "xp_earned"
    LEVEL_UP = "level_up"
    BADGE_EARNED = "badge_earned"

    # Projetos
    PROJECT_STARTED = "project_started"
    PROJECT_COMPLETED = "project_completed"

    # Comunidade
    TEAM_JOINED = "team_joined"
    TEAM_CREATED = "team_created"
    MENTORSHIP_REQUESTED = "mentorship_requested"
    MENTORSHIP_ACCEPTED = "mentorship_accepted"

    # Sistema
    USER_UPDATED = "user_updated"
    USER_PREFERENCES_UPDATED = "user_preferences_updated"
    ASSESSMENT_COMPLETED = "assessment_completed"
    STUDY_SESSION_COMPLETED = "study_session_completed"

    # Área/Subárea
    AREA_SELECTED = "area_selected"
    SUBAREA_SELECTED = "subarea_selected"

    # IA
    AI_CONTENT_GENERATED = "ai_content_generated"
    AI_ASSESSMENT_GENERATED = "ai_assessment_generated"
    AI_PATH_GENERATED = "ai_path_generated"

    # Feedback
    FEEDBACK_SUBMITTED = "feedback_submitted"

    # Notificações
    NOTIFICATION_CREATED = "notification_created"


class EventService:
    """Serviço unificado para publicar e processar eventos"""

    def __init__(self):
        self.project_id = os.getenv("FIREBASE_PROJECT_ID", "axiomatic-robot-417213")
        self.topic_name = "app-events"

        # Handlers para processar eventos localmente
        self.handlers = {
            EventTypes.LESSON_COMPLETED: self._handle_lesson_completed,
            EventTypes.MODULE_COMPLETED: self._handle_module_completed,
            EventTypes.LEVEL_COMPLETED: self._handle_level_completed,
            EventTypes.XP_EARNED: self._handle_xp_earned,
            EventTypes.LEVEL_UP: self._handle_level_up,
            EventTypes.BADGE_EARNED: self._handle_badge_earned,
            EventTypes.PROJECT_COMPLETED: self._handle_project_completed,
            EventTypes.TEAM_JOINED: self._handle_team_joined,
            EventTypes.MENTORSHIP_ACCEPTED: self._handle_mentorship_accepted,
        }

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
        Publica evento de forma assíncrona e processa localmente
        """
        # Processar evento localmente primeiro (notificações, etc)
        try:
            handler = self.handlers.get(event_type)
            if handler:
                await handler(user_id, data)
        except Exception as e:
            logger.error(f"Erro ao processar evento {event_type.value} localmente: {e}")

        # Publicar no Pub/Sub se disponível
        if not self.publisher:
            logger.warning("Publisher não inicializado, pulando publicação no Pub/Sub")
            return None

        try:
            # Criar evento com estrutura padrão
            event = {
                "event_id": f"{event_type.value}_{user_id}_{int(datetime.utcnow().timestamp() * 1000)}",
                "event_type": event_type.value,
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
            logger.info(f"Publicando evento: {event_type.value} para usuário: {user_id}")

            # Serializar
            message_bytes = json.dumps(event).encode("utf-8")

            # Publicar
            future = self.publisher.publish(
                self.topic_path,
                message_bytes,
                event_type=event_type.value,
                user_id=user_id
            )

            # Log assíncrono
            asyncio.create_task(self._log_publish_result(future, event_type))

            return event.get("event_id")

        except Exception as e:
            logger.error(f"Erro ao publicar evento {event_type.value}: {e}")
            return None

    async def _log_publish_result(self, future, event_type):
        """Log do resultado da publicação"""
        try:
            message_id = await asyncio.get_event_loop().run_in_executor(
                None, future.result, 5.0
            )
            logger.debug(f"Evento {event_type.value} publicado com ID: {message_id}")
        except Exception as e:
            logger.error(f"Falha ao publicar {event_type.value}: {e}")

    # Handlers para processar eventos e criar notificações
    async def _handle_lesson_completed(self, user_id: str, data: Dict[str, Any]):
        """Processa conclusão de lição"""
        try:
            db = next(get_db())
            message = f"Parabéns! Você completou a lição '{data.get('lesson_title', 'Lição')}'!"
            self._create_notification(db, user_id, "success", message, "/learning")
        except Exception as e:
            logger.error(f"Erro ao processar lesson_completed: {e}")

    async def _handle_module_completed(self, user_id: str, data: Dict[str, Any]):
        """Processa conclusão de módulo"""
        try:
            db = next(get_db())
            message = f"Módulo '{data.get('module_title', 'Módulo')}' concluído! Continue assim!"
            self._create_notification(db, user_id, "success", message, "/learning")
        except Exception as e:
            logger.error(f"Erro ao processar module_completed: {e}")

    async def _handle_level_completed(self, user_id: str, data: Dict[str, Any]):
        """Processa conclusão de nível"""
        try:
            db = next(get_db())
            level_name = data.get('level_name', '')
            message = f"Incrível! Você completou o nível {level_name}!"
            self._create_notification(db, user_id, "award", message, "/achievements")
        except Exception as e:
            logger.error(f"Erro ao processar level_completed: {e}")

    async def _handle_xp_earned(self, user_id: str, data: Dict[str, Any]):
        """Processa ganho de XP - sem notificação para evitar spam"""
        pass

    async def _handle_level_up(self, user_id: str, data: Dict[str, Any]):
        """Processa subida de nível"""
        try:
            db = next(get_db())
            new_level = data.get('new_level', 0)
            message = f"Level UP! Você alcançou o nível {new_level}! 🎉"
            self._create_notification(db, user_id, "award", message, "/profile")
        except Exception as e:
            logger.error(f"Erro ao processar level_up: {e}")

    async def _handle_badge_earned(self, user_id: str, data: Dict[str, Any]):
        """Processa nova conquista"""
        try:
            db = next(get_db())
            badge_name = data.get('badge_name', 'Nova Conquista')
            message = f"Nova conquista desbloqueada: {badge_name}! 🏆"
            self._create_notification(db, user_id, "award", message, "/achievements")
        except Exception as e:
            logger.error(f"Erro ao processar badge_earned: {e}")

    async def _handle_project_completed(self, user_id: str, data: Dict[str, Any]):
        """Processa conclusão de projeto"""
        try:
            db = next(get_db())
            project_title = data.get('project_title', 'Projeto')
            xp = data.get('xp_earned', 0)
            message = f"Projeto '{project_title}' concluído! +{xp} XP ganhos!"
            self._create_notification(db, user_id, "success", message, "/projects")
        except Exception as e:
            logger.error(f"Erro ao processar project_completed: {e}")

    async def _handle_team_joined(self, user_id: str, data: Dict[str, Any]):
        """Processa entrada em time"""
        try:
            db = next(get_db())
            team_name = data.get('team_name', 'Time')
            message = f"Bem-vindo ao time '{team_name}'! 👥"
            self._create_notification(db, user_id, "info", message, "/community")
        except Exception as e:
            logger.error(f"Erro ao processar team_joined: {e}")

    async def _handle_mentorship_accepted(self, user_id: str, data: Dict[str, Any]):
        """Processa aceitação de mentoria"""
        try:
            db = next(get_db())
            mentor_name = data.get('mentor_name', 'Mentor')
            message = f"{mentor_name} aceitou seu pedido de mentoria! 🎓"
            self._create_notification(db, user_id, "success", message, "/community")
        except Exception as e:
            logger.error(f"Erro ao processar mentorship_accepted: {e}")

    def _create_notification(self, db, user_id: str, notification_type: str, message: str, link: str = None):
        """
        Cria uma nova notificação no Firestore
        """
        import time

        notification_data = {
            "user_id": user_id,
            "type": notification_type,
            "message": message,
            "link": link,
            "is_read": False,
            "created_at": time.time()
        }

        try:
            db.collection("notifications").add(notification_data)
            logger.debug(f"Notificação criada para usuário {user_id}: {message}")
        except Exception as e:
            logger.error(f"Erro ao criar notificação: {e}")

    def _log_event(self, event_type: EventTypes, user_id: str, data: Dict[str, Any]):
        """Registra evento para analytics"""
        # TODO: Implementar logging estruturado para analytics
        # Por enquanto, apenas log básico
        logger.info(f"Event logged: {event_type.value} | User: {user_id} | Data: {json.dumps(data)[:100]}")


# Instância singleton
event_service = EventService()