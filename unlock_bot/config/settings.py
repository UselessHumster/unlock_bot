import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    max_bot_token: str
    domains: tuple[str, ...]
    search_zone: str
    admin_chat: int
    database_path: str
    telegram_proxy: str | None = None
    admin_user_ids: tuple[int, ...] = ()
    restricted_symbols: tuple[str, ...] = (
        "'",
        '"',
        ";",
        "=",
        ")",
        "(",
        "#",
        "|",
        "+",
        "*",
        "!",
        "<",
        ">",
        "{",
        "}",
        "[",
        "]",
        "~",
        "/",
        "\\",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "BOT_TOKEN": os.getenv("BOT_TOKEN"),
            "MAX_BOT_TOKEN": os.getenv("MAX_BOT_TOKEN") or os.getenv("MAX_TOKEN"),
            "DOMAINS": os.getenv("DOMAINS"),
            "SEARCH_ZONE": os.getenv("SEARCH_ZONE"),
            "ADMIN_CHAT": os.getenv("ADMIN_CHAT"),
            "DATABASE_PATH": os.getenv("DATABASE_PATH"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        domains = tuple(
            domain.strip().lower()
            for domain in required["DOMAINS"].split(";")
            if domain.strip()
        )
        if not domains:
            raise RuntimeError("DOMAINS must contain at least one domain")

        try:
            admin_chat = int(required["ADMIN_CHAT"])
        except ValueError as error:
            raise RuntimeError("ADMIN_CHAT must be an integer") from error

        return cls(
            telegram_bot_token=required["BOT_TOKEN"],
            max_bot_token=required["MAX_BOT_TOKEN"],
            domains=domains,
            search_zone=required["SEARCH_ZONE"],
            admin_chat=admin_chat,
            database_path=required["DATABASE_PATH"],
            telegram_proxy=os.getenv("BOT_PROXY") or None,
            admin_user_ids=tuple(
                int(value.strip())
                for value in os.getenv("ADMIN_USER_IDS", "").split(",")
                if value.strip()
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
