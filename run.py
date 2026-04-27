"""
EVR Trading Bot - Baslatici.

Kullanim:
    python run.py api          # Sadece REST API
    python run.py bot          # Sadece bot dongusu (tek sefer)
    python run.py bot --loop   # Scheduler modu
    python run.py migrate      # Bekleyen migration'lari uygula
    python run.py all          # API + Bot
"""
import sys
import threading


def start_api():
    """FastAPI sunucusunu baslat."""
    import uvicorn
    from evr_bot.database import init_db

    init_db()
    uvicorn.run("evr_bot.app:app", host="0.0.0.0", port=8000, reload=False)


def start_bot(loop: bool = False):
    """Bot dongusunu baslat."""
    from evr_bot.main_bot import main

    sys.argv = ["main_bot"]
    if not loop:
        sys.argv.append("--once")
    main()


def run_migrations():
    """Bekleyen migration'lari uygula."""
    from evr_bot.database import init_db

    init_db()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "api":
        start_api()
    elif cmd == "bot":
        loop = "--loop" in sys.argv
        start_bot(loop=loop)
    elif cmd == "migrate":
        run_migrations()
    elif cmd == "all":
        api_thread = threading.Thread(target=start_api, daemon=True)
        api_thread.start()
        start_bot(loop=True)
    else:
        print(f"Bilinmeyen komut: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
