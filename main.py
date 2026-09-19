# main.py
import logging
from logging.handlers import RotatingFileHandler
import sys

from config import Config
from database import Database
from reaction_manager import ReactionManager
from master_bot import MasterBot

import asyncio


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


async def async_setup():
    """Do all async setup WITHOUT running the bot's event loop."""
    logger = logging.getLogger(__name__)

    Config.validate()
    logger.info("Config validated")

    db = Database(Config.DB_PATH)
    await db.initialize()

    reaction_manager = ReactionManager(db)
    bot_count = await reaction_manager.initialize_bots()
    logger.info(f"Initialized {bot_count} reaction bots")

    master_bot = MasterBot(Config, db, reaction_manager)
    # Initialize the Application object (this is sync-ish, safe to await)
    await master_bot.initialize()

    return master_bot


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    # Run our own async setup in a temporary loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        master_bot = loop.run_until_complete(async_setup())
    finally:
        # We're done with this temp loop; close it before PTB takes over
        loop.close()

    # Now hand control to PTB's run_polling(), which creates ITS OWN loop
    master_bot.run()


if __name__ == "__main__":
    main()
