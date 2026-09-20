# config.py
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    MASTER_BOT_TOKEN = os.getenv('MASTER_BOT_TOKEN', '')
    ADMIN_USER_IDS = [
        int(x) for x in os.getenv('ADMIN_USER_IDS', '').split(',') if x.strip().isdigit()
    ]

    DB_PATH = os.getenv('DB_PATH', './reactions.db')

    MIN_REACTIONS_PER_POST = int(os.getenv('MIN_REACTIONS_PER_POST', 5))
    MAX_REACTIONS_PER_POST = int(os.getenv('MAX_REACTIONS_PER_POST', 11))
    MIN_DELAY_MINUTES = int(os.getenv('MIN_DELAY_MINUTES', 1))
    MAX_DELAY_MINUTES = int(os.getenv('MAX_DELAY_MINUTES', 30))

    DEFAULT_EMOJIS = ['👍', '❤', '🔥', '🤣', '😍', '👏', '💯', '🎉', '🤩', '🙏']

    DAILY_LIMIT_PER_BOT = int(os.getenv('DAILY_LIMIT_PER_BOT', 250))
    MAX_BOTS = int(os.getenv('MAX_BOTS', 50))

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', './bot.log')

    @classmethod
    def validate(cls):
        if not cls.MASTER_BOT_TOKEN or ':' not in cls.MASTER_BOT_TOKEN:
            raise RuntimeError("MASTER_BOT_TOKEN is missing or malformed.")
        if not cls.ADMIN_USER_IDS:
            raise RuntimeError("ADMIN_USER_IDS is empty - refusing to start.")
