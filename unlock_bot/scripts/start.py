import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from telegram_with_max import App

from unlock_bot.config import get_settings
from unlock_bot.database import Database
from unlock_bot.messaging import BotController, create_router


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_path)
    await asyncio.to_thread(database.initialize)

    app = App(
        telegram_token=settings.telegram_bot_token,
        max_token=settings.max_bot_token,
        telegram_proxy=settings.telegram_proxy,
    )
    controller = BotController(app=app, database=database, settings=settings)
    app.include_router(create_router(controller))
    notifications = asyncio.create_task(controller.notification_loop())
    try:
        await app.run_polling()
    finally:
        notifications.cancel()
        with suppress(asyncio.CancelledError):
            await notifications
        await controller.ad.close()
        await app.close()
        database.engine.dispose()


def start() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    log_directory = Path("Logs")
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=log_directory / f"unlock_bot_{today}.log",
        filemode="a",
        format="[%(asctime)s]:%(levelname)s:\t%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())


if __name__ == "__main__":
    start()
