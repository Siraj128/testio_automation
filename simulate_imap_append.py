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
    
    # Raw email payload that perfectly matches the Cirro invitation
    raw_email = (
        b'From: "Cirro Support" <support@cirro.io>\r\n'
        b'Subject: New test invitation available!\r\n'
        b'Date: Sun, 19 Jul 2026 00:00:00 +0000\r\n'
        b'\r\n'
        b'This is a simulated email directly injected into the mailbox.\r\n'
    )
    
    print("Injecting fake Cirro email directly into IMAP...")
    res = await client.append(raw_email, mailbox='INBOX')
    print("Append result:", res.result, res.lines)
    print("Email injected! The Oracle server should trigger instantly via IDLE.")

asyncio.run(main())
