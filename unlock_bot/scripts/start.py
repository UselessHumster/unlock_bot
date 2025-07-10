from unlock_bot.telegram import reg_handlers, reg_commands
from unlock_bot.config.aiogram_collection import Dispatcher, MemoryStorage, executor
from unlock_bot.config import bot

import logging

dp = Dispatcher(bot, storage=MemoryStorage())


def start():
    reg_commands(dp)
    reg_handlers(dp)
    logging.basicConfig(level=logging.INFO, filename='Logs/unlock_bot.log', filemode='w',
                        format='[%(asctime)s]:%(levelname)s:\t%(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    executor.start_polling(dp, skip_updates=True)


if __name__ == '__main__':
    start()
