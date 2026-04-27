from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from evr_bot.database import get_db
from evr_bot.models import User
from evr_bot.api.schemas import ApiKeyRequest, MessageResponse
from evr_bot.api.deps import get_current_user
from evr_bot.crypto_utils import encrypt

router = APIRouter()

@router.post("/api-keys", response_model=MessageResponse)
def save_api_keys(
    req: ApiKeyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bybit API anahtarlarini sifreli olarak kaydet."""
    user.api_key_encrypted = encrypt(req.api_key)
    user.api_secret_encrypted = encrypt(req.api_secret)
    db.commit()
    return MessageResponse(message="API anahtarlari sifreli olarak kaydedildi.")


@router.delete("/api-keys", response_model=MessageResponse)
def delete_api_keys(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kayitli API anahtarlarini sil."""
    user.api_key_encrypted = None
    user.api_secret_encrypted = None
    db.commit()
    return MessageResponse(message="API anahtarlari silindi.")
