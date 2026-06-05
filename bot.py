# bot.py - основной файл Telegram бота
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
import logging
from database import db_manager
from parser import schedule_parser
import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_today_russian():
    """Возвращает русское название сегодняшнего дня"""
    days = {
        0: 'Понедельник',
        1: 'Вторник', 
        2: 'Среда',
        3: 'Четверг',
        4: 'Пятница',
        5: 'Суббота',
        6: 'Воскресенье'
    }
    today = datetime.datetime.now().weekday()
    return days.get(today, 'Понедельник')

# Преподаватели (пока демо)
DEMO_TEACHERS = ['Иванов И.И.', 'Петрова А.В.', 'Сидоров П.К.']

def get_groups_from_parser():
    """Получает список групп из парсера"""
    return list(schedule_parser.group_aliases.keys())

def get_main_menu(role):
    """Главное меню в зависимости от роли"""
    if role == 'student':
        return [
            ['📅 Расписание на сегодня', '📅 Расписание на неделю'],
            ['↩️ Назад к списку групп', '👤 Мой профиль'],
            ['↩️ Назад к выбору роли', 'ℹ️ Помощь']
        ]
    else:
        return [
            ['📅 Моё расписание сегодня', '📅 Моё расписание на неделю'],
            ['↩️ Назад к списку преподавателей', '👤 Мой профиль'],
            ['↩️ Назад к выбору роли', 'ℹ️ Помощь']
        ]

def get_role_selection_menu():
    """Меню выбора роли"""
    return [['🎓 Я студент', '👨‍🏫 Я преподаватель']]

def start(update, context):
    """Обработчик команды /start"""
    user = update.message.from_user
    
    # Сохраняем/получаем пользователя в БД
    user_data = db_manager.get_or_create_user(
        chat_id=user.id,
        username=user.username,
        first_name=user.first_name
    )
    
    # Показываем меню выбора роли
    show_role_selection(update)

def help_command(update, context):
    """Обработчик команды /help"""
    user = update.message.from_user
    user_data = db_manager.get_or_create_user(user.id)
    
    help_text = (
        '📚 *Доступные команды:*\n\n'
        '*/start* - начать работу\n'
        '*/help* - показать помощь\n'
        '*/profile* - мой профиль\n'
        '*/refresh* - обновить кэш расписания\n\n'
        '🎯 *Быстрые действия через меню:*\n'
    )
    
    if user_data["role"] == 'student':
        help_text += (
            '• 📅 Расписание на сегодня\n'
            '• 📅 Расписание на неделю\n'
            '• ↩️ Назад к списку групп\n'
            '• ↩️ Назад к выбору роли\n'
        )
    else:
        help_text += (
            '• 📅 Моё расписание сегодня\n'
            '• 📅 Моё расписание на неделю\n'
            '• ↩️ Назад к списку преподавателей\n'
            '• ↩️ Назад к выбору роли\n'
        )
    
    update.message.reply_text(help_text, parse_mode='Markdown')

def profile(update, context):
    """Показать профиль пользователя"""
    user = update.message.from_user
    user_data = db_manager.get_or_create_user(user.id)
    settings = db_manager.get_user_settings(user.id)
    
    role_emoji = '🎓' if user_data["role"] == 'student' else '👨‍🏫'
    profile_text = f'{role_emoji} *Твой профиль:*\n• Имя: {user_data["first_name"]}\n• Роль: {user_data["role"]}\n'
    
    if user_data["role"] == 'student' and settings.get('last_group'):
        profile_text += f'• Моя группа: *{settings["last_group"]}*\n'
    elif user_data["role"] == 'teacher' and settings.get('last_teacher'):
        profile_text += f'• Преподаватель: *{settings["last_teacher"]}*\n'
    else:
        profile_text += f'• Группа/преподаватель: *не выбраны*\n'
    
    profile_text += f'• В системе с: {user_data["created_at"][:10]}'
    
    update.message.reply_text(profile_text, parse_mode='Markdown')

