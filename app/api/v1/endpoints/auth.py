# app/api/v1/endpoints/auth.py
from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
import time

from app.core.security import (
    create_access_token,
    verify_password,
    create_password_hash,
    get_current_user
)
from app.config import get_settings
from app.database import get_db, Collections
from app.schemas.user import Token, UserCreate, UserBase
from app.utils.gamification import initialize_user_gamification

router = APIRouter()
settings = get_settings()


@router.post("/register", response_model=Token)
async def register(
        user_data: UserCreate,
        db=Depends(get_db)
) -> Any:
    """
    Registra um novo usuário

    - Se email fornecido, verifica duplicação
    - Cria ID único se não fornecido
    - Inicializa gamificação (XP, badges)
    - Retorna token de acesso
    """
    # Verificar se email já existe (se fornecido)
    if user_data.email:
        # Buscar por email existente
        existing_users = db.collection(Collections.USERS).where(
            "email", "==", user_data.email
        ).limit(1).get()

        if list(existing_users):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

    # Criar ID único para o usuário
    if user_data.email:
        # Usar parte do email como base para o ID
        user_id = user_data.email.split("@")[0].lower()
        # Verificar se ID já existe
        if db.collection(Collections.USERS).document(user_id).get().exists:
            # Adicionar timestamp se ID já existe
            user_id = f"{user_id}_{int(time.time())}"
    else:
        # Gerar ID baseado em timestamp
        user_id = f"user_{int(time.time())}"

    # Preparar dados do usuário
    user_dict = {
        "email": user_data.email,
        "age": user_data.age,
        "learning_style": user_data.learning_style,
        "created_at": time.time(),
        "last_login": time.time()
    }

    # Adicionar senha hash se fornecida
    if user_data.password:
        user_dict["hashed_password"] = create_password_hash(user_data.password)

    # Inicializar gamificação
    gamification_data = initialize_user_gamification()
    user_dict.update(gamification_data)

    # Criar usuário no Firestore
    try:
        db.collection(Collections.USERS).document(user_id).set(user_dict)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}"
        )

    # Criar token de acesso
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        subject=user_id,
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user_id": user_id  # Adicionar o user_id na resposta
    }


@router.post("/login", response_model=Token)
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db=Depends(get_db)
) -> Any:
    """
    Login do usuário

    - Username pode ser email ou user_id
    - Se password não fornecido, permite login sem senha
    - Atualiza last_login
    - Retorna token de acesso
    """
    username = form_data.username
    password = form_data.password

    # Tentar encontrar usuário por ID primeiro
    user_doc = db.collection(Collections.USERS).document(username).get()

    if not user_doc.exists and "@" in username:
        # Se não encontrou por ID e parece ser email, buscar por email
        users = db.collection(Collections.USERS).where(
            "email", "==", username
        ).limit(1).get()

        user_list = list(users)
        if user_list:
            user_doc = user_list[0]
            username = user_doc.id  # Usar o ID real do documento
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
    elif not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    user_data = user_doc.to_dict() if hasattr(user_doc, 'to_dict') else user_doc._data

    # Verificar senha se o usuário tem senha e foi fornecida
    if user_data.get("hashed_password"):
        if not password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password required for this account"
            )

        if not verify_password(password, user_data["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )

    # Atualizar último login
    user_id = user_doc.id if hasattr(user_doc, 'id') else username
    db.collection(Collections.USERS).document(user_id).update({
        "last_login": time.time()
    })

    # Criar token de acesso
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        subject=user_id,
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user_id": user_id  # Adicionar o user_id na resposta
    }


@router.get("/me", response_model=UserBase)
async def get_current_user_info(
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Obtém informações do usuário atual autenticado
    """
    return UserBase(
        id=current_user["id"],
        email=current_user.get("email"),
        age=current_user.get("age", 14),
        learning_style=current_user.get("learning_style", "didático"),
        current_track=current_user.get("current_track"),
        created_at=current_user.get("created_at")
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
        current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Renova o token de acesso
    """
    # Criar novo token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        subject=current_user["id"],
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60
    }


@router.post("/logout")
async def logout(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Logout do usuário (registra a ação)

    Nota: Com JWT, o logout real acontece no cliente removendo o token
    """
    # Registrar logout (opcional)
    db.collection(Collections.USERS).document(current_user["id"]).update({
        "last_logout": time.time()
    })

    return {"message": "Successfully logged out"}