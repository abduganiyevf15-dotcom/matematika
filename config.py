import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Mini app va admin panel ochiladigan ommaviy HTTPS manzil (masalan https://example.com)
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
# Telegram ID lar, vergul bilan: testlarni botdan tuzish huquqi
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))
# Telegram initData imzosini tekshirish (ishlab chiqarishda True)
VERIFY_INIT_DATA = os.getenv("VERIFY_INIT_DATA", "1") == "1"
