import os
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

class Settings:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DOMAINS = list(map(lambda d: d.lower(), os.getenv("DOMAINS").split(';')))
    SEARCH_ZONE = os.getenv("SEARCH_ZONE")
    ADMIN_CHAT = int(os.getenv("ADMIN_CHAT"))
    DATABASE_PATH = os.getenv("DATABASE_PATH")


    RESTRICTED_SYMBOLS = ['-', ')', '(', '#', '|', '+', '*', '!',
                          '<', '>', '{', '}', '[', ']', '~', '/', '\\']


settings = Settings()
bot = Bot(token=settings.BOT_TOKEN, parse_mode='HTML')





