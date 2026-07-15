"""Telegram notification sender — sends alerts + screenshots + remote control."""
import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime
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


async def notify_test_spotted(test_name: str, config: dict) -> None:
    """Notify that a test was found on the page (before attempting to accept)."""
    await send_message(f"🔍 *Test Spotted!*\n\n{test_name}\n\n⚡ Attempting to accept...", config)


async def notify_crash_recovery(error: str, config: dict) -> None:
    """Notify that the bot crashed and is auto-recovering."""
    await send_message(
        f"🔄 *Auto-Recovery*\n\n"
        f"The bot hit an error and is recovering automatically.\n"
        f"Error: `{error[:200]}`",
        config
    )


async def notify_reauth_success(config: dict) -> None:
    """Notify that session re-authentication succeeded."""
    await send_message("✅ *Re-Auth Success*\nSession restored successfully.", config)


async def notify_schedule_change(period_name: str, mode: str, config: dict) -> None:
    """Notify when the schedule period changes."""
    mode_emoji = {
        "strict": "🔴",
        "normal": "🟢",
        "light": "🟡",
        "sleep": "😴",
    }
    emoji = mode_emoji.get(mode, "🕐")
    await send_message(f"{emoji} *Schedule: {period_name}*\nMode switched to `{mode}`", config)


async def notify_email_reconnected(config: dict) -> None:
    """Notify that the email IMAP listener reconnected."""
    await send_message("📧 *Email Reconnected*\nIMAP listener is back online.", config)


# ==========================================
# HEARTBEAT & DAILY SUMMARY BACKGROUND TASKS
# ==========================================

_heartbeat_task: asyncio.Task | None = None
_daily_task: asyncio.Task | None = None


async def _heartbeat_loop(config: dict) -> None:
    """Send a heartbeat notification every 6 hours."""
    while True:
        await asyncio.sleep(6 * 60 * 60)  # 6 hours
        try:
            from ..bot.engine import get_bot
            from ..database.stats import get_today
            bot = get_bot()
            today = await get_today()

            if bot:
                uptime = bot.status.uptime_str
                state = bot.status.state.value
                text = (
                    f"💓 *Heartbeat*\n\n"
                    f"Status: `{state}`\n"
                    f"Uptime: `{uptime}`\n"
                    f"Today's Polls: `{today['refreshes']}`\n"
                    f"Accepted: `{today['accepted']}`\n"
                    f"Failed: `{today['failed']}`"
                )
            else:
                text = "💓 *Heartbeat*\n\n⚠️ Bot engine not running!"
            await send_message(text, config)
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")


async def _daily_summary_loop(config: dict) -> None:
    """Send a daily summary at midnight IST."""
    while True:
        # Calculate seconds until next midnight
        now = datetime.now()
        tomorrow_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= tomorrow_midnight:
            from datetime import timedelta
            tomorrow_midnight += timedelta(days=1)
        seconds_until = (tomorrow_midnight - now).total_seconds()
        await asyncio.sleep(seconds_until)

        try:
            await _send_daily_summary(config)
        except Exception as e:
            logger.error(f"Daily summary failed: {e}")


async def _send_daily_summary(config: dict) -> None:
    """Build and send the daily summary."""
    from ..database.stats import get_today
    from ..bot.engine import get_bot
    
    today = await get_today()
    bot = get_bot()
    uptime = bot.status.uptime_str if bot else "N/A"
    
    text = (
        f"📊 *Daily Summary — {datetime.now().strftime('%b %d, %Y')}*\n"
        f"─────────────────────\n"
        f"🔄 Polls: `{today['refreshes']}`\n"
        f"✅ Accepted: `{today['accepted']}`\n"
        f"❌ Failed: `{today['failed']}`\n"
        f"⏱ Uptime: `{uptime}`\n"
        f"─────────────────────\n"
        f"_Goodnight! Bot continues running autonomously._"
    )
    await send_message(text, config)


