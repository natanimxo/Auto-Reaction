# reaction_manager.py
import asyncio
import random
import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError, RetryAfter, Unauthorized

logger = logging.getLogger(__name__)

class ReactionManager:
    def __init__(self, database):
        self.db = database
        self.bot_instances = {}  # Cache bot instances
        self.reaction_queue = asyncio.Queue()
        self.active_jobs = {}
        
    async def initialize_bots(self):
        """Initialize bot instances from database"""
        bots = await self.db.get_active_bots()
        for bot_data in bots:
            token = bot_data['bot_token']
            try:
                bot = Bot(token)
                # Verify bot is valid
                me = await bot.get_me()
                self.bot_instances[me.username] = {
                    'bot': bot,
                    'username': me.username,
                    'token': token
                }
                logger.info(f"Bot initialized: @{me.username}")
            except Exception as e:
                logger.error(f"Failed to initialize bot: {e}")
        
        return len(self.bot_instances)
    
    async def schedule_reactions(self, channel_id: str, post_id: int, post_text: str):
        """Schedule staggered reactions for a new post"""
        # Check if post has [no-react] keyword
        if '[no-react]' in post_text.lower():
            logger.info(f"Skipping reactions for post {post_id} in {channel_id} (no-react keyword)")
            return
        
        # Get channel settings
        channel = await self.db.get_channel(channel_id)
        if not channel or not channel['react_mode']:
            logger.info(f"Reactions disabled for channel {channel_id}")
            return
        
        # Calculate number of reactions
        min_reactions = channel['min_reactions']
        max_reactions = channel['max_reactions']
        num_reactions = random.randint(min_reactions, max_reactions)
        
        # Get available bots
        available_bots = list(self.bot_instances.keys())
        if not available_bots:
            logger.error("No bots available for reactions")
            return
        
        # Limit reactions to available bots
        num_reactions = min(num_reactions, len(available_bots))
        
        # Select random bots
        selected_bots = random.sample(available_bots, num_reactions)
        
        # Get emoji list
        emoji_list = channel.get('emoji_list', '👍,❤️,🔥').split(',')
        
        # Create staggered schedule
        max_delay = channel['max_delay_minutes']
        schedule = self._create_staggered_schedule(num_reactions, max_delay)
        
        # Schedule each reaction
        for i, (bot_username, delay) in enumerate(zip(selected_bots, schedule)):
            emoji = random.choice(emoji_list)
            
            # Create async task
            task = asyncio.create_task(
                self._delayed_reaction(
                    channel_id, post_id, bot_username, emoji, delay
                )
            )
            
            # Store task reference
            job_id = f"{channel_id}_{post_id}_{i}"
            self.active_jobs[job_id] = task
            
            # Add cleanup callback
            task.add_done_callback(
                lambda t, jid=job_id: self.active_jobs.pop(jid, None)
            )
    
    def _create_staggered_schedule(self, num_reactions: int, max_delay_minutes: int) -> List[float]:
        """Create staggered timing schedule"""
        schedule = []
        
        if num_reactions <= 3:
            # All in first wave
            for _ in range(num_reactions):
                schedule.append(random.uniform(60, 180))  # 1-3 minutes
        elif num_reactions <= 7:
            # Two waves
            first_wave = random.randint(1, 3)
            second_wave = num_reactions - first_wave
            
            for _ in range(first_wave):
                schedule.append(random.uniform(60, 180))  # 1-3 minutes
            
            for _ in range(second_wave):
                schedule.append(random.uniform(300, 600))  # 5-10 minutes
        else:
            # Three waves
            first_wave = random.randint(1, 3)
            second_wave = random.randint(2, 4)
            third_wave = num_reactions - first_wave - second_wave
            
            for _ in range(first_wave):
                schedule.append(random.uniform(60, 180))  # 1-3 minutes
            
            for _ in range(second_wave):
                schedule.append(random.uniform(300, 600))  # 5-10 minutes
            
            for _ in range(third_wave):
                schedule.append(random.uniform(900, max_delay_minutes * 60))  # 15-30+ minutes
        
        # Add small random jitter
        schedule = [s + random.uniform(2, 5) for s in schedule]
        
        # Sort schedule
        schedule.sort()
        
        return schedule
    
    async def _delayed_reaction(self, channel_id: str, post_id: int, 
                               bot_username: str, emoji: str, delay: float):
        """Execute delayed reaction"""
        try:
            # Wait for delay
            await asyncio.sleep(delay)
            
            # Get bot instance
            bot_data = self.bot_instances.get(bot_username)
            if not bot_data:
                logger.error(f"Bot {bot_username} not found")
                return
            
            bot = bot_data['bot']
            
            # Attempt reaction
            try:
                # Send reaction
                await bot.set_message_reaction(
                    chat_id=channel_id,
                    message_id=post_id,
                    reaction=[{
                        'type': 'emoji',
                        'emoji': emoji
                    }]
                )
                
                # Log success
                await self.db.log_reaction(
                    channel_id, post_id, bot_username, emoji, True
                )
                
                # Increment bot count
                await self.db.increment_bot_reaction_count(bot_username)
                
                logger.info(f"✅ Reaction added: @{bot_username} reacted {emoji} to post {post_id}")
                
            except RetryAfter as e:
                # Rate limited
                logger.warning(f"Rate limited for {bot_username}: {e.retry_after}s")
                await self.db.log_reaction(
                    channel_id, post_id, bot_username, emoji, False, f"Rate limited: {e.retry_after}s"
                )
                
                # Wait and retry once
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await bot.set_message_reaction(
                        chat_id=channel_id,
                        message_id=post_id,
                        reaction=[{'type': 'emoji', 'emoji': emoji}]
                    )
                    await self.db.log_reaction(channel_id, post_id, bot_username, emoji, True)
                    logger.info(f"✅ Reaction added after retry: @{bot_username}")
                except Exception as retry_error:
                    logger.error(f"Retry failed for {bot_username}: {retry_error}")
                    
            except Unauthorized:
                # Bot token invalid
                logger.error(f"Bot {bot_username} is unauthorized")
                await self.db.log_reaction(
                    channel_id, post_id, bot_username, emoji, False, "Unauthorized"
                )
                
            except TelegramError as e:
                logger.error(f"Telegram error for {bot_username}: {e}")
                await self.db.log_reaction(
                    channel_id, post_id, bot_username, emoji, False, str(e)
                )
                
        except asyncio.CancelledError:
            logger.info(f"Reaction cancelled for {bot_username}")
        except Exception as e:
            logger.error(f"Unexpected error in delayed reaction: {e}")
