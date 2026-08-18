import asyncio
import json
import logging
import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


# Эндпоинт для предотвращения засыпания на Render (Anti-Sleep)
@app.get("/ping")
def ping_server():
  return {"status": "alive"}


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
    cursor.execute(
        "SELECT telegram_id FROM device_sessions WHERE device_uuid = ?",
        (data.deviceUuid,),
    )
    session = cursor.fetchone()

    if session:
      old_telegram_id = session["telegram_id"]
      if old_telegram_id != data.telegramId:
        cursor.execute(
            "DELETE FROM users WHERE telegram_id = ?", (old_telegram_id,)
        )
        cursor.execute(
            "DELETE FROM device_sessions WHERE device_uuid = ?",
            (data.deviceUuid,),
        )

    cursor.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (data.telegramId,)
    )
    user = cursor.fetchone()

    if not user:
      cursor.execute(
          "INSERT INTO users (telegram_id, username, first_name, last_name)"
          " VALUES (?, ?, ?, ?)",
          (
              data.telegramId,
              data.username,
              data.firstName,
              data.lastName,
          ),
      )
    else:
      cursor.execute(
          "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE"
          " telegram_id = ?",
          (
              data.username,
              data.firstName,
              data.lastName,
              data.telegramId,
          ),
      )

    cursor.execute(
        "REPLACE INTO device_sessions (device_uuid, telegram_id, updated_at)"
        " VALUES (?, ?, CURRENT_TIMESTAMP)",
        (data.deviceUuid, data.telegramId),
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
GROUP_ID = -1004208823431  # Ваша группа для заказов


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
  keyboard = types.InlineKeyboardMarkup(
      inline_keyboard=[
          [
              types.InlineKeyboardButton(
                  text="🍽 Открыть меню Terassa",
                  web_app=types.WebAppInfo(
                      url="https://ваш-сайт-на-render.onrender.com"
                  ),
              )
          ]
      ]
  )
  await message.answer(
      "Добро пожаловать в ресторан **Terassa**! Нажмите кнопку ниже, чтобы"
      " открыть меню и сделать заказ:",
      reply_markup=keyboard,
      parse_mode="Markdown",
  )


# Обработчик заказов из Mini App (aiogram 3.x)
@dp.message(
    lambda message: message.web_app_data is not None
)  # Проверяем, что пришли данные из WebApp
async def receive_web_app_data(message: types.Message):
  try:
    data = json.loads(message.web_app_data.data)

    text = (
        f"🚨 **Новый заказ #{data['order_id']}!**\n\n"
        f"👤 **Имя:** {data['client_name']}\n"
        f"🏷 **Тип:** {'Доставка' if data['type'] == 'delivery' else 'Самовывоз'}\n"
        f"📍 **Адрес:** {data['address']}\n"
        f"🛒 **Состав:** {data['items']}\n"
        f"💰 **Итого:** {data['total']:,} VND\n"
        f"🕒 **Время:** {data['time']}"
    )

    await bot.send_message(GROUP_ID, text, parse_mode="Markdown")
    await message.answer(
        f"Спасибо за заказ #{data['order_id']}! Мы уже начали его готовить."
    )
  except Exception as e:
    logging.error(f"Ошибка обработки заказа из WebApp: {e}")


# Функция запуска Telegram-бота в фоне параллельно с FastAPI
async def start_telegram_bot():
  await dp.start_polling(bot)


@app.on_event("startup")
async def startup_event():
  # Запускаем бота асинхронно вместе с поднятием FastAPI
  asyncio.create_task(start_telegram_bot())


if __name__ == "__main__":
  # Render передает свой порт через переменные окружения, локально запустится на 8000
  port = int(os.environ.get("PORT", 8000))
  uvicorn.run("main:app", host="0.0.0.0", port=port)
