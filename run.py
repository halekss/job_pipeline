"""
run.py - Point d'entrée principal du pipeline de veille emploi

Orchestre dans l'ordre :
  1. Collecte des offres (toutes les sources)
  2. Filtrage et scoring
  3. Déduplication (offres déjà vues)
  4. Envoi de l'alerte email
  5. Marquage des offres comme vues

Usage :
    python run.py
    python run.py --dry-run        # sans envoi email ni marquage
    python run.py --reset-dedup    # remet la base dedup à zéro
    python run.py --no-alternance  # inclut toutes les offres, pas que les alternances
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Chargement du .env depuis la racine du projet
load_dotenv(Path(__file__).parent / ".env")

# Ajout de la racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from sources.france_travail import FranceTravailSource
from pipeline.filter import filter_offers
from pipeline.dedup import DedupStore
from notifier.mailer import EmailNotifier

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent / "storage" / "pipeline.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("run")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KEYWORDS  = ["Data Analyst", "Big Data", "alternance data", "data engineer", "remote", "télétravail"]
LOCATIONS = ["59", "80", "69", "75"]   # Nord, Paris, Rhône — à adapter

MIN_SCORE       = 20
ALTERNANCE_ONLY = True   # False pour recevoir aussi les CDI/CDD pertinents
DEDUP_PURGE_DAYS = 60    # Entrées plus vieilles supprimées automatiquement


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, reset_dedup: bool = False, alternance_only: bool = ALTERNANCE_ONLY):
    logger.info("=" * 60)
    logger.info("Démarrage du pipeline job_pipeline")
    logger.info("=" * 60)

    # Dossier storage
    storage_dir = Path(__file__).parent / "storage"
    storage_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Collecte
    # ------------------------------------------------------------------
    logger.info("[1/5] Collecte des offres...")
    all_offers = []

    try:
        ft = FranceTravailSource(
            keywords=KEYWORDS,
            locations=LOCATIONS,
            max_results=150,
        )
        ft_offers = ft.fetch()
        all_offers.extend(ft_offers)
        logger.info("France Travail : %d offres", len(ft_offers))
    except Exception as e:
        logger.error("Erreur France Travail : %s", e)

    # Ici on pourra ajouter d'autres sources plus tard :
    # all_offers.extend(IndeedSource(...).fetch())
    # all_offers.extend(WTTJSource(...).fetch())

    if not all_offers:
        logger.warning("Aucune offre collectée. Fin du pipeline.")
        return

    logger.info("Total collecté : %d offres", len(all_offers))

    # ------------------------------------------------------------------
    # 2. Filtrage et scoring
    # ------------------------------------------------------------------
    logger.info("[2/5] Filtrage et scoring...")
    filtered = filter_offers(
        all_offers,
        min_score=MIN_SCORE,
        alternance_only=alternance_only,
    )
    logger.info("%d offres après filtrage (seuil=%d)", len(filtered), MIN_SCORE)

    if not filtered:
        logger.info("Aucune offre pertinente. Fin du pipeline.")
        return

    # ------------------------------------------------------------------
    # 3. Déduplication
    # ------------------------------------------------------------------
    logger.info("[3/5] Déduplication...")
    store = DedupStore()

    if reset_dedup:
        store.reset()
        logger.warning("Base dedup réinitialisée.")

    store.purge_old(days=DEDUP_PURGE_DAYS)
    new_offers = store.filter_new(filtered)
    logger.info("%d nouvelles offres après déduplication", len(new_offers))

    if not new_offers:
        logger.info("Toutes les offres ont déjà été envoyées. Fin du pipeline.")
        return

    # ------------------------------------------------------------------
    # 4. Envoi email
    # ------------------------------------------------------------------
    logger.info("[4/5] Envoi de l'alerte email...")

    email_sent = False
    if dry_run:
        logger.info("[DRY RUN] Email non envoyé. Offres qui auraient été envoyées :")
        for o in new_offers:
            logger.info("  [%.0f] %s · %s · %s", o.score, o.title, o.company, o.location)
        email_sent = True  # en dry-run on considère que c'est OK pour le marquage
    else:
        try:
            notifier = EmailNotifier()
            email_sent = notifier.send(
                new_offers,
                keywords=KEYWORDS,
                locations=LOCATIONS,
            )
            if not email_sent:
                logger.error("Échec de l'envoi email. Les offres ne seront pas marquées comme vues.")
        except ValueError as e:
            logger.error("Configuration email manquante : %s", e)

    # ------------------------------------------------------------------
    # 5. Marquage comme vues (uniquement si l'email a été envoyé)
    # ------------------------------------------------------------------
    logger.info("[5/5] Marquage des offres...")
    if dry_run:
        logger.info("[DRY RUN] Marquage ignoré.")
    elif email_sent:
        store.mark_seen(new_offers)
    else:
        logger.warning("Email non envoyé : offres non marquées, elles ressortiront au prochain run.")

    logger.info("=" * 60)
    logger.info("Pipeline terminé. %d offre(s) traitée(s).", len(new_offers))
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de veille emploi")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Exécute le pipeline sans envoyer d'email ni marquer les offres",
    )
    parser.add_argument(
        "--reset-dedup",
        action="store_true",
        help="Remet la base de déduplication à zéro avant l'exécution",
    )
    parser.add_argument(
        "--no-alternance",
        action="store_true",
        help="Désactive le filtre alternance uniquement",
    )
    args = parser.parse_args()

    run(
        dry_run=args.dry_run,
        reset_dedup=args.reset_dedup,
        alternance_only=not args.no_alternance,
    )