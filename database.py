# database.py
import aiosqlite
import json
from datetime import datetime, date
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        
    async def initialize(self):
        """Create database tables if they don't exist"""
        async with aiosqlite.connect(self.db_path) as db:
            # Channels table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT,
                    react_mode BOOLEAN DEFAULT TRUE,
                    min_reactions INTEGER DEFAULT 5,
                    max_reactions INTEGER DEFAULT 11,
                    max_delay_minutes INTEGER DEFAULT 30,
                    emoji_list TEXT DEFAULT '👍,❤️,🔥,😂,😍,👏,💯,🎉,🤩,🙌',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Bot tokens table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS bot_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_token TEXT UNIQUE NOT NULL,
                    bot_username TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    daily_limit INTEGER DEFAULT 250,
                    reactions_today INTEGER DEFAULT 0,
                    last_reset DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Reactions log table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS reactions_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    post_id INTEGER NOT NULL,
                    bot_username TEXT NOT NULL,
                    emoji TEXT NOT NULL,
                    success BOOLEAN DEFAULT TRUE,
                    error_message TEXT,
                    reacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User states table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    state_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, channel_id, state_key)
                )
            ''')
            
            await db.commit()
            logger.info("Database initialized successfully")
    
    # Channel Management
    async def add_channel(self, channel_id: str, channel_name: str = None) -> bool:
        """Add a new channel to monitor"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT OR IGNORE INTO channels (channel_id, channel_name) VALUES (?, ?)',
                    (channel_id, channel_name)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding channel: {e}")
            return False
    
    async def get_channel(self, channel_id: str) -> Optional[Dict]:
        """Get channel settings"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM channels WHERE channel_id = ?',
                (channel_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def update_channel_react_mode(self, channel_id: str, mode: bool) -> bool:
        """Update channel reaction mode"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'UPDATE channels SET react_mode = ? WHERE channel_id = ?',
                    (mode, channel_id)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating channel mode: {e}")
            return False
    
    async def get_all_channels(self) -> List[Dict]:
        """Get all monitored channels"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM channels')
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # Bot Token Management
    async def add_bot_token(self, token: str, username: str = None) -> bool:
        """Add a new bot token"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT OR IGNORE INTO bot_tokens (bot_token, bot_username, last_reset) VALUES (?, ?, ?)',
                    (token, username, date.today().isoformat())
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding bot token: {e}")
            return False
    
    async def get_active_bots(self) -> List[Dict]:
        """Get all active bot tokens"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM bot_tokens WHERE is_active = TRUE AND reactions_today < daily_limit'
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def increment_bot_reaction_count(self, bot_username: str) -> bool:
        """Increment reaction count for a bot"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'UPDATE bot_tokens SET reactions_today = reactions_today + 1 WHERE bot_username = ?',
                    (bot_username,)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error incrementing bot count: {e}")
            return False
    
    # Reaction Logging
    async def log_reaction(self, channel_id: str, post_id: int, bot_username: str, 
                          emoji: str, success: bool = True, error: str = None) -> bool:
        """Log a reaction attempt"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO reactions_log 
                       (channel_id, post_id, bot_username, emoji, success, error_message) 
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (channel_id, post_id, bot_username, emoji, success, error)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error logging reaction: {e}")
            return False
    
    async def get_stats(self, channel_id: str = None) -> Dict:
        """Get reaction statistics"""
        async with aiosqlite.connect(self.db_path) as db:
            if channel_id:
                cursor = await db.execute(
                    '''SELECT COUNT(*) as total, 
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful 
                       FROM reactions_log 
                       WHERE channel_id = ? AND DATE(reacted_at) = DATE('now')''',
                    (channel_id,)
                )
            else:
                cursor = await db.execute(
                    '''SELECT COUNT(*) as total, 
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful 
                       FROM reactions_log 
                       WHERE DATE(reacted_at) = DATE('now')'''
                )
            row = await cursor.fetchone()
            return {
                'total': row[0] or 0,
                'successful': row[1] or 0,
                'failed': (row[0] or 0) - (row[1] or 0)
            }
