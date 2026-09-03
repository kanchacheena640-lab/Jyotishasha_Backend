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
    """
    Task 17B -- CONTRACT CHANGE: this function no longer swallows a send
    failure. Before this task, every exception here (auth failure,
    connection refused, timeout, quota exceeded, ...) was caught and only
    print()ed, so the caller could never tell a successful send apart from
    a silently failed one -- the root cause of the report-email
    observability gap (Task 17A). Now: returns normally on a successful
    send (unchanged); RAISES the original exception on any failure, so
    the caller (tasks.py) can durably record the outcome. Never logs
    SENDER_PASSWORD/SENDER_EMAIL credentials -- only the recipient and
    attachment path on success, and the caller decides what (bounded,
    sanitized) failure detail is worth persisting.
    """
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

    # Send Email -- any exception here (SMTP connect/login/send failure,
    # or the os.path.exists/open above) now propagates to the caller
    # instead of being caught and hidden.
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    server.send_message(msg)
    server.quit()

    print(f"Email sent successfully to {to_email} with attachment {pdf_path}")

# -------------------
if __name__ == "__main__":
    send_email(
        to_email="test_receiver@gmail.com",  # <-- TEST EMAIL
        subject="Test Astrology Report",
        body="Here is your astrology report.",
        pdf_path="report.pdf"
    )
