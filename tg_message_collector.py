#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль для сбора личных сообщений из Telegram через API.
Использует библиотеку Telethon для доступа к Telegram.
Соблюдает ограничения API для предотвращения блокировок и FloodWait.
"""

import os
import sys
import json
import time
import asyncio
import logging
import random
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty, InputPeerUser, InputPeerChannel, InputPeerChat, PeerUser, User
from telethon.errors import FloodWaitError

# Настройка подробного логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tg_collector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Получение учетных данных из переменных окружения
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
PHONE = os.getenv('PHONE')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'data/messages')

# Проверка наличия необходимых переменных окружения
if not all([API_ID, API_HASH, PHONE]):
    logger.error("❌ Ошибка: Не найдены необходимые переменные окружения (API_ID, API_HASH, PHONE)")
    sys.exit(1)

# Создание директории для выходных файлов, если она не существует
os.makedirs(OUTPUT_DIR, exist_ok=True)
logger.info(f"📁 Директория для хранения сообщений: {os.path.abspath(OUTPUT_DIR)}")

# Константы ограничений Telegram API (по официальной документации)
# https://core.telegram.org/bots/faq
MAX_MESSAGES_PER_SECOND_PER_CHAT = 1  # 1 сообщение в секунду в одном чате
MAX_MESSAGES_PER_MINUTE_PER_GROUP = 20  # 20 сообщений в минуту в группу
MAX_BULK_MESSAGES_PER_SECOND = 30  # ~30 сообщений в секунду при массовых уведомлениях
SAFE_LIMIT_FACTOR = 0.7  # Используем 70% от максимальных лимитов для безопасности

class TelegramMessageCollector:
    """Класс для сбора сообщений из личных чатов Telegram."""
    
    def __init__(self, api_id, api_hash, phone):
        """
        Инициализация сборщика сообщений.
        
        Args:
            api_id (int): Telegram API ID
            api_hash (str): Telegram API Hash
            phone (str): Номер телефона для аутентификации
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client = TelegramClient('session_message_collector', api_id, api_hash)
        self.me = None
        self.messages_data = []
        
        # Статистика обработки
        self.stats = {
            "chats_processed": 0,
            "messages_collected": 0,
            "flood_wait_errors": 0,
            "total_wait_time": 0,
            "start_time": None,
            "end_time": None
        }
        
    async def start(self):
        """Запуск клиента Telegram и аутентификация."""
        logger.info("🔄 Запуск клиента Telegram...")
        self.stats["start_time"] = datetime.now()
        
        try:
            await self.client.start(phone=self.phone)
            self.me = await self.client.get_me()
            logger.info(f"✅ Вход выполнен как: {self.me.first_name} (@{self.me.username})")
            logger.info(f"🆔 User ID: {self.me.id}")
        except Exception as e:
            logger.error(f"❌ Ошибка при авторизации: {e}")
            raise
    
    async def safe_api_call(self, coroutine, description):
        """
        Безопасный вызов API с обработкой FloodWaitError.
        
        Args:
            coroutine: Корутина для выполнения
            description (str): Описание вызова для логирования
            
        Returns:
            Результат выполнения корутины
        """
        while True:
            try:
                logger.debug(f"📡 Выполнение API вызова: {description}")
                return await coroutine
            except FloodWaitError as e:
                self.stats["flood_wait_errors"] += 1
                self.stats["total_wait_time"] += e.seconds
                
                logger.warning(f"⚠️ FloodWaitError: Необходимо подождать {e.seconds} секунд перед следующим запросом ({description})")
                await asyncio.sleep(e.seconds + random.uniform(0.5, 1.5))  # Добавляем случайную задержку
            except Exception as e:
                logger.error(f"❌ Ошибка при вызове API ({description}): {e}")
                # Добавляем небольшую задержку при ошибке
                await asyncio.sleep(random.uniform(3, 5))
                raise
    
    async def collect_personal_chats(self, limit_per_chat=None, max_chats=None, delay_between_chats=5):
        """
        Сбор сообщений из личных чатов с улучшенной обработкой ограничений API.
        
        Args:
            limit_per_chat (int, optional): Максимальное количество сообщений для загрузки из каждого чата.
                                           None означает загрузку всех доступных сообщений.
            max_chats (int, optional): Максимальное количество чатов для обработки за один запуск.
                                      None означает обработку всех доступных чатов.
            delay_between_chats (int): Минимальная задержка между обработкой чатов
            
        Returns:
            list: Список собранных сообщений
        """
        logger.info("🔍 Получение списка диалогов...")
        
        # Получаем диалоги с большими паузами между запросами
        dialogs = []
        offset_date = None
        offset_id = 0
        offset_peer = InputPeerEmpty()
        
        # Постепенно загружаем диалоги небольшими порциями
        chunks_loaded = 0
        chunk_size = 100  # Увеличен размер порции для получения большего количества диалогов
        
        logger.info("📊 Параметры сбора сообщений:")
        if limit_per_chat:
            logger.info(f"   - Максимум {limit_per_chat} сообщений из каждого чата")
        else:
            logger.info(f"   - Загрузка ВСЕХ доступных сообщений из каждого чата")
            
        if max_chats:
            logger.info(f"   - Обработка не более {max_chats} чатов")
        else:
            logger.info(f"   - Обработка ВСЕХ доступных чатов")
            
        logger.info(f"   - Минимальная задержка между чатами: {delay_between_chats} секунд")
        
        while True:  # Убрано ограничение на количество порций диалогов
            try:
                logger.info(f"📥 Загрузка порции диалогов #{chunks_loaded+1} (размер порции: {chunk_size})...")
                
                result = await self.safe_api_call(
                    self.client(GetDialogsRequest(
                        offset_date=offset_date,
                        offset_id=offset_id,
                        offset_peer=offset_peer,
                        limit=chunk_size,
                        hash=0
                    )),
                    f"GetDialogsRequest (chunk #{chunks_loaded+1})"
                )
                
                if not result.dialogs:
                    logger.info("👍 Все диалоги загружены")
                    break
                    
                logger.info(f"✅ Загружено {len(result.dialogs)} диалогов")
                dialogs.extend(result.dialogs)
                
                offset_date = result.messages[-1].date
                offset_peer = result.dialogs[-1].peer
                offset_id = result.messages[-1].id
                
                chunks_loaded += 1
                
                # Добавляем случайную паузу между запросами (безопасная пауза)
                pause_time = random.uniform(4.0, 6.0)
                logger.info(f"⏱️ Пауза {pause_time:.1f} секунд перед загрузкой следующей порции диалогов...")
                await asyncio.sleep(pause_time)
                
            except Exception as e:
                logger.error(f"❌ Ошибка при загрузке диалогов: {e}")
                # Больше ждем при ошибке
                await asyncio.sleep(15)
        
        logger.info(f"📊 Найдено {len(dialogs)} диалогов всего")
        
        # Увеличим уровень логирования для отладки
        logging.getLogger().setLevel(logging.DEBUG)
        
        # Фильтрация только личных чатов с расширенной диагностикой
        personal_chats = []
        logger.info("🔍 Начинаю анализ типов диалогов...")
        user_count = 0
        
        for i, dialog in enumerate(dialogs):
            try:
                # Проверяем peer чата
                if hasattr(dialog, 'peer'):
                    peer = dialog.peer
                    
                    # Проверяем, является ли peer личным пользователем
                    if isinstance(peer, PeerUser):
                        user_count += 1
                        
                        # Безопасно получаем ID пользователя
                        user_id = getattr(peer, 'user_id', 'Unknown')
                        
                        # Безопасный вывод идентификатора диалога
                        dialog_id = f"ID:{user_id}"
                        try:
                            if hasattr(dialog, 'title') and dialog.title:
                                dialog_id = f"{dialog.title} (ID:{user_id})"
                        except:
                            pass
                            
                        if i < 20:  # Подробный вывод только для первых 20 диалогов
                            logger.debug(f"   ✅ Найден личный чат #{user_count}: {dialog_id}")
                        
                        # Сохраняем диалог и ID пользователя для дальнейшего использования
                        personal_chats.append((dialog, user_id))
            except Exception as e:
                if i < 20:  # Подробный вывод только для первых 20 диалогов
                    logger.debug(f"   ⚠️ Ошибка при анализе диалога: {e}")
                continue
        
        logger.info(f"👤 Найдено личных чатов: {len(personal_chats)} из {len(dialogs)} диалогов")
        
        # Ограничиваем количество обрабатываемых чатов
        if max_chats and len(personal_chats) > max_chats:
            logger.info(f"🔍 Ограничиваем обработку до {max_chats} чатов")
            personal_chats = personal_chats[:max_chats]
        
        total_messages = 0
        
        for chat_index, (chat, user_id) in enumerate(personal_chats):
            self.stats["chats_processed"] += 1
            
            chat_info = f"User ID:{user_id}"
            logger.info(f"💬 Обработка чата [{chat_index+1}/{len(personal_chats)}] с: {chat_info}")
            chat_start_time = time.time()
            
            try:
                # Получение сообщений из текущего чата по user_id
                messages = []
                msg_count = 0
                
                logger.info(f"🔄 Загрузка сообщений из чата с {chat_info} (лимит: {limit_per_chat if limit_per_chat else 'все сообщения'})...")
                
                # Используем user_id напрямую для получения сообщений
                message_iterator = self.client.iter_messages(user_id, limit=limit_per_chat)
                
                async for message in message_iterator:
                    if message.text and message.from_id and hasattr(message.from_id, 'user_id'):
                        # Сохраняем только если сообщение от вас
                        if message.from_id.user_id == self.me.id:
                            messages.append({
                                "chat_id": user_id,
                                "chat_type": "personal",
                                "message_id": message.id,
                                "text": message.text,
                                "date": message.date.isoformat(),
                                "is_reply": message.is_reply
                            })
                            
                            msg_count += 1
                            # Делаем микропаузы каждые 20 сообщений
                            if msg_count % 20 == 0:
                                await asyncio.sleep(0.3)
                                logger.debug(f"⏱️ Микропауза после обработки {msg_count} сообщений...")
                
                self.messages_data.extend(messages)
                total_messages += len(messages)
                self.stats["messages_collected"] += len(messages)
                
                chat_elapsed_time = time.time() - chat_start_time
                logger.info(f"✅ Получено {len(messages)} ваших сообщений из чата с {chat_info} за {chat_elapsed_time:.1f} сек")
                
                # Значительная пауза между обработкой чатов (в соответствии с официальными ограничениями)
                pause_time = max(delay_between_chats, random.uniform(delay_between_chats, delay_between_chats * 1.5))
                logger.info(f"⏱️ Пауза {pause_time:.1f} секунд перед следующим чатом...")
                await asyncio.sleep(pause_time)
                
            except Exception as e:
                logger.error(f"❌ Ошибка при получении сообщений из чата {chat_info}: {e}")
                # Еще дольше ждем при ошибке
                await asyncio.sleep(15)
        
        logger.info(f"🎉 Всего получено {total_messages} ваших сообщений из {self.stats['chats_processed']} личных чатов")
        return self.messages_data
    
    async def save_messages_to_json(self, filename=None):
        """
        Сохранение собранных сообщений в JSON файл.
        
        Args:
            filename (str, optional): Имя файла для сохранения. По умолчанию генерируется автоматически.
            
        Returns:
            str: Путь к созданному файлу
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"telegram_messages_{timestamp}.json"
        
        file_path = os.path.join(OUTPUT_DIR, filename)
        
        logger.info(f"💾 Сохранение {len(self.messages_data)} сообщений в файл...")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.messages_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Сообщения сохранены в файл: {file_path}")
        return file_path
    
    async def close(self):
        """Завершение работы клиента."""
        await self.client.disconnect()
        logger.info("👋 Клиент Telegram отключен")
        
        # Фиксируем время завершения и выводим статистику
        self.stats["end_time"] = datetime.now()
        elapsed_time = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        logger.info("\n" + "="*50)
        logger.info("📊 ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(f"⏱️ Время выполнения: {elapsed_time:.1f} секунд")
        logger.info(f"💬 Обработано чатов: {self.stats['chats_processed']}")
        logger.info(f"📝 Собрано сообщений: {self.stats['messages_collected']}")
        logger.info(f"⚠️ Случаев FloodWaitError: {self.stats['flood_wait_errors']}")
        logger.info(f"⏳ Общее время ожидания из-за FloodWaitError: {self.stats['total_wait_time']} секунд")
        if self.stats["messages_collected"] > 0:
            logger.info(f"⚡️ Средняя скорость: {self.stats['messages_collected'] / elapsed_time:.2f} сообщений/сек")
        logger.info("="*50)

async def main():
    """Основная функция для запуска сбора сообщений."""
    logger.info("🚀 Запуск сборщика сообщений из Telegram")
    
    collector = TelegramMessageCollector(API_ID, API_HASH, PHONE)
    
    try:
        await collector.start()
        
        # Сбор личных сообщений без ограничений
        # Установите limit_per_chat=N для ограничения количества сообщений на чат
        # Установите max_chats=N для ограничения количества обрабатываемых чатов
        messages = await collector.collect_personal_chats(
            limit_per_chat=None,  # None = все доступные сообщения
            max_chats=None,       # None = все доступные чаты
            delay_between_chats=5 # Задержка между обработкой чатов
        )
        
        # Получение текущей даты и времени в удобном формате
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"messages_full_{timestamp}.json"
        
        # Сохранение сообщений в JSON-файл
        await collector.save_messages_to_json(filename)
        
        # Вывод статистики
        collector.stats["end_time"] = datetime.now()
        elapsed_time = (collector.stats["end_time"] - collector.stats["start_time"]).total_seconds()
        
        logger.info("\n" + "="*50)
        logger.info("📊 ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(f"⏱️ Время выполнения: {elapsed_time:.1f} секунд")
        logger.info(f"💬 Обработано чатов: {collector.stats['chats_processed']}")
        logger.info(f"📝 Собрано сообщений: {collector.stats['messages_collected']}")
        logger.info(f"⚠️ Случаев FloodWaitError: {collector.stats['flood_wait_errors']}")
        logger.info(f"⏳ Общее время ожидания из-за FloodWaitError: {collector.stats['total_wait_time']} секунд")
        if collector.stats["messages_collected"] > 0:
            logger.info(f"⚡️ Средняя скорость: {collector.stats['messages_collected'] / elapsed_time:.2f} сообщений/сек")
        logger.info("="*50)
        
    except Exception as e:
        logger.error(f"❌ Произошла ошибка: {e}", exc_info=True)
    finally:
        # Закрытие клиента
        await collector.client.disconnect()
        logger.info("👋 Клиент отключен")

if __name__ == "__main__":
    # Запуск асинхронной функции main
    start_time = time.time()
    asyncio.run(main())
    total_time = time.time() - start_time
    logger.info(f"⏱️ Общее время выполнения скрипта: {total_time:.2f} секунд")
