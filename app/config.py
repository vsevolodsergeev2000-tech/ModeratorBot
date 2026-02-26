import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("MOD_BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH")

# Интервал опроса БД в секундах
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))

if not BOT_TOKEN:
    raise ValueError("MOD_BOT_TOKEN не задан в .env")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не задан в .env (укажите хотя бы один ID)")
if not DB_PATH:
    raise ValueError("DB_PATH не задан в .env (путь к bot_database.db из RatingBot)")
