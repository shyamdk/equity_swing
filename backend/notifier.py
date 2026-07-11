"""Push (ntfy.sh) and email notifications.

Push setup  : Install the free ntfy app (iOS/Android) → subscribe to your topic.
              No account needed. Topic name is like a private channel — make it unique.
Email setup : Use a Gmail App Password (Google Account → Security → App Passwords).
              Regular Gmail password will NOT work.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from loguru import logger

from src.config import NTFY_TOPIC, SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL


def send_push(title: str, body: str, priority: str = "default", tags: str = "chart_increasing") -> bool:
    """POST to ntfy.sh/<topic>. Returns True on success."""
    if not NTFY_TOPIC:
        logger.debug("Push skipped — NTFY_TOPIC not set")
        return False
    try:
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     tags,
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"Push sent: {title}")
        return True
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")
        return False


def send_email(subject: str, html_body: str) -> bool:
    """Send via Gmail SMTP SSL. Returns True on success."""
    if not (SMTP_USER and SMTP_PASSWORD and NOTIFY_EMAIL):
        logger.debug("Email skipped — SMTP credentials not set")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = SMTP_USER
        msg["To"]      = NOTIFY_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email sent: {subject} → {NOTIFY_EMAIL}")
        return True
    except Exception as e:
        logger.warning(f"Email failed: {e}")
        return False


def notify(title: str, body: str, html_body: str | None = None, priority: str = "default") -> dict:
    """Send both push and email. Returns {'push': bool, 'email': bool}."""
    return {
        "push":  send_push(title, body, priority),
        "email": send_email(title, html_body or f"<p>{body}</p>"),
    }


def test_notifications() -> dict:
    """Send a test push and email. Use to verify credentials."""
    return notify(
        title="Equity Swing — Test Notification",
        body="Notifications are working correctly.",
        priority="low",
    )
