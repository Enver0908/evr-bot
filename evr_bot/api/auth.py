from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
import bcrypt

from evr_bot.database import get_db
from evr_bot.models import User, SubscriptionStatus
from evr_bot.api.schemas import RegisterRequest, LoginRequest, TokenResponse, MessageResponse
from evr_bot.api.deps import create_token
from evr_bot.config import LIFETIME_MEMBER_EMAILS

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

class PwdCtx:
    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
    def verify(self, password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False

pwd_ctx = PwdCtx()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def sync_lifetime_membership(user: User) -> bool:
    if normalize_email(user.email) not in LIFETIME_MEMBER_EMAILS:
        return False

    changed = False
    if not user.is_lifetime_member:
        user.is_lifetime_member = True
        changed = True
    if user.subscription_status != SubscriptionStatus.ACTIVE:
        user.subscription_status = SubscriptionStatus.ACTIVE
        changed = True
    return changed


def is_authorized_login(email: str) -> bool:
    return normalize_email(email) in LIFETIME_MEMBER_EMAILS

@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    """Public kayit kapali; kullanicilar yalnizca admin tarafindan acilir."""
    raise HTTPException(status_code=403, detail="Kayit kapali. Kullanici hesabi admin tarafindan olusturulur.")

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """Kullanici girisi."""
    normalized_email = normalize_email(req.email)
    if not is_authorized_login(normalized_email):
        raise HTTPException(status_code=401, detail="Gecersiz e-posta veya sifre.")

    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if not user or not pwd_ctx.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Gecersiz e-posta veya sifre.")

    if sync_lifetime_membership(user):
        db.commit()
        db.refresh(user)

    token = create_token(user.id, user.email)
    return TokenResponse(access_token=token, email=user.email)

@router.post("/subscription/activate", response_model=MessageResponse)
def activate_subscription():
    """Abonelik akisi kapali; kullanici yetkisi admin tarafindan verilir."""
    raise HTTPException(status_code=403, detail="Abonelik akisi kapali. Yetki admin tarafindan verilir.")


@router.post("/subscription/deactivate", response_model=MessageResponse)
def deactivate_subscription():
    """Abonelik akisi kapali; kullanici yetkisi admin tarafindan verilir."""
    raise HTTPException(status_code=403, detail="Abonelik akisi kapali. Yetki admin tarafindan verilir.")
