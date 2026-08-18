import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Добавьте ID вашей группы
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", -1004208823431))

DB_PATH = os.path.join(os.path.dirname(__file__), "terassa.db")
MENU_JSON_PATH = os.path.join(os.path.dirname(__file__), "public", "menu.json")
