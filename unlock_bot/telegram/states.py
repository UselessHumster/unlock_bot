from unlock_bot.config.aiogram_collection import State, StatesGroup

class RegStates(StatesGroup):
    await_email = State()
    await_code = State()


class ConnectStates(StatesGroup):
    await_upn = State()