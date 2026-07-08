"""
Test du notifier - Génère un aperçu HTML sans envoyer d'email.

Usage (depuis la racine job_pipeline/) :
    python notifier/test_notifier.py

Ouvre le fichier email_preview.html dans ton navigateur pour voir le rendu.
"""

import sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from sources.base_source import JobOffer
from notifier.formatter import render_email


def make_offer(id, title, company, location, contract, score, salary=None,
               remote=None, skills=None, days_ago=1):
    return JobOffer(
        id=id,
        title=title,
        company=company,
        location=location,
        description=(
            "Dans le cadre de notre développement, nous recherchons un(e) alternant(e) "
            "passionné(e) par la data. Vous travaillerez sur des projets d'analyse et "
            "de visualisation de données en collaboration avec nos équipes métier."
        ),
        url=f"https://candidat.francetravail.fr/offres/recherche/detail/{id}",
        source="France Travail",
        published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        contract_type=contract,
        remote=remote,
        salary=salary,
        skills=skills or [],
        score=score,
    )


def main():
    offers = [
        make_offer(
            "ft_001", "Junior Data Analyst Circularity (f/m/d)",
            "Entreprise non communiquée", "59 - Villeneuve-d'Ascq",
            "CDD - 12 Mois", score=88.0,
            skills=["Python", "SQL", "Power BI", "Pandas"],
            days_ago=3,
        ),
        make_offer(
            "ft_002", "Alternance Data Analyste (H/F)",
            "CGL", "59 - Lille",
            "CDD - 12 Mois", score=61.0,
            salary="Selon profil",
            skills=["Python", "SQL", "Airflow"],
            remote="partial",
            days_ago=6,
        ),
        make_offer(
            "ft_003", "Apprenti Data Analyst H/F",
            "PROXISERVE", "59 - Lambersart",
            "CDD - 12 Mois", score=48.0,
            skills=["SQL", "Excel", "Power BI"],
            days_ago=7,
        ),
        make_offer(
            "ft_004", "Alternance Data Analyst en alternance",
            "Décathlon", "59 - Lille",
            "CDD - 12 Mois", score=29.0,
            remote="full",
            salary="Selon grille alternance",
            days_ago=10,
        ),
    ]

    keywords  = ["Data Analyst", "Big Data", "alternance data"]
    locations = ["59 - Nord", "80 - Somme"]

    html = render_email(offers, keywords, locations)

    output_path = Path(__file__).parent.parent / "email_preview.html"
    output_path.write_text(html, encoding="utf-8")

    print("=" * 55)
    print("Aperçu généré !")
    print(f"Ouvre ce fichier dans ton navigateur :")
    print(f"  {output_path.resolve()}")
    print("=" * 55)


if __name__ == "__main__":
    main()