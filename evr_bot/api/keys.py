from fastapi import APIRouter, Depends, HTTPException
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
    import logging
    _logger = logging.getLogger("evr_bot.api.keys")

    from evr_bot.market_data import create_exchange
    try:
        exc = create_exchange(req.api_key, req.api_secret)
        exc.fetch_balance()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"API Anahtari gecersiz veya erisim reddedildi: {str(e)[:100]}")

    # ── Trade permission metadata kontrolü ──
    trade_permission_verified = False
    trade_permission_warning = ""
    try:
        # Bybit v5 key info endpoint — hangi yetkilerin aktif olduğunu döner
        key_info = exc.private_get_user_query_api()
        permissions = (key_info.get("result") or {}).get("permissions", {})
        spot_perms = permissions.get("Spot", [])
        if "SpotTrade" in spot_perms:
            trade_permission_verified = True
        else:
            trade_permission_warning = (
                " UYARI: Bu API anahtarinda Spot Trade izni tespit edilemedi. "
                "Bybit'te key olusturulurken 'Spot Trade' yetkisini aktif ettiginizden emin olun, "
                "aksi halde bot islem yapamaz."
            )
            _logger.warning(
                "User %s: API key kaydedildi ama SpotTrade izni bulunamadi. Permissions: %s",
                user.email, permissions,
            )
    except Exception as perm_exc:
        # Permission sorgusu başarısız olursa key'i yine kaydet ama uyar
        trade_permission_warning = (
            " Trade izni dogrulanamadi (Bybit API yanit vermedi). "
            "Trade yetkisi ilk bot isleminde dogrulanacaktir."
        )
        _logger.warning(
            "User %s: Trade permission kontrolu basarisiz: %s", user.email, perm_exc,
        )

    user.api_key_encrypted = encrypt(req.api_key)
    user.api_secret_encrypted = encrypt(req.api_secret)
    db.commit()

    if trade_permission_verified:
        msg = "API anahtarlari dogrulandi (bakiye okuma + trade izni) ve kaydedildi."
    else:
        msg = f"API anahtarlari kaydedildi (bakiye okuma dogrulandi).{trade_permission_warning}"

    return MessageResponse(message=msg)


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
