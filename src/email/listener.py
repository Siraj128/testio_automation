"""Email IMAP Listener for instant Test IO invitation triggers.

Robust version with:
- Watchdog that auto-restarts the listener if it dies
- Heartbeat logging every cycle so you can see it's alive
- Telegram alerts on listener death / recovery
- Proper cleanup of IMAP IDLE on every path
- Catches ALL exceptions (including aioimaplib internal bugs)
"""
import asyncio
import logging
import os
import traceback
from datetime import datetime

import aioimaplib

logger = logging.getLogger(__name__)

_email_task: asyncio.Task | None = None
_watchdog_task: asyncio.Task | None = None
_stop_event = asyncio.Event()

# Track listener health for watchdog
_last_heartbeat: datetime | None = None
_listener_alive = False
_consecutive_failures = 0


async def _safe_notify(config: dict, message: str) -> None:
    """Send a Telegram notification, never raising."""
    try:
        from ..notifications.telegram import notify_status
        await notify_status(message, config)
    except Exception:
        pass


async def _parse_email_headers(fetch_response) -> tuple[str, str]:
    """Extract From and Subject from an aioimaplib fetch response.
    
    Returns (from_addr, subject) — both empty strings on failure.
    """
    try:
        raw_text = ""
        for line in fetch_response.lines:
            if isinstance(line, (bytes, bytearray)):
                raw_text += line.decode('utf-8', errors='ignore') + "\n"
            elif isinstance(line, str):
                raw_text += line + "\n"

        import re
        from email.header import decode_header

        def _dec(text):
            if not text:
                return ""
            try:
                parts = decode_header(text)
                res = ""
                for p, enc in parts:
                    if isinstance(p, bytes):
                        res += p.decode(enc or 'utf-8', errors='ignore')
                    else:
                        res += p
                return res
            except Exception:
                return text

        from_match = re.search(r'(?i)From:\s*([^\r\n]+)', raw_text)
        subj_match = re.search(r'(?i)Subject:\s*([^\r\n]+)', raw_text)
        mid_match = re.search(r'(?i)Message-ID:\s*([^\r\n]+)', raw_text)
        date_match = re.search(r'(?i)Date:\s*([^\r\n]+)', raw_text)

        from_addr = _dec(from_match.group(1).strip()) if from_match else ""
        subject = _dec(subj_match.group(1).strip()) if subj_match else ""
        msg_id_hdr = _dec(mid_match.group(1).strip()) if mid_match else ""
        date_hdr = _dec(date_match.group(1).strip()) if date_match else ""
        
        return from_addr, subject, msg_id_hdr, date_hdr
    except Exception as e:
        logger.warning(f"Failed to parse email headers: {e}")
        return "", "", "", ""


def _is_invitation(subject: str) -> bool:
    """Check if an email subject indicates a test invitation."""
    subject_lower = subject.lower()
    return any(
        k in subject_lower
        for k in ["invitation", "invited", "new test", "test cycle", "available"]
    )


async def _do_imap_search(client, search_query: str) -> set[str]:
    """Run an IMAP search and return a set of message ID strings."""
    msg_ids = set()
    try:
        res = await client.search(search_query)
        if res.result == 'OK' and res.lines:
            for line in res.lines:
                if isinstance(line, (bytes, bytearray)):
                    line = line.decode('utf-8', errors='ignore')
                if isinstance(line, str):
                    msg_ids.update(mid for mid in line.strip().split() if mid.isdigit())
    except Exception as e:
        logger.warning(f"IMAP search '{search_query}' failed: {e}")
    return msg_ids


