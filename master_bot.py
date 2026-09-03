# master_bot.py
import logging
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class MasterBot:
    def __init__(self, config, database, reaction_manager):
        self.config = config
        self.db = database
        self.reaction_manager = reaction_manager
        self.application = None
        
    async def initialize(self):
        """Initialize the master bot"""
        self.application = Application.builder().token(
            self.config.MASTER_BOT_TOKEN
        ).build()
        
        # Register handlers
        self._register_handlers()
        
        logger.info("Master bot initialized")
        
    def _register_handlers(self):
        """Register all command and callback handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        self.application.add_handler(CommandHandler("panel", self.cmd_panel))
        self.application.add_handler(CommandHandler("react_on", self.cmd_react_on))
        self.application.add_handler(CommandHandler("react_off", self.cmd_react_off))
        self.application.add_handler(CommandHandler("toggle", self.cmd_toggle))
        self.application.add_handler(CommandHandler("react_status", self.cmd_status))
        self.application.add_handler(CommandHandler("set_count", self.cmd_set_count))
        self.application.add_handler(CommandHandler("channels", self.cmd_channels))
        self.application.add_handler(CommandHandler("add_bot", self.cmd_add_bot))
        self.application.add_handler(CommandHandler("list_bots", self.cmd_list_bots))
        self.application.add_handler(CommandHandler("stats", self.cmd_stats))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Message handler for channel posts
        self.application.add_handler(
            MessageHandler(filters.ChatType.CHANNEL, self.handle_channel_post)
        )
        
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await self.show_control_panel(update, context)
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
🤖 **Auto-Reaction Bot Control**

**Quick Commands:**
/react_on - Enable reactions
/react_off - Disable reactions
/toggle - Toggle reactions ON/OFF
/react_status - Check current status
/panel - Show control panel

**Settings:**
/set_count [1-15] - Set reactions per post
/channels - View all channels
/stats - View statistics

**Bot Management:**
/add_bot [token] - Add reaction bot
/list_bots - List all bots
        """
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show control panel"""
        await self.show_control_panel(update, context)
    
    async def show_control_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display the interactive control panel"""
        user_id = update.effective_user.id
        
        # Get all channels
        channels = await self.db.get_all_channels()
        
        if not channels:
            await update.message.reply_text(
                "❌ No channels configured. Please add channels first."
            )
            return
        
        # Create panel for each channel
        for channel in channels:
            panel_text, keyboard = await self._build_channel_panel(channel)
            
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    panel_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    panel_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
    
    async def _build_channel_panel(self, channel: Dict):
        """Build control panel for a channel"""
        status = "✅ ENABLED" if channel['react_mode'] else "❌ DISABLED"
        
        # Get stats
        stats = await self.db.get_stats(channel['channel_id'])
        
        panel_text = f"""
📊 **Reaction Control Panel**
━━━━━━━━━━━━━━━━━━━━━
**Channel:** {channel.get('channel_name', channel['channel_id'])}
**Auto-Reactions:** {status}

**Total bots:** {len(self.reaction_manager.bot_instances)}
**Reactions per post:** {channel['min_reactions']}-{channel['max_reactions']}
**Emojis:** {channel.get('emoji_list', '👍,❤️,🔥')[:50]}...

**Today's Stats:**
✅ Successful: {stats['successful']}
❌ Failed: {stats['failed']}
        """
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 TOGGLE REACTIONS",
                    callback_data=f"toggle_{channel['channel_id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 VIEW STATS",
                    callback_data=f"stats_{channel['channel_id']}"
                ),
                InlineKeyboardButton(
                    "📋 LOGS",
                    callback_data=f"logs_{channel['channel_id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ SETTINGS",
                    callback_data=f"settings_{channel['channel_id']}"
                )
            ]
        ]
        
        return panel_text, InlineKeyboardMarkup(keyboard)
    
    async def cmd_react_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enable reactions for current channel"""
        channel_id = str(update.effective_chat.id)
        
        # Get channel
        channel = await self.db.get_channel(channel_id)
        if not channel:
            await update.message.reply_text(
                "❌ This channel is not registered. Use /add_channel first."
            )
            return
        
        await self.db.update_channel_react_mode(channel_id, True)
        
        await update.message.reply_text(
            f"✅ Auto-reactions ENABLED for {channel.get('channel_name', channel_id)}. "
            f"New posts will receive {channel['min_reactions']}-{channel['max_reactions']} staggered reactions."
        )
    
    async def cmd_react_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Disable reactions for current channel"""
        channel_id = str(update.effective_chat.id)
        
        channel = await self.db.get_channel(channel_id)
        if not channel:
            await update.message.reply_text(
                "❌ This channel is not registered."
            )
            return
        
        await self.db.update_channel_react_mode(channel_id, False)
        
        await update.message.reply_text(
            f"❌ Auto-reactions DISABLED for {channel.get('channel_name', channel_id)}. "
            f"New posts will NOT receive automatic reactions."
        )
    
    async def cmd_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle reactions on/off"""
        channel_id = str(update.effective_chat.id)
        
        channel = await self.db.get_channel(channel_id)
        if not channel:
            await update.message.reply_text("❌ Channel not registered.")
            return
        
        new_mode = not channel['react_mode']
        await self.db.update_channel_react_mode(channel_id, new_mode)
        
        status = "ENABLED ✅" if new_mode else "DISABLED ❌"
        await update.message.reply_text(
            f"🔄 Auto-reactions {status} for {channel.get('channel_name', channel_id)}"
        )
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check reaction status"""
        channel_id = str(update.effective_chat.id)
        
        channel = await self.db.get_channel(channel_id)
        if not channel:
            await update.message.reply_text("❌ Channel not registered.")
            return
        
        status = "✅ ENABLED" if channel['react_mode'] else "❌ DISABLED"
        
        await update.message.reply_text(
            f"📊 **Auto-Reaction Status**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Channel:** {channel.get('channel_name', channel_id)}\n"
            f"**Status:** {status}\n"
            f"**Reactions per post:** {channel['min_reactions']}-{channel['max_reactions']}\n"
            f"**Max delay:** {channel['max_delay_minutes']} minutes\n"
            f"**Active bots:** {len(self.reaction_manager.bot_instances)}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def cmd_set_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set number of reactions per post"""
        if not context.args:
            await update.message.reply_text(
                "Usage: /set_count [1-15]\nExample: /set_count 8"
            )
            return
        
        try:
            count = int(context.args[0])
            if count < 1 or count > 15:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid count. Please use a number between 1 and 15."
            )
            return
        
        channel_id = str(update.effective_chat.id)
        
        # Update in database
        async with aiosqlite.connect(self.db.db_path) as db:
            await db.execute(
                'UPDATE channels SET min_reactions = ?, max_reactions = ? WHERE channel_id = ?',
                (max(1, count - 2), count, channel_id)
            )
            await db.commit()
        
        await update.message.reply_text(
            f"✅ Reactions per post set to {max(1, count-2)}-{count}"
        )
    
    async def cmd_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all channels with status"""
        channels = await self.db.get_all_channels()
        
        if not channels:
            await update.message.reply_text("❌ No channels registered.")
            return
        
        text = "📊 **Channel Status**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for i, channel in enumerate(channels, 1):
            status = "✅ ON" if channel['react_mode'] else "❌ OFF"
            text += f"{i}. {channel.get('channel_name', channel['channel_id'])} - {status}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_add_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a new reaction bot"""
        if not context.args:
            await update.message.reply_text(
                "Usage: /add_bot [bot_token]\n"
                "Get token from @BotFather"
            )
            return
        
        token = context.args[0]
        
        # Verify token
        try:
            bot = Bot(token)
            me = await bot.get_me()
            
            # Add to database
            await self.db.add_bot_token(token, me.username)
            
            # Add to active bots
            self.reaction_manager.bot_instances[me.username] = {
                'bot': bot,
                'username': me.username,
                'token': token
            }
            
            await update.message.reply_text(
                f"✅ Bot @{me.username} added successfully!\n"
                f"Total active bots: {len(self.reaction_manager.bot_instances)}"
            )
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Invalid bot token: {str(e)}"
            )
    
    async def cmd_list_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all registered bots"""
        bots = await self.db.get_active_bots()
        
        if not bots:
            await update.message.reply_text("❌ No bots registered.")
            return
        
        text = "🤖 **Registered Bots**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for i, bot in enumerate(bots, 1):
            usage = f"{bot['reactions_today']}/{bot['daily_limit']}"
            text += f"{i}. @{bot['bot_username']} - {usage} reactions today\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show daily statistics"""
        stats = await self.db.get_stats()
        
        text = f"""
📊 **Daily Statistics**
━━━━━━━━━━━━━━━━━━━━━
**Total reactions:** {stats['total']}
✅ **Successful:** {stats['successful']}
❌ **Failed:** {stats['failed']}
**Success rate:** {(stats['successful']/stats['total']*100) if stats['total'] > 0 else 0:.1f}%
**Active bots:** {len(self.reaction_manager.bot_instances)}
        """
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline buttons"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("toggle_"):
            channel_id = data.split("_")[1]
            
            # Get channel
            channel = await self.db.get_channel(channel_id)
            if channel:
                # Toggle mode
                new_mode = not channel['react_mode']
                await self.db.update_channel_react_mode(channel_id, new_mode)
                
                # Update panel
                panel_text, keyboard = await self._build_channel_panel(
                    await self.db.get_channel(channel_id)
                )
                
                await query.edit_message_text(
                    panel_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                status = "ENABLED ✅" if new_mode else "DISABLED ❌"
                await query.message.reply_text(
                    f"🔄 Auto-reactions {status}"
                )
        
        elif data.startswith("stats_"):
            channel_id = data.split("_")[1]
            stats = await self.db.get_stats(channel_id)
            
            text = f"""
📊 **Channel Statistics**
━━━━━━━━━━━━━━━━━━━━━
**Total today:** {stats['total']}
✅ **Success:** {stats['successful']}
❌ **Failed:** {stats['failed']}
            """
            
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new posts in channels"""
        # Check if message is from a monitored channel
        channel_id = str(update.effective_chat.id)
        
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return
        
        # Schedule reactions
        post_text = update.effective_message.text or update.effective_message.caption or ""
        post_id = update.effective_message.message_id
        
        await self.reaction_manager.schedule_reactions(channel_id, post_id, post_text)
        
        logger.info(f"Scheduled reactions for post {post_id} in channel {channel_id}")
    
    async def run(self):
        """Run the master bot"""
        logger.info("Starting master bot...")
        await self.application.run_polling()
