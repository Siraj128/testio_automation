import asyncio
import os
import yaml
from aioimaplib import aioimaplib
from dotenv import load_dotenv

async def main():
    load_dotenv()
    
    imap_server = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    email_address = os.getenv("EMAIL_ADDRESS")
    app_password = os.getenv("EMAIL_PASSWORD")
    
    client = aioimaplib.IMAP4_SSL(host=imap_server, port=imap_port)
    await client.wait_hello_from_server()
    await client.login(email_address, app_password)
    await client.select("INBOX")
    
    status, response = await client.search('FROM "cirro"')
    msg_ids = response[0].split()
    if not msg_ids:
        status, response = await client.search('FROM "test.io"')
        msg_ids = response[0].split()
        
    latest_msg_id = msg_ids[-1]
    print(f"Fetching message ID {latest_msg_id}")
    
    fetch_response = await client.fetch(latest_msg_id.decode('utf-8'), '(BODY.PEEK[HEADER] BODY.PEEK[TEXT])')
    
    headers_bytes = b""
    body_bytes = b""
    for line in fetch_response.lines:
        if isinstance(line, bytearray):
            line_lower = bytes(line[:500]).lower()
            if b"delivered-to:" in line_lower or b"received:" in line_lower or b"from:" in line_lower or b"subject:" in line_lower:
                headers_bytes = bytes(line)
            else:
                body_bytes = bytes(line)
                
    raw_email_bytes = headers_bytes.strip() + b"\r\n\r\n" + body_bytes.lstrip()
    
    import email
    from email import policy
    msg = email.message_from_bytes(raw_email_bytes, policy=policy.default)
    print("From:", msg.get("From"))
    print("Subject:", msg.get("Subject"))
    print("Is multipart:", msg.is_multipart())
    
    html_content = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html_content = part.get_content()
    
    import re
    links = re.findall(r'href=[\'"]?([^\'" >]+)', html_content)
    print("HTML LINKS FOUND:", len(links))
    for link in links:
        if "test_cycles" in link or "pstmrk.it" in link:
            print("LINK:", link)
    return
            


asyncio.run(main())
