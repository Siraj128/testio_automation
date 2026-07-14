"""Telegram notification sender — sends alerts + screenshots."""
import os
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import to avoid dependency issues during startup
_bot = None


async def _get_bot():
    """Lazy-initialize the Telegram bot."""
    global _bot
    if _bot is None:
        try:
            from telegram import Bot
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if token:
                _bot = Bot(token=token)
            else:
                logger.warning("TELEGRAM_BOT_TOKEN not set — notifications disabled")
        except ImportError:
            logger.warning("python-telegram-bot not installed — notifications disabled")
    return _bot


def _should_send(category: str, config: dict) -> bool:
    """Check if notifications are enabled for this category."""
    notif_config = config.get("notifications", {})
    if not notif_config.get("enabled", True):
        return False
    return notif_config.get(category, True)


async def send_message(text: str, config: dict) -> None:
    """Send a text message to the configured Telegram chat."""
    bot = await _get_bot()
    if not bot:
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID not set — skipping notification")
        return

    try:
        async with bot:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )
        logger.info(f"📱 Telegram message sent: {text[:50]}...")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


async def send_photo(photo_path: str, caption: str, config: dict) -> None:
    """Send a photo (screenshot) to the configured Telegram chat."""
    bot = await _get_bot()
    if not bot:
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        return

    try:
        path = Path(photo_path)
        if not path.exists():
            logger.warning(f"Screenshot not found: {photo_path}")
            await send_message(caption, config)
            return

        async with bot:
            with open(path, "rb") as photo:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption[:1024],  # Telegram caption limit
                    parse_mode="Markdown",
                )
        logger.info(f"📱 Telegram photo sent: {path.name}")
    except Exception as e:
        logger.error(f"Telegram photo send failed: {e}")
        # Fallback to text-only
        await send_message(caption, config)


async def notify_accepted(test_name: str, screenshot_path: str | None, config: dict) -> None:
    """Notify that a test was successfully accepted."""
    if not _should_send("on_accept", config):
        return

    text = f"🎯 *Test Accepted!*\n\n{test_name}"
    notif_config = config.get("notifications", {})

    if screenshot_path and notif_config.get("send_screenshot", True):
        await send_photo(screenshot_path, text, config)
    else:
        await send_message(text, config)


async def notify_error(error: str, screenshot_path: str | None, config: dict) -> None:
    """Notify about an error during acceptance."""
    if not _should_send("on_error", config):
        return

    text = f"❌ *Acceptance Failed*\n\n{error}"
    notif_config = config.get("notifications", {})

    if screenshot_path and notif_config.get("send_screenshot", True):
        await send_photo(screenshot_path, text, config)
    else:
        await send_message(text, config)


async def notify_status(message: str, config: dict) -> None:
    """Send a general status notification."""
    notif_config = config.get("notifications", {})
    if not notif_config.get("enabled", True):
        return
    await send_message(message, config)

# ==========================================
# REMOTE CONTROL LISTENER
# ==========================================

_app = None

async def start_telegram_listener() -> None:
    """Start the Telegram polling listener for remote control."""
    global _app
    
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("No TELEGRAM_BOT_TOKEN found — remote control disabled.")
        return
        
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
        from telegram import BotCommand
        
        _app = ApplicationBuilder().token(token).build()
        
        # Add handlers
        _app.add_handler(CommandHandler("start", _cmd_start))
        _app.add_handler(CommandHandler("status", _cmd_status))
        _app.add_handler(CommandHandler("pause", _cmd_pause))
        _app.add_handler(CommandHandler("resume", _cmd_resume))
        _app.add_handler(CommandHandler("screenshot", _cmd_screenshot))
        _app.add_handler(CommandHandler("stats", _cmd_stats))
        _app.add_handler(CommandHandler("speed", _cmd_speed))
        _app.add_handler(CallbackQueryHandler(_btn_speed, pattern="^speed_"))
        
        await _app.initialize()
        await _app.start()
        
        # Set the persistent menu commands in the Telegram UI
        commands = [
            BotCommand("status", "Check current state and stats"),
            BotCommand("stats", "View 7-day weekly report"),
            BotCommand("speed", "Adjust polling speed"),
            BotCommand("pause", "Pause the bot"),
            BotCommand("resume", "Resume the bot"),
            BotCommand("screenshot", "Take a live screenshot"),
        ]
        await _app.bot.set_my_commands(commands)
        
        await _app.updater.start_polling(drop_pending_updates=True)
        logger.info("📱 Telegram remote control active! Listening for commands...")
        
    except ImportError:
        logger.warning("python-telegram-bot not installed — remote control disabled.")
    except Exception as e:
        logger.error(f"Failed to start Telegram listener: {e}")

async def stop_telegram_listener() -> None:
    """Safely stop the Telegram polling listener."""
    global _app
    if _app:
        try:
            await _app.updater.stop()
            await _app.stop()
            await _app.shutdown()
            logger.info("📱 Telegram listener stopped.")
        except Exception as e:
            logger.error(f"Error stopping Telegram listener: {e}")

