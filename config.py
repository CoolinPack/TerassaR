import os

# Токен вашего Telegram-бота (лучше заменить на переменные окружения в продакшене)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Пути к файлам и базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), "terassa.db")
MENU_JSON_PATH = os.path.join(os.path.dirname(__file__), "public", "menu.json")
