#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram-бот для автоматической генерации ответов в стиле пользователя.
Интегрируется с системой генерации ответов на основе векторной базы данных сообщений.
"""

import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Импорт модуля генерации ответов
from response_generator import ResponseGenerator

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Получение токена бота из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TELEGRAM_BOT_TOKEN:
    logger.error("Токен Telegram-бота не найден. Добавьте TELEGRAM_BOT_TOKEN в файл .env")
    sys.exit(1)

class TelegramResponseBot:
    """Класс для Telegram-бота, генерирующего ответы в стиле пользователя."""
    
    def __init__(self, token):
        """
        Инициализация бота.
        
        Args:
            token (str): Токен Telegram-бота
        """
        self.token = token
        self.response_generator = ResponseGenerator()
        # Словарь для хранения истории диалогов с пользователями
        # Ключ: chat_id, Значение: список сообщений в формате [{role, content}]
        self.conversation_history = {}
        # Максимальная длина истории диалога для каждого пользователя
        self.max_history_length = 1000
        logger.info("Инициализация Telegram-бота для генерации ответов")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /start.
        
        Args:
            update (Update): Объект обновления Telegram
            context (ContextTypes.DEFAULT_TYPE): Контекст обработчика
        """
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        # Очищаем историю диалога при команде /start
        self.conversation_history[chat_id] = []
        
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! 👋\n\n"
            f"Я - бот, который генерирует ответы в стиле владельца на основе анализа его сообщений из Telegram.\n\n"
            f"Просто напишите мне любой вопрос или сообщение, и я отвечу так, как это сделал бы мой владелец."
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /help.
        
        Args:
            update (Update): Объект обновления Telegram
            context (ContextTypes.DEFAULT_TYPE): Контекст обработчика
        """
        await update.message.reply_text(
            "Доступные команды:\n"
            "/start - Начать взаимодействие с ботом\n"
            "/help - Показать эту справку\n"
            "/info - Информация о боте и принципе его работы\n"
            "/clear - Очистить историю диалога\n\n"
            "Чтобы получить ответ в стиле владельца, просто напишите любое сообщение."
        )
    
    async def info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /info.
        
        Args:
            update (Update): Объект обновления Telegram
            context (ContextTypes.DEFAULT_TYPE): Контекст обработчика
        """
        await update.message.reply_text(
            "🤖 *Как работает этот бот?*\n\n"
            "1️⃣ Бот анализирует ваше сообщение\n"
            "2️⃣ Находит похожие сообщения владельца из его личных чатов\n"
            "3️⃣ На основе этих примеров генерирует ответ, имитирующий стиль речи владельца\n\n"
            "Бот использует технологии векторных баз данных и нейронных сетей для максимально точной имитации стиля общения.",
            parse_mode='Markdown'
        )
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /clear - очищает историю диалога.
        
        Args:
            update (Update): Объект обновления Telegram
            context (ContextTypes.DEFAULT_TYPE): Контекст обработчика
        """
        chat_id = update.effective_chat.id
        self.conversation_history[chat_id] = []
        
        await update.message.reply_text(
            "🧹 История диалога очищена. Теперь я не буду учитывать наш предыдущий разговор при ответах."
        )
    
    def _add_to_history(self, chat_id, role, content):
        """
        Добавляет сообщение в историю диалога и ограничивает её длину.
        
        Args:
            chat_id (int): ID чата
            role (str): Роль отправителя ('user' или 'assistant')
            content (str): Текст сообщения
        """
        # Инициализируем историю для нового чата
        if chat_id not in self.conversation_history:
            self.conversation_history[chat_id] = []
            
        # Добавляем новое сообщение
        self.conversation_history[chat_id].append({"role": role, "content": content})
        
        # Ограничиваем длину истории
        if len(self.conversation_history[chat_id]) > self.max_history_length:
            # Удаляем самое старое сообщение
            self.conversation_history[chat_id].pop(0)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик текстовых сообщений.
        Генерирует ответ в стиле пользователя и отправляет его.
        
        Args:
            update (Update): Объект обновления Telegram
            context (ContextTypes.DEFAULT_TYPE): Контекст обработчика
        """
        user_message = update.message.text
        user_name = update.effective_user.first_name
        chat_id = update.effective_chat.id
        
        logger.info(f"Получено сообщение от {user_name} (ID: {chat_id}): {user_message}")
        
        # Добавляем сообщение пользователя в историю
        self._add_to_history(chat_id, "user", user_message)
        
        # Отправка индикатора "печатает"
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        try:
            # Получаем историю текущего диалога
            history = self.conversation_history.get(chat_id, [])
            
            # Генерация ответа в стиле пользователя с учетом истории диалога
            # (последние N сообщений для контекста)
            response_text = self.response_generator.generate_response(
                user_message,
                conversation_history=history
            )
            
            # Добавляем ответ бота в историю
            self._add_to_history(chat_id, "assistant", response_text)
            
            # Отправка ответа
            await update.message.reply_text(response_text)
            logger.info(f"Отправлен ответ пользователю {user_name}")
            
        except Exception as e:
            logger.error(f"Ошибка при генерации ответа: {e}")
            await update.message.reply_text(
                "К сожалению, произошла ошибка при генерации ответа. Пожалуйста, попробуйте позже."
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик ошибок бота.
        
        Args:
            update (Update): Объект обновления Telegram
            context (ContextTypes.DEFAULT_TYPE): Контекст обработчика
        """
        logger.error(f"Произошла ошибка: {context.error}")
    
    def run(self):
        """Запуск бота."""
        logger.info("Запуск Telegram-бота...")
        
        # Создание приложения
        application = Application.builder().token(self.token).build()
        
        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("info", self.info_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Регистрация обработчика ошибок
        application.add_error_handler(self.error_handler)
        
        # Запуск бота
        application.run_polling()
        
        logger.info("Бот запущен")

def main():
    """Основная функция для запуска бота."""
    try:
        # Создание и запуск бота
        bot = TelegramResponseBot(TELEGRAM_BOT_TOKEN)
        bot.run()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