# --- Command Handlers ---

async def _verify_user(update) -> bool:
    """Ensure the sender is the authorized user."""
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(update.effective_chat.id) != chat_id:
        await update.message.reply_text("Unauthorized.")
        return False
    return True

async def _cmd_start(update, context) -> None:
    if not await _verify_user(update): return
    from telegram import ReplyKeyboardMarkup
    
    text = (
        "🤖 *Test IO Bot Remote Control*\n\n"
        "Welcome! Use the buttons below to control the bot instantly."
    )
    
    # Create persistent clickable buttons that type the commands for the user
    keyboard = [
        ["/status", "/stats"],
        ["/speed", "/screenshot"],
        ["/pause", "/resume"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def _cmd_status(update, context) -> None:
    if not await _verify_user(update): return
    try:
        from ..bot.engine import get_bot
        from ..database.stats import get_today
        bot = get_bot()
        today = await get_today()
        
        if bot:
            state = bot.status.state
            active = bot.status.active_test_count
            text = (
                f"📊 *Live Bot Status*\n\n"
                f"State: `{state}`\n"
                f"Active Tests: `{active}`\n\n"
                f"📆 *Today's Stats*\n"
                f"Refreshes: `{today['refreshes']}`\n"
                f"Accepted: `{today['accepted']}`\n"
                f"Failed: `{today['failed']}`"
            )
        else:
            text = "Bot engine is not running."
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def _cmd_stats(update, context) -> None:
    if not await _verify_user(update): return
    try:
        from ..database.stats import get_weekly
        report = await get_weekly()
        
        text = "📊 *7-Day Weekly Report*\n"
        text += "─────────────────────\n"
        text += "`Date    | Polls | ✅ | ❌`\n"
        
        tot_polls = 0
        tot_acc = 0
        tot_fail = 0
        
        for day in report:
            text += f"`{day['display_date']:<7} | {day['refreshes']:>5} | {day['accepted']:>2} | {day['failed']:>2}`\n"
            tot_polls += day['refreshes']
            tot_acc += day['accepted']
            tot_fail += day['failed']
            
        text += "─────────────────────\n"
        text += f"`TOTAL   | {tot_polls:>5} | {tot_acc:>2} | {tot_fail:>2}`"
        
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def _cmd_speed(update, context) -> None:
    if not await _verify_user(update): return
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = [
        [InlineKeyboardButton("🐢 Slow (60-120s)", callback_data="speed_60_120")],
        [InlineKeyboardButton("🚶 Normal (20-60s)", callback_data="speed_20_60")],
        [InlineKeyboardButton("🏃 Fast (10-25s)", callback_data="speed_10_25")],
        [InlineKeyboardButton("⚡ Turbo (5-12s)", callback_data="speed_5_12")],
        [InlineKeyboardButton("🔄 Auto (Schedule Default)", callback_data="speed_auto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🏎️ Select polling speed:", reply_markup=reply_markup)

async def _btn_speed(update, context) -> None:
    query = update.callback_query
    await query.answer()
    
    if not await _verify_user(update): return
    
    try:
        from ..bot.engine import get_bot
        bot = get_bot()
        if not bot:
            await query.edit_message_text(text="Bot engine is not running.")
            return
            
        if query.data == "speed_auto":
            bot.reset_poll_speed()
            await query.edit_message_text(text="🔄 Speed reset to your 24-hour Schedule Defaults")
            return
            
        # Parse speed_MIN_MAX
        parts = query.data.split("_")
        min_sec = int(parts[1])
        max_sec = int(parts[2])
        
        bot.set_poll_speed(min_sec, max_sec)
        await query.edit_message_text(text=f"🏎️ Speed adjusted to {min_sec}-{max_sec}s")
    except Exception as e:
        await query.edit_message_text(text=f"Error: {e}")

async def _cmd_pause(update, context) -> None:
    if not await _verify_user(update): return
    try:
        from ..bot.engine import get_bot
        bot = get_bot()
        if bot:
            bot.pause()
            await update.message.reply_text("⏸ Bot paused successfully.")
        else:
            await update.message.reply_text("Bot engine is not running.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def _cmd_resume(update, context) -> None:
    if not await _verify_user(update): return
    try:
        from ..bot.engine import get_bot
        bot = get_bot()
        if bot:
            bot.resume()
            await update.message.reply_text("▶️ Bot resumed successfully.")
        else:
            await update.message.reply_text("Bot engine is not running.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def _cmd_screenshot(update, context) -> None:
    if not await _verify_user(update): return
    try:
        from ..bot.engine import get_bot
        bot = get_bot()
        if not bot:
            await update.message.reply_text("Bot engine is not running.")
            return
            
        await update.message.reply_text("📸 Taking screenshot...")
        path = await bot.force_screenshot()
        
        if path and Path(path).exists():
            with open(path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption="Live view")
        else:
            await update.message.reply_text("❌ Failed to capture screenshot.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
