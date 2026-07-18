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
    await client.select('INBOX')

    # Get the latest message ID
    res = await client.search('ALL')
    latest = res.lines[0].split()[-1]

    print("Marking message", latest, "as UNSEEN...")
    await client.store(latest, '-FLAGS', '\\Seen')
    
    print("Done")

asyncio.run(main())
