# app/utils/cache_system.py
from collections import OrderedDict
import time
import hashlib
import json
from http.client import HTTPException
from typing import Any, Optional, Callable
from functools import wraps
import logging

from starlette import status

logger = logging.getLogger(__name__)


class LRUCache:
    """Cache LRU (Least Recently Used) com TTL (Time To Live)."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 86400):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.hit_count = 0
        self.miss_count = 0

    def get(self, key: str) -> Optional[Any]:
        """Recupera um item do cache."""
        if key not in self.cache:
            self.miss_count += 1
            return None

        value, timestamp = self.cache[key]

        # Verificar se expirou
        if time.time() - timestamp > self.ttl_seconds:
            del self.cache[key]
            self.miss_count += 1
            return None

        # Mover para o fim (mais recentemente usado)
        self.cache.move_to_end(key)
        self.hit_count += 1
        return value

    def set(self, key: str, value: Any):
        """Armazena um item no cache."""
        # Se já existe, remover para atualizar posição
        if key in self.cache:
            del self.cache[key]

        # Se atingiu o limite, remover o mais antigo
        elif len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)

        # Adicionar ao final
        self.cache[key] = (value, time.time())

    def clear(self):
        """Limpa todo o cache."""
        self.cache.clear()
        self.hit_count = 0
        self.miss_count = 0

    def get_stats(self) -> dict:
        """Retorna estatísticas do cache."""
        total_requests = self.hit_count + self.miss_count
        hit_rate = self.hit_count / total_requests if total_requests > 0 else 0

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate": hit_rate,
            "ttl_seconds": self.ttl_seconds
        }


# Instâncias globais de cache
llm_cache = LRUCache(max_size=1000, ttl_seconds=86400)  # 24 horas
content_cache = LRUCache(max_size=500, ttl_seconds=3600)  # 1 hora
user_cache = LRUCache(max_size=200, ttl_seconds=300)  # 5 minutos


def generate_cache_key(prefix: str, **kwargs) -> str:
    """
    Gera uma chave de cache única baseada nos parâmetros.

    Args:
        prefix: Prefixo para identificar o tipo de cache
        **kwargs: Parâmetros para gerar a chave

    Returns:
        Chave hash única
    """
    # Remover parâmetros que não devem afetar o cache
    excluded_keys = ['user_id', 'timestamp', 'use_cache']

    # Criar representação estável dos parâmetros
    params = {k: v for k, v in sorted(kwargs.items()) if k not in excluded_keys}
    params_str = json.dumps(params, sort_keys=True)

    # Gerar hash
    combined = f"{prefix}::{params_str}"
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


def cached_llm_response(ttl_seconds: Optional[int] = None):
    """
    Decorador para cachear respostas de LLM.

    Args:
        ttl_seconds: TTL customizado (opcional)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Verificar se o cache está habilitado
            if not kwargs.get('use_cache', True):
                return func(*args, **kwargs)

            # Gerar chave de cache
            cache_key = generate_cache_key(
                f"llm_{func.__name__}",
                args=str(args),
                **kwargs
            )

            # Tentar recuperar do cache
            cached_value = llm_cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value

            # Executar função e cachear resultado
            logger.debug(f"Cache miss for {func.__name__}")
            result = func(*args, **kwargs)

            # Usar TTL customizado se fornecido
            if ttl_seconds:
                original_ttl = llm_cache.ttl_seconds
                llm_cache.ttl_seconds = ttl_seconds
                llm_cache.set(cache_key, result)
                llm_cache.ttl_seconds = original_ttl
            else:
                llm_cache.set(cache_key, result)

            return result

        return wrapper

    return decorator


def cached_content(ttl_seconds: Optional[int] = None):
    """
    Decorador para cachear conteúdo do banco de dados.

    Args:
        ttl_seconds: TTL customizado (opcional)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Gerar chave de cache
            cache_key = generate_cache_key(
                f"content_{func.__name__}",
                args=str(args),
                **kwargs
            )

            # Tentar recuperar do cache
            cached_value = content_cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Content cache hit for {func.__name__}")
                return cached_value

            # Executar função e cachear resultado
            logger.debug(f"Content cache miss for {func.__name__}")
            result = func(*args, **kwargs)

            # Usar TTL customizado se fornecido
            if ttl_seconds:
                original_ttl = content_cache.ttl_seconds
                content_cache.ttl_seconds = ttl_seconds
                content_cache.set(cache_key, result)
                content_cache.ttl_seconds = original_ttl
            else:
                content_cache.set(cache_key, result)

            return result

        return wrapper

    return decorator


def invalidate_cache(cache_type: str = "all", pattern: Optional[str] = None):
    """
    Invalida entradas do cache.

    Args:
        cache_type: Tipo de cache ("llm", "content", "user", "all")
        pattern: Padrão para invalidação seletiva (opcional)
    """
    caches = {
        "llm": llm_cache,
        "content": content_cache,
        "user": user_cache
    }

    if cache_type == "all":
        for cache in caches.values():
            cache.clear()
        logger.info("All caches cleared")
    elif cache_type in caches:
        if pattern:
            # Invalidação seletiva
            cache = caches[cache_type]
            keys_to_remove = [
                key for key in cache.cache.keys()
                if pattern in key
            ]
            for key in keys_to_remove:
                del cache.cache[key]
            logger.info(f"Removed {len(keys_to_remove)} entries from {cache_type} cache")
        else:
            caches[cache_type].clear()
            logger.info(f"{cache_type} cache cleared")


# Endpoint para gerenciamento de cache
from fastapi import APIRouter, Depends
from app.core.security import get_current_user

cache_router = APIRouter()


@cache_router.get("/stats")
async def get_cache_stats(
        current_user: dict = Depends(get_current_user)
) -> Any:
    """Obtém estatísticas de todos os caches."""
    return {
        "llm_cache": llm_cache.get_stats(),
        "content_cache": content_cache.get_stats(),
        "user_cache": user_cache.get_stats()
    }


@cache_router.post("/clear")
async def clear_cache(
        cache_type: str = "all",
        pattern: Optional[str] = None,
        current_user: dict = Depends(get_current_user)
) -> Any:
    """Limpa o cache especificado."""
    # Verificar se é admin (implementar lógica de permissão)
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem limpar o cache"
        )

    invalidate_cache(cache_type, pattern)

    return {
        "message": f"Cache {cache_type} limpo com sucesso",
        "pattern": pattern
    }