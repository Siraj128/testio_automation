import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv

def send_spoofed_test_email():
    load_dotenv()
    user = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    
    msg = EmailMessage()
    msg.set_content("This is a simulated test invitation to test the IMAP IDLE trigger.")
    
    # We spoof the display name to "Cirro Support" so it matches the IMAP FROM "cirro" search
    msg['Subject'] = "New test invitation available!"
    msg['From'] = f'"Cirro Support" <{user}>'
    msg['To'] = user
    
    print(f"Logging into SMTP as {user}...")
    try:
        # Gmail SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(user, password)
            print("Sending simulated Cirro email...")
            smtp.send_message(msg)
            print("Email sent successfully! Check your Oracle server logs.")
    except Exception as e:
        print("Failed to send email:", e)

if __name__ == "__main__":
    send_spoofed_test_email()
