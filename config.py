# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Master Bot Token
    MASTER_BOT_TOKEN = os.getenv('MASTER_BOT_TOKEN', 'YOUR_MASTER_BOT_TOKEN_HERE')
    
    # Database
    DB_PATH = os.getenv('DB_PATH', './reactions.db')
    
    # Reaction Settings
    MIN_REACTIONS_PER_POST = int(os.getenv('MIN_REACTIONS_PER_POST', 5))
    MAX_REACTIONS_PER_POST = int(os.getenv('MAX_REACTIONS_PER_POST', 11))
    MIN_DELAY_MINUTES = int(os.getenv('MIN_DELAY_MINUTES', 1))
    MAX_DELAY_MINUTES = int(os.getenv('MAX_DELAY_MINUTES', 30))
    
    # Emoji List
    DEFAULT_EMOJIS = ['👍', '❤️', '🔥', '😂', '😍', '👏', '💯', '🎉', '🤩', '🙌']
    
    # Rate Limiting
    DAILY_LIMIT_PER_BOT = int(os.getenv('DAILY_LIMIT_PER_BOT', 250))
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 10))
    BATCH_PAUSE_SECONDS = int(os.getenv('BATCH_PAUSE_SECONDS', 30))
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', './bot.log')
    
    # Inline Keyboard Settings
    SHOW_EMOJIS_IN_PANEL = os.getenv('SHOW_EMOJIS_IN_PANEL', 'True').lower() == 'true'
    SHOW_STATS_IN_PANEL = os.getenv('SHOW_STATS_IN_PANEL', 'True').lower() == 'true'
