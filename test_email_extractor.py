import imaplib
import yaml
import email
from email import policy
import re

def test_extraction():
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    imap_cfg = config.get("email", {})
    if not imap_cfg:
        print("❌ Error: 'email' configuration block not found in config.yaml.")
        print("Make sure you are running this on the server where IMAP is configured!")
        return
        
    mail = imaplib.IMAP4_SSL(imap_cfg.get("imap_server", "imap.gmail.com"))
    mail.login(imap_cfg["email_address"], imap_cfg["app_password"])
    mail.select("INBOX")
    
    status, messages = mail.search(None, 'FROM "test.io"')
    if not messages[0]:
        status, messages = mail.search(None, 'FROM "cirro"')
        
    msg_ids = messages[0].split()
    if not msg_ids:
        print("No test.io emails found.")
        return
        
    latest_id = msg_ids[-1]
    status, msg_data = mail.fetch(latest_id, '(RFC822)')
    
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email, policy=policy.default)
    
    html_content = ""
    plain_content = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try: plain_content = part.get_content()
                except Exception: pass
            elif ctype == "text/html":
                try: html_content = part.get_content()
                except Exception: pass
    else:
        ctype = msg.get_content_type()
        if ctype == "text/html":
            try: html_content = msg.get_content()
            except Exception: pass
        else:
            try: plain_content = msg.get_content()
            except Exception: pass
            
    print(f"--- Extracted from Email: {msg.get('Subject')} ---")
    
    test_url = None
    links = re.findall(r'href=[\'"]?([^\'" >]+)', html_content)
    
    # Priority 1: A link that contains the word "test_cycles"
    for link in links:
        if "test_cycles" in link:
            test_url = link
            print(f"✅ Priority 1 Match (test_cycles): {test_url}")
            break
            
    # Priority 2: Obfuscated link before "Click this link for more details"
    if not test_url:
        click_match = re.search(r'href=[\'"]?([^\'" >]+)[^>]*>[^<]*Click this link for more details', html_content, re.IGNORECASE)
        if click_match:
            test_url = click_match.group(1)
            print(f"✅ Priority 2 Match (Obfuscated Tracking Link): {test_url}")
            
    # Priority 3: Fallback ID
    if not test_url:
        id_match = re.search(r'#(\d{5,7})', plain_content + html_content)
        if id_match:
            test_url = f"https://tester.test.io/test_cycles/{id_match.group(1)}"
            print(f"✅ Priority 3 Match (Reconstructed ID Link): {test_url}")
        else:
            print("❌ Could not extract any link!")
            print("HTML Snippet:\n", html_content[:500])

test_extraction()
