
import smtplib
import os
from email.mime.text import MIMEText
from email.header import Header

MAIL_HOST = "smtp.gmail.com"
MAIL_PORT = 465
MAIL_USER = os.environ.get("MAIL_USER", "leavertondrozdowskisu239@gmail.com")
MAIL_PASS = os.environ.get("MAIL_PASS", "saimfxiilntucmph")
RECEIVER = "tosinx@gmail.com"

def test_send():
    print(f"📧 Connecting to {MAIL_HOST}...")
    try:
        smtp_obj = smtplib.SMTP_SSL(MAIL_HOST, MAIL_PORT)
        print("🔑 Logging in...")
        smtp_obj.login(MAIL_USER, MAIL_PASS)
        
        msg = MIMEText("This is a debug email from Antigravity Agent.", 'plain', 'utf-8')
        msg['From'] = MAIL_USER
        msg['To'] = RECEIVER
        msg['Subject'] = Header("Antigravity Debug Test", 'utf-8')
        
        print(f"📤 Sending to {RECEIVER}...")
        smtp_obj.sendmail(MAIL_USER, [RECEIVER], msg.as_string())
        smtp_obj.quit()
        print("✅ Email Sent Successfully!")
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_send()
