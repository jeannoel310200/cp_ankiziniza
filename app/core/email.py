from fastapi_mail import (
    ConnectionConfig,
    FastMail,
    MessageSchema,
    MessageType,
)

from app.core.config import get_settings

settings = get_settings()

mail_enabled = (
    settings.enable_mail_notification
)

if mail_enabled:
    mail_config = ConnectionConfig(
        MAIL_USERNAME=settings.mail_username,
        MAIL_PASSWORD=settings.mail_password,
        MAIL_FROM=settings.mail_from,
        MAIL_PORT=settings.mail_port,
        MAIL_SERVER=settings.mail_server,
        MAIL_FROM_NAME=settings.mail_from_name,
        MAIL_STARTTLS=settings.mail_starttls,
        MAIL_SSL_TLS=settings.mail_ssl_tls,
        USE_CREDENTIALS=settings.use_credentials,
        VALIDATE_CERTS=settings.validate_certs,
    )

    fast_mail = FastMail(mail_config)

else:
    fast_mail = None

def create_message(
    recipients: list[str],subject: str, body: str,
) -> MessageSchema:
    return MessageSchema(
        recipients=recipients,subject=subject,body=body,subtype=MessageType.html,
    )

async def send_email(
    recipients: list[str],
    subject: str,
    body: str,
) -> bool:

    if fast_mail is None:
        return False

    message = create_message(
        recipients=recipients,
        subject=subject,
        body=body,
    )

    await fast_mail.send_message(message)
    return True