def refresh_command(update, context):
    """
    Обработчик команды /refresh - обновление кэша расписания
    """
    user = update.message.from_user
    user_data = db_manager.get_or_create_user(user.id)
    
    # Получаем аргументы команды
    args = context.args
    wait_message = update.message.reply_text("🔄 Обновляю расписание...")
    
    try:
        # Вариант 1: без аргументов - обновляем текущую группу
        if not args:
            settings = db_manager.get_user_settings(user.id)
            
            if user_data["role"] == 'student':
                if not settings.get('last_group'):
                    update.message.reply_text("❌ Сначала выбери группу!")
                    return
                
                group = settings['last_group']
                
                # Получаем свежие данные с сайта (без использования кэша)
                week = schedule_parser.get_current_week()
                schedule_data = schedule_parser.parse_group_schedule(group, use_cache=False)
                
                # Проверяем, что данные реальные (не демо)
                if schedule_data and any(lesson.get('is_real', False) for lesson in schedule_data):
                    # Сохраняем в кэш
                    db_manager.cache_schedule(group, week, schedule_data, cache_hours=6)
                    update.message.reply_text(f"✅ Расписание для группы *{group}* обновлено!", parse_mode='Markdown')
                else:
                    update.message.reply_text(f"⚠️ Не удалось получить свежие данные для группы *{group}* (используется демо)", parse_mode='Markdown')
            
            elif user_data["role"] == 'teacher':
                update.message.reply_text("❌ Для преподавателей обновление пока не реализовано")
        
        # Вариант 2: указана конкретная группа
        elif len(args) == 1:
            group = args[0]
            
            # Проверяем, существует ли такая группа
            if group not in schedule_parser.group_aliases.keys():
                update.message.reply_text(f"❌ Группа *{group}* не найдена", parse_mode='Markdown')
                return
            
            # Получаем свежие данные с сайта (без использования кэша)
            week = schedule_parser.get_current_week()
            schedule_data = schedule_parser.parse_group_schedule(group, use_cache=False)
            
            if schedule_data and any(lesson.get('is_real', False) for lesson in schedule_data):
                db_manager.cache_schedule(group, week, schedule_data, cache_hours=6)
                update.message.reply_text(f"✅ Расписание для группы *{group}* обновлено!", parse_mode='Markdown')
            else:
                update.message.reply_text(f"⚠️ Не удалось получить свежие данные для группы *{group}* (используется демо)", parse_mode='Markdown')
        
        # Неверный формат
        else:
            update.message.reply_text(
                "❓ Неверная команда. Используйте:\n"
                "`/refresh` - обновить текущую группу\n"
                "`/refresh ИСП-8-22` - обновить конкретную группу",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Ошибка в refresh_command: {e}")
        update.message.reply_text(f"❌ Произошла ошибка: {e}")
    
    finally:
        # Удаляем сообщение о ожидании
        context.bot.delete_message(chat_id=update.effective_chat.id, 
                                  message_id=wait_message.message_id)

def schedule_today(update, context):
    """Показать расписание на СЕГОДНЯ"""
    # Показываем статус "печатает"
    update.message.reply_chat_action(action='typing')
    wait_message = update.message.reply_text("🔍 Ищу расписание на сегодня...")
    
    try:
        user = update.message.from_user
        user_data = db_manager.get_or_create_user(user.id)
        settings = db_manager.get_user_settings(user.id)
        
        today_name = get_today_russian()
        
        if user_data["role"] == 'student':
            if not settings.get('last_group'):
                context.bot.delete_message(chat_id=update.effective_chat.id, 
                                          message_id=wait_message.message_id)
                update.message.reply_text("❌ Сначала выбери группу!")
                show_group_selection(update)
                return
            
            # Ещё раз показываем статус, если парсинг долгий
            update.message.reply_chat_action(action='typing')
            
            # Получаем расписание с использованием кэша (6 часов)
            schedule_data = schedule_parser.parse_group_schedule(
                settings['last_group'], 
                use_cache=True, 
                cache_hours=6
            )
            
            # Фильтруем на сегодня
            today_lessons = [lesson for lesson in schedule_data if lesson['day'] == today_name]
            
            # Удаляем сообщение о ожидании
            context.bot.delete_message(chat_id=update.effective_chat.id, 
                                      message_id=wait_message.message_id)
            
            if today_lessons:
                # Показываем, откуда данные
                source = "✅ *Реальное расписание*" if today_lessons[0].get('is_real', False) else "⚠️ *Демо-данные*"
                
                formatted = schedule_parser.format_schedule_for_telegram(
                    today_lessons, 
                    f"📅 Расписание группы {settings['last_group']} на СЕГОДНЯ ({today_name})"
                )
            else:
                formatted = f"🎉 У группы {settings['last_group']} на {today_name} нет занятий!"
                
        else:
            if not settings.get('last_teacher'):
                context.bot.delete_message(chat_id=update.effective_chat.id, 
                                          message_id=wait_message.message_id)
                update.message.reply_text("❌ Сначала выбери преподавателя!")
                show_teacher_selection(update)
                return
                
            # Для преподавателей используем демо-данные
            schedule_data = schedule_parser.parse_teacher_schedule(settings['last_teacher'])
            
            # Фильтруем только сегодняшний день
            today_schedule = [lesson for lesson in schedule_data if lesson['day'] == today_name]
            
            # Удаляем сообщение о ожидании
            context.bot.delete_message(chat_id=update.effective_chat.id, 
                                      message_id=wait_message.message_id)
            
            if today_schedule:
                formatted = f"📅 Расписание преподавателя {settings['last_teacher']} на СЕГОДНЯ ({today_name})\n\n"
                formatted += "⚠️ *Используются демо-данные*\n\n"
                
                for lesson in today_schedule:
                    formatted += f"⏰ {lesson['time']}\n"
                    formatted += f"📚 {lesson['subject']}\n"
                    
                    if lesson.get('group') and lesson['group'].strip():
                        formatted += f"🎓 Группа: {lesson['group']}\n"
                    
                    if lesson.get('classroom') and lesson['classroom'].strip():
                        formatted += f"🚪 {lesson['classroom']}\n"
                    
                    formatted += "─" * 20 + "\n"
            else:
                formatted = f"🎉 У преподавателя {settings['last_teacher']} на {today_name} нет пар!"
        
        update.message.reply_text(formatted, parse_mode='Markdown')
        
    except Exception as e:
        # При ошибке удаляем сообщение о ожидании
        context.bot.delete_message(chat_id=update.effective_chat.id, 
                                  message_id=wait_message.message_id)
        update.message.reply_text(f"❌ Произошла ошибка: {e}")
        logger.error(f"Ошибка в schedule_today: {e}")

def send_long_message(update, text, max_length=4096):
    """Разбивает длинное сообщение на части"""
    if len(text) <= max_length:
        update.message.reply_text(text)
        return
    
    # Разбиваем на части
    parts = []
    current_part = ""
    
    lines = text.split('\n')
    for line in lines:
        if len(current_part + line + '\n') < max_length - 100:
            current_part += line + '\n'
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + '\n'
    
    if current_part:
        parts.append(current_part.strip())
    
    # Отправляем части
    for i, part in enumerate(parts):
        if i == 0:
            update.message.reply_text(part)
        else:
            update.message.reply_text(f"*(продолжение)*\n\n{part}", parse_mode='Markdown')

    logger.info(f"Сообщение разбито на {len(parts)} частей")

def schedule_week(update, context):
    """Показать расписание на неделю"""
    # Показываем статус "печатает"
    update.message.reply_chat_action(action='typing')
    wait_message = update.message.reply_text("🔍 Ищу расписание на неделю...")
    
    try:
        user = update.message.from_user
        user_data = db_manager.get_or_create_user(user.id)
        settings = db_manager.get_user_settings(user.id)
        
        if user_data["role"] == 'student':
            if not settings.get('last_group'):
                context.bot.delete_message(chat_id=update.effective_chat.id, 
                                          message_id=wait_message.message_id)
                update.message.reply_text("❌ Сначала выбери группу!")
                show_group_selection(update)
                return
            
            # Получаем расписание с использованием кэша
            schedule_data = schedule_parser.parse_group_schedule(
                settings['last_group'], 
                use_cache=True, 
                cache_hours=6
            )
            
            # Удаляем сообщение о ожидании
            context.bot.delete_message(chat_id=update.effective_chat.id, 
                                      message_id=wait_message.message_id)
            
            formatted = schedule_parser.format_schedule_for_telegram(
                schedule_data, 
                f"📅 Расписание группы {settings['last_group']} на неделю"
            )
        else:
            if not settings.get('last_teacher'):
                context.bot.delete_message(chat_id=update.effective_chat.id, 
                                          message_id=wait_message.message_id)
                update.message.reply_text("❌ Сначала выбери преподавателя!")
                show_teacher_selection(update)
                return
                
            schedule_data = schedule_parser.parse_teacher_schedule(settings['last_teacher'])
            
            # Удаляем сообщение о ожидании
            context.bot.delete_message(chat_id=update.effective_chat.id, 
                                      message_id=wait_message.message_id)
            
            formatted = schedule_parser.format_teacher_schedule(
                schedule_data, 
                settings['last_teacher']
            )
            # Добавляем заголовок "на неделю"
            formatted = formatted.replace(
                f"👨‍🏫 Расписание преподавателя {settings['last_teacher']}",
                f"📅 Расписание преподавателя {settings['last_teacher']} на неделю"
            )
        
        send_long_message(update, formatted)
        
    except Exception as e:
        context.bot.delete_message(chat_id=update.effective_chat.id, 
                                  message_id=wait_message.message_id)
        update.message.reply_text(f"❌ Произошла ошибка: {e}")
        logger.error(f"Ошибка в schedule_week: {e}")

def show_role_selection(update):
    """Показать выбор роли"""
    keyboard = get_role_selection_menu()
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        '👋 Привет! Я бот для расписания занятий.\n\n'
        'Выбери свою роль:',
        reply_markup=reply_markup
    )

