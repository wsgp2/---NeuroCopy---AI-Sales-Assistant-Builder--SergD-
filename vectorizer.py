#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль для создания векторной базы данных из текстовых сообщений.
Преобразует сообщения в векторные представления и сохраняет их для последующего поиска.
"""

import os
import json
import logging
import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import chromadb

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Директории для работы
INPUT_DIR = os.getenv('OUTPUT_DIR', './data/messages')
DB_DIR = os.getenv('DB_DIR', './data/vector_db')

# Создание директорий, если они не существуют
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)

class MessageVectorizer:
    """Класс для преобразования текстовых сообщений в векторные представления и их хранения."""
    
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """
        Инициализация объекта векторизатора.
        
        Args:
            model_name (str): Название модели SentenceTransformer для создания эмбеддингов
        """
        logger.info(f"Инициализация векторизатора с моделью {model_name}")
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        
        # Инициализация клиента ChromaDB (современный способ)
        self.client = chromadb.PersistentClient(
            path=DB_DIR
        )
        
        # Создание или подключение к коллекции
        try:
            self.collection = self.client.get_collection("my_messages")
            logger.info("Подключение к существующей коллекции 'my_messages'")
            # Получаем текущее количество документов для генерации уникальных ID
            self.current_id_counter = self._get_current_count()
            logger.info(f"Текущий счетчик ID: {self.current_id_counter}")
        except:
            self.collection = self.client.create_collection("my_messages")
            logger.info("Создана новая коллекция 'my_messages'")
            self.current_id_counter = 0
    
    def _get_current_count(self):
        """
        Получает текущее максимальное значение ID из базы данных.
        
        Returns:
            int: Максимальное число в ID (из msg_X)
        """
        try:
            # Получаем все ID из коллекции
            all_ids = self.collection.get()["ids"]
            if not all_ids:
                return 0
                
            # Извлекаем числовую часть из ID формата msg_X
            id_numbers = [int(id_str.split('_')[1]) for id_str in all_ids if '_' in id_str]
            if not id_numbers:
                return 0
                
            return max(id_numbers) + 1
        except Exception as e:
            logger.error(f"Ошибка при получении текущего счетчика ID: {e}")
            return 0
    
    def load_messages(self, file_path):
        """
        Загрузка сообщений из JSON файла.
        
        Args:
            file_path (str): Путь к JSON-файлу с сообщениями
            
        Returns:
            list: Список сообщений
        """
        logger.info(f"Загрузка сообщений из файла {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            logger.info(f"Загружено {len(messages)} сообщений")
            return messages
        except Exception as e:
            logger.error(f"Ошибка при загрузке сообщений: {e}")
            return []
    
    def create_embeddings(self, messages):
        """
        Создание векторных представлений для сообщений.
        
        Args:
            messages (list): Список словарей с сообщениями
            
        Returns:
            tuple: Тексты сообщений и их векторные представления
        """
        logger.info("Создание векторных представлений для сообщений")
        
        # Извлечение текстов сообщений
        texts = [msg["text"] for msg in messages]
        
        # Создание эмбеддингов
        embeddings = self.model.encode(texts, show_progress_bar=True)
        
        logger.info(f"Создано {len(embeddings)} векторных представлений")
        return texts, embeddings
    
    def add_to_vector_db(self, messages, texts, embeddings):
        """
        Добавление сообщений и их векторных представлений в базу данных.
        Проверяет существование сообщений по message_id и предотвращает дублирование.
        
        Args:
            messages (list): Список словарей с сообщениями
            texts (list): Список текстовых сообщений
            embeddings (numpy.ndarray): Массив векторных представлений
            
        Returns:
            int: Количество добавленных документов
        """
        logger.info("Добавление сообщений в векторную базу данных")
        
        # Преобразование numpy массива в список
        embeddings_list = embeddings.tolist()
        
        # Получаем все существующие ID из базы для предотвращения дубликатов
        try:
            all_data = self.collection.get()
            existing_message_ids = set()
            existing_db_ids = set(all_data["ids"])
            
            # Извлекаем все message_id из метаданных
            for metadata in all_data["metadatas"]:
                if metadata and "message_id" in metadata:
                    existing_message_ids.add(metadata["message_id"])
                    
            logger.info(f"Найдено {len(existing_message_ids)} существующих сообщений в базе")
        except Exception as e:
            logger.error(f"Ошибка при получении существующих сообщений: {e}")
            existing_message_ids = set()
            existing_db_ids = set()
        
        # Подготовка данных для добавления
        ids = []
        filtered_texts = []
        filtered_embeddings = []
        filtered_metadatas = []
        
        # Фильтрация уже существующих сообщений
        for i, msg in enumerate(messages):
            message_id = str(msg["message_id"])
            
            # Если сообщение уже существует, пропускаем его
            if message_id in existing_message_ids:
                continue
            
            # Если сообщение новое, добавляем его
            # Генерируем уникальный ID, убедившись, что он не существует в базе
            msg_id = f"msg_{self.current_id_counter}"
            while msg_id in existing_db_ids:
                self.current_id_counter += 1
                msg_id = f"msg_{self.current_id_counter}"
            
            self.current_id_counter += 1
            
            ids.append(msg_id)
            filtered_texts.append(texts[i])
            filtered_embeddings.append(embeddings_list[i])
            
            # Добавляем метаданные
            metadata = {
                "chat_id": str(msg["chat_id"]),
                "chat_type": msg.get("chat_type", "Unknown"),
                "message_id": message_id,
                "date": msg["date"],
                "is_reply": "true" if msg["is_reply"] else "false"
            }
            filtered_metadatas.append(metadata)
        
        # Если нет новых сообщений, возвращаем 0
        if not ids:
            logger.info("Нет новых сообщений для добавления")
            return 0
        
        # Добавление документов в коллекцию
        try:
            self.collection.add(
                ids=ids,
                embeddings=filtered_embeddings,
                documents=filtered_texts,
                metadatas=filtered_metadatas
            )
            logger.info(f"Добавлено {len(ids)} новых документов в базу данных")
            return len(ids)
        except Exception as e:
            logger.error(f"Ошибка при добавлении в базу данных: {e}")
            return 0
    
    def remove_duplicates(self):
        """
        Удаляет дубликаты сообщений из базы данных на основе message_id.
        
        Returns:
            int: Количество удаленных дубликатов
        """
        logger.info("Начало процесса удаления дубликатов")
        
        try:
            # Получаем все документы и их метаданные
            all_data = self.collection.get()
            ids = all_data["ids"]
            metadatas = all_data["metadatas"]
            
            if not ids:
                logger.info("База данных пуста, нет дубликатов для удаления")
                return 0
            
            # Словарь для отслеживания уникальных message_id
            unique_message_ids = {}
            ids_to_delete = []
            
            # Находим дубликаты
            for i, metadata in enumerate(metadatas):
                message_id = metadata.get("message_id")
                if not message_id:
                    continue
                
                if message_id in unique_message_ids:
                    # Это дубликат, добавляем его ID в список для удаления
                    ids_to_delete.append(ids[i])
                else:
                    # Это уникальное сообщение, запоминаем его
                    unique_message_ids[message_id] = ids[i]
            
            # Удаляем найденные дубликаты
            if ids_to_delete:
                self.collection.delete(ids=ids_to_delete)
                logger.info(f"Удалено {len(ids_to_delete)} дубликатов")
                return len(ids_to_delete)
            else:
                logger.info("Дубликатов не найдено")
                return 0
                
        except Exception as e:
            logger.error(f"Ошибка при удалении дубликатов: {e}")
            return 0
    
    def process_message_file(self, file_path):
        """
        Полный процесс обработки файла с сообщениями:
        загрузка, создание эмбеддингов, добавление в базу данных.
        
        Args:
            file_path (str): Путь к JSON-файлу с сообщениями
            
        Returns:
            int: Количество обработанных сообщений
        """
        # Загрузка сообщений
        messages = self.load_messages(file_path)
        if not messages:
            return 0
        
        # Создание эмбеддингов
        texts, embeddings = self.create_embeddings(messages)
        
        # Удаление дубликатов перед добавлением новых данных
        duplicates_removed = self.remove_duplicates()
        if duplicates_removed > 0:
            logger.info(f"Очищено {duplicates_removed} дубликатов из базы данных")
        
        # Добавление в базу данных
        added_count = self.add_to_vector_db(messages, texts, embeddings)
        
        # В новой версии ChromaDB для PersistentClient не нужен вызов persist()
        # Данные сохраняются автоматически
        logger.info("База данных сохранена на диск")
        
        return added_count
    
    def process_latest_file(self):
        """
        Обработка последнего созданного файла с сообщениями в директории.
        
        Returns:
            int: Количество обработанных сообщений
        """
        try:
            # Получение списка JSON-файлов
            json_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]
            
            if not json_files:
                logger.warning("В директории не найдено JSON-файлов с сообщениями")
                return 0
            
            # Сортировка по дате создания (последние файлы в конце)
            json_files.sort(key=lambda x: os.path.getctime(os.path.join(INPUT_DIR, x)))
            
            # Выбор последнего файла
            latest_file = json_files[-1]
            file_path = os.path.join(INPUT_DIR, latest_file)
            
            logger.info(f"Найден последний файл: {latest_file}")
            
            # Обработка файла
            return self.process_message_file(file_path)
            
        except Exception as e:
            logger.error(f"Ошибка при обработке последнего файла: {e}")
            return 0
    
    def query_similar_messages(self, query_text, n_results=5):
        """
        Поиск сообщений, наиболее похожих на заданный запрос.
        
        Args:
            query_text (str): Текст запроса
            n_results (int): Количество результатов для возврата
            
        Returns:
            dict: Результаты запроса (найденные сообщения и метаданные)
        """
        logger.info(f"Поиск сообщений, похожих на: '{query_text}'")
        
        # Получение векторного представления запроса
        query_embedding = self.model.encode([query_text])[0].tolist()
        
        # Выполнение запроса к базе данных
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        logger.info(f"Найдено {len(results['ids'][0])} похожих сообщений")
        
        return results

def main():
    """Основная функция для запуска векторизации сообщений."""
    try:
        # Создание экземпляра векторизатора
        vectorizer = MessageVectorizer()
        
        # Удаление дубликатов перед обработкой новых данных
        duplicates_removed = vectorizer.remove_duplicates()
        if duplicates_removed > 0:
            logger.info(f"Очищено {duplicates_removed} дубликатов из базы данных")
        
        # Обработка последнего файла с сообщениями
        processed_count = vectorizer.process_latest_file()
        
        if processed_count > 0:
            logger.info(f"Успешно обработано и добавлено в базу данных {processed_count} сообщений")
            
            # Тестовый запрос
            query = "Привет, как дела?"
            results = vectorizer.query_similar_messages(query)
            
            logger.info("Примеры найденных сообщений:")
            for i, doc in enumerate(results['documents'][0][:3]):
                logger.info(f"{i+1}. {doc}")
        else:
            logger.warning("Не удалось обработать сообщения. Проверьте наличие файлов и логи ошибок.")
        
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    main()
