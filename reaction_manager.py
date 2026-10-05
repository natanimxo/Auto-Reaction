# reaction_manager.py
import asyncio
import math
import random
import logging
from typing import List, Dict

from telegram import Bot, ReactionTypeEmoji
from telegram.constants import ReactionEmoji
from telegram.error import TelegramError, RetryAfter, Forbidden, BadRequest

logger = logging.getLogger(__name__)

# Default minimum spacing (seconds) between two reactions on the same post, so
# they don't all land within the same minute or two. Deployments override it with
# the MIN_REACTION_GAP_SECONDS env var (config.py -> main.py -> ReactionManager).
MIN_GAP_SECONDS = 90

# Telegram only accepts a fixed set of emoji as reactions. Compare against the
# enum's values, exactly as PTB itself does.
VALID_REACTION_EMOJIS = set(ReactionEmoji)


def normalize_emojis(emojis: List[str]) -> List[str]:
    """Make an emoji list safe for set_message_reaction.

    - strips U+FE0F (variation selector): "\u2764\ufe0f" is not valid, "\u2764" is
    - drops anything Telegram doesn't allow as a reaction
    - falls back to thumbs-up if nothing valid remains
    Applied at send time so old DB rows keep working without a migration.
    """
    cleaned = [e.replace("\ufe0f", "").strip() for e in emojis]
    valid = [e for e in cleaned if e in VALID_REACTION_EMOJIS]
    return valid or ["\U0001F44D"]


class ReactionManager:
    def __init__(self, database, min_gap_seconds: int = MIN_GAP_SECONDS):
        self.db = database
        self.min_gap_seconds = max(0, int(min_gap_seconds))
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

        emojis = normalize_emojis([
            e.strip()
            for e in (channel.get('emoji_list') or '👍,❤,🔥').split(',')
            if e.strip()
        ])

        delays = self._create_staggered_schedule(num, channel['max_delay_minutes'])

        plan = []
        for i, (bot_user, delay) in enumerate(zip(selected, delays)):
            emoji = random.choice(emojis)
            plan.append(f"{bot_user}@{delay:.0f}s")
            task = asyncio.create_task(
                self._delayed_reaction(channel_id, post_id, bot_user, emoji, delay)
            )
            job_id = f"{channel_id}_{post_id}_{i}"
            self.active_jobs[job_id] = task
            task.add_done_callback(
                lambda t, jid=job_id: self.active_jobs.pop(jid, None)
            )

        # Immediate proof that scheduling ran (the first "OK" is >= 60s away).
        logger.info(
            f"Scheduled {num} reactions for post {post_id} in {channel_id}: "
            + " ".join(plan)
        )

    def min_window_minutes(self, n: int) -> int:
        """Smallest max-delay window (whole minutes) that can honour the minimum
        gap for n reactions: the first can't land before 60s, then (n - 1) gaps.
        Used by the scheduler's warning and by the delay/count pickers in the UI.
        """
        return math.ceil((60 + (max(1, n) - 1) * self.min_gap_seconds) / 60)

    def _create_staggered_schedule(self, n: int, max_delay_minutes: int) -> List[float]:
        max_seconds = max(60, max_delay_minutes * 60)
        gap = self.min_gap_seconds

        # Feasibility check. The first reaction can't land before 60s, and n
        # reactions need (n - 1) gaps after it, so the window must be at least
        # 60 + (n - 1) * gap seconds. If it isn't, no schedule can satisfy the
        # minimum gap: warn once and spread evenly over the whole window instead
        # (that is the closest we can get, and it never exceeds max_seconds).
        if n > 1 and 60 + (n - 1) * gap > max_seconds:
            needed_minutes = self.min_window_minutes(n)
            logger.warning(
                f"max_delay_minutes={max_delay_minutes} is too low for {n} "
                f"reactions per post with a {gap}s minimum gap (needs >= "
                f"{needed_minutes} min); falling back to even spacing"
            )
            step = (max_seconds - 60) / (n - 1)
            return [60 + i * step for i in range(n)]

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
        return self._enforce_min_gap(schedule[:n], max_seconds)

    def _enforce_min_gap(self, schedule: List[float], max_seconds: float) -> List[float]:
        """Keep the bucketed "early burst, then stragglers" shape, but make sure
        consecutive reactions are at least self.min_gap_seconds apart.

        Assumes the caller already checked that the window is big enough
        (60 + (n - 1) * gap <= max_seconds).
        """
        gap = self.min_gap_seconds
        n = len(schedule)
        schedule = sorted(schedule)

        # Pass 1: push anything too close to its predecessor forward. The little
        # random jitter keeps the spacing from looking mechanical.
        for i in range(1, n):
            if schedule[i] - schedule[i - 1] < gap:
                schedule[i] = schedule[i - 1] + gap + random.uniform(0, 10)

        # Pass 2: pushing may have run past the ceiling. Clipping would stack
        # reactions at max_seconds, and naively scaling the tail would shrink the
        # gaps we just enforced. Trick: subtract the mandatory spacing (i * gap)
        # from each value, so the gap rule becomes "values never decrease" -
        # any monotonic rescale in that space keeps every gap >= min, and then
        # add the spacing back.
        if schedule and schedule[-1] > max_seconds:
            slack = [v - i * gap for i, v in enumerate(schedule)]
            limit = max_seconds - (n - 1) * gap   # >= 60 thanks to the caller's check
            # Overflow point: first reaction that no longer leaves room for the
            # ones after it. Everything before it is left exactly as it was.
            k = next(i for i, v in enumerate(slack) if v > limit)
            anchor = slack[k - 1] if k > 0 else 60.0
            factor = (limit - anchor) / (slack[-1] - anchor)
            for i in range(k, n):
                slack[i] = anchor + (slack[i] - anchor) * factor
            schedule = [v + i * gap for i, v in enumerate(slack)]

        # Float rounding can leave the last value a hair over max_seconds.
        return [min(v, max_seconds) for v in schedule]

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
                    reaction=[ReactionTypeEmoji(emoji=emoji)],
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
                        reaction=[ReactionTypeEmoji(emoji=emoji)],
                    )
                    await self.db.log_reaction(channel_id, post_id,
                                               bot_username, emoji, True)
                    await self.db.increment_bot_reaction_count(bot_username)
                except Exception as e2:
                    await self.db.log_reaction(channel_id, post_id,
                                               bot_username, emoji, False, str(e2))

            except Forbidden as e:
                logger.error(f"@{bot_username} forbidden in {channel_id} - deactivating")
                await self.db.set_bot_active(bot_username, False)
                self.bot_instances.pop(bot_username, None)
                await self.db.log_reaction(channel_id, post_id,
                                           bot_username, emoji, False, f"Forbidden: {e}")

            except BadRequest as e:
                logger.error(f"BadRequest for @{bot_username} in {channel_id}: {e}")
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
