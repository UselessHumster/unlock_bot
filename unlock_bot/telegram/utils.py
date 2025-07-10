import logging

from unlock_bot.config import settings
from unlock_bot.config.aiogram_collection import types
from unlock_bot.ad import get_ad_user_by_upn

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
    logging.info(f'User sent message {msg=}. Checking for restricted symbols')
    if restricted := list(filter(lambda symbol: symbol in msg, settings.RESTRICTED_SYMBOLS)):
        logging.info(f'Found {restricted=} in {msg=}, return empty string')
        return ''
    logging.info('Restricted symbols not found, clearing message')
    cleared_message = msg.split(' ')[0].lower()
    logging.info(f'{cleared_message=}')
    return cleared_message


async def unlock_user(message, tg_username, upn):
    try:
        ad_user = get_ad_user_by_upn(upn)
        ad_user.unlock()
    except Exception as exception:
        logging.warn(f'Error at unlocking AD User {exception=}')
        await message.answer('❌ Произошла ошибка, попробуйте снова')
        await message.bot.send_message(text=f'❌ Пользователь {tg_username} попытался разблокировать {message.text=}, но произошла ошибка\n\n'
                                    f'{exception.__str__()}', chat_id=settings.ADMIN_CHAT)
    else:
        msg_to_user = f'✅ Учетная запись {upn} успешно разблокирована'
        msg_to_admin = f' успешно разблокировал {upn} ✅'
        text_for_admin = f'Пользователь {tg_username} с ID {str(message.from_user.id)} {msg_to_admin}'
        await message.answer(msg_to_user)
        await message.bot.send_message(text=text_for_admin, chat_id=settings.ADMIN_CHAT)