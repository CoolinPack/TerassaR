import sqlite3
import os
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей Telegram
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица привязки устройств для отслеживания смены аккаунта
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_sessions (
            device_uuid TEXT PRIMARY KEY,
            telegram_id INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()

# Инициализируем БД при запуске модуля
init_db()
