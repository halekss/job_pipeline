"""
Test de IndeedSource._fetch_batch / fetch() (sources/indeed.py) avec
StealthyFetcher.fetch mocké (aucun appel réseau réel).

Usage (depuis sources/) :
    python test_indeed_fetch.py
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indeed import IndeedSource
from base_source import JobOffer


class FakeScraplingResponse:
    def __init__(self, status):
        self.status = status

    def css(self, selector):
        return []


def test_fetch_batch_returns_empty_list_on_non_200():
    source = IndeedSource(keywords=["data analyst"], locations=["59"])

    with patch("indeed.StealthyFetcher.fetch", return_value=FakeScraplingResponse(403)):
        offers = source._fetch_batch("data analyst", "59")

    assert offers == [], f"attendu liste vide sur 403, obtenu {offers}"
    print("OK: test_fetch_batch_returns_empty_list_on_non_200")


def test_fetch_batch_returns_empty_list_on_exception():
    source = IndeedSource(keywords=["data analyst"], locations=["59"])

    with patch("indeed.StealthyFetcher.fetch", side_effect=RuntimeError("bloqué")):
        offers = source._fetch_batch("data analyst", "59")

    assert offers == [], f"attendu liste vide sur exception, obtenu {offers}"
    print("OK: test_fetch_batch_returns_empty_list_on_exception")


def test_fetch_deduplicates_across_keyword_location_combinations():
    source = IndeedSource(keywords=["data analyst", "big data"], locations=["59"])
    duplicate_offer = JobOffer(
        id="indeed_same", title="Data Analyst", company="ACME",
        location="Lille", description="", url="https://fr.indeed.com/viewjob?jk=same",
        source="Indeed",
    )

    with patch.object(IndeedSource, "_fetch_batch", return_value=[duplicate_offer]):
        offers = source.fetch()

    assert len(offers) == 1, f"attendu 1 offre dédupliquée, obtenu {len(offers)}"
    print("OK: test_fetch_deduplicates_across_keyword_location_combinations")


def test_build_params_maps_known_department_to_city_label():
    source = IndeedSource(keywords=["data analyst"], locations=["59"])
    params = source._build_params("data analyst", "59")

    assert params == {"q": "data analyst", "l": "Lille"}, params
    print("OK: test_build_params_maps_known_department_to_city_label")


def test_build_params_passes_through_unknown_location():
    source = IndeedSource(keywords=["data analyst"], locations=["Toulouse"])
    params = source._build_params("data analyst", "Toulouse")

    assert params == {"q": "data analyst", "l": "Toulouse"}, params
    print("OK: test_build_params_passes_through_unknown_location")


def main():
    test_fetch_batch_returns_empty_list_on_non_200()
    test_fetch_batch_returns_empty_list_on_exception()
    test_fetch_deduplicates_across_keyword_location_combinations()
    test_build_params_maps_known_department_to_city_label()
    test_build_params_passes_through_unknown_location()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
