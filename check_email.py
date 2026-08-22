import imaplib
import email
from email import policy
import yaml
import re

import os
from dotenv import load_dotenv

def check_email():
    load_dotenv()
    
    imap_server = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    email_address = os.getenv("EMAIL_ADDRESS")
    app_password = os.getenv("EMAIL_PASSWORD")
    
    if not email_address or not app_password:
        print("Missing EMAIL_ADDRESS or EMAIL_PASSWORD in .env")
        return
        
    mail = imaplib.IMAP4_SSL(imap_server, imap_port)
    mail.login(email_address, app_password)
    mail.select("inbox")
    
    # Search for all test.io or cirro emails
    status, response = mail.search(None, 'FROM "cirro"')
    msg_ids = response[0].split()
    if not msg_ids:
        status, response = mail.search(None, 'FROM "test.io"')
        msg_ids = response[0].split()
        
    if not msg_ids:
        print("No emails found from cirro or test.io.")
        return
        
    latest_msg_id = msg_ids[-1]
    print(f"Fetching message ID {latest_msg_id}")
    
    status, fetch_resp = mail.fetch(latest_msg_id, '(RFC822)')
    raw_email = fetch_resp[0][1]
    
    msg = email.message_from_bytes(raw_email, policy=policy.default)
    
    print("Subject:", msg.get("Subject"))
    
    html_content = ""
    plain_content = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain_content = part.get_content()
            elif ctype == "text/html":
                html_content = part.get_content()
    else:
        ctype = msg.get_content_type()
        if ctype == "text/html":
            html_content = msg.get_content()
        else:
            plain_content = msg.get_content()
            
    print("\n--- HTML TEXT (Extracting Links) ---")
    links = re.findall(r'href=[\'"]?([^\'" >]+)', html_content)
    test_url = None
    
    for link in links:
        if "test_cycles" in link:
            test_url = link
            print(f"Priority 1 Match (test_cycles): {test_url}")
            break
            
    if not test_url:
        click_match = re.search(r'href=[\'"]?([^\'" >]+)[^>]*>[^<]*Click this link for more details', html_content, re.IGNORECASE)
        if click_match:
            test_url = click_match.group(1)
            print(f"Priority 2 Match (Obfuscated): {test_url}")
            
    if not test_url:
        id_match = re.search(r'#(\d{5,7})', plain_content + html_content)
        if id_match:
            test_url = f"https://tester.test.io/test_cycles/{id_match.group(1)}"
            print(f"Priority 3 Match (Reconstructed): {test_url}")
            
    print("\nALL LINKS FOUND IN EMAIL:")
    for link in links:
        print(" -", link)

check_email()
