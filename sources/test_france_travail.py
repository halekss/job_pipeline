"""
Script de test rapide pour le connecteur France Travail.

Nécessite FT_CLIENT_ID et FT_CLIENT_SECRET dans le .env à la racine du projet
(chargé automatiquement) ou en variables d'environnement.

Usage :
    python test_france_travail.py
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv(Path(__file__).parent.parent / ".env")

from france_travail import FranceTravailSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main():
    print("=" * 60)
    print("Test du connecteur France Travail")
    print("=" * 60)

    source = FranceTravailSource(
        keywords=["Data Analyst", "Big Data", "alternance data"],
        locations=["59", "80"],  # libellé + code INSEE
        max_results=20,
    )

    print(f"\nSource : {source.name}")
    print(f"Mots-clés : {source.keywords}")
    print(f"Localisations : {source.locations}")
    print("\nRecherche en cours...\n")

    offers = source.fetch()

    if not offers:
        print("Aucune offre trouvée. Vérifie tes credentials ou tes paramètres.")
        return

    print(f"{len(offers)} offre(s) récupérée(s)\n")
    print("-" * 60)

    for i, offer in enumerate(offers[:5], 1):
        print(f"\n[{i}] {offer.title}")
        print(f"    Entreprise : {offer.company}")
        print(f"    Lieu       : {offer.location}")
        print(f"    Contrat    : {offer.contract_type or 'N/A'}")
        print(f"    Salaire    : {offer.salary or 'N/A'}")
        print(f"    Remote     : {offer.remote or 'N/A'}")
        print(f"    Publié le  : {offer.published_at or 'N/A'}")
        print(f"    Score      : {offer.score}")
        print(f"    URL        : {offer.url}")
        if offer.skills:
            print(f"    Compétences: {', '.join(offer.skills[:5])}")

    if len(offers) > 5:
        print(f"\n... et {len(offers) - 5} autre(s) offre(s).")

    print("\n" + "=" * 60)
    print("Test terminé.")


if __name__ == "__main__":
    main()