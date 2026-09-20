import logging
from logging.handlers import RotatingFileHandler
import sys

from config import Config
from database import Database
from reaction_manager import ReactionManager
from master_bot import MasterBot


def setup_logging():
    logging.basicConfig(
        level=getattr(Config, "LOG_LEVEL", logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(
                Config.LOG_FILE,
                maxBytes=10 * 1024 * 1024,
                backupCount=5
            ),
            logging.StreamHandler(sys.stdout),
        ]
    )
    # httpx logs each request URL at INFO, and Bot API URLs look like
    # https://api.telegram.org/bot<TOKEN>/getUpdates, so the token would land in
    # every log line. WARNING hides successful requests but keeps real problems.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    Config.validate()
    logger.info("Config validated")

    db = Database(Config.DB_PATH)

    reaction_manager = ReactionManager(db)

    master_bot = MasterBot(
        config=Config,
        database=db,
        reaction_manager=reaction_manager
    )

    logger.info("Starting master bot...")
    master_bot.run()


if __name__ == "__main__":
    main()
