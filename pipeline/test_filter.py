"""
Test du pipeline filter.py sur les offres France Travail réelles.

Usage (depuis sources/) :
    python test_filter.py
"""

import logging
import sys
import os
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
load_dotenv(Path(__file__).parent.parent / ".env")

from sources.france_travail import FranceTravailSource
from filter import filter_offers, score_offer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def main():
    print("=" * 65)
    print("Test filter.py")
    print("=" * 65)

    source = FranceTravailSource(
        keywords=["Data Analyst", "Big Data", "alternance data"],
        locations=["59"],
        max_results=50,
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