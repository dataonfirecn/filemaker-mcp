import pytest

from app.core.config import Settings
from app.services.customer_email import (
    CustomerEmailError,
    send_customer_credentials_email,
)


def test_customer_credentials_email_requires_smtp_configuration() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(CustomerEmailError, match="SMTP is not configured"):
        send_customer_credentials_email(
            settings,
            recipient_email="customer@example.com",
            display_name="Customer",
            username="customer",
            temporary_password="Complex!Pass1",
        )


def test_customer_credentials_email_sends_portal_username_and_password(monkeypatch) -> None:
    sent_messages = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 15.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def ehlo(self):
            return None

        def starttls(self, *, context):
            assert context is not None

        def login(self, username, password):
            assert username == "mailer@example.com"
            assert password == "smtp-password"

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr("app.services.customer_email.smtplib.SMTP", FakeSmtp)
    settings = Settings(
        _env_file=None,
        customer_smtp_host="smtp.example.com",
        customer_smtp_username="mailer@example.com",
        customer_smtp_password="smtp-password",
        customer_smtp_from_email="mailer@example.com",
        customer_portal_public_url="https://portal.example.com/customer-chat",
    )

    send_customer_credentials_email(
        settings,
        recipient_email="customer@example.com",
        display_name="Customer One",
        username="customer.one",
        temporary_password="Complex!Pass1",
    )

    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message["To"] == "customer@example.com"
    body = message.get_content()
    assert "https://portal.example.com/customer-chat" in body
    assert "Username: customer.one" in body
    assert "Temporary password: Complex!Pass1" in body
