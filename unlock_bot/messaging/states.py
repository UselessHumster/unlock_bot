from telegram_with_max import State, StatesGroup


class RegistrationStates(StatesGroup):
    await_email = State()


class ConnectStates(StatesGroup):
    await_upn = State()
