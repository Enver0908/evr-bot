from typing import Optional
from pydantic import BaseModel, EmailStr, Field, validator

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Sifre en az 8 karakter olmalidir.')
        if v.isdigit():
            raise ValueError('Sifre sadece rakamlardan olusamaz.')
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str

class ApiKeyRequest(BaseModel):
    api_key: str
    api_secret: str

class MessageResponse(BaseModel):
    message: str

class UserProfile(BaseModel):
    id: int
    email: str
    subscription_status: str
    is_lifetime_member: bool = False
    has_api_keys: bool
    created_at: Optional[str] = None

class BotStateResponse(BaseModel):
    current_state: str
    eski_zirve_fiyati: float
    breakdown_reference_price: float
    last_evr_value: float
    last_btc_price: float
    last_ma600: float
    last_run_at: Optional[str] = None
    shield_pending: bool = False

class TradeLogResponse(BaseModel):
    id: int
    timestamp: str
    action: str
    side: Optional[str] = None
    amount_btc: Optional[float] = None
    amount_usdt: Optional[float] = None
    price: Optional[float] = None
    evr_value: Optional[float] = None
    bot_state_at: Optional[int] = None
    note: Optional[str] = None

class DashboardResponse(BaseModel):
    user: UserProfile
    bot_state: Optional[BotStateResponse] = None
    recent_trades: list[TradeLogResponse]

class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    initial_capital: float = Field(default=10000.0, gt=0, description="Baslangic sermayesi (USD). Sifir veya negatif olamaz.")
