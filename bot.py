import logging
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from config import BOT_TOKEN
import database as db

# Настройка логирования
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Подключаем статические файлы фронтенда
app.mount("/static", StaticFiles(directory="public"), name="static")

@app.get("/")
def serve_index():
    return FileResponse("public/index.html")

# Pydantic модель для синхронизации пользователя из WebApp
class UserSyncSchema(BaseModel):
    telegramId: int
    username: str = ""
    firstName: str = ""
    lastName: str = ""
    deviceUuid: str

@app.post("/api/user/sync")
async def sync_user(data: UserSyncSchema):
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        # 1. Проверяем, было ли устройство привязано к другому Telegram ID
        cursor.execute("SELECT telegram_id FROM device_sessions WHERE device_uuid = ?", (data.deviceUuid,))
        session = cursor.fetchone()

        if session:
            old_telegram_id = session["telegram_id"]
            if old_telegram_id != data.telegramId:
                # Аккаунт на устройстве сменился — удаляем старого пользователя
                cursor.execute("DELETE FROM users WHERE telegram_id = ?", (old_telegram_id,))
                cursor.execute("DELETE FROM device_sessions WHERE device_uuid = ?", (data.deviceUuid,))

        # 2. Создаем или обновляем пользователя
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (data.telegramId,))
        user = cursor.fetchone()

        if not user:
            cursor.execute(
                "INSERT INTO users (telegram_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                (data.telegramId, data.username, data.firstName, data.lastName)
            )
        else:
            cursor.execute(
                "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE telegram_id = ?",
                (data.username, data.firstName, data.lastName, data.telegramId)
            )

        # 3. Обновляем сессию устройства
        cursor.execute(
            "REPLACE INTO device_sessions (device_uuid, telegram_id, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (data.deviceUuid, data.telegramId)
        )

        conn.commit()
        return {"success": True, "firstName": data.firstName}
    except Exception as e:
        conn.rollback()
        logging.error(f"Sync error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()

# Инициализация Telegram Бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Кнопка для открытия WebApp (замените URL на ваш рабочий адрес при деплое)
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🍽 Открыть меню Terassa", web_app=types.WebAppInfo(url="https://your-domain.com"))]
        ]
    )
    await message.answer("Добро пожаловать в ресторан **Terassa**! Нажмите кнопку ниже, чтобы открыть меню и сделать заказ:", reply_markup=keyboard, parse_mode="Markdown")

if __name__ == "__main__":
    # Запуск бота и сервера можно разнести, либо запустить через uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
