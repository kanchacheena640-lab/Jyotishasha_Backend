import html
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from dotenv import load_dotenv
load_dotenv()

# -------------------
# Email Configuration
# -------------------
# Two transports, chosen from the environment at send time:
#
#   * SMTP relay (Brevo): used when SMTP_HOST, SMTP_USER and SMTP_PASSWORD are
#     all set. Logs in with SMTP_USER/SMTP_PASSWORD (the Brevo SMTP login and
#     SMTP key -- not an API key) and sends From SENDER_EMAIL, which must be a
#     sender on the authenticated domain (reports@jyotishasha.com).
#   * Gmail (fallback, the original behaviour): used when none of the three
#     relay variables is set. Logs in with SENDER_EMAIL/SENDER_PASSWORD (a
#     Gmail App Password) and sends From SENDER_EMAIL.
#
# A partially configured relay raises instead of silently switching transport.
# Credentials are never logged or included in raised messages.
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
SMTP_TIMEOUT_SECONDS = 30
DEFAULT_SENDER_NAME = "Jyotishasha Pvt. Ltd."
DEFAULT_ATTACHMENT_FILENAME = "Jyotishasha-Report.pdf"

_RELAY_VARS = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")
_URL_RE = re.compile(r"https://[^\s<>\"']+")


def smtp_settings():
    """Resolve the active transport from the environment. Returns a dict with
    transport/host/port/user/password/sender_email/sender_name/reply_to."""
    present = {name: bool((os.getenv(name) or "").strip()) for name in _RELAY_VARS}
    sender_email = (os.getenv("SENDER_EMAIL") or "").strip()
    common = {
        "sender_email": sender_email,
        "sender_name": (os.getenv("SENDER_NAME") or "").strip() or DEFAULT_SENDER_NAME,
        "reply_to": (os.getenv("REPLY_TO") or "").strip() or None,
    }
    if all(present.values()):
        port_raw = (os.getenv("SMTP_PORT") or "").strip() or "587"
        try:
            port = int(port_raw)
        except ValueError:
            raise ValueError("SMTP_PORT must be a number") from None
        return {
            "transport": "smtp-relay",
            "host": os.getenv("SMTP_HOST").strip(),
            "port": port,
            "user": os.getenv("SMTP_USER").strip(),
            "password": os.getenv("SMTP_PASSWORD").strip(),
            **common,
        }
    if any(present.values()):
        missing = ", ".join(name for name, ok in present.items() if not ok)
        raise ValueError(f"SMTP relay is partially configured; missing: {missing}")
    return {
        "transport": "gmail",
        "host": GMAIL_SMTP_SERVER,
        "port": GMAIL_SMTP_PORT,
        "user": sender_email,
        "password": os.getenv("SENDER_PASSWORD"),
        **common,
    }


def _html_body(body):
    """Simple HTML twin of the plain-text body: escaped paragraphs, line breaks,
    and bare https URLs as links whose visible text is the URL itself."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", body.strip()):
        parts, last = [], 0
        for match in _URL_RE.finditer(block):
            parts.append(html.escape(block[last:match.start()]))
            url = html.escape(match.group(0))
            parts.append(f'<a href="{url}">{url}</a>')
            last = match.end()
        parts.append(html.escape(block[last:]))
        paragraphs.append("<p>" + "".join(parts).replace("\n", "<br>\n") + "</p>")
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8"></head>\n'
        '<body style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.5; color: #222222;">\n'
        + "\n".join(paragraphs)
        + "\n</body></html>\n"
    )


# -------------------
# Email Sender
# -------------------
def send_email(to_email, subject, body, pdf_path, attachment_filename=None):
    """
    Task 17B -- CONTRACT CHANGE: this function no longer swallows a send
    failure. Before this task, every exception here (auth failure,
    connection refused, timeout, quota exceeded, ...) was caught and only
    print()ed, so the caller could never tell a successful send apart from
    a silently failed one -- the root cause of the report-email
    observability gap (Task 17A). Now: returns normally on a successful
    send (unchanged); RAISES the original exception on any failure, so
    the caller (tasks.py) can durably record the outcome. Never logs
    SMTP credentials -- only the recipient, transport and attachment path on
    success, and the caller decides what (bounded, sanitized) failure detail
    is worth persisting.

    attachment_filename: the name the recipient sees for the PDF. Defaults to
    a neutral name; the on-disk path (which contains the customer's name) is
    never used as the attachment name.
    """
    # A paid-report email is never valid without its PDF. Validate the
    # complete attachment before opening an SMTP connection so a missing,
    # unreadable, empty, or non-PDF artifact cannot become a successful
    # attachment-free delivery.
    if not pdf_path or not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"Report PDF is missing: {pdf_path!r}")
    try:
        with open(pdf_path, "rb") as attachment:
            pdf_bytes = attachment.read()
    except OSError as exc:
        raise OSError(f"Report PDF is unreadable: {pdf_path!r}") from exc
    if not pdf_bytes:
        raise ValueError(f"Report PDF is empty: {pdf_path!r}")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError(f"Report artifact is not a valid PDF: {pdf_path!r}")

    settings = smtp_settings()
    sender_email = settings["sender_email"]
    sender_domain = sender_email.rpartition("@")[2] or None

    # Create Email: multipart/mixed = [multipart/alternative(plain, html), pdf]
    # (An unset SENDER_EMAIL leaves From empty, as before; the SMTP server
    # then rejects the send and the caller records FAILED.)
    msg = EmailMessage()
    if sender_email:
        msg["From"] = formataddr((settings["sender_name"], sender_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(usegmt=True)
    msg["Message-ID"] = make_msgid(domain=sender_domain)
    if settings["reply_to"]:
        msg["Reply-To"] = settings["reply_to"]

    msg.set_content(body)
    msg.add_alternative(_html_body(body), subtype="html")

    # Attach the already-validated bytes. There is no attachment-free path.
    msg.add_attachment(
        pdf_bytes, maintype="application", subtype="pdf",
        filename=attachment_filename or DEFAULT_ATTACHMENT_FILENAME,
    )

    # Send Email -- any exception from connect/starttls/login/send propagates
    # to the caller unchanged. After the message is accepted, a failure to
    # close the session politely is ignored so it cannot mark a delivered
    # email FAILED (which would invite a duplicate resend).
    server = smtplib.SMTP(settings["host"], settings["port"], timeout=SMTP_TIMEOUT_SECONDS)
    try:
        server.starttls()
        server.login(settings["user"], settings["password"])
        server.send_message(msg)
    except Exception:
        try:
            server.close()
        except Exception:
            pass
        raise
    try:
        server.quit()
    except Exception:
        pass

    print(f"Email sent successfully to {to_email} via {settings['transport']} with attachment {pdf_path}")

# -------------------
if __name__ == "__main__":
    send_email(
        to_email="test_receiver@gmail.com",  # <-- TEST EMAIL
        subject="Test Astrology Report",
        body="Here is your astrology report.",
        pdf_path="report.pdf"
    )
