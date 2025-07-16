# app/services/user_service.py
from typing import Dict, Any, Optional
from datetime import datetime
import logging
from google.cloud import firestore

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self):
        self.db = firestore.Client()

    async def add_xp(self, user_id: str, amount: int, reason: str = "") -> Dict[str, Any]:
        """
        Adiciona XP ao usuário e retorna os dados atualizados
        """
        try:
            user_ref = self.db.collection("users").document(user_id)
            user_doc = user_ref.get()

            if not user_doc.exists:
                raise ValueError(f"Usuário {user_id} não encontrado")

            user_data = user_doc.to_dict()
            current_xp = user_data.get("profile_xp", 0)
            current_level = user_data.get("profile_level", 1)

            # Calcular novo XP
            new_xp = current_xp + amount

            # Calcular novo nível (100 XP por nível)
            new_level = (new_xp // 100) + 1
            level_changed = new_level > current_level

            # Atualizar usuário
            update_data = {
                "profile_xp": new_xp,
                "profile_level": new_level,
                "updated_at": datetime.utcnow()
            }

            user_ref.update(update_data)

            # Registrar transação de XP
            xp_transaction = {
                "user_id": user_id,
                "amount": amount,
                "reason": reason,
                "old_xp": current_xp,
                "new_xp": new_xp,
                "old_level": current_level,
                "new_level": new_level,
                "level_changed": level_changed,
                "created_at": datetime.utcnow()
            }

            self.db.collection("xp_transactions").add(xp_transaction)

            logger.info(f"XP adicionado: {user_id} +{amount} ({reason})")

            # Retornar dados atualizados
            return {
                "profile_xp": new_xp,
                "profile_level": new_level,
                "xp_earned": amount,
                "level_changed": level_changed
            }

        except Exception as e:
            logger.error(f"Erro ao adicionar XP: {str(e)}")
            raise

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca dados do usuário
        """
        try:
            user_doc = self.db.collection("users").document(user_id).get()

            if user_doc.exists:
                return user_doc.to_dict()
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar usuário: {str(e)}")
            return None

    async def update_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """
        Atualiza dados do usuário
        """
        try:
            user_ref = self.db.collection("users").document(user_id)

            # Adicionar timestamp de atualização
            data["updated_at"] = datetime.utcnow()

            user_ref.update(data)
            logger.info(f"Usuário {user_id} atualizado com sucesso")

            return True

        except Exception as e:
            logger.error(f"Erro ao atualizar usuário: {str(e)}")
            return False