async def _process_new_emails(client, config: dict, trigger_callback) -> int:
    """Check for unseen Cirro/Test.io emails, process them, return count found."""
    import hashlib
    from ..database import stats
    
    # Server-side search for unseen emails from target senders
    msg_ids = set()
    msg_ids |= await _do_imap_search(client, 'UNSEEN FROM "cirro"')
    msg_ids |= await _do_imap_search(client, 'UNSEEN FROM "test.io"')

    if not msg_ids:
        return 0

    logger.info(f"📧 Found {len(msg_ids)} unseen email(s) from Cirro/Test.io")
    invitations_found = 0

    for msg_id in sorted(msg_ids, key=lambda x: int(x)):
        try:
            fetch_response = await client.fetch(
                msg_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID DATE)])'
            )
            if fetch_response.result != 'OK':
                logger.warning(f"Fetch failed for msg {msg_id}: {fetch_response.result}")
                continue

            from_addr, subject, msg_id_hdr, date_hdr = await _parse_email_headers(fetch_response)
            
            # Generate a unique fingerprint for this email
            if msg_id_hdr:
                fingerprint = msg_id_hdr
            else:
                # Fallback if Message-ID is missing (some automated or spoofed emails)
                raw_fp = f"{from_addr}|{subject}|{date_hdr}"
                fingerprint = "hash:" + hashlib.md5(raw_fp.encode('utf-8')).hexdigest()
                
            logger.info(f"  📩 Email #{msg_id}: From={from_addr}, Subject={subject}")

            if _is_invitation(subject):
                # Check if we've already processed this exact email
                if await stats.is_email_processed(fingerprint):
                    logger.info(f"  ℹ️ Email {fingerprint} already processed. Skipping to avoid reload loop.")
                    continue
                    
                invitations_found += 1
                logger.info(f"🚨 NEW TEST INVITATION DETECTED!")
                logger.info(f"   From: {from_addr}")
                logger.info(f"   Subject: {subject}")

                await _safe_notify(
                    config,
                    f"📧 *Email Alert — New Test Invitation!*\n"
                    f"From: {from_addr}\n"
                    f"Subject: {subject}\n"
                    f"⚡ Waking up bot instantly..."
                )
                
                # Mark it as processed in our local database BEFORE triggering callback
                await stats.mark_email_processed(fingerprint)
                trigger_callback()
            else:
                logger.info(f"  ℹ️ Non-invitation email, skipping trigger")

            # We intentionally DO NOT mark the email as \Seen here anymore.
            # This allows the email to remain unread in the user's inbox, 
            # while the local database prevents the bot from infinitely reloading.

        except Exception as e:
            logger.warning(f"Error processing email {msg_id}: {e}")

    return invitations_found


