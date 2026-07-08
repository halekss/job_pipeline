"""
Script de test rapide pour le connecteur Indeed (appel réseau réel).

Usage :
    python test_indeed.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indeed import IndeedSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main():
    print("=" * 60)
    print("Test du connecteur Indeed")
    print("=" * 60)

    source = IndeedSource(
        keywords=["Data Analyst", "Big Data", "alternance data"],
        locations=["59"],
    )

    print(f"\nSource : {source.name}")
    print(f"Mots-clés : {source.keywords}")
    print(f"Localisations : {source.locations}")
    print("\nRecherche en cours...\n")

    offers = source.fetch()

    if not offers:
        print("Aucune offre trouvée (ou Indeed a bloqué la requête).")
        return

    print(f"{len(offers)} offre(s) récupérée(s)\n")
    print("-" * 60)

    for i, offer in enumerate(offers[:5], 1):
        print(f"\n[{i}] {offer.title}")
        print(f"    Entreprise : {offer.company}")
        print(f"    Lieu       : {offer.location}")
        print(f"    Contrat    : {offer.contract_type or 'N/A'}")
        print(f"    Salaire    : {offer.salary or 'N/A'}")
        print(f"    URL        : {offer.url}")

    if len(offers) > 5:
        print(f"\n... et {len(offers) - 5} autre(s) offre(s).")

    print("\n" + "=" * 60)
    print("Test terminé.")


if __name__ == "__main__":
    main()
