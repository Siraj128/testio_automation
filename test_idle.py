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
    await client.idle_start(timeout=30)
    
    push_task = asyncio.create_task(client.wait_server_push())
    
    print("Waiting for server push (mark an email unread now!)...")
    done, pending = await asyncio.wait([push_task])
    print("push_task finished!")
    
    client.idle_done()
    res = await push_task
    print("res:", res)

asyncio.run(main())