async def _listen_loop(config: dict, trigger_callback) -> None:
    """Main IMAP listener loop with IDLE push notifications."""
    global _last_heartbeat, _listener_alive, _consecutive_failures

    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    user = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")

    if not user or not password:
        logger.warning("Email IMAP credentials missing — email listener disabled.")
        return

    reconnect_count = 0

    while not _stop_event.is_set():
        client = None
        try:
            logger.info(f"📧 Connecting to IMAP server {host}:{port}...")
            client = aioimaplib.IMAP4_SSL(host=host, port=port)
            await asyncio.wait_for(client.wait_hello_from_server(), timeout=30)

            login_res = await asyncio.wait_for(client.login(user, password), timeout=30)
            if login_res.result != 'OK':
                logger.error(f"IMAP login failed: {login_res.result}")
                raise RuntimeError("IMAP login failed")

            await asyncio.wait_for(client.select('INBOX'), timeout=30)
            logger.info("📧 Email listener active! Connected and monitoring INBOX.")
            
            _listener_alive = True
            _last_heartbeat = datetime.now()
            _consecutive_failures = 0

            # Notify on reconnection (not first connection)
            if reconnect_count > 0:
                await _safe_notify(config, "📧 *Email Listener Reconnected!*\nBack online and monitoring.")
            reconnect_count += 1

            # === Inner IDLE loop ===
            cycle = 0
            while not _stop_event.is_set():
                cycle += 1
                _last_heartbeat = datetime.now()

                # Check for new emails
                try:
                    found = await _process_new_emails(client, config, trigger_callback)
                    if found > 0:
                        logger.info(f"✅ Processed {found} invitation email(s)")
                except Exception as e:
                    logger.error(f"Error processing emails: {e}")

                # Log heartbeat every 10 cycles (~50 min)
                if cycle % 10 == 1:
                    logger.info(f"💓 Email listener heartbeat — cycle {cycle}, alive since {reconnect_count} connect(s)")

                # Enter IMAP IDLE — wait for server push or timeout
                try:
                    await client.idle_start(timeout=290)
                    
                    # Wait for either: a server push (like EXISTS), stop event, or hard timeout
                    push_task = asyncio.create_task(client.wait_server_push())
                    stop_task = asyncio.create_task(_stop_event.wait())
                    
                    done, pending = await asyncio.wait(
                        [push_task, stop_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Always cleanly end IDLE before doing anything else
                    client.idle_done()
                    
                    # Wait for the push task to finish if it hasn't already
                    try:
                        await asyncio.wait_for(push_task, timeout=5)
                    except (asyncio.TimeoutError, Exception):
                        pass
                    
                    for p in pending:
                        p.cancel()
                        try:
                            await p
                        except (asyncio.CancelledError, Exception):
                            pass

                    if _stop_event.is_set():
                        break

                except asyncio.TimeoutError:
                    # IDLE timed out — this is normal, just loop again
                    logger.debug("IDLE timeout — reconnecting IDLE")
                except Exception as e:
                    logger.warning(f"IDLE error: {e} — will reconnect")
                    break  # Break inner loop to force full reconnect

        except asyncio.CancelledError:
            logger.info("Email listener cancelled")
            break
        except Exception as e:
            _listener_alive = False
            _consecutive_failures += 1
            logger.error(f"Email listener error (attempt #{_consecutive_failures}): {e}")
            logger.debug(traceback.format_exc())

            if _consecutive_failures >= 3:
                await _safe_notify(
                    config,
                    f"🔴 *Email Listener Down!*\n"
                    f"Failed {_consecutive_failures} times.\n"
                    f"Error: `{str(e)[:200]}`\n"
                    f"Will keep retrying..."
                )

        finally:
            _listener_alive = False
            if client:
                try:
                    await client.logout()
                except Exception:
                    pass

        if not _stop_event.is_set():
            wait_time = min(30 * _consecutive_failures, 300)  # Back off up to 5 min
            logger.info(f"Reconnecting in {wait_time} seconds...")
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=wait_time)
            except asyncio.TimeoutError:
                pass  # Normal — stop_event wasn't set, time to reconnect


async def _watchdog_loop(config: dict, trigger_callback) -> None:
    """Watchdog that monitors the listener task and restarts it if it dies."""
    global _email_task, _last_heartbeat

    while not _stop_event.is_set():
        try:
            await asyncio.sleep(120)  # Check every 2 minutes
        except asyncio.CancelledError:
            break

        if _stop_event.is_set():
            break

        # Check if the listener task is still alive
        if _email_task is None or _email_task.done():
            logger.warning("🔄 Watchdog: Email listener task is dead — restarting!")
            await _safe_notify(
                config,
                "🔄 *Watchdog Alert*\nEmail listener died — restarting automatically..."
            )
            _email_task = asyncio.create_task(_listen_loop(config, trigger_callback))
            continue

        # Check heartbeat staleness (no heartbeat for 15 min = probably stuck)
        if _last_heartbeat:
            staleness = (datetime.now() - _last_heartbeat).total_seconds()
            if staleness > 900:  # 15 minutes
                logger.warning(f"🔄 Watchdog: Listener heartbeat stale ({staleness:.0f}s) — restarting!")
                await _safe_notify(
                    config,
                    f"🔄 *Watchdog Alert*\nEmail listener appears stuck (no heartbeat for {staleness/60:.0f} min) — restarting..."
                )
                _email_task.cancel()
                try:
                    await _email_task
                except (asyncio.CancelledError, Exception):
                    pass
                _email_task = asyncio.create_task(_listen_loop(config, trigger_callback))


def start_email_listener(config: dict, trigger_callback) -> None:
    """Start the IMAP listener and watchdog in the background."""
    global _email_task, _watchdog_task
    _stop_event.clear()
    _email_task = asyncio.create_task(_listen_loop(config, trigger_callback))
    _watchdog_task = asyncio.create_task(_watchdog_loop(config, trigger_callback))


async def stop_email_listener() -> None:
    """Stop the IMAP listener and watchdog."""
    _stop_event.set()
    
    if _email_task:
        _email_task.cancel()
        try:
            await _email_task
        except (asyncio.CancelledError, Exception):
            pass
    
    if _watchdog_task:
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except (asyncio.CancelledError, Exception):
            pass
