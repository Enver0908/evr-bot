"""
EVR Trading Bot — Kriptografi Yardımcıları
============================================
Fernet simetrik şifreleme ile API anahtarlarını güvenli saklama.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

from evr_bot.config import BASE_DIR

# Docker volume (/app/data) içinde kalıcı, container rebuild'de kaybolmaz
_DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
_KEY_FILE = _DATA_DIR / ".fernet_key"
_IS_PRODUCTION = os.getenv("ENVIRONMENT", "").lower() == "production"


def _load_or_create_key() -> bytes:
    """Fernet key: ENV → dosya → (sadece dev'de) üret."""
    # 1. Env'den oku (prod'da zorunlu)
    env_key = os.getenv("EVR_FERNET_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    # 2. Prod'da env yoksa dur
    if _IS_PRODUCTION:
        raise RuntimeError(
            "KRİTİK: Production ortamında EVR_FERNET_KEY env değişkeni zorunludur! "
            "Fernet key'i .env dosyasına ekleyin: EVR_FERNET_KEY=<your-base64-key>"
        )

    # 3. Dev — dosyadan oku veya üret (file-lock ile)
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    
    from filelock import FileLock
    lock = FileLock(str(_KEY_FILE) + ".lock", timeout=10)
    with lock:
        # Double-check
        if _KEY_FILE.exists():
            return _KEY_FILE.read_bytes().strip()
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except OSError:
            pass
        return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    """Düz metni şifrele → base64 string döndür."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Şifreli metni çöz → düz metin döndür."""
    return _fernet.decrypt(ciphertext.encode()).decode()
