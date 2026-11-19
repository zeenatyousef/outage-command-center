"""Optional email notifications over SMTP. Does nothing unless SMTP is configured.

Environment variables: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD,
ALERT_EMAIL_TO (comma separated), ALERT_EMAIL_FROM (defaults to SMTP_USER).
For Gmail use an app password, not your normal password.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def email_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("ALERT_EMAIL_TO"))


def send_email(subject: str, body: str) -> bool:
    if not email_configured():
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.getenv("ALERT_EMAIL_FROM") or os.getenv("SMTP_USER", "occ@localhost")
        msg["To"] = os.environ["ALERT_EMAIL_TO"]
        msg.set_content(body)
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            if os.getenv("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception:
        return False
