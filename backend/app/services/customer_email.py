from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr
import smtplib
import ssl

from app.core.config import Settings


class CustomerEmailError(RuntimeError):
    pass


def send_customer_credentials_email(
    settings: Settings,
    *,
    recipient_email: str,
    display_name: str,
    username: str,
    temporary_password: str,
) -> None:
    if not settings.customer_smtp_configured:
        raise CustomerEmailError("SMTP is not configured.")

    message = EmailMessage()
    message["Subject"] = "Your MayakoFM customer portal login"
    message["From"] = formataddr(
        (
            settings.customer_smtp_from_name.strip() or "MayakoFM Customer Portal",
            settings.customer_smtp_from_email.strip(),
        )
    )
    message["To"] = recipient_email.strip()
    portal_url = settings.customer_portal_public_url.strip()
    greeting = display_name.strip() or username
    message.set_content(
        "\n".join(
            [
                f"Hello {greeting},",
                "",
                "Your MayakoFM customer portal account is ready.",
                "",
                f"Portal: {portal_url}",
                f"Username: {username}",
                f"Temporary password: {temporary_password}",
                "",
                "Please sign in and change your password after your first login.",
                "",
                "MayakoFM Customer Portal",
            ]
        )
    )

    deliver_email_message(settings, message)


def send_admin_credentials_email(
    settings: Settings,
    *,
    recipient_email: str,
    username: str,
    password: str,
) -> None:
    """Deliver the StarRC admin backend (FileMaker Data API) login to a recipient.

    The admin backend does not store passwords locally; the credentials come from
    the deployed FileMaker account (``FILEMAKER_USERNAME`` / ``FILEMAKER_PASSWORD``).
    This helper is the secure channel for an operator to send those credentials to
    a trusted mailbox.
    """
    if not settings.customer_smtp_configured:
        raise CustomerEmailError("SMTP is not configured.")
    if not username.strip() or not password:
        raise CustomerEmailError("Admin credentials are not configured.")

    message = EmailMessage()
    message["Subject"] = "StarRC admin backend login"
    message["From"] = formataddr(
        (
            settings.customer_smtp_from_name.strip() or "StarRC Admin",
            settings.customer_smtp_from_email.strip(),
        )
    )
    message["To"] = recipient_email.strip()
    # Admin backend lives at the same origin as the customer portal.
    backend_url = settings.customer_portal_public_url.strip().rstrip("/")
    # Strip a trailing /customer-chat (or similar path) so we link to the site root.
    for suffix in ("/customer-chat", "/customer"):
        if backend_url.endswith(suffix):
            backend_url = backend_url[: -len(suffix)]
            break
    message.set_content(
        "\n".join(
            [
                "Hello,",
                "",
                "Here are the StarRC admin backend (FileMaker Data API) credentials:",
                "",
                f"Backend: {backend_url}",
                f"Username: {username.strip()}",
                f"Password: {password}",
                "",
                "Please keep this information safe and do not forward it.",
                "These credentials are provisioned by the FileMaker server; "
                "contact an administrator if you need them rotated.",
                "",
                "StarRC Admin",
            ]
        )
    )

    deliver_email_message(settings, message)


def deliver_email_message(settings: Settings, message: EmailMessage) -> None:
    smtp_class = smtplib.SMTP_SSL if settings.customer_smtp_ssl else smtplib.SMTP
    try:
        with smtp_class(
            settings.customer_smtp_host.strip(),
            settings.customer_smtp_port,
            timeout=settings.customer_smtp_timeout_seconds,
        ) as smtp:
            smtp.ehlo()
            if settings.customer_smtp_starttls and not settings.customer_smtp_ssl:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.customer_smtp_username.strip():
                smtp.login(
                    settings.customer_smtp_username.strip(),
                    settings.customer_smtp_password,
                )
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise CustomerEmailError("The login email could not be sent.") from exc
