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

    print("starting idle...")
    idle_task = await client.idle_start(timeout=300)
    
    print("Waiting for idle_task to finish (mark an email unread now!)...")
    done, pending = await asyncio.wait([idle_task])
    print("idle_task finished!")
    
    client.idle_done()
    res = await idle_task
    print("res:", res)

asyncio.run(main())
