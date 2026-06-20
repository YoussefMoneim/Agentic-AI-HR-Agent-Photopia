import logging

import config

_log = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body_html: str, body_plain: str) -> bool:
    """Send an email via Azure Communication Services.

    Falls back to mock mode (logging only) when AZURE_COMMUNICATION_CONNECTION_STRING
    is not set or the SDK is not installed — safe for local development.
    """
    if not config.AZURE_COMMUNICATION_CONNECTION_STRING:
        _log.info(
            "EMAIL [mock] TO=%s | SUBJECT=%s\n%s",
            to_email, subject, body_plain,
        )
        return True

    try:
        from azure.communication.email import EmailClient  # lazy import — optional in dev

        client = EmailClient.from_connection_string(config.AZURE_COMMUNICATION_CONNECTION_STRING)
        message = {
            "content": {
                "subject": subject,
                "plainText": body_plain,
                "html": body_html,
            },
            "recipients": {"to": [{"address": to_email}]},
            "senderAddress": config.AZURE_COMMUNICATION_SENDER_EMAIL,
        }
        poller = client.begin_send(message)
        result = poller.result()
        succeeded = result.get("status") == "Succeeded"
        if not succeeded:
            _log.warning("ACS send returned non-success status: %s", result)
        return succeeded

    except ImportError:
        _log.warning("azure-communication-email not installed; falling back to mock email")
        _log.info("EMAIL [mock] TO=%s | SUBJECT=%s\n%s", to_email, subject, body_plain)
        return True

    except Exception:
        _log.exception("Failed to send email to %s", to_email)
        return False
