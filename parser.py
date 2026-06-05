# parser.py - исправленный парсер с упорядоченным временем и поддержкой кэша
import requests
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class ChenkParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        self.base_url = "https://pronew.chenk.ru"
        self.group_codes = {
            '8-22': '304', '7-22': '303', '9-22': '298', '6-22': '302', 
            '3-22': '299', '5-22': '300', '2-22': '297', '4-22': '301'
        }
        self.group_aliases = {
            'ИСП-7-22': '7-22', 'ИСП-8-22': '8-22', 'ИСП-9-22': '9-22', 
            'СА-6-22':'6-22', 'ЭП-3-22':'3-22', 'ЭП-5-22':'5-22', 
            'ЭССиС-2-22':'2-22', 'ЭС-4-22':'4-22'
        }
    
    def get_current_week(self):
        """Автоматический расчет номера недели от 1 сентября текущего учебного года"""
        today = datetime.now()
        current_year = today.year
        
        # Определяем учебный год: если сейчас август-декабрь, то год текущий, иначе предыдущий
        if today.month >= 9:  # Сентябрь-Декабрь
            start_date = datetime(current_year, 9, 1)  # 1 сентября текущего года
        else:  # Январь-Август
            start_date = datetime(current_year - 1, 9, 1)  # 1 сентября прошлого года
        
        # Если сегодня до 1 сентября, берем предыдущий учебный год
        if today < start_date:
            start_date = datetime(current_year - 1, 9, 1)
        
        # Вычисляем разницу в неделях
        days_diff = (today - start_date).days
        week_number = (days_diff // 7) + 1  
        
        week_number = max(1, week_number)
        
        logger.info(f"Рассчитан номер недели: {week_number} (с {start_date.strftime('%d.%m.%Y')})")
        return week_number
    
    def parse_group_schedule(self, group_name, use_cache=True, cache_hours=6):
        """
        Получает расписание группы с использованием кэша
        """
        from database import db_manager  # Импортируем здесь, чтобы избежать циклических зависимостей
        
        real_group_name = self.group_aliases.get(group_name, group_name)
        group_code = self.group_codes.get(real_group_name)
        
        if not group_code:
            logger.warning(f"Код группы не найден для {group_name}, используем демо")
            return self.get_demo_schedule(group_name)
        
        week = self.get_current_week()
        
        # Пробуем получить из кэша
        if use_cache:
            cached_data = db_manager.get_cached_schedule(group_name, week)
            if cached_data:
                logger.info(f"Использовано кэшированное расписание для {group_name} (неделя {week})")
                return cached_data
        
        # Если нет в кэше или кэш отключен, парсим с сайта
        logger.info(f"Загружаем РЕАЛЬНОЕ расписание для {real_group_name}, неделя {week}")
        url = f"{self.base_url}/blocks/manage_groups/website/view.php?dep=3&gr={group_code}&week={week}"
        html = self.fetch_schedule(url)
        
        if not html:
            logger.warning(f"Не удалось загрузить расписание для {real_group_name}, используем демо")
            return self.get_demo_schedule(group_name)
        
        schedule_data = self.parse_real_structure(html)
        
        # Если успешно получили данные, сохраняем в кэш
        if schedule_data and any(lesson.get('is_real', False) for lesson in schedule_data):
            db_manager.cache_schedule(group_name, week, schedule_data, cache_hours)
            logger.info(f"Расписание для {group_name} сохранено в кэш на {cache_hours} часов")
        
        # Логируем найденные пары для отладки
        if schedule_data:
            days_count = {}
            for lesson in schedule_data:
                day = lesson['day']
                days_count[day] = days_count.get(day, 0) + 1
            
            logger.info(f"Расписание для {group_name}: найдено {len(schedule_data)} занятий")
            for day, count in days_count.items():
                logger.info(f"  {day}: {count} пар")
        else:
            logger.warning(f"Расписание для {group_name} пустое, используем демо")
            
        return schedule_data if schedule_data else self.get_demo_schedule(group_name)
    
    def parse_teacher_schedule(self, teacher_name):
        """Парсинг расписания для преподавателя - ДЕМО ВЕРСИЯ"""
        logger.info(f"Используем демо-данные для преподавателя {teacher_name}")
        return self.get_demo_teacher_schedule(teacher_name)
    
    def fetch_schedule(self, url):
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Ошибка загрузки {url}: {e}")
            return None
    
    def parse_real_structure(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        schedule_data = []
        
        # Ищем ВСЕ таблицы с расписанием
        tables = soup.find_all('table', class_='timetable')
        logger.info(f"Найдено таблиц расписания: {len(tables)}")
        
        for table in tables:
            # Ищем все ячейки с днями
            day_cells = table.find_all('td')
            logger.info(f"В таблице найдено ячеек с днями: {len(day_cells)}")
            
            for day_cell in day_cells:
                # Получаем название дня
                day_header = day_cell.find('div', class_='dayHeader')
                day_text = day_header.get_text() if day_header else ""
                day_name = self.extract_day_name(day_text)
                
                # Пропускаем пустые дни
                if day_name == "Неизвестный день":
                    continue
                
                logger.info(f"Обрабатываем день: {day_name}")
                
                # Ищем все блоки занятий в этом дне
                lesson_blocks = day_cell.find_all('div', class_='lessonBlock')
                logger.info(f"  Найдено блоков занятий: {len(lesson_blocks)}")
                
                for lesson_block in lesson_blocks:
                    lessons = self.parse_lesson_block(lesson_block, day_name)
                    schedule_data.extend(lessons)
        
        logger.info(f"Всего распарсено занятий: {len(schedule_data)}")
        return schedule_data
    
    def extract_day_name(self, text):
        days = {
            'понедельник': 'Понедельник',
            'вторник': 'Вторник', 
            'среда': 'Среда',
            'четверг': 'Четверг',
            'пятница': 'Пятница',
            'суббота': 'Суббота'
        }
        
        text_lower = text.lower()
        for ru_name, en_name in days.items():
            if ru_name in text_lower:
                return en_name
        
        return "Неизвестный день"
    
    def parse_lesson_block(self, lesson_block, day_name):
        lessons = []
        
        try:
            # Парсим время из блока
            time_data = self.parse_time_from_lesson_block(lesson_block)
            
            # Проверяем, есть ли информация о времени
            if not time_data.get('time'):
                logger.warning(f"  Блок занятия без времени в день {day_name}")
                return lessons
            
            # Ищем ВСЕ блоки с дисциплинами в этом блоке занятия
            disc_blocks = lesson_block.find_all('div', class_='discBlock')
            logger.info(f"    Найдено блоков дисциплин: {len(disc_blocks)}")
            
            if not disc_blocks:
                # Если нет discBlock, возможно это занятие без подгрупп
                lesson = time_data.copy()
                lesson.update({
                    'day': day_name,
                    'is_real': True,
                    'subject': 'Занятие (детали не указаны)',
                    'teacher': '',
                    'classroom': ''
                })
                
                # Проверяем на отмену
                if 'cancelled' in lesson_block.get('class', []):
                    lesson['subject'] += " (ОТМЕНА)"
                elif lesson_block.find('sup', class_='replace'):
                    lesson['subject'] += " (ЗАМЕНА)"
                
                lessons.append(lesson)
                logger.info(f"      Добавлено занятие без деталей: {lesson['time']}")
            else:
                for disc_block in disc_blocks:
                    lesson = time_data.copy()
                    lesson.update({
                        'day': day_name,
                        'is_real': True
                    })
                    
                    # Парсим предмет
                    subject_elem = disc_block.find('div', class_='discHeader')
                    if subject_elem:
                        subject = self.clean_text(subject_elem.get_text())
                        
                        # Проверяем на отмену/замену
                        parent_block = disc_block.parent
                        if parent_block:
                            if 'cancelled' in parent_block.get('class', []):
                                subject += " (ОТМЕНА)"
                            elif parent_block.find('sup', class_='replace'):
                                subject += " (ЗАМЕНА)"
                        
                        # Также проверяем сам disc_block
                        if 'cancelled' in disc_block.get('class', []):
                            subject += " (ОТМЕНА)"
                        elif disc_block.find('sup', class_='replace'):
                            subject += " (ЗАМЕНА)"
                        
                        lesson['subject'] = subject
                    else:
                        lesson['subject'] = 'Занятие'
                    
                    # Парсим преподавателей и аудитории
                    teachers = []
                    classrooms = []
                    
                    # Ищем ВСЕ подгруппы
                    subgroups = disc_block.find_all('div', class_='discSubgroup')
                    if subgroups:
                        for subgroup in subgroups:
                            # Преподаватель
                            teacher_elem = subgroup.find('div', class_='discSubgroupTeacher')
                            if teacher_elem:
                                teacher = self.clean_text(teacher_elem.get_text())
                                if teacher and teacher not in teachers:
                                    teachers.append(teacher)
                            
                            # Аудитория
                            classroom_elem = subgroup.find('div', class_='discSubgroupClassroom')
                            if classroom_elem:
                                classroom = self.clean_text(classroom_elem.get_text())
                                if classroom and classroom not in classrooms:
                                    classrooms.append(classroom)
                    else:
                        # Если нет подгрупп, ищем информацию в самом disc_block
                        teacher_elem = disc_block.find('div', class_='discSubgroupTeacher')
                        if teacher_elem:
                            teacher = self.clean_text(teacher_elem.get_text())
                            if teacher:
                                teachers.append(teacher)
                        
                        classroom_elem = disc_block.find('div', class_='discSubgroupClassroom')
                        if classroom_elem:
                            classroom = self.clean_text(classroom_elem.get_text())
                            if classroom:
                                classrooms.append(classroom)
                    
                    if teachers:
                        lesson['teacher'] = ', '.join(teachers)
                    if classrooms:
                        lesson['classroom'] = ', '.join(classrooms)
                    
                    # Добавляем занятие если есть время и предмет
                    if lesson.get('time') and lesson.get('subject'):
                        lessons.append(lesson)
                        logger.info(f"      Добавлено занятие: {lesson['time']} - {lesson['subject'][:30]}...")
                    
        except Exception as e:
            logger.error(f"Ошибка парсинга блока: {e}")
        
        return lessons
    
    def parse_time_from_lesson_block(self, lesson_block):
        """Парсим время из блока занятия"""
        time_data = {}
        
        time_block = lesson_block.find('div', class_='lessonTimeBlock')
        if time_block:
            # Номер пары
            number_elem = time_block.find('div', class_='lessonTimeBlockNumber')
            if number_elem:
                number_text = self.clean_text(number_elem.get_text())
                # Извлекаем номер из текста (например, "1 пара" -> "1")
                number_match = re.search(r'\d+', number_text)
                if number_match:
                    time_data['lesson_number'] = number_match.group()
                else:
                    time_data['lesson_number'] = number_text
            
            # Время начала и окончания - ищем все div внутри time_block
            time_divs = time_block.find_all('div')
            
            # Обычно структура: [номер, время_начала, время_окончания]
            start_time = None
            end_time = None
            
            for div in time_divs:
                div_text = self.clean_text(div.get_text())
                # Проверяем, содержит ли текст время в формате ЧЧ:ММ
                if re.match(r'\d{1,2}[\.:]\d{2}', div_text):
                    if not start_time:
                        start_time = div_text
                    elif not end_time:
                        end_time = div_text
            
            # Если не нашли через отдельные div, ищем весь текст
            if not start_time:
                time_text = time_block.get_text()
                times = re.findall(r'(\d{1,2}[\.:]\d{2})', time_text)
                if len(times) >= 2:
                    start_time = times[0]
                    end_time = times[1]
            
            if start_time and end_time:
                start = self.fix_time_format(start_time)
                end = self.fix_time_format(end_time)
                time_data['time'] = f"{start}-{end}"
                logger.info(f"      Распарсено время: {time_data['time']}")
        
        return time_data
    
    def fix_time_format(self, time_str):
        """Исправляем формат времени"""
        if not time_str or time_str == '??-??':
            return "??:??"
        
        # Заменяем точки на двоеточия
        time_str = time_str.replace('.', ':')
        
        # Убираем лишние символы, оставляем только цифры и двоеточие
        time_str = re.sub(r'[^\d:]', '', time_str)
        
        # Проверяем формат ЧЧ:ММ
        if re.match(r'\d{1,2}:\d{2}', time_str):
            # Дополняем часы ведущим нулем если нужно
            parts = time_str.split(':')
            if len(parts[0]) == 1:
                parts[0] = '0' + parts[0]
            return f"{parts[0]}:{parts[1]}"
        
        return "??:??"
    
    def clean_text(self, text):
        """Очистка текста"""
        if not text:
            return ""
        
        # Заменяем множественные пробелы и переносы строк
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def get_demo_schedule(self, group_name):
        """Демо-расписание для групп с 5-6 парами для теста"""
        logger.info(f"Генерируем демо-расписание для {group_name}")
        return [
            {
                'day': 'Понедельник', 
                'time': '08:30-10:00', 
                'subject': 'Информатика (ДЕМО)', 
                'teacher': 'Петров А.В.', 
                'classroom': 'каб. 301', 
                'is_real': False
            },
            {
                'day': 'Понедельник', 
                'time': '10:15-11:45', 
                'subject': 'Математика (ДЕМО)', 
                'teacher': 'Иванова М.К.', 
                'classroom': 'каб. 205', 
                'is_real': False
            },
            {
                'day': 'Понедельник', 
                'time': '12:15-13:45', 
                'subject': 'Физика (ДЕМО)', 
                'teacher': 'Сидоров П.П.', 
                'classroom': 'каб. 112', 
                'is_real': False
            },
            {
                'day': 'Вторник', 
                'time': '08:30-10:00', 
                'subject': 'Базы данных (ДЕМО)', 
                'teacher': 'Петров А.В.', 
                'classroom': 'каб. 301', 
                'is_real': False
            },
            {
                'day': 'Вторник', 
                'time': '10:15-11:45', 
                'subject': 'Веб-программирование (ДЕМО)', 
                'teacher': 'Иванова М.К.', 
                'classroom': 'каб. 205', 
                'is_real': False
            },
            {
                'day': 'Вторник', 
                'time': '12:15-13:45', 
                'subject': 'Английский язык (ДЕМО)', 
                'teacher': 'Смирнова Е.В.', 
                'classroom': 'каб. 308', 
                'is_real': False
            },
            {
                'day': 'Среда', 
                'time': '14:00-15:30', 
                'subject': 'Практика (ДЕМО) (ОТМЕНА)', 
                'teacher': 'Петров А.В.', 
                'classroom': 'каб. 301', 
                'is_real': False
            },
            {
                'day': 'Четверг', 
                'time': '08:30-10:00', 
                'subject': 'Информатика (ДЕМО)', 
                'teacher': 'Петров А.В.', 
                'classroom': 'каб. 301', 
                'is_real': False
            },
            {
                'day': 'Четверг', 
                'time': '10:15-11:45', 
                'subject': 'Математика (ДЕМО) (ЗАМЕНА)', 
                'teacher': 'Иванова М.К.', 
                'classroom': 'каб. 205', 
                'is_real': False
            },
            {
                'day': 'Четверг', 
                'time': '12:15-13:45', 
                'subject': 'Физика (ДЕМО)', 
                'teacher': 'Сидоров П.П.', 
                'classroom': 'каб. 112', 
                'is_real': False
            },
            {
                'day': 'Пятница', 
                'time': '14:00-15:30', 
                'subject': 'Информатика (ДЕМО) (5 пара)', 
                'teacher': 'Петров А.В.', 
                'classroom': 'каб. 301', 
                'is_real': False
            },
            {
                'day': 'Пятница', 
                'time': '15:45-17:15', 
                'subject': 'Информатика (ДЕМО) (6 пара)', 
                'teacher': 'Петров А.В.', 
                'classroom': 'каб. 301', 
                'is_real': False
            },
            {
                'day': 'Суббота', 
                'time': '08:30-10:00', 
                'subject': 'Доп. занятия (ДЕМО)', 
                'teacher': 'Иванова М.К.', 
                'classroom': 'каб. 205', 
                'is_real': False
            }
        ]
    
    def get_demo_teacher_schedule(self, teacher_name):
        """Демо-расписание для преподавателей"""
        return [
            {
                'day': 'Понедельник', 
                'time': '08:30-10:00', 
                'subject': 'Мобильная разработка (ДЕМО)', 
                'group': 'ИСП-7-22', 
                'classroom': 'комп. класс 3', 
                'is_real': False
            },
            {
                'day': 'Понедельник', 
                'time': '10:15-11:45', 
                'subject': 'Веб-разработка (ДЕМО)', 
                'group': 'ИСП-8-22', 
                'classroom': 'комп. класс 1', 
                'is_real': False
            },
            {
                'day': 'Вторник', 
                'time': '12:15-13:45', 
                'subject': 'Базы данных (ДЕМО) (ОТМЕНА)', 
                'group': 'ИСП-9-22', 
                'classroom': 'комп. класс 2', 
                'is_real': False
            }
        ]

    def format_schedule_for_telegram(self, schedule_data, title="📅 Расписание"):
        """Основное форматирование расписания с проверкой длины"""
        if not schedule_data:
            return "❌ Расписание не найдено\n\n⚠️ Используются демо-данные"
        
        is_real = any(lesson.get('is_real', False) for lesson in schedule_data)
        formatted = f"{title}\n\n"
        formatted += "✅ *Реальное расписание*\n\n" if is_real else "⚠️ *Демо-данные*\n\n"
        
        # Группируем по дням
        days = {}
        for lesson in schedule_data:
            day = lesson['day']
            if day not in days:
                days[day] = []
            days[day].append(lesson)
        
        # Сортируем дни в правильном порядке
        day_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        
        for day in day_order:
            if day in days:
                formatted += f"\n📅 *{day}*\n"
                
                # Упорядочиваем занятия по времени
                day_lessons = sorted(days[day], key=lambda x: self.parse_time_for_sorting(x.get('time', '')))
                
                for lesson in day_lessons:
                    # Добавляем номер пары если есть
                    if lesson.get('lesson_number') and lesson['lesson_number'].strip():
                        formatted += f"*{lesson['lesson_number']}.* "
                    
                    formatted += f"⏰ {lesson['time']}\n"
                    formatted += f"📚 {lesson['subject']}\n"
                    
                    if lesson.get('teacher') and lesson['teacher'].strip():
                        formatted += f"👨‍🏫 {lesson['teacher']}\n"
                    
                    if lesson.get('classroom') and lesson['classroom'].strip():
                        formatted += f"🚪 {lesson['classroom']}\n"
                    
                    formatted += "─" * 20 + "\n"
        
        # Проверка длины
        if len(formatted) > 3500:
            logger.warning(f"Расписание слишком длинное ({len(formatted)} символов), используем компактный формат")
            return self.format_schedule_compact(schedule_data, title)
        
        return formatted

    def format_schedule_compact(self, schedule_data, title="📅 Расписание"):
        """Компактное форматирование для длинных расписаний"""
        if not schedule_data:
            return "❌ Расписание не найдено"
        
        is_real = any(lesson.get('is_real', False) for lesson in schedule_data)
        formatted = f"{title}\n"
        formatted += "✅ *Реальное расписание*\n\n" if is_real else "⚠️ *Демо-данные*\n\n"
        formatted += "*Компактный формат:*\n\n"
        
        # Группируем по дням
        days = {}
        for lesson in schedule_data:
            day = lesson['day']
            if day not in days:
                days[day] = []
            days[day].append(lesson)
        
        day_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        
        for day in day_order:
            if day in days:
                formatted += f"*{day}:*\n"
                
                # Упорядочиваем занятия по времени
                day_lessons = sorted(days[day], key=lambda x: self.parse_time_for_sorting(x.get('time', '')))
                
                for lesson in day_lessons:
                    # Компактный формат: Время - Предмет (Преподаватель, Аудитория)
                    line = f"• {lesson['time']} - {lesson['subject']}"
                    
                    if lesson.get('teacher') and lesson['teacher'].strip():
                        line += f" ({lesson['teacher']}"
                        if lesson.get('classroom') and lesson['classroom'].strip() and lesson['classroom'] != '???':
                            line += f", {lesson['classroom']})"
                        else:
                            line += ")"
                    elif lesson.get('classroom') and lesson['classroom'].strip() and lesson['classroom'] != '???':
                        line += f" ({lesson['classroom']})"
                    
                    formatted += line + "\n"
                
                formatted += "\n"
        
        if len(formatted) > 4000:
            formatted = formatted[:4000] + "\n\n... (расписание обрезано)"
        
        return formatted

    def format_teacher_schedule(self, schedule_data, teacher_name):
        """Форматирование расписания преподавателя"""
        if not schedule_data:
            return f"❌ Расписание для преподавателя {teacher_name} не найдено\n\n⚠️ Используются демо-данные"
        
        formatted = f"👨‍🏫 Расписание преподавателя {teacher_name}\n\n"
        formatted += "⚠️ *Используются демо-данные*\n\n"
        
        # Группируем по дням
        days = {}
        for lesson in schedule_data:
            day = lesson['day']
            if day not in days:
                days[day] = []
            days[day].append(lesson)
        
        day_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        
        for day in day_order:
            if day in days:
                formatted += f"\n📅 {day}\n"
                
                # Упорядочиваем занятия по времени
                day_lessons = sorted(days[day], key=lambda x: self.parse_time_for_sorting(x.get('time', '')))
                
                for lesson in day_lessons:
                    formatted += f"⏰ {lesson['time']}\n"
                    formatted += f"📚 {lesson['subject']}\n"
                    
                    if lesson.get('group') and lesson['group'].strip():
                        formatted += f"🎓 Группа: {lesson['group']}\n"
                    
                    if lesson.get('classroom') and lesson['classroom'].strip():
                        formatted += f"🚪 {lesson['classroom']}\n"
                    
                    formatted += "─" * 20 + "\n"
        
        return formatted

    def parse_time_for_sorting(self, time_str):
        """Парсим время для корректной сортировки"""
        if not time_str or '??' in time_str:
            return '99:99'  # Ставим в конец при неизвестном времени
        
        # Извлекаем время начала (первая часть до '-')
        start_time = time_str.split('-')[0].strip()
        
        # Преобразуем в формат для сортировки (HH:MM)
        try:
            # Проверяем, есть ли двоеточие
            if ':' in start_time:
                hours, minutes = start_time.split(':')
                return f"{int(hours):02d}:{int(minutes):02d}"
            else:
                return '99:99'
        except Exception as e:
            logger.error(f"Ошибка парсинга времени для сортировки: {time_str}, {e}")
            return '99:99'


# Инициализируем парсер
schedule_parser = ChenkParser()
logger.info("✅ Парсер инициализирован с упорядоченным временем")