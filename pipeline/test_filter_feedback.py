"""
Test des paramètres company_penalties / extra_negative_keywords de
pipeline/filter.py (COM-13). Aucun appel réseau.

Usage (depuis pipeline/) :
    python test_filter_feedback.py
"""

import sys, os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from filter import score_offer, filter_offers
from sources.base_source import JobOffer
from feedback import DEFAULT_KEYWORD_PENALTY


def _make_offer(title, company, contract_type=None, description=""):
    return JobOffer(
        id="x", title=title, company=company, location="Lille",
        description=description, url="https://example.com", source="test",
        published_at=datetime.now(timezone.utc),
        contract_type=contract_type,
    )


def test_score_offer_unchanged_without_feedback_params():
    offer = _make_offer("Alternance Data Analyst", "ACME", contract_type="alternance")
    assert score_offer(offer) == score_offer(offer, None, None)
    print("OK: test_score_offer_unchanged_without_feedback_params")


def test_company_penalty_reduces_score():
    offer = _make_offer("Alternance Data Analyst", "ACME", contract_type="alternance")
    base_score = score_offer(offer)
    penalized_score = score_offer(offer, company_penalties={"acme": 20.0})
    assert penalized_score == round(base_score - 20.0, 1), (base_score, penalized_score)
    print("OK: test_company_penalty_reduces_score")


def test_company_penalty_matches_case_insensitively():
    offer = _make_offer("Alternance Data Analyst", "ACME Corp", contract_type="alternance")
    penalized_score = score_offer(offer, company_penalties={"acme corp": 20.0})
    base_score = score_offer(offer)
    assert penalized_score == round(base_score - 20.0, 1), (base_score, penalized_score)
    print("OK: test_company_penalty_matches_case_insensitively")


def test_learned_negative_keyword_pushes_alternance_offer_below_threshold():
    # Cas réel COM-13 : "Alternance Comptable" passe le seuil (20) sur le
    # seul bonus alternance (+25 mot-clé +30 contrat = 55), sans mot-clé
    # technique. La pénalité par défaut (DEFAULT_KEYWORD_PENALTY, cf.
    # pipeline/feedback.py) doit être assez forte pour repasser ce cas
    # précis sous le seuil (55 - pénalité < 20 => pénalité > 35).
    offer = _make_offer("Alternance Comptable", "Cabinet XYZ", contract_type="alternance")
    base_score = score_offer(offer)
    assert base_score >= 20, f"précondition : l'offre doit passer le seuil sans feedback (score={base_score})"

    penalized_score = score_offer(
        offer, extra_negative_keywords=[("comptable", DEFAULT_KEYWORD_PENALTY)]
    )
    assert penalized_score < 20, f"attendu score < 20 après pénalité, obtenu {penalized_score}"
    print("OK: test_learned_negative_keyword_pushes_alternance_offer_below_threshold")


def test_learned_negative_keyword_reason_is_regex_escaped():
    # Une raison contenant des caractères spéciaux regex ne doit pas planter.
    offer = _make_offer("Alternance Data Analyst (H/F)", "ACME", contract_type="alternance")
    score = score_offer(offer, extra_negative_keywords=[("h/f) (bonus?", 30.0)])
    assert isinstance(score, float)
    print("OK: test_learned_negative_keyword_reason_is_regex_escaped")


def test_filter_offers_excludes_offer_pushed_below_threshold_by_feedback():
    offer = _make_offer("Alternance Comptable", "Cabinet XYZ", contract_type="alternance")
    without_feedback = filter_offers([offer], min_score=20)
    assert len(without_feedback) == 1, "précondition : l'offre passe sans feedback"

    with_feedback = filter_offers(
        [offer], min_score=20, extra_negative_keywords=[("comptable", DEFAULT_KEYWORD_PENALTY)]
    )
    assert len(with_feedback) == 0, f"attendu 0 offre après pénalité, obtenu {len(with_feedback)}"
    print("OK: test_filter_offers_excludes_offer_pushed_below_threshold_by_feedback")


def main():
    test_score_offer_unchanged_without_feedback_params()
    test_company_penalty_reduces_score()
    test_company_penalty_matches_case_insensitively()
    test_learned_negative_keyword_pushes_alternance_offer_below_threshold()
    test_learned_negative_keyword_reason_is_regex_escaped()
    test_filter_offers_excludes_offer_pushed_below_threshold_by_feedback()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
