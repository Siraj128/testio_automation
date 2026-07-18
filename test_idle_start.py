import asyncio
import os
import aioimaplib
import logging

logging.basicConfig(level=logging.DEBUG)

async def main():
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    user = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")

    client = aioimaplib.IMAP4_SSL(host=host)
    await client.wait_hello_from_server()
    await client.login(user, password)
    await client.select('INBOX')

    print("starting idle...")
    # Does this block until an email arrives?
    f = await client.idle_start(timeout=30)
    print("idle_start returned:", type(f), f)
    
    print("waiting 5 seconds...")
    await asyncio.sleep(5)
    
    print("calling idle_done()...")
    client.idle_done()
    
    print("waiting for f...")
    res = await f
    print("result:", res)

asyncio.run(main())
