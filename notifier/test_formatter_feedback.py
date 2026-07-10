"""
Test du lien mailto "pas intéressé" dans notifier/formatter.py (COM-13).

Usage (depuis notifier/) :
    python test_formatter_feedback.py
"""

import sys, os
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from formatter import render_email
from sources.base_source import JobOffer


def _make_offer():
    return JobOffer(
        id="indeed_abc123", title="Alternance Data Analyst", company="ACME",
        location="Lille", description="...", url="https://example.com",
        source="Indeed", published_at=datetime.now(timezone.utc),
        contract_type="alternance", score=55.0,
    )


def test_mailto_link_present_with_smtp_user_configured():
    with patch.dict(os.environ, {"SMTP_USER": "alex@example.com"}):
        html = render_email([_make_offer()], ["Data Analyst"], ["59"])

    assert "mailto:alex@example.com" in html, html
    assert "%5BJob%20Pipeline%20Feedback%5D%20indeed_abc123" in html, html
    print("OK: test_mailto_link_present_with_smtp_user_configured")


def test_mailto_link_omitted_without_smtp_user():
    with patch.dict(os.environ, {}, clear=True):
        html = render_email([_make_offer()], ["Data Analyst"], ["59"])

    assert "mailto:" not in html, html
    print("OK: test_mailto_link_omitted_without_smtp_user")


def main():
    test_mailto_link_present_with_smtp_user_configured()
    test_mailto_link_omitted_without_smtp_user()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
