# app/core/security.py
from datetime import datetime, timedelta
from typing import Optional, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.config import get_settings
from app.database import get_db
from app.schemas.user import TokenPayload

settings = get_settings()

# Configuração do contexto de criptografia
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_str}/auth/login",
    auto_error=False  # Permite endpoints opcionalmente autenticados
)


def create_password_hash(password: str) -> str:
    """
    Cria hash de senha
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica se a senha corresponde ao hash
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
        subject: Union[str, int],
        expires_delta: Optional[timedelta] = None
) -> str:
    """
    Cria token JWT de acesso
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "access"
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm
    )

    return encoded_jwt


def decode_token(token: str) -> Optional[TokenPayload]:
    """
    Decodifica e valida token JWT
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        token_data = TokenPayload(**payload)
        return token_data
    except JWTError:
        return None


async def get_current_user_id(
        token: Optional[str] = Depends(oauth2_scheme)
) -> Optional[str]:
    """
    Obtém o ID do usuário atual a partir do token (opcional)
    """
    if not token:
        return None

    token_data = decode_token(token)
    if not token_data:
        return None

    return token_data.sub


async def get_current_user_id_required(
        token: str = Depends(oauth2_scheme)
) -> str:
    """
    Obtém o ID do usuário atual a partir do token (obrigatório)
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data.sub


async def get_current_user(
        db=Depends(get_db),
        user_id: str = Depends(get_current_user_id_required)
) -> dict:
    """
    Obtém os dados completos do usuário atual
    """
    user_doc = db.collection("users").document(user_id).get()

    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user_data = user_doc.to_dict()
    user_data["id"] = user_id

    return user_data


# Função auxiliar para autenticação opcional
async def get_optional_current_user(
        db=Depends(get_db),
        user_id: Optional[str] = Depends(get_current_user_id)
) -> Optional[dict]:
    """
    Obtém os dados do usuário atual se autenticado, None caso contrário
    """
    if not user_id:
        return None

    user_doc = db.collection("users").document(user_id).get()

    if not user_doc.exists:
        return None

    user_data = user_doc.to_dict()
    user_data["id"] = user_id

    return user_data