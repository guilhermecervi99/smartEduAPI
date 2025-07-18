from typing import Optional
from pydantic import BaseModel

class NotificationResponse(BaseModel):
    id: str
    type: str
    message: str
    link: Optional[str] = None
    is_read: bool
    created_at: float
    read_at: Optional[float] = None