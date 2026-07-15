import os
import imaplib
from dotenv import load_dotenv

def main():
    load_dotenv()
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    user = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    
    print(f"Connecting to {host}:{port} as {user}")
    client = imaplib.IMAP4_SSL(host, port)
    client.login(user, password)
    client.select('INBOX')
    
    status, response = client.search(None, 'FROM', '"cirro"')
    if status != 'OK' or not response[0]:
        print("No emails found.")
        return
        
    msg_ids = response[0].split()
    last_id = msg_ids[-1]
    
    print(f"Fetching message {last_id.decode()}")
    status, fetch_data = client.fetch(last_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])')
    
    print("--- FETCH DATA ---")
    for item in fetch_data:
        print(repr(item))

if __name__ == "__main__":
    main()
