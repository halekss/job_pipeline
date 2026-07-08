"""
Test de _parse_results (sources/indeed.py) - parsing des offres à partir
d'un fixture HTML sauvegardé (aucun appel réseau).

Usage (depuis sources/) :
    python test_indeed_parsing.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapling.parser import Selector
from indeed import _parse_results

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "indeed_sample.html"


def _load_fixture():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    return Selector(html)


def test_parses_two_offers_from_fixture():
    page = _load_fixture()
    offers = _parse_results(page)

    assert len(offers) == 2, f"attendu 2 offres, obtenu {len(offers)}"
    print("OK: test_parses_two_offers_from_fixture")


def test_parses_offer_with_salary():
    page = _load_fixture()
    offers = _parse_results(page)
    first = offers[0]

    assert first.id == "indeed_406bba8701d62c9c", first.id
    assert first.title == "Alternance - Data Analyst H/F - LILLE - 59 (H/F)", first.title
    assert first.company == "Studi CFA", first.company
    assert first.location == "59000 Lille", first.location
    assert first.salary == "De 504,09 € à 1 867,02 € par mois", first.salary
    assert first.contract_type == "Contrat d'apprentissage", first.contract_type
    assert "IMMEDIATEMENT" in first.description, first.description
    assert first.url == "https://fr.indeed.com/viewjob?jk=406bba8701d62c9c", first.url
    assert first.source == "Indeed"
    print("OK: test_parses_offer_with_salary")


def test_parses_offer_without_salary():
    page = _load_fixture()
    offers = _parse_results(page)
    second = offers[1]

    assert second.id == "indeed_dd5e5bbcdc58578b", second.id
    assert second.company == "Biospringer", second.company
    assert second.salary is None, f"attendu pas de salaire, obtenu {second.salary}"
    assert second.contract_type == "Stage", second.contract_type
    print("OK: test_parses_offer_without_salary")


def main():
    test_parses_two_offers_from_fixture()
    test_parses_offer_with_salary()
    test_parses_offer_without_salary()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
