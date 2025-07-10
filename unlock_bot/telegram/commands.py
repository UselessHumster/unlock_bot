from unlock_bot.config import settings, bot
from unlock_bot.config.aiogram_collection import types, FSMContext, Dispatcher
from unlock_bot.database import get_user_by_tg_id, change_upn, change_san
from unlock_bot.telegram.states import RegStates, ConnectStates
from unlock_bot.telegram.utils import get_tg_username, is_command_with_username, unlock_user
from unlock_bot.ad import is_ad_user_exists, get_locked_users_list


async def command_reg_start(message: types.Message):
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer('Введите вашу рабочую почту')
        await RegStates.await_email.set()
        return
    await message.answer('Вы уже зарегистрированы')


async def command_unlock(message: types.Message):
    user = get_user_by_tg_id(message.from_user.id)
    tg_username = get_tg_username(message)

    if not user:
        await message.answer('Для регистрации используйте команду /start или /reg')
        return

    if not user.upn:
        await message.answer('Для подключения своей учетной записи к боту введите команду /connect <имя пользователя>\n\n'
                             'Например: /connect s_kinzersky')
        return

    await unlock_user(message, tg_username, user.upn)


async def command_connect(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    tg_username = get_tg_username(message)
    user = get_user_by_tg_id(message.from_user.id)




    if not user:
        return

    if current_state is None:
        if user.upn:
            await message.answer('Ваша учетная запись уже подключена')
            return

        if is_command_with_username(message):
            written_upn = message.text.split(' ')[1]

            if not is_ad_user_exists(written_upn):
                msg_to_admin = f'❌Пользователь {tg_username} попытался подключить учетную запись ({written_upn}), но произошла ошибка'
                await bot.send_message(text=msg_to_admin, chat_id=settings.ADMIN_CHAT)
                await message.answer('Такой учетной записи не существует, попробуйте снова')
                return

            change_upn(user, written_upn)
            change_san(user, written_upn)
            await message.answer('Ваша учетная запись подключена')
            msg_to_admin = f'✅Пользователь {tg_username} успешно подключил свою ({written_upn}) учетную запись '
            await bot.send_message(text=msg_to_admin, chat_id=settings.ADMIN_CHAT)


        else:
            await message.answer('Напишите свой логин')
            await ConnectStates.await_upn.set()
            async with state.proxy() as data:
                data['user'] = user

    if current_state == 'ConnectStates:await_upn':
        async with state.proxy() as data:
            user = data['user']
        written_upn = message.text

        if not is_ad_user_exists(written_upn):
            msg_to_admin = f'❌Пользователь {tg_username} попытался подключить учетную запись ({written_upn}), но произошла ошибка'
            await bot.send_message(text=msg_to_admin, chat_id=settings.ADMIN_CHAT)
            await message.answer('Такой учетной записи не существует, попробуйте снова')
            return

        user.connect(written_upn + f'@{settings.DOMAIN}')
        await message.answer('Ваша учетная запись подключена')
        msg_to_admin = f'✅Пользователь {tg_username} успешно подключил свою ({written_upn}) учетную запись '
        await bot.send_message(text=msg_to_admin, chat_id=settings.ADMIN_CHAT)
        await state.finish()


async def command_status(message: types.Message):
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        return

    locked_users = get_locked_users_list()
    locked_txt = 'Сейчас нет заблокированных пользователей'
    if user.permissions == 'admin':
        if locked_users:
            locked_txt = 'Список заблокированных пользователей:\n\n'
            locked_txt += "\n".join(locked_users)


    elif user.permissions == 'guest':
        if user.upn.replace(f'@{settings.DOMAIN}') or user.san in locked_users:
            locked_txt = '❌Ваша учетная запись заблокирована'
        else:
            locked_txt = '✅Ваша учетная запись разблокирована'

    await message.answer(locked_txt)


def reg_commands(dp: Dispatcher):
    dp.register_message_handler(command_reg_start, commands=['start', 'reg'])
    dp.register_message_handler(command_unlock, commands=['unlock'])
    dp.register_message_handler(command_connect, commands=['connect'])
    dp.register_message_handler(command_status, commands=['status'])
