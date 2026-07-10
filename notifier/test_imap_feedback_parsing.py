"""
Test du parsing des emails de feedback (notifier/imap_feedback.py).
Aucun appel réseau réel : construit des emails en mémoire et mocke
imaplib.IMAP4_SSL pour le test d'orchestration.

Usage (depuis notifier/) :
    python test_imap_feedback_parsing.py
"""

import sys, os
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from imap_feedback import (
    _decode_subject,
    _extract_text_body,
    _parse_reason,
    fetch_feedback_emails,
    OFFER_ID_RE,
)


def _build_raw_email(subject: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "alex@example.com"
    msg["To"] = "pipeline@example.com"
    msg.set_content(body)
    return msg.as_bytes()


def test_decode_subject_handles_plain_ascii():
    assert _decode_subject("[Job Pipeline Feedback] indeed_abc123") == "[Job Pipeline Feedback] indeed_abc123"
    print("OK: test_decode_subject_handles_plain_ascii")


def test_offer_id_regex_extracts_id_from_subject():
    match = OFFER_ID_RE.search("Re: [Job Pipeline Feedback] indeed_abc123")
    assert match is not None
    assert match.group(1) == "indeed_abc123", match.group(1)
    print("OK: test_offer_id_regex_extracts_id_from_subject")


def test_offer_id_regex_returns_none_without_marker():
    match = OFFER_ID_RE.search("Re: une offre intéressante")
    assert match is None
    print("OK: test_offer_id_regex_returns_none_without_marker")


def test_extract_text_body_reads_plain_text_part():
    raw = _build_raw_email("test", "Pas intéressé.\n\nRaison (optionnel) : comptabilité")
    import email as email_module
    msg = email_module.message_from_bytes(raw)
    body = _extract_text_body(msg)
    assert "comptabilité" in body, body
    print("OK: test_extract_text_body_reads_plain_text_part")


def test_parse_reason_extracts_filled_reason():
    body = "Pas intéressé.\n\nRaison (optionnel) : comptabilité\n"
    assert _parse_reason(body) == "comptabilité", _parse_reason(body)
    print("OK: test_parse_reason_extracts_filled_reason")


def test_parse_reason_returns_none_when_left_blank():
    body = "Pas intéressé.\n\nRaison (optionnel) : \n"
    assert _parse_reason(body) is None, _parse_reason(body)
    print("OK: test_parse_reason_returns_none_when_left_blank")


def test_parse_reason_returns_none_without_marker():
    body = "Pas intéressé, merci de retirer cette offre."
    assert _parse_reason(body) is None, _parse_reason(body)
    print("OK: test_parse_reason_returns_none_without_marker")


def test_fetch_feedback_emails_parses_and_marks_seen():
    raw1 = _build_raw_email(
        "[Job Pipeline Feedback] indeed_1", "Raison (optionnel) : comptabilité"
    )
    raw2 = _build_raw_email(
        "[Job Pipeline Feedback] ft_2", "Raison (optionnel) : "
    )

    fake_imap = MagicMock()
    fake_imap.login.return_value = ("OK", [b""])
    fake_imap.select.return_value = ("OK", [b""])
    fake_imap.search.return_value = ("OK", [b"1 2"])
    fake_imap.fetch.side_effect = [
        ("OK", [(b"1 (BODY[])", raw1)]),
        ("OK", [(b"2 (BODY[])", raw2)]),
    ]

    with patch("imap_feedback.imaplib.IMAP4_SSL", return_value=fake_imap):
        results = fetch_feedback_emails(
            host="imap.example.com", user="alex@example.com", password="secret"
        )

    assert len(results) == 2, f"attendu 2 résultats, obtenu {len(results)}"
    assert results[0].offer_id == "indeed_1", results[0].offer_id
    assert results[0].reason == "comptabilité", results[0].reason
    assert results[1].offer_id == "ft_2", results[1].offer_id
    assert results[1].reason is None, results[1].reason
    assert fake_imap.store.call_count == 2, "les 2 messages doivent être marqués \\Seen"
    print("OK: test_fetch_feedback_emails_parses_and_marks_seen")


def test_fetch_feedback_emails_returns_empty_list_on_imap_error():
    with patch("imap_feedback.imaplib.IMAP4_SSL", side_effect=OSError("connexion refusée")):
        results = fetch_feedback_emails(
            host="imap.example.com", user="alex@example.com", password="secret"
        )
    assert results == [], f"attendu liste vide, obtenu {results}"
    print("OK: test_fetch_feedback_emails_returns_empty_list_on_imap_error")


def test_fetch_feedback_emails_returns_empty_list_without_credentials():
    with patch.dict(os.environ, {}, clear=True):
        results = fetch_feedback_emails(host="imap.example.com", user=None, password=None)
    assert results == [], f"attendu liste vide, obtenu {results}"
    print("OK: test_fetch_feedback_emails_returns_empty_list_without_credentials")


def main():
    test_decode_subject_handles_plain_ascii()
    test_offer_id_regex_extracts_id_from_subject()
    test_offer_id_regex_returns_none_without_marker()
    test_extract_text_body_reads_plain_text_part()
    test_parse_reason_extracts_filled_reason()
    test_parse_reason_returns_none_when_left_blank()
    test_parse_reason_returns_none_without_marker()
    test_fetch_feedback_emails_parses_and_marks_seen()
    test_fetch_feedback_emails_returns_empty_list_on_imap_error()
    test_fetch_feedback_emails_returns_empty_list_without_credentials()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
