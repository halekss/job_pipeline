"""
feedback.py - Feedback loop sur le scoring (COM-13)

Stocke les retours "pas intéressé" reçus par email (cf.
notifier/imap_feedback.py) et calcule les pénalités à appliquer dans
pipeline/filter.py : pénalité par entreprise récurrente, et mots-clés
négatifs appris à partir des raisons fournies explicitement par Alex.
Cf. docs/superpowers/specs/2026-07-10-feedback-loop-design.md.
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "storage" / "jobs.db"

DEFAULT_COMPANY_THRESHOLD = 2
DEFAULT_COMPANY_PENALTY = 20.0
DEFAULT_KEYWORD_PENALTY = 30.0


class FeedbackStore:
    """
    Stocke les feedbacks "pas intéressé" et calcule les pénalités de scoring.

    Usage :
        store = FeedbackStore()
        store.record("indeed_abc123", reason="comptabilité")
        company_penalties = store.get_company_penalties()
        negative_keywords = store.get_negative_keywords()
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
                CREATE TABLE IF NOT EXISTS feedback (
                    offer_id    TEXT NOT NULL,
                    company     TEXT,
                    reason      TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_created_at
                ON feedback (created_at)
            """)
        logger.debug("Base FeedbackStore initialisée : %s", self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def record(self, offer_id: str, reason: Optional[str] = None):
        """
        Enregistre un feedback. Résout `company` en lisant la table
        `seen_offers` (créée par DedupStore) dans le même fichier SQLite ;
        NULL si la table n'existe pas encore ou si l'offre a été purgée.
        """
        company = None
        with self._conn() as conn:
            try:
                row = conn.execute(
                    "SELECT company FROM seen_offers WHERE id = ?", (offer_id,)
                ).fetchone()
                company = row[0] if row else None
            except sqlite3.OperationalError:
                logger.debug("Table seen_offers absente, company=None pour %s", offer_id)

            conn.execute(
                """
                INSERT INTO feedback (offer_id, company, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (offer_id, company, reason, datetime.now(timezone.utc).isoformat()),
            )
        logger.info(
            "Feedback enregistré : offer_id=%s company=%s reason=%s",
            offer_id, company, reason,
        )

    def get_company_penalties(
        self,
        threshold: int = DEFAULT_COMPANY_THRESHOLD,
        penalty: float = DEFAULT_COMPANY_PENALTY,
    ) -> dict[str, float]:
        """
        {company en minuscules: penalty} pour chaque entreprise avec au
        moins `threshold` feedbacks. Le lowercase se fait en Python (pas en
        SQL : SQLite's LOWER() ne gère pas les accents correctement).
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT company FROM feedback WHERE company IS NOT NULL AND company != ''"
            ).fetchall()

        counts: dict[str, int] = {}
        for (company,) in rows:
            key = company.strip().lower()
            counts[key] = counts.get(key, 0) + 1

        return {company: penalty for company, count in counts.items() if count >= threshold}

    def get_negative_keywords(
        self,
        penalty: float = DEFAULT_KEYWORD_PENALTY,
    ) -> list[tuple[str, float]]:
        """[(raison, penalty), ...] pour chaque raison non vide distincte."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT reason FROM feedback WHERE reason IS NOT NULL AND reason != ''"
            ).fetchall()
        return [(reason, penalty) for (reason,) in rows]

    def purge_old(self, days: int = 60) -> int:
        """Supprime les entrées plus vieilles que `days` jours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM feedback WHERE created_at < ?", (cutoff,))
            deleted = cursor.rowcount
        logger.info("Purge feedback : %d entrées supprimées (> %d jours).", deleted, days)
        return deleted

    def count(self) -> int:
        """Retourne le nombre total de feedbacks en base."""
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    def reset(self):
        """Vide complètement la base (utile pour les tests)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM feedback")
        logger.warning("FeedbackStore réinitialisé.")
