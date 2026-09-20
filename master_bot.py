# master_bot.py
import logging
from functools import wraps

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_EMOJIS = ['👍', '❤️', '🔥', '😂', '😍', '👏', '💯', '🎉', '🤩', '🙌']


class MasterBot:
    def __init__(self, config, database, reaction_manager):
        self.config = config
        self.db = database
        self.reaction_manager = reaction_manager
        self.application = None

    # =======================================================================
    # BUILD + POST INIT
    # =======================================================================

    def build(self):
        self.application = (
            Application.builder()
            .token(self.config.MASTER_BOT_TOKEN)
            .post_init(self.post_init)
            .build()
        )
        self._register_handlers()
        logger.info("MasterBot initialized")

    async def post_init(self, application: Application):
        logger.info("Running post-init setup...")
        await self.db.initialize()
        bot_count = await self.reaction_manager.initialize_bots()
        logger.info(f"Initialized {bot_count} reaction bots")

    def _register_handlers(self):
        h = self.application.add_handler
        h(CommandHandler("start", self.cmd_start))
        h(CommandHandler("panel", self.cmd_start))
        h(CommandHandler("help", self.cmd_help))
        h(CallbackQueryHandler(self.handle_callback))
        h(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            self.handle_private_message
        ))
        h(MessageHandler(
            filters.ChatType.CHANNEL,
            self.handle_channel_post
        ))

    # =======================================================================
    # ADMIN GUARD (used manually — no decorator magic)
    # =======================================================================

    def _is_admin(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user and user.id in self.config.ADMIN_USER_IDS)

    async def _reject(self, update: Update):
        msg = update.effective_message
        if msg:
            try:
                await msg.reply_text("⛔ You are not authorized.")
            except TelegramError:
                pass

    # =======================================================================
    # ENTRY COMMANDS
    # =======================================================================

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            await self._reject(update)
            return
        context.user_data.clear()
        await self._send_main_menu(update, context)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            await self._reject(update)
            return
        await update.effective_message.reply_text(
            "❓ *How to use this bot*\n\n"
            "Everything is done with the buttons — no commands needed.\n\n"
            "📢 *Channels*\n"
            "Add a channel, toggle reactions, set how many reactions per post, "
            "and pick which emojis your bots use.\n\n"
            "🤖 *Bots*\n"
            "Add bot tokens from @BotFather. The more bots you add, "
            "the more reactions each post can get.\n\n"
            "📊 *Stats*\n"
            "See today's reaction activity.\n\n"
            "*Important:* every bot you add here must also be added as an "
            "admin in your target channel, otherwise Telegram will reject "
            "their reactions.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self._main_menu_keyboard(),
        )

    # =======================================================================
    # MAIN MENU
    # =======================================================================

    def _main_menu_keyboard(self):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Channels", callback_data="menu:channels")],
            [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
            [InlineKeyboardButton("📊 Statistics", callback_data="menu:stats")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
            [InlineKeyboardButton("❓ Help", callback_data="menu:help")],
        ])

    async def _send_main_menu(self, update, context):
        text = (
            "🤖 *CONTROL CENTER*\n\n"
            "Pick an option below:"
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=self._main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.effective_message.reply_text(
                text,
                reply_markup=self._main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )

    # =======================================================================
    # CALLBACK ROUTER
    # =======================================================================

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query

        if not query.from_user or query.from_user.id not in self.config.ADMIN_USER_IDS:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return

        await query.answer()
        data = query.data or ""

        try:
            if data == "menu:home":
                context.user_data.clear()
                await self._send_main_menu(update, context)
                return

            # ---------- channels ----------
            if data == "menu:channels":
                await self._show_channels(query)
                return
            if data == "channel_add":
                context.user_data.clear()
                context.user_data["awaiting"] = "channel"
                await query.edit_message_text(
                    "➕ *Add Channel*\n\n"
                    "Send me one of the following:\n\n"
                    "• The channel ID (starts with `-100`)\n"
                    "• The channel @username\n"
                    "• Or forward any message from the channel\n\n"
                    "Send `cancel` to abort.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            if data.startswith("channel:"):
                cid = data.split(":", 1)[1]
                await self._show_channel_panel(query, cid)
                return
            if data.startswith("toggle:"):
                cid = data.split(":", 1)[1]
                ch = await self.db.get_channel(cid)
                if not ch:
                    await query.edit_message_text(
                        "❌ Channel no longer exists.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("◀️ Back", callback_data="menu:channels")
                        ]]),
                    )
                    return
                await self.db.update_channel_react_mode(cid, not bool(ch["react_mode"]))
                await self._show_channel_panel(query, cid)
                return
            if data.startswith("count:"):
                cid = data.split(":", 1)[1]
                await self._show_count_picker(query, cid)
                return
            if data.startswith("setcount:"):
                _, cid, val = data.split(":", 2)
                n = int(val)
                lo = max(1, n - 2)
                await self.db.update_channel_count(cid, lo, n)
                await self._show_channel_panel(query, cid)
                return
            if data.startswith("emoji:"):
                cid = data.split(":", 1)[1]
                await self._show_emoji_picker(query, cid)
                return
            if data.startswith("toggleemoji:"):
                _, cid, idx = data.split(":", 2)
                ch = await self.db.get_channel(cid)
                if not ch:
                    await query.edit_message_text("❌ Channel gone.")
                    return
                current = [e for e in (ch.get("emoji_list") or "").split(",") if e]
                if not current:
                    current = list(DEFAULT_EMOJIS)
                emoji = DEFAULT_EMOJIS[int(idx)]
                if emoji in current:
                    current.remove(emoji)
                else:
                    current.append(emoji)
                if not current:
                    current = [emoji]  # never allow empty
                async with __import__("aiosqlite").connect(self.db.db_path) as db:
                    await db.execute(
                        "UPDATE channels SET emoji_list = ? WHERE channel_id = ?",
                        (",".join(current), cid),
                    )
                    await db.commit()
                await self._show_emoji_picker(query, cid)
                return
            if data.startswith("delay:"):
                cid = data.split(":", 1)[1]
                await self._show_delay_picker(query, cid)
                return
            if data.startswith("setdelay:"):
                _, cid, val = data.split(":", 2)
                async with __import__("aiosqlite").connect(self.db.db_path) as db:
                    await db.execute(
                        "UPDATE channels SET max_delay_minutes = ? WHERE channel_id = ?",
                        (int(val), cid),
                    )
                    await db.commit()
                await self._show_channel_panel(query, cid)
                return
            if data.startswith("delchannel:"):
                cid = data.split(":", 1)[1]
                await self.db.remove_channel(cid)
                await self._show_channels(query)
                return
            if data.startswith("stats:"):
                cid = data.split(":", 1)[1]
                await self._show_channel_stats(query, cid)
                return

            # ---------- bots ----------
            if data == "menu:bots":
                await self._show_bots(query)
                return
            if data == "bot_add":
                context.user_data.clear()
                context.user_data["awaiting"] = "bot"
                await query.edit_message_text(
                    "➕ *Add Bot*\n\n"
                    "Send me a bot token from @BotFather.\n\n"
                    "Tokens look like:\n"
                    "`123456789:AAH...`\n\n"
                    "Send `cancel` to abort.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            if data.startswith("bot:"):
                username = data.split(":", 1)[1]
                await self._show_bot_panel(query, username)
                return
            if data.startswith("delbot:"):
                username = data.split(":", 1)[1]
                await self.db.set_bot_active(username, False)
                self.reaction_manager.bot_instances.pop(username, None)
                await self._show_bots(query)
                return

            # ---------- misc ----------
            if data == "menu:stats":
                await self._show_stats(query)
                return
            if data == "menu:settings":
                await self._show_settings(query)
                return
            if data == "menu:help":
                await self._show_help_button(query)
                return

        except Exception as e:
            logger.exception(f"Callback error: {e}")
            try:
                await query.edit_message_text(
                    f"⚠️ Something went wrong:\n`{e}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")
                    ]]),
                )
            except TelegramError:
                pass

    # =======================================================================
    # CHANNELS VIEW
    # =======================================================================

    async def _show_channels(self, query):
        channels = await self.db.get_all_channels()
        rows = []
        for ch in channels:
            status = "🟢" if ch["react_mode"] else "🔴"
            name = ch.get("channel_name") or ch["channel_id"]
            if len(name) > 32:
                name = name[:29] + "..."
            rows.append([InlineKeyboardButton(
                f"{status} {name}",
                callback_data=f"channel:{ch['channel_id']}",
            )])
        rows.append([InlineKeyboardButton("➕ Add Channel", callback_data="channel_add")])
        rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])

        text = "📢 *Channels*\n\n"
        if channels:
            text += f"You have {len(channels)} channel(s). Tap one to manage it."
        else:
            text += "You haven't added any channels yet. Tap *➕ Add Channel* to start."

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _show_channel_panel(self, query, channel_id):
        ch = await self.db.get_channel(channel_id)
        if not ch:
            await query.edit_message_text("❌ Channel not found.")
            return

        stats = await self.db.get_stats(channel_id)
        status = "🟢 ON" if ch["react_mode"] else "🔴 OFF"
        emojis = ch.get("emoji_list") or "👍,❤️,🔥"

        text = (
            f"📢 *{ch.get('channel_name') or ch['channel_id']}*\n\n"
            f"ID: `{ch['channel_id']}`\n"
            f"Status: {status}\n"
            f"Reactions per post: `{ch['min_reactions']}-{ch['max_reactions']}`\n"
            f"Max delay: `{ch['max_delay_minutes']} min`\n"
            f"Emojis: {emojis}\n\n"
            f"📊 *Today*\n"
            f"✅ {stats['successful']}  ❌ {stats['failed']}"
        )

        toggle_text = "🔴 Turn OFF" if ch["react_mode"] else "🟢 Turn ON"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(toggle_text, callback_data=f"toggle:{channel_id}")],
            [InlineKeyboardButton("🔢 Reactions per post", callback_data=f"count:{channel_id}")],
            [InlineKeyboardButton("😀 Emojis", callback_data=f"emoji:{channel_id}")],
            [InlineKeyboardButton("⏱ Max delay", callback_data=f"delay:{channel_id}")],
            [InlineKeyboardButton("📊 Stats", callback_data=f"stats:{channel_id}")],
            [InlineKeyboardButton("🗑 Remove channel", callback_data=f"delchannel:{channel_id}")],
            [InlineKeyboardButton("◀️ Back", callback_data="menu:channels")],
        ])

        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    async def _show_channel_stats(self, query, channel_id):
        stats = await self.db.get_stats(channel_id)
        total = stats["total"]
        rate = (stats["successful"] / total * 100) if total else 0

        text = (
            f"📊 *Channel Stats*\n\n"
            f"Total: `{total}`\n"
            f"✅ Successful: `{stats['successful']}`\n"
            f"❌ Failed: `{stats['failed']}`\n"
            f"Success rate: `{rate:.1f}%`"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Back", callback_data=f"channel:{channel_id}")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    async def _show_count_picker(self, query, channel_id):
        rows = []
        row = []
        for n in range(1, 16):
            row.append(InlineKeyboardButton(str(n), callback_data=f"setcount:{channel_id}:{n}"))
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("◀️ Back", callback_data=f"channel:{channel_id}")])

        await query.edit_message_text(
            "🔢 *How many reactions per post?*\n\n"
            "Pick a number (1–15). Higher = more bots react.",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _show_emoji_picker(self, query, channel_id):
        ch = await self.db.get_channel(channel_id)
        if not ch:
            await query.edit_message_text("❌ Channel gone.")
            return

        current = [e for e in (ch.get("emoji_list") or "").split(",") if e]
        if not current:
            current = list(DEFAULT_EMOJIS)

        rows = []
        row = []
        for i, emoji in enumerate(DEFAULT_EMOJIS):
            mark = "✅ " if emoji in current else "▫️ "
            row.append(InlineKeyboardButton(mark + emoji, callback_data=f"toggleemoji:{channel_id}:{i}"))
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("◀️ Back", callback_data=f"channel:{channel_id}")])

        await query.edit_message_text(
            "😀 *Emojis*\n\n"
            "Tap to include/exclude. At least one must remain selected.",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _show_delay_picker(self, query, channel_id):
        options = [5, 10, 15, 30, 60, 120]
        rows = []
        row = []
        for m in options:
            row.append(InlineKeyboardButton(f"{m}m", callback_data=f"setdelay:{channel_id}:{m}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("◀️ Back", callback_data=f"channel:{channel_id}")])

        await query.edit_message_text(
            "⏱ *Max delay*\n\n"
            "Largest window for staggering reactions across bots.",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN,
        )

    # =======================================================================
    # BOTS VIEW
    # =======================================================================

    async def _show_bots(self, query):
        rows = []
        bots = await self.db.get_active_bots()

        for b in bots:
            u = b.get("bot_username") or "?"
            used, limit = b["reactions_today"], b["daily_limit"]
            rows.append([InlineKeyboardButton(
                f"🤖 @{u}  ({used}/{limit})",
                callback_data=f"bot:{u}",
            )])

        rows.append([InlineKeyboardButton("➕ Add Bot", callback_data="bot_add")])
        rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])

        text = (
            "🤖 *Bots*\n\n"
            f"Active: `{len(self.reaction_manager.bot_instances)}`\n"
            f"Registered: `{len(bots)}`\n\n"
        )
        if bots:
            text += "Tap a bot for details, or add another."
        else:
            text += (
                "No bots yet.\n\n"
                "*Important:* each bot you add here must also be an admin "
                "in the target channel."
            )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _show_bot_panel(self, query, username):
        row = None
        for b in await self.db.get_active_bots():
            if b["bot_username"] == username:
                row = b
                break
        if not row:
            await query.edit_message_text("❌ Bot not found.")
            return

        text = (
            f"🤖 *@{username}*\n\n"
            f"Status: {'🟢 Active' if row['is_active'] else '🔴 Inactive'}\n"
            f"Used today: `{row['reactions_today']}`\n"
            f"Daily limit: `{row['daily_limit']}`\n"
            f"Last reset: `{row['last_reset'] or 'never'}`"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Remove bot", callback_data=f"delbot:{username}")],
            [InlineKeyboardButton("◀️ Back", callback_data="menu:bots")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    # =======================================================================
    # STATS / SETTINGS / HELP
    # =======================================================================

    async def _show_stats(self, query):
        s = await self.db.get_stats()
        rate = (s["successful"] / s["total"] * 100) if s["total"] else 0
        text = (
            "📊 *Statistics*\n\n"
            f"Total attempts: `{s['total']}`\n"
            f"✅ Successful: `{s['successful']}`\n"
            f"❌ Failed: `{s['failed']}`\n"
            f"Success rate: `{rate:.1f}%`\n"
            f"Active bots: `{len(self.reaction_manager.bot_instances)}`"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    async def _show_settings(self, query):
        text = (
            "⚙️ *Settings*\n\n"
            f"Max bots: `{self.config.MAX_BOTS}`\n"
            f"Daily limit per bot: `{self.config.DAILY_LIMIT_PER_BOT}`\n\n"
            "Per-channel settings live inside each channel's panel."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Channels", callback_data="menu:channels")],
            [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    async def _show_help_button(self, query):
        text = (
            "❓ *Help*\n\n"
            "📢 *Channels*\n"
            "• Add Channel — press ➕, then send the ID, @username, or "
            "forward a message from the channel.\n"
            "• Tap a channel to toggle reactions, pick emoji set, "
            "set reactions per post, and set max delay.\n\n"
            "🤖 *Bots*\n"
            "• Add Bot — press ➕ and paste the token from @BotFather.\n"
            "• Each bot must be an *admin* in the target channel.\n\n"
            "📊 *Stats*\n"
            "Today's attempts, successes, and failures.\n\n"
            "*Tip:* the master bot itself must also be an admin in the "
            "channel to receive new posts."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    # =======================================================================
    # PRIVATE MESSAGE HANDLER (add channel / add bot flows)
    # =======================================================================

    async def handle_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in self.config.ADMIN_USER_IDS:
            return

        awaiting = context.user_data.get("awaiting")
        if not awaiting:
            # Not in a flow — show main menu
            await update.effective_message.reply_text(
                "Tap a button below:",
                reply_markup=self._main_menu_keyboard(),
            )
            return

        text = (update.effective_message.text or "").strip()

        if text.lower() == "cancel":
            context.user_data.clear()
            await update.effective_message.reply_text(
                "❌ Cancelled.",
                reply_markup=self._main_menu_keyboard(),
            )
            return

        # ---------------- ADD CHANNEL ----------------
        if awaiting == "channel":
            channel_id = self._parse_channel_input(update, text)

            if not channel_id:
                await update.effective_message.reply_text(
                    "❌ I couldn't find a channel ID in that.\n\n"
                    "Send the ID (starting with `-100`), an `@username`, "
                    "or *forward* a message from the channel.\n\n"
                    "Send `cancel` to abort.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            name = channel_id
            # Try to fetch the real title
            try:
                chat = await context.bot.get_chat(channel_id)
                name = chat.title or chat.username or channel_id
            except TelegramError:
                pass

            added = await self.db.add_channel(channel_id, name)
            context.user_data.clear()

            if added:
                await update.effective_message.reply_text(
                    f"✅ Channel added: *{name}*\n\n"
                    "Now open its panel to enable reactions.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📢 Open Channels", callback_data="menu:channels")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
                    ]),
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await update.effective_message.reply_text(
                    "ℹ️ That channel is already registered.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📢 Open Channels", callback_data="menu:channels")],
                    ]),
                )
            return

        # ---------------- ADD BOT ----------------
        if awaiting == "bot":
            token = text

            if ":" not in token or len(token) < 20:
                await update.effective_message.reply_text(
                    "❌ That doesn't look like a bot token.\n\n"
                    "Tokens look like:\n`123456789:AAH...`\n\n"
                    "Try again or send `cancel`.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            if await self.db.count_bots() >= self.config.MAX_BOTS:
                context.user_data.clear()
                await update.effective_message.reply_text(
                    f"❌ Bot limit reached ({self.config.MAX_BOTS}). "
                    "Remove some first.",
                    reply_markup=self._main_menu_keyboard(),
                )
                return

            try:
                username = await self.reaction_manager.add_bot(token)
            except Exception as e:
                logger.error(f"Bot add failed: {e}")
                await update.effective_message.reply_text(
                    f"❌ Couldn't add that bot:\n`{e}`\n\n"
                    "Double-check the token, or send `cancel`.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            context.user_data.clear()
            await update.effective_message.reply_text(
                f"✅ Bot added: *@{username}*\n\n"
                f"Active bots: `{len(self.reaction_manager.bot_instances)}`\n\n"
                "⚠️ *Don't forget:* add this bot as an admin in your target "
                "channel, or Telegram will reject its reactions.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 Open Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    def _parse_channel_input(self, update: Update, text: str):
        """Accept: -100..., @username, https://t.me/..., or a forwarded message."""
        msg = update.effective_message

        # Forwarded from a channel?
        origin = getattr(msg, "forward_origin", None) or getattr(msg, "forward_from_chat", None)
        if origin is not None:
            chat = getattr(origin, "chat", None) or origin
            cid = getattr(chat, "id", None)
            if cid:
                return str(cid)

        # Raw text
        t = text.strip()
        if t.startswith("-100") and t[1:].isdigit():
            return t

        if t.startswith("@"):
            return t  # we'll resolve later via get_chat

        if "t.me/" in t:
            part = t.split("t.me/")[-1].split("/")[0].strip()
            if part.startswith("+"):
                return None
            return "@" + part

        return None

    # =======================================================================
    # CHANNEL POSTS
    # =======================================================================

    async def handle_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        channel_id = str(update.effective_chat.id)
        if not await self.db.get_channel(channel_id):
            return
        msg = update.effective_message
        post_text = msg.text or msg.caption or ""
        try:
            await self.reaction_manager.schedule_reactions(
                channel_id, msg.message_id, post_text
            )
        except Exception as e:
            logger.exception(f"Scheduling failed: {e}")

    # =======================================================================
    # RUN
    # =======================================================================

    def run(self):
        if self.application is None:
            self.build()
        logger.info("Starting master bot polling...")
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
