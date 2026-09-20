# database.py
import aiosqlite
import logging
from datetime import date
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def initialize(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT,
                    react_mode BOOLEAN DEFAULT 1,
                    min_reactions INTEGER DEFAULT 5,
                    max_reactions INTEGER DEFAULT 11,
                    max_delay_minutes INTEGER DEFAULT 30,
                    emoji_list TEXT DEFAULT '👍,❤,🔥,🤣,😍,👏,💯,🎉,🤩,🙏',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS bot_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_token TEXT UNIQUE NOT NULL,
                    bot_username TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    daily_limit INTEGER DEFAULT 250,
                    reactions_today INTEGER DEFAULT 0,
                    last_reset DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS reactions_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    post_id INTEGER NOT NULL,
                    bot_username TEXT NOT NULL,
                    emoji TEXT NOT NULL,
                    success BOOLEAN DEFAULT 1,
                    error_message TEXT,
                    reacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.commit()
            logger.info("Database initialized")

    async def add_channel(self, channel_id: str, channel_name: str = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                'INSERT OR IGNORE INTO channels (channel_id, channel_name) VALUES (?, ?)',
                (str(channel_id), channel_name)
            )
            await db.commit()
            return cur.rowcount > 0

    async def remove_channel(self, channel_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                'DELETE FROM channels WHERE channel_id = ?', (str(channel_id),)
            )
            await db.commit()
            return cur.rowcount > 0

    async def get_channel(self, channel_id: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                'SELECT * FROM channels WHERE channel_id = ?', (str(channel_id),)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_all_channels(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM channels ORDER BY id')
            return [dict(r) for r in await cur.fetchall()]

    async def update_channel_react_mode(self, channel_id: str, mode: bool) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                'UPDATE channels SET react_mode = ? WHERE channel_id = ?',
                (1 if mode else 0, str(channel_id))
            )
            await db.commit()
            return cur.rowcount > 0

    async def update_channel_count(self, channel_id: str, min_r: int, max_r: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                'UPDATE channels SET min_reactions = ?, max_reactions = ? WHERE channel_id = ?',
                (min_r, max_r, str(channel_id))
            )
            await db.commit()
            return cur.rowcount > 0

    async def add_bot_token(self, token: str, username: str,
                            daily_limit: int = 250) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                '''INSERT OR IGNORE INTO bot_tokens
                   (bot_token, bot_username, daily_limit, last_reset)
                   VALUES (?, ?, ?, ?)''',
                (token, username, daily_limit, date.today().isoformat())
            )
            await db.commit()
            return cur.rowcount > 0

    async def count_bots(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute('SELECT COUNT(*) FROM bot_tokens')
            (n,) = await cur.fetchone()
            return n

    async def get_active_bots(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                '''SELECT * FROM bot_tokens
                   WHERE is_active = 1 AND reactions_today < daily_limit'''
            )
            return [dict(r) for r in await cur.fetchall()]

    async def set_bot_active(self, username: str, active: bool) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                'UPDATE bot_tokens SET is_active = ? WHERE bot_username = ?',
                (1 if active else 0, username)
            )
            await db.commit()
            return cur.rowcount > 0

    async def increment_bot_reaction_count(self, bot_username: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                'UPDATE bot_tokens SET reactions_today = reactions_today + 1 '
                'WHERE bot_username = ?',
                (bot_username,)
            )
            await db.commit()
            return cur.rowcount > 0

    async def reset_daily_counts(self) -> int:
        today = date.today().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                '''UPDATE bot_tokens
                   SET reactions_today = 0, last_reset = ?
                   WHERE last_reset IS NULL OR last_reset < ?''',
                (today, today)
            )
            await db.commit()
            if cur.rowcount:
                logger.info(f"Reset daily counters for {cur.rowcount} bots")
            return cur.rowcount

    async def log_reaction(self, channel_id: str, post_id: int,
                           bot_username: str, emoji: str,
                           success: bool = True, error: str = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''INSERT INTO reactions_log
                   (channel_id, post_id, bot_username, emoji, success, error_message)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (str(channel_id), post_id, bot_username, emoji,
                 1 if success else 0, error)
            )
            await db.commit()
            return True

    async def get_stats(self, channel_id: str = None) -> Dict:
        async with aiosqlite.connect(self.db_path) as db:
            if channel_id:
                cur = await db.execute(
                    '''SELECT COUNT(*) AS total,
                              COALESCE(SUM(success), 0) AS successful
                       FROM reactions_log
                       WHERE channel_id = ? AND DATE(reacted_at) = DATE('now')''',
                    (str(channel_id),)
                )
            else:
                cur = await db.execute(
                    '''SELECT COUNT(*) AS total,
                              COALESCE(SUM(success), 0) AS successful
                       FROM reactions_log
                       WHERE DATE(reacted_at) = DATE('now')'''
                )
            total, successful = await cur.fetchone()
            total = total or 0
            successful = successful or 0
            return {
                'total': total,
                'successful': successful,
                'failed': total - successful,
            }
