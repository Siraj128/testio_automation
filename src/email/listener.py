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
                # Search for any existing unseen emails before entering IDLE
                status, messages = await client.search('UNSEEN', 'OR', 'FROM', '"test.io"', 'FROM', '"cirro.io"')
                if status == 'OK' and messages[0]:
                    msg_ids = messages[0].decode('utf-8').split()
                    for msg_id in msg_ids:
                        status, msg_data = await client.fetch(msg_id, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
                        if status == 'OK':
                            subject = ""
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    text = response_part[1].decode('utf-8', errors='ignore')
                                    for line in text.splitlines():
                                        if line.lower().startswith('subject:'):
                                            subject = line[8:].strip()
                            
                            subject_lower = subject.lower()
                            if any(k in subject_lower for k in ["invitation", "invited", "new test cycle"]):
                                logger.info(f"🚨 New Test IO invitation email detected: {subject}")
                                try:
                                    from ..notifications.telegram import notify_status
                                    await notify_status(f"📧 *Email Alert:*\n{subject}\n⚡ Waking up instantly...", config)
                                except Exception as e:
                                    logger.error(f"Failed to send email notification: {e}")
                                trigger_callback()
                                
                            # Mark as read
                            await client.store(msg_id, '+FLAGS', '\\Seen')

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
