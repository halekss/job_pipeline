"""
Test du pipeline filter.py sur les offres France Travail réelles.

Usage (depuis sources/) :
    python test_filter.py
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sources.france_travail import FranceTravailSource
from filter import filter_offers, score_offer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

FT_CLIENT_ID     = "PAR_rechercheemploidata_0fd8def2bc40d56042714bead572a6d5775a0fa8cc3a804c9d27882a36739dfd"
FT_CLIENT_SECRET = "68c0d1dfd629e629cac12e1016e9003546b49afa0f267a317141d372c6ccb789"


def main():
    print("=" * 65)
    print("Test filter.py")
    print("=" * 65)

    source = FranceTravailSource(
        keywords=["Data Analyst", "Big Data", "alternance data"],
        locations=["59"],
        max_results=50,
        client_id=FT_CLIENT_ID,
        client_secret=FT_CLIENT_SECRET,
    )

    print("\nRécupération des offres...")
    raw_offers = source.fetch()
    print(f"{len(raw_offers)} offres brutes récupérées.\n")

    # Mode normal (tout garder, trié par score)
    #scored = filter_offers(raw_offers, min_score=0)

    # Mode alternance uniquement
    scored = filter_offers(raw_offers, min_score=0, alternance_only=True)

    print(f"\n{'SCORE':>6}  {'CONTRAT':<20}  TITRE")
    print("-" * 65)
    for o in scored:
        contrat = (o.contract_type or "N/A")[:20]
        print(f"{o.score:>6.1f}  {contrat:<20}  {o.title[:35]}")

    print("\n" + "=" * 65)
    kept = [o for o in scored if o.score >= 20]
    print(f"Offres conservées avec seuil=20 : {len(kept)}/{len(scored)}")

    if kept:
        print("\nTop 3 :")
        for i, o in enumerate(kept[:3], 1):
            print(f"\n  [{i}] {o.title}")
            print(f"      Score    : {o.score}")
            print(f"      Entreprise: {o.company}")
            print(f"      Contrat  : {o.contract_type}")
            print(f"      URL      : {o.url}")


if __name__ == "__main__":
    main()