def start_background_notifiers(config: dict) -> None:
    """Start heartbeat and daily summary background loops."""
    global _heartbeat_task, _daily_task
    _heartbeat_task = asyncio.create_task(_heartbeat_loop(config))
    _daily_task = asyncio.create_task(_daily_summary_loop(config))
    logger.info("📢 Background notifiers started (heartbeat + daily summary)")


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
        _app.add_handler(CommandHandler("testemail", _cmd_testemail))
        _app.add_handler(CommandHandler("daily", _cmd_daily))
        _app.add_handler(CallbackQueryHandler(_btn_speed, pattern="^speed_"))
        
        await _app.initialize()
        await _app.start()
        
        # Set the persistent menu commands in the Telegram UI
        commands = [
            BotCommand("status", "Check current state and stats"),
            BotCommand("stats", "View 7-day weekly report"),
            BotCommand("speed", "Adjust polling speed"),
            BotCommand("screenshot", "Take a live screenshot"),
            BotCommand("testemail", "Verify email listener is alive"),
            BotCommand("daily", "Force send daily summary now"),
            BotCommand("pause", "Pause the bot"),
            BotCommand("resume", "Resume the bot"),
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
    
    keyboard = [
        ["/status", "/stats"],
        ["/speed", "/screenshot"],
        ["/testemail", "/daily"],
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
            state = bot.status.state.value
            uptime = bot.status.uptime_str
            active = bot.status.active_test_count
            last_poll = bot.status.last_poll_at.strftime("%H:%M:%S") if bot.status.last_poll_at else "Never"
            text = (
                f"📊 *Live Bot Status*\n\n"
                f"State: `{state}`\n"
                f"Uptime: `{uptime}`\n"
                f"Active Tests: `{active}`\n"
                f"Last Poll: `{last_poll}`\n\n"
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

async def _cmd_testemail(update, context) -> None:
    """Verify that the email IMAP listener is working."""
    if not await _verify_user(update): return
    
    await update.message.reply_text("📧 Testing email connection...")
    
    try:
        import aioimaplib
        
        host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
        port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
        user = os.getenv("EMAIL_ADDRESS", "")
        password = os.getenv("EMAIL_PASSWORD", "")
        
        if not user or not password:
            await update.message.reply_text("❌ Email credentials not configured in .env")
            return
        
        # Connect and login
        client = aioimaplib.IMAP4_SSL(host=host, port=port)
        await client.wait_hello_from_server()
        login_res = await client.login(user, password)
        
        if login_res.result != 'OK':
            await update.message.reply_text("❌ IMAP login failed! Check EMAIL_PASSWORD in .env")
            return
        
        await client.select('INBOX')
        
        # Search for recent Test.io/Cirro emails
        msg_ids = set()
        
        # Search 1: Cirro
        res_cirro = await client.search('FROM "cirro"')
        if res_cirro.result == 'OK' and res_cirro.lines:
            for line in res_cirro.lines:
                if isinstance(line, bytes): line = line.decode('utf-8', errors='ignore')
                msg_ids.update([mid for mid in line.strip().split() if mid.isdigit()])
                
        # Search 2: Test.io
        res_testio = await client.search('FROM "test.io"')
        if res_testio.result == 'OK' and res_testio.lines:
            for line in res_testio.lines:
                if isinstance(line, bytes): line = line.decode('utf-8', errors='ignore')
                msg_ids.update([mid for mid in line.strip().split() if mid.isdigit()])
        
        testio_emails = []
        if msg_ids:
            # Sort numerically
            sorted_ids = sorted(list(msg_ids), key=lambda x: int(x))
            
            # Check the last 10 matching emails
            recent_ids = sorted_ids[-10:] if len(sorted_ids) > 10 else sorted_ids
            
            for msg_id in reversed(recent_ids):
                try:
                    fetch_response = await client.fetch(
                        msg_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'
                    )
                    if fetch_response.result != 'OK':
                        continue
                    
                    raw_text = ""
                    for line in fetch_response.lines:
                        if isinstance(line, bytes):
                            raw_text += line.decode('utf-8', errors='ignore') + "\n"
                        elif isinstance(line, str):
                            raw_text += line + "\n"
                    
                    import re
                    from_match = re.search(r'(?im)^From:\s*(.*)', raw_text)
                    subj_match = re.search(r'(?im)^Subject:\s*(.*)', raw_text)
                    date_match = re.search(r'(?im)^Date:\s*(.*)', raw_text)
                    
                    from_addr = from_match.group(1).strip() if from_match else ""
                    subject = subj_match.group(1).strip() if subj_match else ""
                    date = date_match.group(1).strip() if date_match else ""
                    
                    testio_emails.append({
                        "from": from_addr,
                        "subject": subject,
                        "date": date
                    })
                except Exception:
                    continue
        
        await client.logout()
        
        # Build report
        if testio_emails:
            text = "✅ *Email Connection Working!*\n\n"
            text += f"Connected to: `{host}`\n"
            text += f"Account: `{user}`\n\n"
            text += "*Recent Test.io Emails:*\n"
            for i, email in enumerate(testio_emails, 1):
                text += f"\n{i}. {email['subject']}\n"
                text += f"   From: {email['from']}\n"
                text += f"   Date: {email['date']}\n"
        else:
            text = (
                "✅ *Email Connection Working!*\n\n"
                f"Connected to: `{host}`\n"
                f"Account: `{user}`\n\n"
                "⚠️ No recent Test.io/Cirro emails found in the last 20 messages."
            )
        
        # Also check if the background IMAP listener is alive
        from ..email.listener import _email_task
        if _email_task and not _email_task.done():
            text += "\n\n🟢 Background IMAP IDLE listener: *Active*"
        else:
            text += "\n\n🔴 Background IMAP IDLE listener: *Dead* — will auto-restart"
            
        # Trigger an instant reload of the bot to simulate real-time behavior
        try:
            from ..bot.engine import _bot_instance
            if _bot_instance:
                _bot_instance.trigger_instant_reload()
                text += "\n🚀 *Simulating Instant Bot Wakeup...*"
                
                # Also notify via the standard bot notification channel for realism
                from .telegram import notify_status
                await notify_status(
                    "📧 *Manual Email Test Triggered!*\n"
                    "⚡ Waking up bot instantly...", 
                    _bot_instance.config
                )
        except Exception as e:
            text += f"\n⚠️ Failed to trigger bot reload: {e}"
        
        await update.message.reply_text(text, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Email test failed:\n`{e}`", parse_mode="Markdown")

async def _cmd_daily(update, context) -> None:
    """Force-send the daily summary right now."""
    if not await _verify_user(update): return
    try:
        from ..bot.engine import get_bot
        bot = get_bot()
        config = bot.config if bot else {}
        await _send_daily_summary(config)
        await update.message.reply_text("📊 Daily summary sent above!")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
