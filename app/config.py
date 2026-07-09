import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_manager_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            raise ValueError(f"Invalid Telegram user ID in MANAGER_TELEGRAM_IDS: {item}")
    return ids


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    manager_telegram_ids: set[int]
    database_url: str
    timezone: str
    daily_send_time: str
    send_delay_seconds: float
    default_reminder_message: str


def get_settings() -> Settings:
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is missing. Add it to .env')

    return Settings(
        telegram_bot_token=token,
        manager_telegram_ids=_parse_manager_ids(os.getenv('MANAGER_TELEGRAM_IDS', '')),
        database_url=os.getenv('DATABASE_URL', 'sqlite:///reminder_bot.db'),
        timezone=os.getenv('TIMEZONE', 'Asia/Dubai'),
        daily_send_time=os.getenv('DAILY_SEND_TIME', '10:00'),
        send_delay_seconds=float(os.getenv('SEND_DELAY_SECONDS', '1.2')),
        default_reminder_message=os.getenv(
            'DEFAULT_REMINDER_MESSAGE',
            'Good morning,\n\nThis is a gentle reminder regarding the pending payment settlement.\n\nKindly arrange the payment at your earliest convenience.\n\nThank you.'
        ).replace('\\n', '\n'),
    )
