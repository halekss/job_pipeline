"""
dedup.py - Déduplication des offres d'emploi

Garde en mémoire les IDs des offres déjà vues dans une base SQLite
pour ne pas envoyer deux fois la même offre dans les alertes mail.

Deux niveaux de déduplication :
  1. Dans la session courante (entre sources différentes)
  2. Entre les exécutions (via SQLite)
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

try:
    from sources.base_source import JobOffer
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from sources.base_source import JobOffer

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "storage" / "jobs.db"


class DedupStore:
    """
    Stocke les IDs des offres déjà envoyées et filtre les doublons.

    Usage :
        store = DedupStore()
        new_offers = store.filter_new(offers)
        store.mark_seen(new_offers)
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self):
        """Crée la table si elle n'existe pas."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_offers (
                    id          TEXT PRIMARY KEY,
                    title       TEXT,
                    company     TEXT,
                    source      TEXT,
                    seen_at     TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_at
                ON seen_offers (seen_at)
            """)
        logger.debug("Base DedupStore initialisée : %s", self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def filter_new(self, offers: list[JobOffer]) -> list[JobOffer]:
        """
        Retourne uniquement les offres dont l'ID n'a pas encore été vu.
        Ne modifie pas la base (appeler mark_seen ensuite).
        """
        if not offers:
            return []

        ids = [o.id for o in offers]
        placeholders = ",".join("?" * len(ids))

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id FROM seen_offers WHERE id IN ({placeholders})",
                ids,
            ).fetchall()

        already_seen = {row[0] for row in rows}
        new_offers = [o for o in offers if o.id not in already_seen]

        logger.info(
            "Déduplication : %d nouvelles offres sur %d (%d déjà vues)",
            len(new_offers), len(offers), len(already_seen),
        )
        return new_offers

    def mark_seen(self, offers: list[JobOffer]):
        """Enregistre les offres comme vues dans la base."""
        if not offers:
            return

        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (o.id, o.title, o.company, o.source, now)
            for o in offers
        ]

        with self._conn() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO seen_offers (id, title, company, source, seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

        logger.info("%d offres marquées comme vues.", len(offers))

    def purge_old(self, days: int = 60):
        """
        Supprime les entrées plus vieilles que `days` jours.
        À appeler périodiquement pour éviter que la base grossisse indéfiniment.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM seen_offers WHERE seen_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount

        logger.info("Purge : %d entrées supprimées (> %d jours).", deleted, days)
        return deleted

    def count(self) -> int:
        """Retourne le nombre total d'offres en base."""
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM seen_offers").fetchone()[0]

    def reset(self):
        """Vide complètement la base (utile pour les tests)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM seen_offers")
        logger.warning("DedupStore réinitialisé.")