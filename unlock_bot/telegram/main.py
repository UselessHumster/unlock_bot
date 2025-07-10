import logging
from unlock_bot.config.aiogram_collection import types, FSMContext, Dispatcher, Text, ContentType
from unlock_bot.config import bot, settings
from unlock_bot.telegram.utils import get_tg_username, clearing_message, unlock_user
from unlock_bot.telegram.states import RegStates
from unlock_bot.database import get_user_by_tg_id, create_user
from unlock_bot.active_directory import is_ad_user_exists




async def main_stream(message: types.Message):
    user = get_user_by_tg_id(message.from_user.id)
    tg_username = get_tg_username(message)
    if not user:
        await bot.send_message(
            text=f'Пользователь {tg_username} без прав доступа написал мне - "{message.text}"', chat_id=set)
        await message.answer('У Вас не хватает прав доступа')
        return

    written_upn = clearing_message(message)
    await unlock_user(message, tg_username, written_upn)




async def registering(message: types.Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state == 'RegStates:await_email':
        if f"@{settings.DOMAIN}" not in message.text.lower():
            await message.answer('Вы указали почту неправильно, попробуйте ещё раз')
            return

        email = clearing_message(message)
        if not is_ad_user_exists(email):
            await message.answer('Такого пользователя не существует, проверьте правильность написания почты, '
                                 'или если у вас менялась фамилия - укажите почту с использованием старой фамилии')
            return

        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.insert(types.InlineKeyboardButton(text='Да', callback_data=f'reg_yes_{message.text.lower()}_{message.from_user.id}'))
        keyboard.insert(types.InlineKeyboardButton(text='Нет', callback_data=f'reg_no_{message.text.lower()}_{message.from_user.id}'))

        tg_username = get_tg_username(message)

        await bot.send_message(text=f'Пользователь {tg_username} с ID {str(message.from_user.id)} хочет подключить учетную запись '
                                    f'{message.text.lower()} к своему аккаунту. Принять? @n1popov', chat_id=settings.ADMIN_CHAT, reply_markup=keyboard)
        await message.answer('Я отослал данные администраторам, пожалуйста, дождитесь их решения о принятии вас в белый список. Я сообщу вам!')
        await state.finish()


async def admin_decision_handler(call: types.CallbackQuery):
    action = call.data.split('_')[1]
    user_id = int(call.data.split('_')[3])
    upn = call.data.split('_')[2]
    if action == 'yes':
        create_user(user_id, upn=upn, san=upn)
        await bot.send_message(text='✅Вы успешно зарегистрированы\n\n Чтобы разблокировать свою учетную запись нажмите на сюда ---> /unlock \n'
                                    'Либо вы можете воспользоваться кнопкой "Меню" в переписке со мной и нажать "Разблокировать"', chat_id=user_id)
        await call.message.edit_text(f'✅Пользователь успешно зарегистрирован ({upn})')
    else:
        await call.message.edit_text(text=f'❌Пользователь НЕ зарегистрирован ({upn})')
        await bot.send_message(text='❌Администратор отказал вам в регистрации. Если вы считаете что это ошибка - попробуйте снова и напишите /start', chat_id=user_id)


def reg_handlers(dp: Dispatcher):
    dp.register_message_handler(registering, state=RegStates.await_email, content_types=ContentType.ANY)
    dp.register_message_handler(registering, state=RegStates.await_code, content_types=ContentType.ANY)

    dp.register_callback_query_handler(admin_decision_handler, Text(startswith='reg'))

    dp.register_message_handler(main_stream)