def show_group_selection(update):
    """Показать выбор группы - динамически из парсера"""
    groups = get_groups_from_parser()
    groups.sort()  # Сортируем для красоты
    
    # Создаем ряды по 2 группы
    keyboard = []
    for i in range(0, len(groups), 2):
        if i + 1 < len(groups):
            keyboard.append([groups[i], groups[i + 1]])
        else:
            keyboard.append([groups[i]])
    
    keyboard.append(['↩️ Назад к выбору роли'])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        '🎓 Выбери свою группу:',
        reply_markup=reply_markup
    )

def show_teacher_selection(update):
    """Показать выбор преподавателя"""
    keyboard = [[teacher] for teacher in DEMO_TEACHERS]
    keyboard.append(['↩️ Назад к выбору роли'])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        '👨‍🏫 Выбери преподавателя:',
        reply_markup=reply_markup
    )

def show_main_menu(update, role):
    """Показать главное меню"""
    menu = get_main_menu(role)
    reply_markup = ReplyKeyboardMarkup(menu, resize_keyboard=True)
    update.message.reply_text('Главное меню:', reply_markup=reply_markup)

def handle_role_selection(update, context):
    """Обработка выбора роли и текстовых сообщений"""
    text = update.message.text
    user = update.message.from_user
    user_data = db_manager.get_or_create_user(user.id)
    
    # Получаем актуальный список групп из парсера
    available_groups = get_groups_from_parser()

    # Обработка выбора роли
    if text == '🎓 Я студент':
        db_manager.update_user_role(user.id, 'student')
        show_group_selection(update)
        
    elif text == '👨‍🏫 Я преподаватель':
        db_manager.update_user_role(user.id, 'teacher')
        show_teacher_selection(update)
    
    # Обработка выбора группы для студентов
    elif text in available_groups and user_data["role"] == 'student':
        db_manager.update_user_group(user.id, text)
        update.message.reply_text(f'🎓 Отлично! Группа {text} сохранена.')
        show_main_menu(update, 'student')
    
    # Обработка выбора преподавателя для преподавателей
    elif text in DEMO_TEACHERS and user_data["role"] == 'teacher':
        db_manager.update_user_teacher(user.id, text)
        update.message.reply_text(f'👨‍🏫 Прекрасно! Преподаватель {text} сохранен.')
        show_main_menu(update, 'teacher')
    
    # Обработка главного меню
    elif text == '📅 Расписание на сегодня' or text == '📅 Моё расписание сегодня':
        schedule_today(update, context)
        
    elif text == '📅 Расписание на неделю' or text == '📅 Моё расписание на неделю':
        schedule_week(update, context)
        
    # Обработка кнопок "Назад" из главного меню
    elif text == '↩️ Назад к списку групп':
        show_group_selection(update)
        
    elif text == '↩️ Назад к списку преподавателей':
        show_teacher_selection(update)
        
    elif text == '↩️ Назад к выбору роли':
        show_role_selection(update)
        
    elif text == '👤 Мой профиль':
        profile(update, context)
        
    elif text == 'ℹ️ Помощь':
        help_command(update, context)
    
    else:
        # Если команда не распознана
        update.message.reply_text('Используй кнопки меню для навигации.')

def main():
    """Основная функция"""
    TOKEN = 'Введите сюда свой токен, или возпользуйтесь токеном из моего Дипломного проекта'
    
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Добавляем обработчики
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("profile", profile))
    dispatcher.add_handler(CommandHandler("refresh", refresh_command))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_role_selection))
    
    # Запускаем бота
    logger.info("🤖 Бот запускается...")
    updater.start_polling()
    logger.info("✅ Бот запущен! Для остановки: Ctrl+C")
    updater.idle()

if __name__ == '__main__':
    main()