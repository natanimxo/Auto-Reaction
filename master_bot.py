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


class MasterBot:

    def __init__(self, config, database, reaction_manager):
        self.config = config
        self.db = database
        self.reaction_manager = reaction_manager
        self.application = None

    # =========================================================
    # ADMIN CHECK
    # =========================================================

    def admin_only(self, func):

        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):

            user = update.effective_user

            if not user or user.id not in self.config.ADMIN_USER_IDS:

                message = update.effective_message

                if message:
                    try:
                        await message.reply_text(
                            "⛔ You are not authorized to use this bot."
                        )
                    except TelegramError:
                        pass

                return

            return await func(update, context)

        return wrapper

    # =========================================================
    # BUILD APPLICATION
    # =========================================================

    def build(self):

        self.application = (
            Application.builder()
            .token(self.config.MASTER_BOT_TOKEN)
            .post_init(self.post_init)
            .build()
        )

        self._register_handlers()

        logger.info("MasterBot initialized")

    # =========================================================
    # POST INIT
    # =========================================================

    async def post_init(self, application: Application):

        logger.info("Running post-init setup...")

        await self.db.initialize()

        bot_count = await self.reaction_manager.initialize_bots()

        logger.info(
            f"Initialized {bot_count} reaction bots"
        )

    # =========================================================
    # HANDLERS
    # =========================================================

    def _register_handlers(self):

    self.application.add_handler(
        CommandHandler("start", self.cmd_start)
    )

    self.application.add_handler(
        CommandHandler("panel", self.cmd_start)
    )

    self.application.add_handler(
        CommandHandler("help", self.cmd_help)
    )

    self.application.add_handler(
        CallbackQueryHandler(self.handle_callback)
    )

    self.application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT,
            self.handle_private_message
        )
    )

    self.application.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL,
            self.handle_channel_post
        )
    )

    # =========================================================
    # MAIN MENU
    # =========================================================

    def main_menu_keyboard(self):

        return InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "📢 Channels",
                    callback_data="menu:channels"
                )
            ],

            [
                InlineKeyboardButton(
                    "📊 Statistics",
                    callback_data="menu:stats"
                )
            ],

            [
                InlineKeyboardButton(
                    "⚙️ Settings",
                    callback_data="menu:settings"
                )
            ],

            [
                InlineKeyboardButton(
                    "❓ Help",
                    callback_data="menu:help"
                )
            ],

        ])

    async def cmd_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):

        user = update.effective_user

        if not user or user.id not in self.config.ADMIN_USER_IDS:
            await update.effective_message.reply_text(
                "⛔ You are not authorized to use this bot."
            )
            return

        await update.effective_message.reply_text(
            "🤖 *CONTROL CENTER*\n\n"
            "Welcome! Choose what you want to manage below.",
            reply_markup=self.main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )

    # =========================================================
    # CHANNEL MENU
    # =========================================================

    async def show_channels(
        self,
        query
    ):

        channels = await self.db.get_all_channels()

        rows = []

        if channels:

            for channel in channels:

                status = (
                    "🟢"
                    if channel["react_mode"]
                    else "🔴"
                )

                name = (
                    channel.get("channel_name")
                    or channel["channel_id"]
                )

                rows.append([
                    InlineKeyboardButton(
                        f"{status} {name}",
                        callback_data=(
                            f"channel:{channel['channel_id']}"
                        )
                    )
                ])

        rows.append([
            InlineKeyboardButton(
                "➕ Add Channel",
                callback_data="channel_add"
            )
        ])

        rows.append([
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="menu:home"
            )
        ])

        text = (
            "📢 *CHANNELS*\n\n"
            "Select a channel to manage it."
        )

        if not channels:
            text += (
                "\n\nYou haven't added any channels yet."
            )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN
        )

    # =========================================================
    # CHANNEL PANEL
    # =========================================================

    async def show_channel_panel(
        self,
        query,
        channel_id
    ):

        channel = await self.db.get_channel(channel_id)

        if not channel:

            await query.edit_message_text(
                "❌ Channel not found.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "◀️ Back",
                            callback_data="menu:channels"
                        )
                    ]
                ])
            )

            return

        status = (
            "🟢 ON"
            if channel["react_mode"]
            else "🔴 OFF"
        )

        stats = await self.db.get_stats(channel_id)

        name = (
            channel.get("channel_name")
            or channel["channel_id"]
        )

        text = (
            f"📢 *{name}*\n\n"

            f"Status: {status}\n"
            f"Reactions/post: "
            f"{channel['min_reactions']}-"
            f"{channel['max_reactions']}\n"
            f"Max delay: "
            f"{channel['max_delay_minutes']} minutes\n\n"

            f"📊 Today's statistics\n"
            f"Successful: {stats['successful']}\n"
            f"Failed: {stats['failed']}"
        )

        toggle_text = (
            "🔴 Turn OFF"
            if channel["react_mode"]
            else "🟢 Turn ON"
        )

        keyboard = [

            [
                InlineKeyboardButton(
                    toggle_text,
                    callback_data=f"toggle:{channel_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "📊 Statistics",
                    callback_data=f"stats:{channel_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "◀️ Back",
                    callback_data="menu:channels"
                )
            ],

        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

    # =========================================================
    # STATISTICS
    # =========================================================

    async def show_statistics(self, query):

        stats = await self.db.get_stats()

        total = stats["total"]
        successful = stats["successful"]
        failed = stats["failed"]

        if total:
            success_rate = (
                successful / total
            ) * 100
        else:
            success_rate = 0

        text = (
            "📊 *STATISTICS*\n\n"

            f"Total attempts: `{total}`\n"
            f"Successful: `{successful}`\n"
            f"Failed: `{failed}`\n"
            f"Success rate: `{success_rate:.1f}%`\n\n"

            f"Active bot connections: "
            f"`{len(self.reaction_manager.bot_instances)}`"
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="menu:home"
                )
            ]

        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

    # =========================================================
    # SETTINGS
    # =========================================================

    async def show_settings(self, query):

        text = (
            "⚙️ *SETTINGS*\n\n"

            "Your current global configuration:\n\n"

            f"Maximum connected accounts: "
            f"`{self.config.MAX_BOTS}`\n"

            f"Default daily limit: "
            f"`{self.config.DAILY_LIMIT_PER_BOT}`\n\n"

            "Channel-specific settings can be "
            "managed from the channel panel."
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "📢 Manage Channels",
                    callback_data="menu:channels"
                )
            ],

            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="menu:home"
                )
            ]

        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

    # =========================================================
    # HELP
    # =========================================================

    async def show_help(self, query):

        text = (
            "❓ *HOW TO USE THE BOT*\n\n"

            "📢 *Channels*\n"
            "Add and manage the channels connected "
            "to the system.\n\n"

            "📊 *Statistics*\n"
            "See today's activity and success rate.\n\n"

            "⚙️ *Settings*\n"
            "View the current configuration.\n\n"

            "Everything important can be accessed "
            "from the buttons, so you don't need "
            "to memorize commands."
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="menu:home"
                )
            ]

        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

    # =========================================================
    # CALLBACK HANDLER
    # =========================================================

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):

        query = update.callback_query

        user = query.from_user

        if user.id not in self.config.ADMIN_USER_IDS:

            await query.answer(
                "⛔ Unauthorized.",
                show_alert=True
            )

            return

        await query.answer()

        data = query.data or ""

        # -------------------------
        # MAIN MENU
        # -------------------------

        if data == "menu:home":

            await query.edit_message_text(
                "🤖 *CONTROL CENTER*\n\n"
                "Choose an option:",
                reply_markup=self.main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )

            return

        # -------------------------
        # CHANNEL LIST
        # -------------------------

        if data == "menu:channels":

            await self.show_channels(query)

            return

        # -------------------------
        # STATISTICS
        # -------------------------

        if data == "menu:stats":

            await self.show_statistics(query)

            return

        # -------------------------
        # SETTINGS
        # -------------------------

        if data == "menu:settings":

            await self.show_settings(query)

            return

        # -------------------------
        # HELP
        # -------------------------

        if data == "menu:help":

            await self.show_help(query)

            return

        # -------------------------
        # ADD CHANNEL
        # -------------------------

        if data == "channel_add":

            context.user_data["awaiting_channel"] = True

            await query.edit_message_text(
                "➕ *ADD CHANNEL*\n\n"
                "Send me the channel ID.\n\n"
                "Example:\n"
                "`-1001234567890`\n\n"
                "You can cancel by sending:\n"
                "`cancel`",
                parse_mode=ParseMode.MARKDOWN
            )

            return

        # -------------------------
        # OPEN CHANNEL
        # -------------------------

        if data.startswith("channel:"):

            channel_id = data.split(":", 1)[1]

            await self.show_channel_panel(
                query,
                channel_id
            )

            return

        # -------------------------
        # TOGGLE
        # -------------------------

        if data.startswith("toggle:"):

            channel_id = data.split(":", 1)[1]

            channel = await self.db.get_channel(
                channel_id
            )

            if not channel:

                await query.edit_message_text(
                    "❌ Channel no longer exists."
                )

                return

            new_mode = not bool(
                channel["react_mode"]
            )

            await self.db.update_channel_react_mode(
                channel_id,
                new_mode
            )

            await self.show_channel_panel(
                query,
                channel_id
            )

            return

        # -------------------------
        # CHANNEL STATS
        # -------------------------

        if data.startswith("stats:"):

            channel_id = data.split(":", 1)[1]

            stats = await self.db.get_stats(
                channel_id
            )

            text = (
                "📊 *CHANNEL STATISTICS*\n\n"
                f"Successful: `{stats['successful']}`\n"
                f"Failed: `{stats['failed']}`\n"
                f"Total: `{stats['total']}`"
            )

            keyboard = InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "◀️ Back",
                        callback_data=f"channel:{channel_id}"
                    )
                ]

            ])

            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )

            return

    # =========================================================
    # ADD CHANNEL MESSAGE HANDLER
    # =========================================================

    async def handle_private_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):

        user = update.effective_user

        if not user:
            return

        if user.id not in self.config.ADMIN_USER_IDS:
            return

        if not context.user_data.get(
            "awaiting_channel"
        ):
            return

        text = (
            update.effective_message.text
            or ""
        ).strip()

        if text.lower() == "cancel":

            context.user_data.pop(
                "awaiting_channel",
                None
            )

            await update.effective_message.reply_text(
                "❌ Cancelled.",
                reply_markup=self.main_menu_keyboard()
            )

            return

        if not text.startswith("-100"):

            await update.effective_message.reply_text(
                "❌ That doesn't look like a Telegram "
                "channel ID.\n\n"
                "Channel IDs normally look like:\n"
                "`-1001234567890`\n\n"
                "Try again or send `cancel`.",
                parse_mode=ParseMode.MARKDOWN
            )

            return

        channel_id = text

        added = await self.db.add_channel(
            channel_id,
            channel_id
        )

        context.user_data.pop(
            "awaiting_channel",
            None
        )

        if added:

            await update.effective_message.reply_text(
                "✅ *Channel added!*\n\n"
                f"Channel ID: `{channel_id}`\n\n"
                "You can now manage it from "
                "the Channels menu.",
                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "📢 Open Channels",
                            callback_data="menu:channels"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "🏠 Main Menu",
                            callback_data="menu:home"
                        )
                    ]

                ]),
                parse_mode=ParseMode.MARKDOWN
            )

        else:

            await update.effective_message.reply_text(
                "ℹ️ That channel is already registered.",
                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "📢 Open Channels",
                            callback_data="menu:channels"
                        )
                    ]

                ])
            )

    # =========================================================
    # CHANNEL POSTS
    # =========================================================

    async def handle_channel_post(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):

        channel_id = str(
            update.effective_chat.id
        )

        if not await self.db.get_channel(
            channel_id
        ):
            return

        msg = update.effective_message

        post_text = (
            msg.text
            or msg.caption
            or ""
        )

        await self.reaction_manager.schedule_reactions(
            channel_id,
            msg.message_id,
            post_text
        )

    # =========================================================
    # RUN
    # =========================================================

    def run(self):

        if self.application is None:
            self.build()

        logger.info(
            "Starting master bot polling..."
        )

        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
