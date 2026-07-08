"""
Test de EmailNotifier.send_failure_alert (notifier/mailer.py).

Usage (depuis notifier/) :
    python test_failure_alert.py
"""
import sys
import os
from email import message_from_string
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from notifier.mailer import EmailNotifier


def _make_notifier() -> EmailNotifier:
    return EmailNotifier(
        smtp_host="smtp.test.com",
        smtp_port=587,
        smtp_user="bot@test.com",
        smtp_password="pw",
        recipient="alex@test.com",
    )


def test_send_failure_alert_sends_email_with_reason():
    notifier = _make_notifier()

    with patch("notifier.mailer.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        result = notifier.send_failure_alert("Erreur auth France Travail : 400 invalid_client")

    assert result is True, "attendu True quand l'envoi réussit"
    mock_server.login.assert_called_once_with("bot@test.com", "pw")
    _, _, message_str = mock_server.sendmail.call_args[0]
    parsed = message_from_string(message_str)
    html_part = parsed.get_payload(0).get_payload(decode=True).decode("utf-8")
    assert "Erreur auth France Travail" in html_part
    print("OK: test_send_failure_alert_sends_email_with_reason")


def test_send_failure_alert_returns_false_on_smtp_error():
    notifier = _make_notifier()

    with patch("notifier.mailer.smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.side_effect = OSError("network down")

        result = notifier.send_failure_alert("panne réseau")

    assert result is False, "attendu False quand smtplib échoue"
    print("OK: test_send_failure_alert_returns_false_on_smtp_error")


def main():
    test_send_failure_alert_sends_email_with_reason()
    test_send_failure_alert_returns_false_on_smtp_error()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
