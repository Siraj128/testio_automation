import asyncio
import os
import aioimaplib

async def main():
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    user = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    
    print(f"Connecting to {host}:{port} as {user}")
    client = aioimaplib.IMAP4_SSL(host=host, port=port)
    await client.wait_hello_from_server()
    await client.login(user, password)
    await client.select('INBOX')
    
    res_cirro = await client.search('FROM "cirro"')
    msg_ids = set()
    if res_cirro.result == 'OK' and res_cirro.lines:
        for line in res_cirro.lines:
            if isinstance(line, bytes): line = line.decode('utf-8', errors='ignore')
            msg_ids.update([mid for mid in line.strip().split() if mid.isdigit()])
            
    if not msg_ids:
        print("No cirro emails found")
        return
        
    last_id = sorted(list(msg_ids), key=lambda x: int(x))[-1]
    
    print(f"Fetching message {last_id}")
    fetch_response = await client.fetch(last_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])')
    
    print("--- FETCH RESPONSE LINES ---")
    for line in fetch_response.lines:
        print(repr(line))

if __name__ == "__main__":
    asyncio.run(main())
