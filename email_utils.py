import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from dotenv import load_dotenv
load_dotenv()

import os

# -------------------
# Email Configuration
# -------------------
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.getenv("SENDER_EMAIL")         # <-- EDIT
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")   # <-- Use App Password (not normal password)

# -------------------
# Email Sender
# -------------------
def send_email(to_email, subject, body, pdf_path):
    try:
        # Create Email
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject

        # Email Body
        msg.attach(MIMEText(body, 'plain'))

        # Attach PDF
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(pdf_path)}')
                msg.attach(part)

        # Send Email
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()

        print(f"Email sent successfully to {to_email} with attachment {pdf_path}")
    except Exception as e:
        print(f"Error sending email: {e}")

# -------------------
if __name__ == "__main__":
    send_email(
        to_email="test_receiver@gmail.com",  # <-- TEST EMAIL
        subject="Test Astrology Report",
        body="Here is your astrology report.",
        pdf_path="report.pdf"
    )
