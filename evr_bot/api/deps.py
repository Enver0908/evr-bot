from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
import jwt

from evr_bot.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, SECRET_KEY
from evr_bot.database import get_db
from evr_bot.models import SubscriptionStatus, User

security = HTTPBearer()


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token suresi dolmus.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Gecersiz token.")


def get_current_user(
    token_data: dict = Depends(verify_token),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.id == int(token_data["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanici bulunamadi.")
    return user


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if user.is_lifetime_member:
        return user

    if user.subscription_status != SubscriptionStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="Aboneliginiz aktif degil.")

    if user.subscription_expires:
        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if user.subscription_expires.replace(tzinfo=None) < now_utc_naive:
            raise HTTPException(status_code=403, detail="Abonelik suresi dolmus.")

    return user
