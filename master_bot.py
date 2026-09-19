# master_bot.py
import logging
from typing import Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


def admin_only(func):
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in self.config.ADMIN_USER_IDS:
            target = update.effective_message or (
                update.callback_query.message if update.callback_query else None
            )
            if target:
                try:
                    await target.reply_text("Unauthorized.")
                except TelegramError:
                    pass
            return
        return await func(self, update, context)
    return wrapper


class MasterBot:
    def __init__(self, config, database, reaction_manager):
        self.config = config
        self.db = database
        self.reaction_manager = reaction_manager
        self.application = None

    async def post_init(self, application: Application):
        """Called by PTB after the Application is initialized, before polling."""
        logger.info("Running post-init setup...")
        await self.db.initialize()
        bot_count = await self.reaction_manager.initialize_bots()
        logger.info(f"Initialized {bot_count} reaction bots")

    async def initialize(self):
        self.application = (
            Application.builder()
            .token(self.config.MASTER_BOT_TOKEN)
            .post_init(self.post_init)
            .build()
        )
        self._register_handlers()
        logger.info("MasterBot initialized")

    def _register_handlers(self):
        h = self.application.add_handler
        h(CommandHandler("start", self.cmd_start))
        h(CommandHandler("help", self.cmd_help))
        h(CommandHandler("panel", self.cmd_panel))
        h(CommandHandler("add_channel", self.cmd_add_channel))
        h(CommandHandler("remove_channel", self.cmd_remove_channel))
        h(CommandHandler("react_on", self.cmd_react_on))
        h(CommandHandler("react_off", self.cmd_react_off))
        h(CommandHandler("toggle", self.cmd_toggle))
        h(CommandHandler("react_status", self.cmd_status))
        h(CommandHandler("set_count", self.cmd_set_count))
        h(CommandHandler("channels", self.cmd_channels))
        h(CommandHandler("add_bot", self.cmd_add_bot))
        h(CommandHandler("list_bots", self.cmd_list_bots))
        h(CommandHandler("stats", self.cmd_stats))
        h(CallbackQueryHandler(self.handle_callback))
        h(MessageHandler(filters.ChatType.CHANNEL, self.handle_channel_post))

    @admin_only
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_control_panel(update, context, edit=False)

    @admin_only
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "*Auto-Reaction Bot Control*\n\n"
            "*Channels:*\n"
            "`/add_channel <id> [name]`\n"
            "`/remove_channel <id>`\n"
            "`/channels`\n\n"
            "*Reactions:*\n"
            "`/react_on <id>`  `/react_off <id>`  `/toggle <id>`\n"
            "`/react_status <id>`\n"
            "`/set_count <id> <1-15>`\n\n"
            "*Bots:*\n"
            "`/add_bot <token>`  `/list_bots`\n\n"
            "*Other:*\n"
            "`/panel`  `/stats`"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_control_panel(update, context, edit=False)

    @admin_only
    async def cmd_add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "Usage: `/add_channel -1001234567890 [Name]`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        channel_id = context.args[0]
        name = " ".join(context.args[1:]) or channel_id
        added = await self.db.add_channel(channel_id, name)
        if added:
            await update.message.reply_text(
                f"Added channel `{channel_id}`.", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("Channel already registered.")

    @admin_only
    async def cmd_remove_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/remove_channel <id>`",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        ok = await self.db.remove_channel(context.args[0])
        await update.message.reply_text("Removed." if ok else "Not found.")

    @admin_only
    async def cmd_react_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._set_mode(update, context, True)

    @admin_only
    async def cmd_react_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._set_mode(update, context, False)

    @admin_only
    async def cmd_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/toggle <channel_id>`",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        cid = context.args[0]
        channel = await self.db.get_channel(cid)
        if not channel:
            await update.message.reply_text("Channel not registered.")
            return
        new_mode = not bool(channel['react_mode'])
        await self.db.update_channel_react_mode(cid, new_mode)
        await update.message.reply_text(
            f"{'ENABLED' if new_mode else 'DISABLED'} for `{cid}`",
            parse_mode=ParseMode.MARKDOWN
        )

    @admin_only
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/react_status <channel_id>`",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        channel = await self.db.get_channel(context.args[0])
        if not channel:
            await update.message.reply_text("Not registered.")
            return
        status = "ENABLED" if channel['react_mode'] else "DISABLED"
        await update.message.reply_text(
            f"*Status*\n"
            f"Channel: `{channel['channel_id']}`\n"
            f"Name: {channel.get('channel_name') or '-'}\n"
            f"Mode: {status}\n"
            f"Per post: {channel['min_reactions']}-{channel['max_reactions']}\n"
            f"Max delay: {channel['max_delay_minutes']} min\n"
            f"Active bots: {len(self.reaction_manager.bot_instances)}",
            parse_mode=ParseMode.MARKDOWN
        )

    @admin_only
    async def cmd_set_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) != 2:
            await update.message.reply_text(
                "Usage: `/set_count <channel_id> <1-15>`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        cid = context.args[0]
        try:
            n = int(context.args[1])
            if not 1 <= n <= 15:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Count must be 1-15.")
            return
        if not await self.db.get_channel(cid):
            await update.message.reply_text("Channel not registered.")
            return
        lo = max(1, n - 2)
        await self.db.update_channel_count(cid, lo, n)
        await update.message.reply_text(f"Set to {lo}-{n} reactions per post.")

    @admin_only
    async def cmd_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        channels = await self.db.get_all_channels()
        if not channels:
            await update.message.reply_text("No channels registered.")
            return
        lines = ["*Channels*", ""]
        for i, ch in enumerate(channels, 1):
            status = "ON" if ch['react_mode'] else "OFF"
            lines.append(
                f"{i}. [{status}] `{ch['channel_id']}` - "
                f"{(ch.get('channel_name') or '')[:30]} "
                f"({ch['min_reactions']}-{ch['max_reactions']})"
            )
        await update.message.reply_text("\n".join(lines),
                                        parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_add_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/add_bot <token>`",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        if await self.db.count_bots() >= self.config.MAX_BOTS:
            await update.message.reply_text("Bot limit reached.")
            return
        try:
            username = await self.reaction_manager.add_bot(context.args[0])
            await update.message.reply_text(
                f"Added @{username}\n"
                f"Active: {len(self.reaction_manager.bot_instances)}"
            )
        except Exception as e:
            await update.message.reply_text(f"Invalid token: {e}")

    @admin_only
    async def cmd_list_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        bots = await self.db.get_active_bots()
        if not bots:
            await update.message.reply_text("No active bots.")
            return
        lines = ["*Active Bots*", ""]
        for i, b in enumerate(bots, 1):
            lines.append(
                f"{i}. @{b['bot_username']} - "
                f"{b['reactions_today']}/{b['daily_limit']} today"
            )
        await update.message.reply_text("\n".join(lines),
                                        parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        s = await self.db.get_stats()
        rate = (s['successful'] / s['total'] * 100) if s['total'] else 0.0
        await update.message.reply_text(
            f"*Daily Stats*\n"
            f"Total: {s['total']}\n"
            f"Success: {s['successful']}\n"
            f"Failed: {s['failed']}\n"
            f"Rate: {rate:.1f}%\n"
            f"Active bots: {len(self.reaction_manager.bot_instances)}",
            parse_mode=ParseMode.MARKDOWN
        )

    async def _set_mode(self, update, context, mode: bool):
        if not context.args:
            cmd = 'react_on' if mode else 'react_off'
            await update.message.reply_text(
                f"Usage: `/{cmd} <channel_id>`", parse_mode=ParseMode.MARKDOWN
            )
            return
        cid = context.args[0]
        if not await self.db.get_channel(cid):
            await update.message.reply_text("Channel not registered.")
            return
        await self.db.update_channel_react_mode(cid, mode)
        await update.message.reply_text(
            f"{'ENABLED' if mode else 'DISABLED'} for `{cid}`",
            parse_mode=ParseMode.MARKDOWN
        )

    async def show_control_panel(self, update, context, edit=False):
        channels = await self.db.get_all_channels()
        if not channels:
            text = "No channels yet. Add one with `/add_channel <id> <name>`."
            if edit and update.callback_query:
                await update.callback_query.edit_message_text(
                    text, parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            return

        rows = []
        for ch in channels:
            status = "ON " if ch['react_mode'] else "OFF"
            label = f"[{status}] {ch.get('channel_name') or ch['channel_id']}"
            rows.append([InlineKeyboardButton(
                label, callback_data=f"view:{ch['channel_id']}"
            )])
        kb = InlineKeyboardMarkup(rows)
        text = "*Reaction Control Panel*\nSelect a channel:"
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(
                text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )

    async def _build_channel_panel(self, channel: Dict):
        status = "ENABLED" if channel['react_mode'] else "DISABLED"
        stats = await self.db.get_stats(channel['channel_id'])
        emojis = (channel.get('emoji_list') or '')[:40]
        text = (
            f"*Channel Panel*\n"
            f"Channel: `{channel['channel_id']}`\n"
            f"Name: {channel.get('channel_name') or '-'}\n"
            f"Auto: {status}\n"
            f"Per post: {channel['min_reactions']}-{channel['max_reactions']}\n"
            f"Emojis: {emojis}\n\n"
            f"Today - OK {stats['successful']} / FAIL {stats['failed']}"
        )
        cid = channel['channel_id']
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Toggle", callback_data=f"toggle:{cid}")],
            [InlineKeyboardButton("Stats", callback_data=f"stats:{cid}")],
            [InlineKeyboardButton("Back", callback_data="back")],
        ])
        return text, kb

    @admin_only
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        data = q.data or ""

        if data == "back":
            await self.show_control_panel(update, context, edit=True)
            return

        if ":" not in data:
            return
        action, cid = data.split(":", 1)

        channel = await self.db.get_channel(cid)
        if not channel:
            await q.edit_message_text("Channel no longer registered.")
            return

        if action == "view":
            text, kb = await self._build_channel_panel(channel)
            await q.edit_message_text(text, reply_markup=kb,
                                      parse_mode=ParseMode.MARKDOWN)

        elif action == "toggle":
            new_mode = not bool(channel['react_mode'])
            await self.db.update_channel_react_mode(cid, new_mode)
            channel = await self.db.get_channel(cid)
            text, kb = await self._build_channel_panel(channel)
            await q.edit_message_text(text, reply_markup=kb,
                                      parse_mode=ParseMode.MARKDOWN)

        elif action == "stats":
            s = await self.db.get_stats(cid)
            await q.edit_message_text(
                f"*Channel Stats*\n"
                f"Total: {s['total']}\n"
                f"OK: {s['successful']}  FAIL: {s['failed']}",
                parse_mode=ParseMode.MARKDOWN
            )

    async def handle_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        channel_id = str(update.effective_chat.id)
        if not await self.db.get_channel(channel_id):
            return
        msg = update.effective_message
        post_text = msg.text or msg.caption or ""
        await self.reaction_manager.schedule_reactions(
            channel_id, msg.message_id, post_text
        )

    def run(self):
        logger.info("Starting master bot polling...")
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
