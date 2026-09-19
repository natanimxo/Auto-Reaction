# main.py
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sys

from config import Config
from database import Database
from reaction_manager import ReactionManager
from master_bot import MasterBot


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(
                Config.LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5
            ),
            logging.StreamHandler(sys.stdout),
        ]
    )


async def async_main():
    setup_logging()
    logger = logging.getLogger(__name__)

    Config.validate()
    logger.info("Config validated")

    db = Database(Config.DB_PATH)
    await db.initialize()

    reaction_manager = ReactionManager(db)
    bot_count = await reaction_manager.initialize_bots()
    logger.info(f"Initialized {bot_count} reaction bots")

    master_bot = MasterBot(Config, db, reaction_manager)
    await master_bot.initialize()

    return master_bot


def main():
    master_bot = asyncio.run(async_main())
    master_bot.run()


if __name__ == "__main__":
    main()
