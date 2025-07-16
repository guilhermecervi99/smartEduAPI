# app/services/event_types.py
from enum import Enum


class EventTypes(str, Enum):
    """Todos os tipos de eventos do sistema"""

    # Usuário
    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_UPDATED = "user.updated"
    USER_PREFERENCES_UPDATED = "user.preferences.updated"

    # Mapeamento
    MAPPING_STARTED = "mapping.started"
    MAPPING_COMPLETED = "mapping.completed"
    MAPPING_TEXT_ANALYZED = "mapping.text.analyzed"
    TRACK_SELECTED = "track.selected"
    SUBAREA_SELECTED = "subarea.selected"

    # Progresso
    PROGRESS_INITIALIZED = "progress.initialized"
    PROGRESS_UPDATED = "progress.updated"
    LESSON_STARTED = "lesson.started"
    LESSON_COMPLETED = "lesson.completed"
    MODULE_COMPLETED = "module.completed"
    LEVEL_COMPLETED = "level.completed"
    STEP_ADVANCED = "step.advanced"
    AREA_CHANGED = "area.changed"
    NAVIGATION_OCCURRED = "navigation.occurred"

    # Avaliações
    ASSESSMENT_STARTED = "assessment.started"
    ASSESSMENT_COMPLETED = "assessment.completed"

    # Projetos
    PROJECT_STARTED = "project.started"
    PROJECT_UPDATED = "project.updated"
    PROJECT_COMPLETED = "project.completed"

    # Gamificação
    XP_EARNED = "xp.earned"
    BADGE_EARNED = "badge.earned"
    LEVEL_UP = "level.up"
    STREAK_UPDATED = "streak.updated"

    # Sessões
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    FOCUS_SESSION_COMPLETED = "focus.session.completed"

    # Feedback
    FEEDBACK_SUBMITTED = "feedback.submitted"
    CONTENT_RATED = "content.rated"

    # LLM/AI
    AI_CONTENT_GENERATED = "ai.content.generated"
    AI_ASSESSMENT_GENERATED = "ai.assessment.generated"
    AI_PATH_GENERATED = "ai.path.generated"
    AI_TUTOR_INTERACTION = "ai.tutor.interaction"