import os
import urllib.parse
from datetime import datetime, timedelta, timezone
import random
import time
from pathlib import Path
import logging

try:
    from curl_cffi import requests
    import capsolver
except ImportError:
    pass

# KMFG Yapilandirma (env'den okunur)

BASE_DIR = Path(__file__).parent
CSV_FILE = BASE_DIR / "evr_data.csv"
LOG_FILE = BASE_DIR / "scraper.log"

# Logger Ayarlari
logger = logging.getLogger("EvrScraper")
logger.setLevel(logging.INFO)
if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(sh)
    logger.addHandler(fh)

def scrape(headless: bool = True, last_n_days: int = 7) -> list[dict] | None:
    EMAIL = os.environ.get("KMFG_EMAIL")
    PASSWORD = os.environ.get("KMFG_PASSWORD")
    CAPSOLVER_KEY = os.environ.get("CAPSOLVER_KEY")
    
    if not all([EMAIL, PASSWORD, CAPSOLVER_KEY]):
        raise EnvironmentError("KRITIK GUVENLIK HATASI: KMFG_EMAIL, KMFG_PASSWORD veya CAPSOLVER_KEY tanimli degil! Lutfen .env dosyanizi kontrol edin.")

    logger.info("=" * 60)
    logger.info("EVR Scraper baslatiliyor (Gizli API - %d gunluk)...", last_n_days)
    
    # 1. CapSolver
    token = None
    import capsolver
    capsolver.api_key = CAPSOLVER_KEY
    for attempt in range(1, 4):
        try:
            logger.info("CapSolver bypass token aliniyor (Deneme %d/3)...", attempt)
            solution = capsolver.solve({
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": "https://kmquant.com/panel/panel.php",
                "websiteKey": "0x4AAAAAAA0dupD6YNAnT2to"
            })
            token = solution.get("token")
            if token:
                logger.info("Token basariyla alindi!")
                break
            else:
                logger.warning("CapSolver token dondurmedi, tekrar deneniyor...")
        except Exception as e:
            logger.error("CapSolver ag hatasi (Deneme %d): %s", attempt, e)
            if attempt == 3:
                return None
            time.sleep(3)
            
    if not token:
        logger.error("3 denemede de Turnstile tokeni alinamadi.")
        return None

    # 2. Login via curl_cffi
    try:
        logger.info("KMFG sistemine Chrome110 kimligiyle giris yapiliyor...")
        session = requests.Session(impersonate="chrome110")

        # Once login sayfasini GET et: session cookie kur
        r_init = session.get("https://kmquant.com/panel/panel.php", timeout=30)
        logger.info("Login sayfasi GET edildi. Status: %s | Cookies: %s", r_init.status_code, list(session.cookies.keys()))

        login_resp = session.post(
            "https://kmquant.com/panel/panel.php",
            data={
                "email": EMAIL,
                "password": PASSWORD,
                "cf-turnstile-response": token,
                "g-recaptcha-response": token,
                "login": ""
            },
            allow_redirects=True,
            timeout=30
        )
        logger.info("Login POST tamamlandi. Final URL: %s | Status: %s | Cookies: %s",
                    login_resp.url, login_resp.status_code, list(session.cookies.keys()))

        # Login basarisizsa (login_token cookie yoksa) erken cik
        if "login_token" not in session.cookies:
            logger.error("Login basarisiz: login_token cookie set edilmedi. Cookies: %s", list(session.cookies.keys()))
            logger.error("Login response preview: %s", login_resp.text[:500].replace("\n", " "))
            return None
        logger.info("Login basarili! login_token cookie alindi.")

        # 3. Get JWT Token
        logger.info("KMFG Grafik paneline erisim saglaniyor (Yetki Tokeni icin)...")
        r_target = session.get("https://kmquant.com/app/btc.php?opt=KMFG", timeout=30)
        logger.info("btc.php GET edildi. Status: %s | URL: %s", r_target.status_code, r_target.url)
        
        import re
        # Birden fazla pattern dene (KMQuant sayfa yapısı değişmiş olabilir)
        jwt_patterns = [
            r"jwtToken\s*=\s*['\"]([^'\"]+)['\"]",
            r"jwt_token\s*=\s*['\"]([^'\"]+)['\"]",
            r"token\s*=\s*['\"]([^'\"]+)['\"]",
            r"Authorization['\"]?\s*:\s*['\"]Bearer ([^'\"]+)['\"]",
            r"Bearer ([A-Za-z0-9\-_\.]+)",
            r"['\"]token['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        ]
        kmfg_token = None
        for pattern in jwt_patterns:
            m = re.search(pattern, r_target.text)
            if m:
                kmfg_token = m.group(1)
                logger.info("JWT Token bulundu (pattern: %s)", pattern[:40])
                break
        if not kmfg_token:
            # Debug: sayfa içeriğinin ilk 2000 karakterini logla
            preview = r_target.text[:2000].replace("\n", " ").replace("\r", "")
            logger.error("JWT Token bulunamadi. HTTP status: %s", r_target.status_code)
            logger.error("Sayfa preview (ilk 2000 kar): %s", preview)
            return None
        

        # 4. Fetch JSON Data directly
        logger.info("Dogrudan KMFG veritabanindan Json verisi cekiliyor...")
        r_api = session.get(
            f"https://data.kmquant.com/data?wallet=&func=KMFG&email={EMAIL}",
            headers={
                "Authorization": "Bearer " + kmfg_token,
                "Origin": "https://kmquant.com",
                "Referer": "https://kmquant.com/app/btc.php?opt=KMFG"
            },
            timeout=30
        )
        
        json_data = r_api.json()
        points = []
        
        # Bulletproof parser for nested array variations
        if isinstance(json_data, list):
            for item in json_data:
                if isinstance(item, dict) and "data" in item:
                    candidate = item["data"]
                    if isinstance(candidate, dict):
                        points = candidate.get("kmfg", candidate.get("b", []))
                    elif isinstance(candidate, list):
                        points = candidate
                    break
        elif isinstance(json_data, dict):
            pts = json_data.get("data", [])
            if isinstance(pts, dict):
                points = pts.get("kmfg", pts.get("b", []))
            elif isinstance(pts, list):
                points = pts
                
        if not points:
            logger.error("Veritabanindan rakam donmedi. Donen yapi: %s", type(json_data))
            return None
            
        logger.info("Toplam %d adet veri dondu. %d gunluk filtre uygulaniyor...", len(points), last_n_days)
        if len(points) > 0:
            logger.info("Ornek ilk veri: %s", points[0])
            logger.info("Ornek son veri: %s", points[-1])
        
        # 5. Format records
        records = []
        # 14 günlük tam tarama için timezone bagimsiz date() kullanilacak
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=last_n_days)).date()
        
        for pt in points:
            try:
                # pt could be list [ts, val] or dict {"time": ts, "value": val} or {"tarih": "YYYY-MM-DD", "kmfg": val}
                if isinstance(pt, dict):
                    if "tarih" in pt and "kmfg" in pt:
                        dt = datetime.strptime(pt["tarih"], "%Y-%m-%d")
                        val = float(pt["kmfg"])
                    else:
                        ts_ms = float(pt.get("time", pt.get("x", 0)))
                        val = float(pt.get("value", pt.get("y", 0)))
                        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    ts_ms, val = float(pt[0]), float(pt[1])
                    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                else: 
                    continue
            except Exception:
                continue
                
            if dt.date() >= cutoff_date:
                evr_raw = val
                evr_val = evr_raw if evr_raw > 1 else evr_raw * 100
                evr_val = round(evr_val, 2)
                if int(evr_val) == evr_val:
                    evr_val = int(evr_val)
                    
                records.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "evr_value": evr_val
                })
        
        if records:
            logger.info("Cekim basarili! Son gun: %s -> %s", records[-1]['date'], records[-1]['evr_value'])
        return records

    except Exception as e:
        logger.exception("API Veri cekme hatasi: %s", e)
        return None

if __name__ == "__main__":
    import json
    res = scrape(headless=True, last_n_days=14)
    if res:
        print("CSV guncellendi (test amacli) - Veriler hazir.")
