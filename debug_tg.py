import os
import asyncio
import logging
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('TelegramDebug')

# API данные из файла .env (вводим напрямую для отладки)
API_ID = 14749377
API_HASH = 'd92c61459052f0607f6ed29fef08d939'
PHONE = '+79222474175'

# Целевой канал и сообщение
TARGET_CHANNEL_USERNAME = "youtubegroup"  # Попробуем использовать username канала
TARGET_CHANNEL_ID = -1002175364727  # ID в правильном формате для группы/канала
TARGET_MESSAGE_ID = 864

# Директория для сохранения
DOWNLOADS_DIR = './downloads'
Path(DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)

async def main():
    """Функция для отладки подключения к Telegram API"""
    logger.info("🚀 Запуск отладочного скрипта Telegram")
    
    # Создаем клиент с полной отладкой
    client = TelegramClient(
        'debug_session', 
        API_ID, 
        API_HASH,
        device_model="MacOS",
        system_version="14",
        app_version="1.0"
    )
    
    try:
        # Подключаемся с интерактивным режимом для детализации ошибок
        logger.debug("Начинаем подключение к Telegram...")
        
        # Запуск клиента без параметров для интерактивного ввода
        await client.start()
        
        # Проверяем авторизацию
        if await client.is_user_authorized():
            logger.info("👤 Пользователь авторизован успешно")
            
            # Пытаемся получить информацию о канале
            try:
                # Попробуем сначала username, если не работает - ID канала
                try:
                    logger.debug(f"Получаем информацию о канале по username: {TARGET_CHANNEL_USERNAME}...")
                    channel = await client.get_entity(TARGET_CHANNEL_USERNAME)
                except Exception as username_error:
                    logger.warning(f"Не удалось получить канал по username: {str(username_error)}")
                    logger.debug(f"Пробуем получить канал по ID: {TARGET_CHANNEL_ID}...")
                    channel = await client.get_entity(TARGET_CHANNEL_ID)
                logger.info(f"📺 Канал найден: {getattr(channel, 'title', 'Без названия')}")
                
                # Получаем сообщение
                logger.debug(f"Запрашиваем сообщение {TARGET_MESSAGE_ID}...")
                messages = await client.get_messages(channel, ids=[TARGET_MESSAGE_ID])
                
                if messages and messages[0]:
                    msg = messages[0]
                    logger.info(f"💬 Сообщение получено: ID={msg.id}, дата={msg.date}")
                    
                    # Проверяем наличие медиа
                    if hasattr(msg, 'media') and msg.media:
                        logger.info(f"📹 Медиа найдено: {type(msg.media).__name__}")
                        
                        # Пытаемся скачать медиа
                        file_path = Path(DOWNLOADS_DIR) / f"debug_video_{msg.id}.mp4"
                        logger.debug(f"Начинаем скачивание в {file_path}...")
                        
                        path = await client.download_media(msg.media, file=str(file_path))
                        
                        if path:
                            logger.info(f"✅ Успешно скачано: {path}")
                        else:
                            logger.error("❌ Файл не был скачан (пустой путь)")
                    else:
                        logger.warning("⚠️ Сообщение не содержит медиа")
                else:
                    logger.warning(f"⚠️ Сообщение с ID {TARGET_MESSAGE_ID} не найдено")
            
            except Exception as e:
                logger.error(f"❌ Ошибка при работе с каналом: {str(e)}", exc_info=True)
        else:
            logger.error("❌ Пользователь не авторизован")
    
    except SessionPasswordNeededError:
        logger.error("❌ Требуется двухфакторная аутентификация. Введите код в интерактивном режиме.")
    
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {str(e)}", exc_info=True)
    
    finally:
        # Отключаемся от API
        await client.disconnect()
        logger.info("👋 Отключение от Telegram API")

# Запуск программы
if __name__ == "__main__":
    asyncio.run(main())
