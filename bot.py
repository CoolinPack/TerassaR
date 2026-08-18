import asyncio
import json
import logging
import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from html import escape
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from config import BOT_TOKEN, GROUP_CHAT_ID
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


class OrderSchema(BaseModel):
  order_id: int
  user_id: str | int = "Гость"
  username: str = "не указан"
  client_name: str = "Клиент"
  type: str = "delivery"
  address: str = "Не указан"
  total: int | float = 0
  items: str = "Состав не передан"
  time: str = "Не указано"


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


@app.post("/api/orders")
async def create_order(data: OrderSchema):
  """Принимает заказ напрямую от Mini App и отправляет его в Telegram-группу."""
  logging.info(
      "Получен заказ через API: #%s, user_id=%s, username=%s",
      data.order_id, data.user_id, data.username
  )

  order_type = data.type if data.type in ("delivery", "pickup") else "delivery"
  type_str = "Доставка" if order_type == "delivery" else "Самовывоз"

  # Экранируем пользовательские данные, чтобы спецсимволы
  # в имени/адресе/составе не ломали форматирование Telegram.
  client_name = escape(str(data.client_name))
  username = escape(str(data.username))
  address = escape(str(data.address))
  items = escape(str(data.items))
  time_str = escape(str(data.time))
  user_id = escape(str(data.user_id))

  try:
    total = float(data.total)
    total_str = f"{total:,.0f}" if total.is_integer() else f"{total:,.2f}"
  except (TypeError, ValueError):
    total_str = "0"

  text = (
      f"🚨 <b>Новый заказ #{data.order_id}</b>\n\n"
      f"👤 <b>Имя:</b> {client_name}\n"
      f"🔹 <b>Username:</b> @{username.lstrip('@')}\n"
      f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
      f"🏷 <b>Тип:</b> {type_str}\n"
      f"📍 <b>Адрес:</b> {address}\n"
      f"🛒 <b>Состав:</b> {items}\n"
      f"💰 <b>Итого:</b> {total_str} VND\n"
      f"🕒 <b>Время:</b> {time_str}"
  )

  try:
    logging.info(
        "Отправляю API-заказ #%s в группу %s",
        data.order_id, GROUP_CHAT_ID
    )
    await bot.send_message(GROUP_CHAT_ID, text, parse_mode="HTML")
    logging.info(
        "API-заказ #%s успешно отправлен в группу %s",
        data.order_id, GROUP_CHAT_ID
    )
    return {"success": True, "order_id": data.order_id}
  except Exception as e:
    logging.error(
        "Ошибка отправки API-заказа #%s в группу %s: %s",
        data.order_id, GROUP_CHAT_ID, e, exc_info=True
    )
    raise HTTPException(
        status_code=502,
        detail="Не удалось отправить заказ в Telegram"
    )


# Инициализация Telegram Бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.info(f"GROUP_CHAT_ID установлен: {GROUP_CHAT_ID}")


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
  keyboard = types.InlineKeyboardMarkup(
      inline_keyboard=[
          [
              types.InlineKeyboardButton(
                  text="🍽 Открыть меню Terassa",
                  web_app=types.WebAppInfo(
                      url="https://terassar.onrender.com"
                  ),
              )
          ]
      ]
  )
  await message.answer(
      "Нажмите кнопку ниже, чтобы открыть меню и сделать заказ:",
      reply_markup=keyboard,
  )


# Обработчик заказов из Mini App (aiogram 3.x)
@dp.message(lambda message: message.web_app_data is not None)
async def receive_web_app_data(message: types.Message):
  """Оставлен для совместимости со старыми запусками Mini App через sendData()."""
  logging.info(f"Получено сырое web_app_data: {message.web_app_data.data}")
  try:
    data = json.loads(message.web_app_data.data)
    logging.info(f"Распарсенные данные заказа: {data}")

    order_id = data.get("order_id", "Не указан")
    client_name = escape(str(data.get("client_name", "Клиент")))
    order_type = data.get("type", "delivery")
    type_str = "Доставка" if order_type == "delivery" else "Самовывоз"
    address = escape(str(data.get("address", "Не указан")))
    items = escape(str(data.get("items", "Состав не передан")))
    total = data.get("total", 0)
    time_str = escape(str(data.get("time", "Не указано")))

    text = (
        f"🚨 <b>Новый заказ #{order_id}</b>\n\n"
        f"👤 <b>Имя:</b> {client_name}\n"
        f"🏷 <b>Тип:</b> {type_str}\n"
        f"📍 <b>Адрес:</b> {address}\n"
        f"🛒 <b>Состав:</b> {items}\n"
        f"💰 <b>Итого:</b> {total:,} VND\n"
        f"🕒 <b>Время:</b> {time_str}"
    )

    logging.info(f"Отправляю legacy-заказ #{order_id} в группу {GROUP_CHAT_ID}")
    await bot.send_message(GROUP_CHAT_ID, text, parse_mode="HTML")
    logging.info(f"Заказ #{order_id} успешно отправлен в группу {GROUP_CHAT_ID}")

    await message.answer(
        f"Спасибо за заказ #{order_id}! Мы уже начали его готовить."
    )
  except Exception as e:
    logging.error(f"Ошибка обработки заказа из WebApp: {e}", exc_info=True)


# Функция запуска Telegram-бота в фоне параллельно с FastAPI
async def start_telegram_bot():
  await dp.start_polling(bot)


@app.on_event("startup")
async def startup_event():
  asyncio.create_task(start_telegram_bot())


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 8000))
  uvicorn.run("bot:app", host="0.0.0.0", port=port)
