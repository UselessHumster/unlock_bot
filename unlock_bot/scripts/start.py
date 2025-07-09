from unlock_bot.telegram import reg_handlers, reg_commands
from unlock_bot.config.aiogram_collection import Dispatcher, MemoryStorage, executor
from unlock_bot.config import bot

import logging

dp = Dispatcher(bot, storage=MemoryStorage())


def start():
    reg_handlers(dp)
    reg_commands(dp)
    logging.basicConfig(level=logging.INFO)
    executor.start_polling(dp, skip_updates=True)


if __name__ == '__main__':
    start()
