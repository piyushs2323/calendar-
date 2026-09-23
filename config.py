import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # your telegram chat id, reminders go here
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///buyers.db")
DEFAULT_PLAN_DAYS = int(os.getenv("DEFAULT_PLAN_DAYS", "30"))
# hour (24h, server time) the daily expiry check runs
EXPIRY_CHECK_HOUR = int(os.getenv("EXPIRY_CHECK_HOUR", "9"))
