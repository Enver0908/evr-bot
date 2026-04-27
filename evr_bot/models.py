"""
EVR Trading Bot — Veritabanı Modelleri
=======================================
SQLAlchemy ORM ile User, BotState ve TradeLog tanımları.
PostgreSQL uyumlu.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    Enum as SAEnum, ForeignKey, Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════════════════
# ENUM TANIMLARI
# ═══════════════════════════════════════════════════════════════════════════════

class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"


class BotStateEnum(int, enum.Enum):
    NORMAL = 1   # Fiyat > MA_600
    SHIELD = 2   # Nakit modu (Fiyat < MA_600)
    BLIND = 3    # Körleşme / Dipten uyanış


class TradeAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    SHIELD_SELL = "SHIELD_SELL"      # MA_600 kırılımında tüm BTC satışı
    STATE_CHANGE = "STATE_CHANGE"    # Durum değişikliği logu

class ExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════════
# KULLANICI
# ═══════════════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    # Abonelik
    subscription_status = Column(
        SAEnum(SubscriptionStatus, name="subscription_status_enum",
               create_constraint=True, native_enum=False),
        default=SubscriptionStatus.INACTIVE,
        nullable=False,
    )
    subscription_expires = Column(DateTime, nullable=True)
    is_lifetime_member = Column(Boolean, default=False, nullable=False)

    # Bybit API (şifrelenmiş)
    api_key_encrypted = Column(Text, nullable=True)
    api_secret_encrypted = Column(Text, nullable=True)

    # Zaman damgaları
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # İlişkiler
    bot_state = relationship(
        "UserBotState", uselist=False, back_populates="user",
        cascade="all, delete-orphan",
    )
    trade_logs = relationship(
        "TradeLog", back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        membership = "lifetime" if self.is_lifetime_member else self.subscription_status.value
        return f"<User {self.email} [{membership}]>"


# ═══════════════════════════════════════════════════════════════════════════════
# BOT DURUMU (Her kullanıcı için bağımsız)
# ═══════════════════════════════════════════════════════════════════════════════

class UserBotState(Base):
    __tablename__ = "bot_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Durum makinesi
    current_state = Column(
        SAEnum(BotStateEnum, name="bot_state_enum",
               create_constraint=True, native_enum=False),
        default=BotStateEnum.NORMAL,
        nullable=False,
    )

    # Hafıza değişkenleri
    eski_zirve_fiyati = Column(Float, default=0.0)          # ATH (All-Time High bu süreçte)
    breakdown_reference_price = Column(Float, default=0.0)   # MA_600 kırılım fiyatı

    # Son çalışma bilgisi
    last_evr_value = Column(Float, default=0.0)
    last_btc_price = Column(Float, default=0.0)
    last_ma600 = Column(Float, default=0.0)
    last_run_at = Column(DateTime, nullable=True)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # İlişki
    user = relationship("User", back_populates="bot_state")

    def __repr__(self):
        return f"<BotState user={self.user_id} state={self.current_state.name}>"


# ═══════════════════════════════════════════════════════════════════════════════
# İŞLEM KAYDI
# ═══════════════════════════════════════════════════════════════════════════════

class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    action = Column(
        SAEnum(TradeAction, name="trade_action_enum",
               create_constraint=True, native_enum=False),
        nullable=False,
    )
    execution_status = Column(
        SAEnum(ExecutionStatus, name="execution_status_enum",
               create_constraint=True, native_enum=False),
        default=ExecutionStatus.UNKNOWN,
        nullable=False,
    )

    # İşlem detayları
    symbol = Column(String(20), default="BTC/USDT")
    side = Column(String(10), nullable=True)       # "buy" / "sell"
    amount_btc = Column(Float, nullable=True)       # BTC miktarı
    amount_usdt = Column(Float, nullable=True)      # USDT karşılığı
    price = Column(Float, nullable=True)            # İşlem fiyatı
    order_id = Column(String(100), nullable=True)   # Borsa order ID
    client_order_id = Column(String(100), nullable=True) # İstemci (Yerel) Order ID
    
    # Durum bilgisi (o anki)
    evr_value = Column(Float, nullable=True)
    bot_state_at = Column(Integer, nullable=True)

    # Not
    note = Column(Text, nullable=True)

    # İlişki
    user = relationship("User", back_populates="trade_logs")

    def __repr__(self):
        return f"<Trade {self.action.value} {self.amount_btc} BTC @ {self.price}>"


# ═══════════════════════════════════════════════════════════════════════════════
# PIYASA VERISI (Market Data)
# ═══════════════════════════════════════════════════════════════════════════════

class MarketData(Base):
    """Günlük BTC fiyatı, EVR değerleri ve MA600 hesaplamalarının tutulduğu tablo."""
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_str = Column(String(10), unique=True, nullable=False, index=True) # YYYY-MM-DD
    btc_price = Column(Float, nullable=False)
    evr_raw = Column(Integer, nullable=True)        # 0-100 arasi ham puan
    evr_index = Column(Float, nullable=True)        # 0.0-10.0 arasi indeks puani
    ma_600 = Column(Float, nullable=True)           # Hesaplanan MA600 degeri
    
    # Zaman damgası
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<MarketData {self.date_str} BTC: {self.btc_price} EVR: {self.evr_raw}>"
