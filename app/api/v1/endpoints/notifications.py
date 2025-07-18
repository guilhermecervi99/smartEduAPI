from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.notifications import NotificationResponse
import time

router = APIRouter()


@router.get("/", response_model=List[NotificationResponse])
async def get_notifications(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        unread_only: bool = Query(False),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Obtém notificações do usuário
    """
    query = db.collection("notifications").where("user_id", "==", current_user["id"])

    if unread_only:
        query = query.where("is_read", "==", False)

    query = query.order_by("created_at", direction="DESCENDING")
    query = query.limit(limit).offset(offset)

    notifications = []
    for doc in query.stream():
        notif_data = doc.to_dict()
        notif_data["id"] = doc.id
        notifications.append(NotificationResponse(**notif_data))

    return notifications


@router.post("/mark-as-read")
async def mark_all_as_read(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Marca todas as notificações como lidas
    """
    notifications = db.collection("notifications") \
        .where("user_id", "==", current_user["id"]) \
        .where("is_read", "==", False) \
        .stream()

    batch = db.batch()
    count = 0

    for doc in notifications:
        batch.update(doc.reference, {"is_read": True, "read_at": time.time()})
        count += 1

    if count > 0:
        batch.commit()

    return {"message": f"{count} notificações marcadas como lidas"}


@router.post("/{notification_id}/mark-as-read")
async def mark_as_read(
        notification_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Marca uma notificação específica como lida
    """
    notif_ref = db.collection("notifications").document(notification_id)
    notif_doc = notif_ref.get()

    if not notif_doc.exists:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")

    notif_data = notif_doc.to_dict()
    if notif_data.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    notif_ref.update({"is_read": True, "read_at": time.time()})

    return {"message": "Notificação marcada como lida"}


@router.delete("/{notification_id}")
async def delete_notification(
        notification_id: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
) -> Any:
    """
    Remove uma notificação
    """
    notif_ref = db.collection("notifications").document(notification_id)
    notif_doc = notif_ref.get()

    if not notif_doc.exists:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")

    notif_data = notif_doc.to_dict()
    if notif_data.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    notif_ref.delete()

    return {"message": "Notificação removida"}


# Função auxiliar para criar notificações
def create_notification(db, user_id: str, notification_type: str, message: str, link: str = None):
    """
    Cria uma nova notificação para o usuário
    """
    notification_data = {
        "user_id": user_id,
        "type": notification_type,
        "message": message,
        "link": link,
        "is_read": False,
        "created_at": time.time()
    }

    db.collection("notifications").add(notification_data)