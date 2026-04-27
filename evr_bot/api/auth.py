from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import bcrypt
from datetime import datetime, timedelta, timezone

from evr_bot.database import get_db
from evr_bot.models import User, UserBotState, SubscriptionStatus, BotStateEnum
from evr_bot.api.schemas import RegisterRequest, LoginRequest, TokenResponse, MessageResponse
from evr_bot.api.deps import create_token, get_current_user

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

@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    """Yeni kullanici kaydi."""
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayitli.")

    user = User(
        email=req.email,
        password_hash=pwd_ctx.hash(req.password),
        subscription_status=SubscriptionStatus.INACTIVE,
    )
    db.add(user)
    db.flush()

    # BotState olustur
    bot_state = UserBotState(user_id=user.id, current_state=BotStateEnum.NORMAL)
    db.add(bot_state)
    
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Kayit sirasinda hata olustu.")

    token = create_token(user.id, user.email)
    return TokenResponse(access_token=token, email=user.email)

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """Kullanici girisi."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not pwd_ctx.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Gecersiz e-posta veya sifre.")

    token = create_token(user.id, user.email)
    return TokenResponse(access_token=token, email=user.email)

@router.post("/subscription/activate", response_model=MessageResponse)
def activate_subscription(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aboneligi aktif et (demo: aninda aktif, uretimde odeme entegrasyonu eklenecek)."""
    if user.is_lifetime_member:
        return MessageResponse(message="Bu hesap omur boyu uyelikte; ek aktivasyon gerekmiyor.")

    import os
    if os.getenv("ENVIRONMENT", "production") == "production":
        raise HTTPException(status_code=403, detail="Abonelik endpoint'i uretim asamasinda devre disidir.")

    user.subscription_status = SubscriptionStatus.ACTIVE
    user.subscription_expires = (datetime.now(timezone.utc) + timedelta(days=30)).replace(tzinfo=None)
    db.commit()
    return MessageResponse(message="Abonelik 30 gun sureyle aktif edildi.")


@router.post("/subscription/deactivate", response_model=MessageResponse)
def deactivate_subscription(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aboneligi iptal et."""
    if user.is_lifetime_member:
        raise HTTPException(status_code=403, detail="Omur boyu uyelik devre disi birakilamaz.")

    user.subscription_status = SubscriptionStatus.INACTIVE
    db.commit()
    return MessageResponse(message="Abonelik iptal edildi.")
