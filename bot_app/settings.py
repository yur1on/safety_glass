import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put it in .env (BOT_TOKEN=...)")