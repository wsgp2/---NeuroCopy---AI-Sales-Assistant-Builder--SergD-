#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль для генерации ответов в стиле пользователя.
Использует векторную базу данных сообщений и модель LLM для создания ответов.
"""

import os
import sys
import json
import logging
import argparse
from dotenv import load_dotenv
import openai

# Подключение модуля векторизатора
from vectorizer import MessageVectorizer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# API-ключ для OpenAI (нужно добавить в .env)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

class ResponseGenerator:
    """Класс для генерации ответов в стиле пользователя."""
    
    def __init__(self, openai_api_key=None, model_name="gpt-4o-mini"):
        """
        Инициализация генератора ответов.
        
        Args:
            openai_api_key (str, optional): API-ключ для OpenAI
            model_name (str): Название модели для генерации
        """
        # Настройка API-ключа
        self.api_key = openai_api_key or OPENAI_API_KEY
        
        if not self.api_key:
            logger.error("API-ключ OpenAI не найден. Добавьте OPENAI_API_KEY в .env файл")
            
        # Инициализация клиента OpenAI
        self.client = openai.OpenAI(api_key=self.api_key)
        self.model_name = model_name
        
        # Инициализация векторизатора сообщений
        try:
            self.vectorizer = MessageVectorizer()
            logger.info("Генератор ответов инициализирован")
        except Exception as e:
            logger.error(f"Ошибка при инициализации векторизатора: {e}")
    
    def find_similar_messages(self, query, n_results=5):
        """
        Поиск сообщений, похожих на заданный запрос.
        
        Args:
            query (str): Текст запроса
            n_results (int): Количество результатов для возврата
            
        Returns:
            dict: Результаты запроса
        """
        return self.vectorizer.query_similar_messages(query, n_results)
    
    def format_examples_for_prompt(self, results):
        """
        Форматирование результатов запроса для использования в промпте.
        
        Args:
            results (dict): Результаты запроса из векторной БД
            
        Returns:
            str: Отформатированный текст с примерами
        """
        examples = []
        
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]
        
        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            chat_type = meta.get('chat_type', 'Unknown')
            date = meta.get('date', 'Unknown date')
            example = f"Пример {i+1} (чат типа: {chat_type}, {date}):\n{doc}\n"
            examples.append(example)
        
        return "\n".join(examples)
    
    def generate_response(self, query, temperature=0.7, max_tokens=500, conversation_history=None):
        """
        Генерация ответа в стиле пользователя на основе запроса.
        
        Args:
            query (str): Текст запроса
            temperature (float): Температура генерации (разнообразие)
            max_tokens (int): Максимальная длина ответа
            conversation_history (list, optional): История диалога в формате [{"role": "user"/"assistant", "content": "текст сообщения"}, ...]
            
        Returns:
            str: Сгенерированный ответ
        """
        logger.info(f"Генерация ответа на запрос: '{query}'")
        
        # Поиск похожих сообщений
        similar_results = self.find_similar_messages(query, n_results=8)
        examples = self.format_examples_for_prompt(similar_results)
        
        # Формирование системного промпта
        system_prompt = f"""
        Ты - персональный ассистент, который отвечает точно в стиле пользователя.
        Тебе предоставлены примеры реальных сообщений пользователя из личных чатов.
        
        Твоя задача - сгенерировать ответ на вопрос/запрос, максимально имитируя:
        1. Стиль речи пользователя
        2. Тональность сообщений
        3. Характерные обороты и выражения
        4. Длину предложений и абзацев
        5. Использование эмодзи, пунктуации и форматирования
        6. Уровень формальности общения
        
        Вот примеры предыдущих сообщений пользователя:
        
        {examples}
        
        Отвечай так, как если бы ты был этим конкретным пользователем, копируя его речевые особенности.
        Используй типичные для пользователя слова, выражения и стиль.
        """
        
        # Подготовка списка сообщений для API запроса
        messages = [{"role": "system", "content": system_prompt}]
        
        # Добавление истории диалога, если она предоставлена
        if conversation_history and len(conversation_history) > 0:
            # Ограничиваем количество сообщений из истории, чтобы не превышать лимит токенов
            context_messages = conversation_history[-6:] # берем последние 6 сообщений (3 обмена репликами)
            
            logger.info(f"Добавление {len(context_messages)} сообщений из истории диалога")
            
            # Добавляем сообщения из истории диалога
            messages.extend(context_messages)
        else:
            # Если нет истории, просто добавляем текущий запрос
            messages.append({"role": "user", "content": query})
        
        try:
            # Вызов API для генерации ответа с использованием нового интерфейса OpenAI API
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # Извлечение текста ответа
            generated_text = response.choices[0].message.content.strip()
            
            logger.info("Ответ успешно сгенерирован")
            return generated_text
            
        except Exception as e:
            logger.error(f"Ошибка при генерации ответа: {e}")
            return f"Произошла ошибка при генерации ответа: {e}"
    
    def interactive_mode(self):
        """Запуск интерактивного режима для тестирования генерации ответов."""
        logger.info("Запуск интерактивного режима. Для выхода введите 'exit' или 'quit'")
        
        print("\n==== Интерактивный режим генерации ответов в вашем стиле ====")
        print("Введите ваш запрос, и система сгенерирует ответ в вашем стиле речи")
        print("Для выхода введите 'exit' или 'quit'\n")
        
        conversation_history = []
        
        while True:
            try:
                query = input("\nВведите запрос: ").strip()
                
                if query.lower() in ('exit', 'quit'):
                    print("Завершение работы...")
                    break
                
                if not query:
                    continue
                
                # Генерация и вывод ответа
                response = self.generate_response(query, conversation_history=conversation_history)
                print("\n==== Ответ в вашем стиле ====")
                print(response)
                print("=============================\n")
                
                # Добавляем текущий запрос и ответ в историю диалога
                conversation_history.append({"role": "user", "content": query})
                conversation_history.append({"role": "assistant", "content": response})
                
            except KeyboardInterrupt:
                print("\nПринудительное завершение...")
                break
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                print(f"Произошла ошибка: {e}")
        
        print("Интерактивный режим завершен.")

def main():
    """Основная функция для запуска генератора ответов."""
    parser = argparse.ArgumentParser(description='Генератор ответов в стиле пользователя')
    parser.add_argument('--query', '-q', type=str, help='Запрос для генерации ответа')
    parser.add_argument('--interactive', '-i', action='store_true', help='Запуск в интерактивном режиме')
    parser.add_argument('--temperature', '-t', type=float, default=0.7, help='Температура генерации (разнообразие)')
    parser.add_argument('--max-tokens', '-m', type=int, default=500, help='Максимальная длина ответа в токенах')
    
    args = parser.parse_args()
    
    try:
        # Создание экземпляра генератора
        generator = ResponseGenerator()
        
        if args.interactive:
            # Запуск интерактивного режима
            generator.interactive_mode()
        elif args.query:
            # Генерация ответа на заданный запрос
            response = generator.generate_response(
                args.query, 
                temperature=args.temperature,
                max_tokens=args.max_tokens
            )
            print("\n==== Ответ в вашем стиле ====")
            print(response)
            print("=============================\n")
        else:
            parser.print_help()
        
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
