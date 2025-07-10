from unlock_bot.config import settings
from unlock_bot.config.aiogram_collection import types

def get_tg_username(message):
    if message.from_user.username is not None and message.from_user.full_name is not None:
        tg_username = f'@{message.from_user.username} ({message.from_user.full_name})'
    else:
        tg_username = message.from_user.full_name
    return tg_username

def is_command_with_username(message: types.Message):
    return len(message.text.split(' ')) > 1

def clearing_message(message: types.Message):
    msg = message.text
    if list(filter(lambda symbol: symbol in msg, settings.RESTRICTED_SYMBOLS)):
        return ''

    return message.text.split(' ')[0].lower()