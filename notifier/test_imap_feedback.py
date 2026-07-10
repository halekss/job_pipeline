"""
Script de test rapide pour la lecture IMAP des feedbacks (appel réseau réel).

Usage :
    python test_imap_feedback.py
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv(Path(__file__).parent.parent / ".env")

from imap_feedback import fetch_feedback_emails

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main():
    print("=" * 60)
    print("Test de lecture des feedbacks IMAP")
    print("=" * 60)

    results = fetch_feedback_emails()

    if not results:
        print("Aucun feedback non lu trouvé (ou erreur de connexion, voir logs).")
        return

    print(f"{len(results)} feedback(s) trouvé(s)\n")
    for fb in results:
        print(f"  offer_id={fb.offer_id}  reason={fb.reason!r}")

    print("\nTerminé.")


if __name__ == "__main__":
    main()
