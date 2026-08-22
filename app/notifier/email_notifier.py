"""
email_notifier — sends the site owner a heads-up when a demo visitor
creates a JIRA ticket. Uses Gmail SMTP (smtplib, stdlib only — no new
dependency) with an App Password, not the account's normal password.

Best-effort by design: a failed notification should never break the
ticket-creation flow that triggered it. Callers should wrap calls in
their own try/except (or use send_notification, which already does).
"""
import smtplib
from email.mime.text import MIMEText

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def is_configured() -> bool:
    return bool(settings.smtp_username and settings.smtp_app_password)


def send_notification(subject: str, body: str) -> bool:
    """
    Sends a plain-text notification email to settings.notify_email (falling
    back to settings.smtp_username if unset). Returns True on success, False
    on any failure — never raises, so a broken/unconfigured mailer can't
    take down the caller's actual work (e.g. JIRA ticket creation).
    """
    if not is_configured():
        logger.info("Email notifications not configured (SMTP_USERNAME/SMTP_APP_PASSWORD unset) — skipping.")
        return False

    to_addr = settings.notify_email or settings.smtp_username

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_username
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_app_password)
            server.sendmail(settings.smtp_username, [to_addr], msg.as_string())
        logger.info("Notification email sent to %s", to_addr)
        return True
    except Exception as exc:
        logger.warning("Failed to send notification email: %s", exc)
        return False


def notify_ticket_created(
    ticket_id: str,
    ticket_url: str,
    error_message: str,
    service: str,
    severity: str,
) -> bool:
    subject = f"[Debug Pipeline] JIRA ticket {ticket_id} created ({severity})"
    body = (
        f"A visitor to your Debug Pipeline demo created a JIRA ticket.\n\n"
        f"Ticket:   {ticket_id}\n"
        f"URL:      {ticket_url}\n"
        f"Severity: {severity}\n"
        f"Service:  {service}\n"
        f"Error:    {error_message}\n"
    )
    return send_notification(subject, body)
