"""
Script de test rapide pour le connecteur France Travail.

Usage :
    export FT_CLIENT_ID="ton_id"
    export FT_CLIENT_SECRET="ton_secret"
    python test_france_travail.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
        client_id='PAR_rechercheemploidata_0fd8def2bc40d56042714bead572a6d5775a0fa8cc3a804c9d27882a36739dfd',
        client_secret='68c0d1dfd629e629cac12e1016e9003546b49afa0f267a317141d372c6ccb789'
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