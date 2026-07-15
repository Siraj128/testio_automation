"""Email IMAP Listener for instant Test IO invitation triggers."""
import asyncio
import logging
import os
import aioimaplib

logger = logging.getLogger(__name__)

_email_task: asyncio.Task | None = None
_stop_event = asyncio.Event()

async def _listen_loop(config: dict, trigger_callback) -> None:
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    user = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")

    if not user or not password:
        logger.warning("Email IMAP credentials missing — instant reload disabled.")
        return

    while not _stop_event.is_set():
        try:
            logger.info(f"Connecting to IMAP server {host}:{port}...")
            client = aioimaplib.IMAP4_SSL(host=host, port=port)
            await client.wait_hello_from_server()
            
            login_res = await client.login(user, password)
            if login_res.result != 'OK':
                logger.error("IMAP login failed. Check credentials.")
                return

            await client.select('INBOX')
            logger.info("📧 Email listener active! Waiting for push notifications (IDLE)...")
            
            while not _stop_event.is_set():
                # Simple search: get ALL unseen emails
                response = await client.search('UNSEEN')
                
                if response.result == 'OK' and response.lines:
                    # Extract message IDs from the response
                    msg_ids = []
                    for line in response.lines:
                        if isinstance(line, bytes):
                            line = line.decode('utf-8', errors='ignore')
                        if isinstance(line, str):
                            ids = line.strip().split()
                            msg_ids.extend([mid for mid in ids if mid.isdigit()])
                    
                    for msg_id in msg_ids:
                        try:
                            # Fetch the FROM and SUBJECT headers
                            fetch_response = await client.fetch(
                                msg_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])'
                            )
                            
                            if fetch_response.result != 'OK':
                                logger.debug(f"Fetch failed for msg {msg_id}: {fetch_response.result}")
                                continue
                            
                            # Parse headers from response lines
                            from_addr = ""
                            subject = ""
                            
                            raw_text = ""
                            for line in fetch_response.lines:
                                if isinstance(line, bytes):
                                    raw_text += line.decode('utf-8', errors='ignore')
                                elif isinstance(line, str):
                                    raw_text += line
                            
                            for text_line in raw_text.splitlines():
                                text_line_stripped = text_line.strip()
                                if text_line_stripped.lower().startswith('from:'):
                                    from_addr = text_line_stripped[5:].strip().lower()
                                elif text_line_stripped.lower().startswith('subject:'):
                                    subject = text_line_stripped[8:].strip()
                            
                            # Check if this email is from Test.io / Cirro
                            is_testio_email = any(
                                sender in from_addr 
                                for sender in ["test.io", "cirro.io", "cirro", "testio"]
                            )
                            
                            if is_testio_email:
                                subject_lower = subject.lower()
                                is_invitation = any(
                                    k in subject_lower 
                                    for k in ["invitation", "invited", "new test", "test cycle", "available"]
                                )
                                
                                if is_invitation:
                                    logger.info(f"🚨 New Test IO invitation email detected!")
                                    logger.info(f"   From: {from_addr}")
                                    logger.info(f"   Subject: {subject}")
                                    try:
                                        from ..notifications.telegram import notify_status
                                        await notify_status(
                                            f"📧 *Email Alert!*\n"
                                            f"Subject: {subject}\n"
                                            f"⚡ Waking up instantly...", 
                                            config
                                        )
                                    except Exception as e:
                                        logger.error(f"Failed to send email notification: {e}")
                                    trigger_callback()
                                else:
                                    logger.debug(f"Non-invitation email from Test.io: {subject}")
                                
                                # Mark Test.io emails as read
                                await client.store(msg_id, '+FLAGS', '\\Seen')
                                
                        except Exception as e:
                            logger.debug(f"Skipping email {msg_id}: {e}")

                # Use IDLE to wait for server push or timeout after 5 mins
                idle_task = asyncio.create_task(client.idle())
                stop_task = asyncio.create_task(_stop_event.wait())
                timeout_task = asyncio.create_task(asyncio.sleep(300))
                
                done, pending = await asyncio.wait(
                    [idle_task, stop_task, timeout_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                if not idle_task.done():
                    client.idle_done()
                    await idle_task
                    
                for p in pending:
                    p.cancel()
                            
        except Exception as e:
            logger.error(f"Email listener error: {e}", exc_info=True)
            if not _stop_event.is_set():
                logger.info("Reconnecting in 30 seconds...")
                await asyncio.sleep(30)


def start_email_listener(config: dict, trigger_callback) -> None:
    """Start the IMAP listener in the background."""
    global _email_task
    _stop_event.clear()
    _email_task = asyncio.create_task(_listen_loop(config, trigger_callback))


async def stop_email_listener() -> None:
    """Stop the IMAP listener."""
    if _email_task:
        _stop_event.set()
        await _email_task
