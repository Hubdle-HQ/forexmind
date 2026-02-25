"""
Email alerts when pipeline_health status = failed.
Uses SMTP (Gmail) from .env: SMTP_SERVICE, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

logger = logging.getLogger(__name__)


def send_pipeline_failure_alert(source: str, error_msg: str) -> None:
    """
    Send alert email when a failed row is inserted into pipeline_health.
    """
    smtp_service = os.getenv("SMTP_SERVICE", "smtp.gmail.com")
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").replace("\xa0", " ").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL")
    from_name = os.getenv("SMTP_FROM_NAME", "ForexMind")

    if not all([smtp_user, smtp_password, from_email]):
        logger.warning("SMTP not configured — skipping alert (SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL required)")
        return

    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = from_email
    msg["Subject"] = f"[ForexMind] Pipeline failure: {source}"

    body = f"Pipeline health check failed.\n\nSource: {source}\nError: {error_msg or 'Unknown'}"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_service, 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, [from_email], msg.as_string())
        logger.info("Alert email sent for %s", source)
    except Exception as e:
        logger.exception("Failed to send alert email: %s", e)
