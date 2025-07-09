import os
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

class Settings:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DOMAIN = os.getenv("DOMAIN").lower()
    SEARCH_ZONE = os.getenv("SEARCH_ZONE")
    ADMIN_CHAT = int(os.getenv("ADMIN_CHAT"))


    RESTRICTED_SYMBOLS = ['-', ')', '(', '#', '|', '+', '.', '*', '!',
                          '<', '>', '{', '}', '[', ']', '~', '/', '\\']


settings = Settings()
bot = Bot(token=settings.BOT_TOKEN, parse_mode='HTML')





