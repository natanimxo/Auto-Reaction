# reaction_manager.py
import asyncio
import random
import logging
from typing import List, Dict

from telegram import Bot
from telegram.error import TelegramError, RetryAfter, Forbidden, BadRequest

logger = logging.getLogger(__name__)


class ReactionManager:
    def __init__(self, database):
        self.db = database
        self.bot_instances: Dict[str, Dict] = {}
        self.active_jobs: Dict[str, asyncio.Task] = {}

    async def initialize_bots(self) -> int:
        await self.db.reset_daily_counts()
        bots = await self.db.get_active_bots()
        for bot_data in bots:
            token = bot_data['bot_token']
            try:
                bot = Bot(token)
                me = await bot.get_me()
                self.bot_instances[me.username] = {
                    'bot': bot,
                    'username': me.username,
                    'token': token,
                }
                logger.info(f"Bot initialized: @{me.username}")
            except Forbidden:
                logger.error("Bot token forbidden, deactivating.")
                if bot_data.get('bot_username'):
                    await self.db.set_bot_active(bot_data['bot_username'], False)
            except BadRequest:
                logger.error("Bot token invalid, deactivating.")
                if bot_data.get('bot_username'):
                    await self.db.set_bot_active(bot_data['bot_username'], False)
            except Exception as e:
                logger.error(f"Failed to init bot: {e}")
        return len(self.bot_instances)

    async def add_bot(self, token: str) -> str:
        bot = Bot(token)
        me = await bot.get_me()
        await self.db.add_bot_token(token, me.username)
        self.bot_instances[me.username] = {
            'bot': bot,
            'username': me.username,
            'token': token,
        }
        return me.username

    async def shutdown(self):
        for task in list(self.active_jobs.values()):
            task.cancel()
        if self.active_jobs:
            await asyncio.gather(*self.active_jobs.values(), return_exceptions=True)
        self.active_jobs.clear()

    async def schedule_reactions(self, channel_id: str, post_id: int,
                                 post_text: str):
        if '[no-react]' in (post_text or '').lower():
            logger.info(f"[no-react] skipping post {post_id}")
            return

        channel = await self.db.get_channel(channel_id)
        if not channel or not channel['react_mode']:
            logger.info(f"Reactions disabled/unknown for {channel_id}")
            return

        available = list(self.bot_instances.keys())
        if not available:
            logger.error("No bots available")
            return

        num = random.randint(channel['min_reactions'], channel['max_reactions'])
        num = max(1, min(num, len(available)))
        selected = random.sample(available, num)

        emojis = [
            e.strip()
            for e in (channel.get('emoji_list') or '👍,❤️,🔥').split(',')
            if e.strip()
        ] or ['👍']

        delays = self._create_staggered_schedule(num, channel['max_delay_minutes'])

        for i, (bot_user, delay) in enumerate(zip(selected, delays)):
            emoji = random.choice(emojis)
            task = asyncio.create_task(
                self._delayed_reaction(channel_id, post_id, bot_user, emoji, delay)
            )
            job_id = f"{channel_id}_{post_id}_{i}"
            self.active_jobs[job_id] = task
            task.add_done_callback(
                lambda t, jid=job_id: self.active_jobs.pop(jid, None)
            )

    def _create_staggered_schedule(self, n: int, max_delay_minutes: int) -> List[float]:
        max_seconds = max(60, max_delay_minutes * 60)
        schedule: List[float] = []

        if n <= 3:
            for _ in range(n):
                schedule.append(random.uniform(60, min(180, max_seconds)))
        elif n <= 7:
            first = random.randint(1, min(3, n))
            second = n - first
            for _ in range(first):
                schedule.append(random.uniform(60, min(180, max_seconds)))
            for _ in range(second):
                schedule.append(random.uniform(300, min(600, max_seconds)))
        else:
            first = random.randint(1, 3)
            second = random.randint(2, 4)
            third = max(0, n - first - second)
            for _ in range(first):
                schedule.append(random.uniform(60, min(180, max_seconds)))
            for _ in range(second):
                schedule.append(random.uniform(300, min(600, max_seconds)))
            for _ in range(third):
                schedule.append(random.uniform(900, max_seconds))

        schedule = [max(1.0, min(max_seconds, s + random.uniform(2, 5)))
                    for s in schedule]
        schedule.sort()
        while len(schedule) < n:
            schedule.append(max_seconds)
        return schedule[:n]

    async def _delayed_reaction(self, channel_id: str, post_id: int,
                                bot_username: str, emoji: str, delay: float):
        try:
            await asyncio.sleep(delay)

            bot_data = self.bot_instances.get(bot_username)
            if not bot_data:
                logger.error(f"Bot @{bot_username} not in cache")
                return
            bot = bot_data['bot']

            try:
                await bot.set_message_reaction(
                    chat_id=channel_id,
                    message_id=post_id,
                    reaction=[{'type': 'emoji', 'emoji': emoji}],
                )
                await self.db.log_reaction(channel_id, post_id,
                                           bot_username, emoji, True)
                await self.db.increment_bot_reaction_count(bot_username)
                logger.info(f"OK @{bot_username} -> {emoji} on post {post_id}")

            except RetryAfter as e:
                wait = int(getattr(e, 'retry_after', 5)) + 1
                logger.warning(f"Rate-limited @{bot_username}, retry in {wait}s")
                await asyncio.sleep(wait)
                try:
                    await bot.set_message_reaction(
                        chat_id=channel_id, message_id=post_id,
                        reaction=[{'type': 'emoji', 'emoji': emoji}],
                    )
                    await self.db.log_reaction(channel_id, post_id,
                                               bot_username, emoji, True)
                    await self.db.increment_bot_reaction_count(bot_username)
                except Exception as e2:
                    await self.db.log_reaction(channel_id, post_id,
                                               bot_username, emoji, False, str(e2))

            except Forbidden as e:
                logger.error(f"@{bot_username} forbidden - deactivating")
                await self.db.set_bot_active(bot_username, False)
                self.bot_instances.pop(bot_username, None)
                await self.db.log_reaction(channel_id, post_id,
                                           bot_username, emoji, False, f"Forbidden: {e}")

            except BadRequest as e:
                logger.error(f"BadRequest for @{bot_username}: {e}")
                await self.db.log_reaction(channel_id, post_id,
                                           bot_username, emoji, False, f"BadRequest: {e}")

            except TelegramError as e:
                await self.db.log_reaction(channel_id, post_id,
                                           bot_username, emoji, False, str(e))

        except asyncio.CancelledError:
            logger.info(f"Cancelled reaction by @{bot_username}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
