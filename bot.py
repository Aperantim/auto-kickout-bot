import configparser
import logging
import sys
import sqlite3
import traceback
from datetime import datetime, timedelta
from telegram.ext import Filters, MessageHandler, Updater, CallbackContext
from telegram.error import BadRequest
from apscheduler.schedulers.background import BackgroundScheduler

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание и настройка базы данных
def create_database():
    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER,
            user_id INTEGER,
            join_date TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    connection.commit()
    connection.close()

def add_user_to_db(chat_id, user_id, join_date):
    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (chat_id, user_id, join_date)
        VALUES (?, ?, ?)
    ''', (chat_id, user_id, join_date))
    connection.commit()
    connection.close()

def get_users_to_kick(chat_id, delta):
    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('''
        SELECT user_id FROM users
        WHERE chat_id = ? AND
        julianday('now') - julianday(join_date) > ?
    ''', (chat_id, delta.days))
    users = cursor.fetchall()
    connection.close()
    return [user[0] for user in users]

def remove_user_from_db(chat_id, user_id):
    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('''
        DELETE FROM users WHERE chat_id = ? AND user_id = ?
    ''', (chat_id, user_id))
    connection.commit()
    connection.close()

# Обработчики бота
def error_callback(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def kickout(update, context):
    chat = update.effective_chat
    for new_user in update.effective_message.new_chat_members:
        add_user_to_db(chat.id, new_user.id, datetime.now().isoformat())
        logger.info(f'User {new_user.id} added to chat {chat.id}')

def kick_old_users(context: CallbackContext):
    chat_id = context.job.context
    users_to_kick = get_users_to_kick(chat_id, timedelta(days=7))
    for user_id in users_to_kick:
        try:
            context.bot.ban_chat_member(chat_id, user_id)
            context.bot.unban_chat_member(chat_id, user_id)  # Разбан, чтобы пользователь мог вступить снова
            remove_user_from_db(chat_id, user_id)
            logger.info(f'User {user_id} kicked from chat {chat_id} after 7 days')
        except BadRequest as e:
            logger.error(f'Failed to kick user {user_id} from chat {chat_id}: {e.message}')

def main():
    # Загрузка конфигурации
    config = configparser.ConfigParser()
    config.read('config.ini')

    # Создание базы данных
    create_database()

    # Настройка бота
    updater = Updater(config['BOT']['accesstoken'], use_context=True)
    dp = updater.dispatcher
    dp.add_error_handler(error_callback)
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, kickout))

    # Настройка планировщика для ежедневной проверки и удаления пользователей
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_old_users, 'interval', days=1, args=[updater], misfire_grace_time=3600)
    scheduler.start()

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
