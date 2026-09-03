# main.py
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sys
from config import Config
from database import Database
from reaction_manager import ReactionManager
from master_bot import MasterBot

# Setup logging
def setup_logging():
    """Configure logging"""
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(
                Config.LOG_FILE,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            ),
            logging.StreamHandler(sys.stdout)
        ]
    )

async def main():
    """Main entry point"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("Starting Auto-Reaction Bot System...")
    
    # Initialize database
    db = Database(Config.DB_PATH)
    await db.initialize()
    
    # Initialize reaction manager
    reaction_manager = ReactionManager(db)
    bot_count = await reaction_manager.initialize_bots()
    logger.info(f"Initialized {bot_count} reaction bots")
    
    # Initialize master bot
    master_bot = MasterBot(Config, db, reaction_manager)
    await master_bot.initialize()
    
    # Start master bot
    await master_bot.run()

if __name__ == "__main__":
    asyncio.run(main())
