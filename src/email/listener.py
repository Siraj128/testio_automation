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
                # Simple search: just get ALL unseen emails (no complex OR/FROM filters)
                status, messages = await client.search('UNSEEN')
                
                if status == 'OK' and messages and messages[0]:
                    msg_ids_raw = messages[0]
                    if isinstance(msg_ids_raw, bytes):
                        msg_ids_raw = msg_ids_raw.decode('utf-8')
                    msg_ids = msg_ids_raw.strip().split()
                    
                    for msg_id in msg_ids:
                        if not msg_id:
                            continue
                        try:
                            status, msg_data = await client.fetch(msg_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')
                            if status != 'OK':
                                continue
                            
                            from_addr = ""
                            subject = ""
                            
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    text = response_part[1].decode('utf-8', errors='ignore')
                                    for line in text.splitlines():
                                        line_lower = line.lower().strip()
                                        if line_lower.startswith('from:'):
                                            from_addr = line[5:].strip().lower()
                                        elif line_lower.startswith('subject:'):
                                            subject = line[8:].strip()
                            
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
                                            f"From: {from_addr}\n"
                                            f"Subject: {subject}\n"
                                            f"⚡ Waking up instantly...", 
                                            config
                                        )
                                    except Exception as e:
                                        logger.error(f"Failed to send email notification: {e}")
                                    trigger_callback()
                                else:
                                    logger.debug(f"Non-invitation email from Test.io: {subject}")
                                
                                # Mark as read
                                await client.store(msg_id, '+FLAGS', '\\Seen')
                            # Don't mark non-testio emails as read (leave them alone)
                            
                        except Exception as e:
                            logger.error(f"Error processing email {msg_id}: {e}")

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
