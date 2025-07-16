# Em app/api/deps.py, adicione:

from app.services.user_service import UserService

# Instância singleton do UserService
_user_service = None

def get_user_service() -> UserService:
    """
    Dependency para obter instância do UserService
    """
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service