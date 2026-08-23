"""Verify production SMTP DNS, TLS, and authentication without sending mail."""

from __future__ import annotations

import json
import smtplib
import ssl

from app.core.config import Settings


def main() -> None:
    settings = Settings()
    if not settings.customer_smtp_configured:
        raise SystemExit("Customer SMTP is not configured")

    context = ssl.create_default_context()
    client_type = smtplib.SMTP_SSL if settings.customer_smtp_ssl else smtplib.SMTP
    with client_type(
        settings.customer_smtp_host,
        settings.customer_smtp_port,
        timeout=settings.customer_smtp_timeout_seconds,
        **({"context": context} if settings.customer_smtp_ssl else {}),
    ) as client:
        client.ehlo()
        tls_active = settings.customer_smtp_ssl
        if settings.customer_smtp_starttls and not settings.customer_smtp_ssl:
            client.starttls(context=context)
            client.ehlo()
            tls_active = True
        authenticated = False
        if settings.customer_smtp_username:
            client.login(
                settings.customer_smtp_username,
                settings.customer_smtp_password,
            )
            authenticated = True
        status, _ = client.noop()

    result = {
        "configured": True,
        "host": settings.customer_smtp_host,
        "port": settings.customer_smtp_port,
        "tls": tls_active,
        "authenticated": authenticated,
        "noopStatus": status,
        "fromName": settings.customer_smtp_from_name,
        "fromEmailConfigured": bool(settings.customer_smtp_from_email),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if status != 250:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
