import asyncio
import os
import aioimaplib
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)

async def main():
    load_dotenv()
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    user = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")

    client = aioimaplib.IMAP4_SSL(host=host)
    await client.wait_hello_from_server()
    await client.login(user, password)
    
    import time
    from email.utils import formatdate
    
    current_date = formatdate(time.time(), localtime=False)
    
    # Raw email matching exactly what Cirro sends for Test IO invitations
    raw_email = f"Delivered-To: {user}\r\n" \
                f"From: Cirro <hello@test.io>\r\n" \
                f"To: {user}\r\n" \
                f"Subject: New test invitation available!\r\n" \
                f"Date: {current_date}\r\n" \
                f"Message-ID: <{time.time()}@test.io>\r\n" \
                f"\r\n" \
                f"This is a simulated email directly injected into the mailbox.\r\n"
    
    print("Injecting fake Cirro email directly into IMAP...")
    res = await client.append(raw_email.encode('utf-8'), mailbox='INBOX')
    print("Append result:", res.result, res.lines)
    print("Email injected! The Oracle server should trigger instantly via IDLE.")

asyncio.run(main())
