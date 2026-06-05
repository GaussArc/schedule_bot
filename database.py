# database.py - модуль для работы с базой данных
import sqlite3
import logging
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self.init_db()
    
    def connect(self):
        """Подключение к базе данных"""
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
    
    def close(self):
        """Закрытие подключения"""
        if self.conn:
            self.conn.close()
    
    def init_db(self):
        """Инициализация базы данных (создание таблиц)"""
        self.connect()
        
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                role TEXT DEFAULT 'student',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица настроек пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                last_group TEXT,
                last_teacher TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        
        # Таблица кэша расписания
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedule_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                week_number INTEGER NOT NULL,
                schedule_data TEXT NOT NULL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                UNIQUE(group_name, week_number)
            )
        ''')
        
        self.conn.commit()
        logger.info("✅ База данных инициализирована")
    
    # ========== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ==========
    
    def get_or_create_user(self, chat_id, username=None, first_name=None):
        """Получить пользователя или создать нового"""
        self.cursor.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        user = self.cursor.fetchone()
        
        if not user:
            # Создаём нового пользователя
            self.cursor.execute(
                "INSERT INTO users (chat_id, username, first_name) VALUES (?, ?, ?)",
                (chat_id, username, first_name)
            )
            self.conn.commit()
            
            # Получаем ID нового пользователя
            user_id = self.cursor.lastrowid
            
            # Создаём пустые настройки для пользователя
            self.cursor.execute(
                "INSERT INTO user_settings (user_id) VALUES (?)",
                (user_id,)
            )
            self.conn.commit()
            
            # Получаем полные данные пользователя
            self.cursor.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
            user = self.cursor.fetchone()
            logger.info(f"👤 Новый пользователь: {chat_id} (@{username})")
        else:
            logger.debug(f"Существующий пользователь: chat_id={chat_id}")
        
        return dict(user)
    
    def update_user_role(self, chat_id, role):
        """Обновить роль пользователя"""
        self.cursor.execute(
            "UPDATE users SET role = ? WHERE chat_id = ?",
            (role, chat_id)
        )
        self.conn.commit()
        logger.debug(f"Роль пользователя {chat_id} обновлена на {role}")
        return True
    
    def update_user_group(self, chat_id, group):
        """Обновить последнюю выбранную группу"""
        # Получаем user_id по chat_id
        self.cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
        user = self.cursor.fetchone()
        
        if user:
            self.cursor.execute(
                "UPDATE user_settings SET last_group = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (group, user['id'])
            )
            self.conn.commit()
            logger.debug(f"Группа для {chat_id} обновлена на {group}")
            return True
        return False
    
    def update_user_teacher(self, chat_id, teacher):
        """Обновить последнего выбранного преподавателя"""
        self.cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
        user = self.cursor.fetchone()
        
        if user:
            self.cursor.execute(
                "UPDATE user_settings SET last_teacher = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (teacher, user['id'])
            )
            self.conn.commit()
            logger.debug(f"Преподаватель для {chat_id} обновлен на {teacher}")
            return True
        return False
    
    def get_user_settings(self, chat_id):
        """Получить настройки пользователя"""
        self.cursor.execute('''
            SELECT us.* FROM user_settings us
            JOIN users u ON u.id = us.user_id
            WHERE u.chat_id = ?
        ''', (chat_id,))
        settings = self.cursor.fetchone()
        
        if settings:
            return dict(settings)
        return {}
    
    # ========== РАБОТА С КЭШЕМ РАСПИСАНИЯ ==========
    
    def cache_schedule(self, group_name, week_number, schedule_data, cache_hours=6):
        """
        Сохраняет расписание в кэш на указанное количество часов
        """
        try:
            # Сериализуем данные в JSON
            schedule_json = json.dumps(schedule_data, ensure_ascii=False, default=str)
            
            # Рассчитываем время истечения
            expires_at = datetime.now() + timedelta(hours=cache_hours)
            
            # Проверяем, есть ли уже запись
            self.cursor.execute(
                "SELECT id FROM schedule_cache WHERE group_name = ? AND week_number = ?",
                (group_name, week_number)
            )
            existing = self.cursor.fetchone()
            
            if existing:
                # Обновляем существующую запись
                self.cursor.execute("""
                    UPDATE schedule_cache 
                    SET schedule_data = ?, expires_at = ?, cached_at = CURRENT_TIMESTAMP
                    WHERE group_name = ? AND week_number = ?
                """, (schedule_json, expires_at, group_name, week_number))
            else:
                # Создаём новую запись
                self.cursor.execute("""
                    INSERT INTO schedule_cache (group_name, week_number, schedule_data, expires_at)
                    VALUES (?, ?, ?, ?)
                """, (group_name, week_number, schedule_json, expires_at))
            
            self.conn.commit()
            logger.info(f"Расписание для группы {group_name} (неделя {week_number}) сохранено в кэш на {cache_hours} ч.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении в кэш: {e}")
            return False
    
    def get_cached_schedule(self, group_name, week_number):
        """
        Получает расписание из кэша, если оно не истекло
        """
        try:
            now = datetime.now()
            
            self.cursor.execute("""
                SELECT schedule_data, expires_at 
                FROM schedule_cache 
                WHERE group_name = ? AND week_number = ? AND expires_at > ?
            """, (group_name, week_number, now))
            
            result = self.cursor.fetchone()
            
            if result:
                schedule_json, expires_at = result
                # Десериализуем JSON
                schedule_data = json.loads(schedule_json)
                
                # Конвертируем строки дат обратно в объекты (если нужно)
                for lesson in schedule_data:
                    # Убеждаемся, что is_real сохраняется
                    lesson['is_real'] = lesson.get('is_real', False)
                
                expires_at_dt = datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else expires_at
                expires_str = expires_at_dt.strftime("%H:%M %d.%m.%Y")
                
                logger.info(f"Расписание для группы {group_name} (неделя {week_number}) получено из кэша, истекает {expires_str}")
                return schedule_data
            else:
                logger.info(f"Расписание для группы {group_name} (неделя {week_number}) не найдено в кэше или истекло")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при получении из кэша: {e}")
            return None
    
    def clear_expired_cache(self):
        """
        Очищает истекшие записи кэша
        """
        try:
            now = datetime.now()
            self.cursor.execute("DELETE FROM schedule_cache WHERE expires_at <= ?", (now,))
            deleted = self.cursor.rowcount
            self.conn.commit()
            if deleted > 0:
                logger.info(f"Очищено {deleted} истекших записей кэша")
            return deleted
        except Exception as e:
            logger.error(f"Ошибка при очистке кэша: {e}")
            return 0


# Создаём глобальный экземпляр менеджера БД
db_manager = DatabaseManager()