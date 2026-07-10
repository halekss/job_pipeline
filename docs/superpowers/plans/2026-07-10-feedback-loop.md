# Feedback Loop Implementation Plan (COM-13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Alex mark offers "pas intéressé" (optionally with a reason) by replying to the alert email, and use that feedback to penalize repeat-offending companies and learn domain-mismatch keywords (e.g. "alternance comptable" slipping through on the alternance bonus alone) in `pipeline/filter.py`'s scoring.

**Architecture:** A `mailto:` link per offer in the email (no server needed) → Alex replies from his own client → next run reads unread replies via IMAP (same Gmail account/credentials already used for SMTP) → parses `offer_id` + optional reason → persists in a new `feedback` table in the existing `storage/jobs.db` SQLite file → `pipeline/filter.py` receives the computed penalties as plain function parameters (no I/O inside `filter.py` itself).

**Tech Stack:** Python 3.13, stdlib `sqlite3`, `imaplib`, `email` (no new dependencies).

## Global Constraints

- No new hosting/infrastructure — feedback travels over the existing email channel only (spec: `docs/superpowers/specs/2026-07-10-feedback-loop-design.md`).
- Reuse `SMTP_USER`/`SMTP_PASSWORD` for IMAP (Gmail app passwords work for both) — no new required secrets. `IMAP_HOST` is optional, defaults to `imap.gmail.com`.
- `pipeline/filter.py` stays pure (no DB/network access) — it receives `company_penalties: dict[str, float]` and `extra_negative_keywords: list[tuple[str, float]]` as parameters with `None`/empty defaults that preserve current scoring behavior exactly.
- Company penalty: threshold 2 occurrences, magnitude 20 points (subtracted, same convention as `NEGATIVE_KEYWORDS`/`AGE_PENALTIES` — positive numbers in config, subtracted in scoring).
- Learned negative keyword (from explicit reason): magnitude 40 points, applied from the first occurrence (no threshold — it's a deliberate signal from Alex). *(Corrected from 30 during Task 3: 30 was insufficient to push a pure alternance-bonus offer — score 55, no tech keywords — below MIN_SCORE=20; verified 55-30=25 stays above threshold, 55-40=15 clears it with margin.)*
- Company name matching is case-insensitive on the full string (no fuzzy matching) — must lowercase in Python, not SQL (SQLite's `LOWER()` only handles ASCII and would mishandle accented French company names like "Décathlon" or "bioMérieux").
- Tests follow this repo's convention: plain `assert`-based scripts with a `main()` function, run via `python <file>.py` (no pytest).
- IMAP/network failures must never crash the pipeline — log and degrade gracefully (empty feedback), same pattern as `IndeedSource.fetch()`.

---

### Task 1: `FeedbackStore` (SQLite persistence)

**Files:**
- Create: `pipeline/feedback.py`
- Create: `pipeline/test_feedback.py`

**Interfaces:**
- Consumes: nothing new (uses the `seen_offers` table already created by `pipeline/dedup.py::DedupStore`, same `storage/jobs.db` file).
- Produces: `FeedbackStore(db_path: Path = DEFAULT_DB_PATH)` with `.record(offer_id: str, reason: Optional[str] = None)`, `.get_company_penalties(threshold: int = 2, penalty: float = 20.0) -> dict[str, float]`, `.get_negative_keywords(penalty: float = 30.0) -> list[tuple[str, float]]`, `.purge_old(days: int = 60) -> int`, `.count() -> int`, `.reset()`. Consumed by Task 3 (via `run.py`, wired in Task 5) and directly by this task's tests.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/test_feedback.py`:

```python
"""
Test de feedback.py - Pas besoin de credentials, base SQLite temporaire.

Usage (depuis pipeline/) :
    python test_feedback.py
"""

import sys, os, tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dedup import DedupStore
from feedback import FeedbackStore
from sources.base_source import JobOffer
from datetime import datetime, timezone


def _make_db_path() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


def _make_offer(id: str, company: str) -> JobOffer:
    return JobOffer(
        id=id, title="Alternance Comptable", company=company, location="Lille",
        description="...", url="https://example.com", source="test",
        published_at=datetime.now(timezone.utc),
    )


def _cleanup(db_path: Path):
    import gc
    gc.collect()
    db_path.unlink(missing_ok=True)


def test_record_resolves_company_from_seen_offers():
    db_path = _make_db_path()
    dedup = DedupStore(db_path=db_path)
    dedup.mark_seen([_make_offer("indeed_1", "ISCOD")])

    store = FeedbackStore(db_path=db_path)
    store.record("indeed_1", reason=None)

    with store._conn() as conn:
        row = conn.execute("SELECT company FROM feedback WHERE offer_id = ?", ("indeed_1",)).fetchone()
    assert row[0] == "ISCOD", f"attendu 'ISCOD', obtenu {row[0]}"

    dedup._conn().close()
    store._conn().close()
    _cleanup(db_path)
    print("OK: test_record_resolves_company_from_seen_offers")


def test_record_handles_missing_seen_offers_table():
    # FeedbackStore utilisé seul, sans DedupStore initialisé au préalable :
    # ne doit pas planter, company reste NULL.
    db_path = _make_db_path()
    store = FeedbackStore(db_path=db_path)
    store.record("ft_unknown", reason="comptabilité")

    with store._conn() as conn:
        row = conn.execute("SELECT company, reason FROM feedback WHERE offer_id = ?", ("ft_unknown",)).fetchone()
    assert row[0] is None, f"attendu company=None, obtenu {row[0]}"
    assert row[1] == "comptabilité", f"attendu reason='comptabilité', obtenu {row[1]}"

    store._conn().close()
    _cleanup(db_path)
    print("OK: test_record_handles_missing_seen_offers_table")


def test_company_penalty_applies_only_above_threshold():
    db_path = _make_db_path()
    dedup = DedupStore(db_path=db_path)
    dedup.mark_seen([
        _make_offer("indeed_1", "ISCOD"),
        _make_offer("indeed_2", "ISCOD"),
        _make_offer("indeed_3", "Studi CFA"),
    ])

    store = FeedbackStore(db_path=db_path)
    store.record("indeed_1")
    store.record("indeed_2")   # ISCOD : 2 feedbacks -> pénalisé
    store.record("indeed_3")   # Studi CFA : 1 feedback -> pas pénalisé

    penalties = store.get_company_penalties(threshold=2, penalty=20.0)
    assert penalties == {"iscod": 20.0}, f"attendu {{'iscod': 20.0}}, obtenu {penalties}"

    dedup._conn().close()
    store._conn().close()
    _cleanup(db_path)
    print("OK: test_company_penalty_applies_only_above_threshold")


def test_company_penalty_is_case_and_accent_safe():
    db_path = _make_db_path()
    dedup = DedupStore(db_path=db_path)
    dedup.mark_seen([
        _make_offer("indeed_1", "Décathlon"),
        _make_offer("indeed_2", "DÉCATHLON"),
    ])

    store = FeedbackStore(db_path=db_path)
    store.record("indeed_1")
    store.record("indeed_2")

    penalties = store.get_company_penalties(threshold=2, penalty=20.0)
    assert penalties == {"décathlon": 20.0}, f"attendu {{'décathlon': 20.0}}, obtenu {penalties}"

    dedup._conn().close()
    store._conn().close()
    _cleanup(db_path)
    print("OK: test_company_penalty_is_case_and_accent_safe")


def test_get_negative_keywords_deduplicates_reasons():
    db_path = _make_db_path()
    store = FeedbackStore(db_path=db_path)
    store.record("ft_1", reason="comptabilité")
    store.record("ft_2", reason="comptabilité")
    store.record("ft_3", reason="RH")
    store.record("ft_4", reason=None)

    keywords = store.get_negative_keywords(penalty=30.0)
    assert sorted(keywords) == sorted([("comptabilité", 30.0), ("RH", 30.0)]), keywords

    store._conn().close()
    _cleanup(db_path)
    print("OK: test_get_negative_keywords_deduplicates_reasons")


def test_purge_old_removes_entries_past_cutoff():
    db_path = _make_db_path()
    store = FeedbackStore(db_path=db_path)
    store.record("ft_1", reason="comptabilité")

    deleted = store.purge_old(days=0)
    assert deleted == 1, f"attendu 1 entrée supprimée, obtenu {deleted}"
    assert store.count() == 0, f"attendu 0 entrée restante, obtenu {store.count()}"

    store._conn().close()
    _cleanup(db_path)
    print("OK: test_purge_old_removes_entries_past_cutoff")


def main():
    test_record_resolves_company_from_seen_offers()
    test_record_handles_missing_seen_offers_table()
    test_company_penalty_applies_only_above_threshold()
    test_company_penalty_is_case_and_accent_safe()
    test_get_negative_keywords_deduplicates_reasons()
    test_purge_old_removes_entries_past_cutoff()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd pipeline && ../.venv/Scripts/python.exe test_feedback.py`
Expected: `ModuleNotFoundError: No module named 'feedback'`

- [ ] **Step 3: Create `pipeline/feedback.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd pipeline && ../.venv/Scripts/python.exe test_feedback.py`
Expected: 6 `OK:` lines then `Tous les tests passent.`

- [ ] **Step 5: Commit**

```bash
git add pipeline/feedback.py pipeline/test_feedback.py
git commit -m "Add FeedbackStore for COM-13 feedback loop"
```

---

### Task 2: IMAP feedback email parsing

**Files:**
- Create: `notifier/imap_feedback.py`
- Create: `notifier/test_imap_feedback_parsing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `FeedbackEmail` dataclass (`offer_id: str`, `reason: Optional[str]`) and `fetch_feedback_emails(host: str = None, port: int = 993, user: str = None, password: str = None) -> list[FeedbackEmail]`. Consumed by `run.py` in Task 5.

- [ ] **Step 1: Write the failing tests**

Create `notifier/test_imap_feedback_parsing.py`:

```python
"""
Test du parsing des emails de feedback (notifier/imap_feedback.py).
Aucun appel réseau réel : construit des emails en mémoire et mocke
imaplib.IMAP4_SSL pour le test d'orchestration.

Usage (depuis notifier/) :
    python test_imap_feedback_parsing.py
"""

import sys, os
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from imap_feedback import (
    _decode_subject,
    _extract_text_body,
    _parse_reason,
    fetch_feedback_emails,
    OFFER_ID_RE,
)


def _build_raw_email(subject: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "alex@example.com"
    msg["To"] = "pipeline@example.com"
    msg.set_content(body)
    return msg.as_bytes()


def test_decode_subject_handles_plain_ascii():
    assert _decode_subject("[Job Pipeline Feedback] indeed_abc123") == "[Job Pipeline Feedback] indeed_abc123"
    print("OK: test_decode_subject_handles_plain_ascii")


def test_offer_id_regex_extracts_id_from_subject():
    match = OFFER_ID_RE.search("Re: [Job Pipeline Feedback] indeed_abc123")
    assert match is not None
    assert match.group(1) == "indeed_abc123", match.group(1)
    print("OK: test_offer_id_regex_extracts_id_from_subject")


def test_offer_id_regex_returns_none_without_marker():
    match = OFFER_ID_RE.search("Re: une offre intéressante")
    assert match is None
    print("OK: test_offer_id_regex_returns_none_without_marker")


def test_extract_text_body_reads_plain_text_part():
    raw = _build_raw_email("test", "Pas intéressé.\n\nRaison (optionnel) : comptabilité")
    import email as email_module
    msg = email_module.message_from_bytes(raw)
    body = _extract_text_body(msg)
    assert "comptabilité" in body, body
    print("OK: test_extract_text_body_reads_plain_text_part")


def test_parse_reason_extracts_filled_reason():
    body = "Pas intéressé.\n\nRaison (optionnel) : comptabilité\n"
    assert _parse_reason(body) == "comptabilité", _parse_reason(body)
    print("OK: test_parse_reason_extracts_filled_reason")


def test_parse_reason_returns_none_when_left_blank():
    body = "Pas intéressé.\n\nRaison (optionnel) : \n"
    assert _parse_reason(body) is None, _parse_reason(body)
    print("OK: test_parse_reason_returns_none_when_left_blank")


def test_parse_reason_returns_none_without_marker():
    body = "Pas intéressé, merci de retirer cette offre."
    assert _parse_reason(body) is None, _parse_reason(body)
    print("OK: test_parse_reason_returns_none_without_marker")


def test_fetch_feedback_emails_parses_and_marks_seen():
    raw1 = _build_raw_email(
        "[Job Pipeline Feedback] indeed_1", "Raison (optionnel) : comptabilité"
    )
    raw2 = _build_raw_email(
        "[Job Pipeline Feedback] ft_2", "Raison (optionnel) : "
    )

    fake_imap = MagicMock()
    fake_imap.login.return_value = ("OK", [b""])
    fake_imap.select.return_value = ("OK", [b""])
    fake_imap.search.return_value = ("OK", [b"1 2"])
    fake_imap.fetch.side_effect = [
        ("OK", [(b"1 (BODY[])", raw1)]),
        ("OK", [(b"2 (BODY[])", raw2)]),
    ]

    with patch("imap_feedback.imaplib.IMAP4_SSL", return_value=fake_imap):
        results = fetch_feedback_emails(
            host="imap.example.com", user="alex@example.com", password="secret"
        )

    assert len(results) == 2, f"attendu 2 résultats, obtenu {len(results)}"
    assert results[0].offer_id == "indeed_1", results[0].offer_id
    assert results[0].reason == "comptabilité", results[0].reason
    assert results[1].offer_id == "ft_2", results[1].offer_id
    assert results[1].reason is None, results[1].reason
    assert fake_imap.store.call_count == 2, "les 2 messages doivent être marqués \\Seen"
    print("OK: test_fetch_feedback_emails_parses_and_marks_seen")


def test_fetch_feedback_emails_returns_empty_list_on_imap_error():
    with patch("imap_feedback.imaplib.IMAP4_SSL", side_effect=OSError("connexion refusée")):
        results = fetch_feedback_emails(
            host="imap.example.com", user="alex@example.com", password="secret"
        )
    assert results == [], f"attendu liste vide, obtenu {results}"
    print("OK: test_fetch_feedback_emails_returns_empty_list_on_imap_error")


def test_fetch_feedback_emails_returns_empty_list_without_credentials():
    with patch.dict(os.environ, {}, clear=True):
        results = fetch_feedback_emails(host="imap.example.com", user=None, password=None)
    assert results == [], f"attendu liste vide, obtenu {results}"
    print("OK: test_fetch_feedback_emails_returns_empty_list_without_credentials")


def main():
    test_decode_subject_handles_plain_ascii()
    test_offer_id_regex_extracts_id_from_subject()
    test_offer_id_regex_returns_none_without_marker()
    test_extract_text_body_reads_plain_text_part()
    test_parse_reason_extracts_filled_reason()
    test_parse_reason_returns_none_when_left_blank()
    test_parse_reason_returns_none_without_marker()
    test_fetch_feedback_emails_parses_and_marks_seen()
    test_fetch_feedback_emails_returns_empty_list_on_imap_error()
    test_fetch_feedback_emails_returns_empty_list_without_credentials()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd notifier && ../.venv/Scripts/python.exe test_imap_feedback_parsing.py`
Expected: `ModuleNotFoundError: No module named 'imap_feedback'`

- [ ] **Step 3: Create `notifier/imap_feedback.py`**

```python
"""
imap_feedback.py - Lecture des réponses "pas intéressé" par IMAP (COM-13)

Lit les mails non lus dont le sujet contient le marqueur
[Job Pipeline Feedback], envoyés en réponse au lien mailto généré par
notifier/formatter.py. Réutilise les identifiants SMTP (Gmail accepte les
mots de passe d'application aussi bien en IMAP qu'en SMTP) — aucun nouveau
secret requis. Cf. docs/superpowers/specs/2026-07-10-feedback-loop-design.md.
"""

import imaplib
import email
import logging
import os
import re
from dataclasses import dataclass
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

SUBJECT_MARKER = "[Job Pipeline Feedback]"
OFFER_ID_RE = re.compile(r"\[Job Pipeline Feedback\]\s*(\S+)")
REASON_RE = re.compile(r"raison\s*(?:\(optionnel\))?\s*:\s*(.+)", re.IGNORECASE)


@dataclass
class FeedbackEmail:
    offer_id: str
    reason: Optional[str]


def _decode_subject(raw_subject: str) -> str:
    """Décode un sujet potentiellement encodé (RFC 2047) en str lisible."""
    if not raw_subject:
        return ""
    decoded = ""
    for text, charset in decode_header(raw_subject):
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _extract_text_body(msg: email.message.Message) -> str:
    """Extrait la partie text/plain d'un email (simple ou multipart)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""

    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _parse_reason(body: str) -> Optional[str]:
    """Extrait la raison de la ligne 'Raison (optionnel) : ...' si remplie."""
    match = REASON_RE.search(body)
    if not match:
        return None
    reason = match.group(1).strip()
    return reason or None


def fetch_feedback_emails(
    host: str = None,
    port: int = 993,
    user: str = None,
    password: str = None,
) -> list[FeedbackEmail]:
    """
    Se connecte en IMAP et retourne les feedbacks non lus trouvés.

    Ne lève jamais d'exception : toute erreur (credentials manquants,
    connexion, IMAP) est loguée et retourne une liste vide, pour ne
    jamais bloquer le run principal.
    """
    host = host or os.getenv("IMAP_HOST", "imap.gmail.com")
    user = user or os.getenv("SMTP_USER")
    password = password or os.getenv("SMTP_PASSWORD")

    if not user or not password:
        logger.error("[Feedback] SMTP_USER/SMTP_PASSWORD requis pour lire les feedbacks IMAP.")
        return []

    results: list[FeedbackEmail] = []

    try:
        imap = imaplib.IMAP4_SSL(host, port)
    except Exception as e:
        logger.error("[Feedback] Erreur de connexion IMAP : %s", e)
        return []

    try:
        imap.login(user, password)
        imap.select("INBOX")

        typ, data = imap.search(None, "UNSEEN", "SUBJECT", f'"{SUBJECT_MARKER}"')
        if typ != "OK":
            logger.warning("[Feedback] Recherche IMAP échouée : %s", typ)
            return []

        message_numbers = data[0].split() if data and data[0] else []

        for num in message_numbers:
            typ, msg_data = imap.fetch(num, "(BODY[])")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_subject(msg.get("Subject", ""))

            match = OFFER_ID_RE.search(subject)
            if not match:
                logger.warning("[Feedback] Sujet sans offer_id reconnaissable : %s", subject)
                imap.store(num, "+FLAGS", "\\Seen")
                continue

            offer_id = match.group(1)
            body = _extract_text_body(msg)
            reason = _parse_reason(body)

            results.append(FeedbackEmail(offer_id=offer_id, reason=reason))
            imap.store(num, "+FLAGS", "\\Seen")

    except Exception as e:
        logger.error("[Feedback] Erreur IMAP : %s", e)
        return []
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return results
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd notifier && ../.venv/Scripts/python.exe test_imap_feedback_parsing.py`
Expected: 10 `OK:` lines then `Tous les tests passent.`

- [ ] **Step 5: Commit**

```bash
git add notifier/imap_feedback.py notifier/test_imap_feedback_parsing.py
git commit -m "Add IMAP feedback email parsing for COM-13"
```

---

### Task 3: `pipeline/filter.py` scoring extension

**Files:**
- Modify: `pipeline/filter.py:159-229` (functions `score_offer` and `filter_offers`)
- Create: `pipeline/test_filter_feedback.py`

**Interfaces:**
- Consumes: `company_penalties: dict[str, float]` and `extra_negative_keywords: list[tuple[str, float]]`, same shapes as `FeedbackStore.get_company_penalties()`/`get_negative_keywords()` from Task 1.
- Produces: `score_offer(offer, company_penalties=None, extra_negative_keywords=None)` and `filter_offers(offers, min_score=MIN_SCORE, alternance_only=False, company_penalties=None, extra_negative_keywords=None)` — both keep working with only the original arguments (defaults preserve current behavior exactly). Consumed by `run.py` in Task 5.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/test_filter_feedback.py`:

```python
"""
Test des paramètres company_penalties / extra_negative_keywords de
pipeline/filter.py (COM-13). Aucun appel réseau.

Usage (depuis pipeline/) :
    python test_filter_feedback.py
"""

import sys, os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from filter import score_offer, filter_offers
from sources.base_source import JobOffer


def _make_offer(title, company, contract_type=None, description=""):
    return JobOffer(
        id="x", title=title, company=company, location="Lille",
        description=description, url="https://example.com", source="test",
        published_at=datetime.now(timezone.utc),
        contract_type=contract_type,
    )


def test_score_offer_unchanged_without_feedback_params():
    offer = _make_offer("Alternance Data Analyst", "ACME", contract_type="alternance")
    assert score_offer(offer) == score_offer(offer, None, None)
    print("OK: test_score_offer_unchanged_without_feedback_params")


def test_company_penalty_reduces_score():
    offer = _make_offer("Alternance Data Analyst", "ACME", contract_type="alternance")
    base_score = score_offer(offer)
    penalized_score = score_offer(offer, company_penalties={"acme": 20.0})
    assert penalized_score == round(base_score - 20.0, 1), (base_score, penalized_score)
    print("OK: test_company_penalty_reduces_score")


def test_company_penalty_matches_case_insensitively():
    offer = _make_offer("Alternance Data Analyst", "ACME Corp", contract_type="alternance")
    penalized_score = score_offer(offer, company_penalties={"acme corp": 20.0})
    base_score = score_offer(offer)
    assert penalized_score == round(base_score - 20.0, 1), (base_score, penalized_score)
    print("OK: test_company_penalty_matches_case_insensitively")


def test_learned_negative_keyword_pushes_alternance_offer_below_threshold():
    # Cas réel COM-13 : "Alternance Comptable" passe le seuil (20) sur le
    # seul bonus alternance (+25 mot-clé +30 contrat), sans mot-clé
    # technique. Un mot-clé négatif appris doit repasser sous le seuil.
    offer = _make_offer("Alternance Comptable", "Cabinet XYZ", contract_type="alternance")
    base_score = score_offer(offer)
    assert base_score >= 20, f"précondition : l'offre doit passer le seuil sans feedback (score={base_score})"

    penalized_score = score_offer(
        offer, extra_negative_keywords=[("comptable", 30.0)]
    )
    assert penalized_score < 20, f"attendu score < 20 après pénalité, obtenu {penalized_score}"
    print("OK: test_learned_negative_keyword_pushes_alternance_offer_below_threshold")


def test_learned_negative_keyword_reason_is_regex_escaped():
    # Une raison contenant des caractères spéciaux regex ne doit pas planter.
    offer = _make_offer("Alternance Data Analyst (H/F)", "ACME", contract_type="alternance")
    score = score_offer(offer, extra_negative_keywords=[("h/f) (bonus?", 30.0)])
    assert isinstance(score, float)
    print("OK: test_learned_negative_keyword_reason_is_regex_escaped")


def test_filter_offers_excludes_offer_pushed_below_threshold_by_feedback():
    offer = _make_offer("Alternance Comptable", "Cabinet XYZ", contract_type="alternance")
    without_feedback = filter_offers([offer], min_score=20)
    assert len(without_feedback) == 1, "précondition : l'offre passe sans feedback"

    with_feedback = filter_offers(
        [offer], min_score=20, extra_negative_keywords=[("comptable", 30.0)]
    )
    assert len(with_feedback) == 0, f"attendu 0 offre après pénalité, obtenu {len(with_feedback)}"
    print("OK: test_filter_offers_excludes_offer_pushed_below_threshold_by_feedback")


def main():
    test_score_offer_unchanged_without_feedback_params()
    test_company_penalty_reduces_score()
    test_company_penalty_matches_case_insensitively()
    test_learned_negative_keyword_pushes_alternance_offer_below_threshold()
    test_learned_negative_keyword_reason_is_regex_escaped()
    test_filter_offers_excludes_offer_pushed_below_threshold_by_feedback()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd pipeline && ../.venv/Scripts/python.exe test_filter_feedback.py`
Expected: `TypeError: score_offer() takes 1 positional argument but 3 were given` (or similar — the new parameters don't exist yet)

- [ ] **Step 3: Modify `pipeline/filter.py`**

Replace lines 159-177 (the current `score_offer` function):

```python
def score_offer(
    offer: JobOffer,
    company_penalties: Optional[dict[str, float]] = None,
    extra_negative_keywords: Optional[list[tuple[str, float]]] = None,
) -> float:
    """
    Calcule et retourne le score total d'une offre (0-100, peut dépasser).

    Le score est la somme de :
      - mots-clés dans titre + description
      - bonus type de contrat
      - bonus télétravail
      - malus ancienneté
      - malus entreprise récurrente dans le feedback "pas intéressé" (COM-13)
      - malus mots-clés négatifs appris depuis les raisons de feedback (COM-13)
    """
    full_text = f"{offer.title} {offer.description} {' '.join(offer.skills)}"

    text_score      = _score_text(full_text)
    contract_score  = _score_contract(offer.contract_type)
    remote_score    = _score_remote(offer.remote)
    freshness_score = _score_freshness(offer.published_at)
    company_score   = _score_company_feedback(offer.company, company_penalties)
    learned_score   = _score_learned_negative_keywords(full_text, extra_negative_keywords)

    total = (
        text_score + contract_score + remote_score + freshness_score
        + company_score + learned_score
    )
    return round(max(0.0, total), 1)
```

Add these two new functions right before `score_offer` (after `_score_freshness`, which ends at line 156):

```python
def _score_company_feedback(
    company: str, company_penalties: Optional[dict[str, float]]
) -> float:
    """Malus si l'entreprise a reçu suffisamment de feedback 'pas intéressé' (COM-13)."""
    if not company or not company_penalties:
        return 0.0
    return -company_penalties.get(company.strip().lower(), 0.0)


def _score_learned_negative_keywords(
    text: str, extra_negative_keywords: Optional[list[tuple[str, float]]]
) -> float:
    """Malus pour les mots-clés négatifs appris depuis les raisons de feedback (COM-13)."""
    if not extra_negative_keywords:
        return 0.0

    text_lower = text.lower()
    score = 0.0
    for reason, penalty in extra_negative_keywords:
        pattern = re.escape(reason.strip().lower())
        if pattern and re.search(pattern, text_lower):
            score -= penalty
    return score
```

Replace lines 195-210 (the `filter_offers` signature and docstring) with:

```python
def filter_offers(
    offers: list[JobOffer],
    min_score: float = MIN_SCORE,
    alternance_only: bool = False,
    company_penalties: Optional[dict[str, float]] = None,
    extra_negative_keywords: Optional[list[tuple[str, float]]] = None,
) -> list[JobOffer]:
    """
    Score toutes les offres, écarte celles sous le seuil, trie par score décroissant.

    Args:
        offers                   : liste brute de JobOffer
        min_score                : seuil minimum (défaut MIN_SCORE)
        alternance_only          : si True, garde uniquement les offres en alternance
        company_penalties        : {entreprise en minuscules: pénalité} issu du feedback (COM-13)
        extra_negative_keywords  : [(raison, pénalité), ...] issu du feedback (COM-13)

    Returns:
        Liste filtrée et triée, score rempli dans chaque JobOffer.
    """
    logger.info("Scoring de %d offres (seuil=%d)...", len(offers), min_score)

    for offer in offers:
        offer.score = score_offer(offer, company_penalties, extra_negative_keywords)
```

(the rest of `filter_offers`, from `before = len(offers)` onward, is unchanged.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd pipeline && ../.venv/Scripts/python.exe test_filter_feedback.py`
Expected: 6 `OK:` lines then `Tous les tests passent.`

Also re-run: `../.venv/Scripts/python.exe test_dedup.py` and `../.venv/Scripts/python.exe test_feedback.py` — expected: still pass (unchanged from Task 1).

- [ ] **Step 5: Commit**

```bash
git add pipeline/filter.py pipeline/test_filter_feedback.py
git commit -m "Apply feedback penalties in filter.py scoring (COM-13)"
```

---

### Task 4: Mailto link in the email template

**Files:**
- Modify: `notifier/formatter.py:1-87` (imports + `_format_offer`)
- Modify: `notifier/templates/email.html:32-33` (CSS)
- Create: `notifier/test_formatter_feedback.py`

**Interfaces:**
- Consumes: `os.getenv("SMTP_USER")` (already the pattern used in `notifier/mailer.py`).
- Produces: `_format_offer(offer)` now renders a second CTA link. No signature change — `render_email()`'s public interface is untouched, so nothing else needs to change to consume this.

- [ ] **Step 1: Write the failing test**

Create `notifier/test_formatter_feedback.py`:

```python
"""
Test du lien mailto "pas intéressé" dans notifier/formatter.py (COM-13).

Usage (depuis notifier/) :
    python test_formatter_feedback.py
"""

import sys, os
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from formatter import render_email
from sources.base_source import JobOffer


def _make_offer():
    return JobOffer(
        id="indeed_abc123", title="Alternance Data Analyst", company="ACME",
        location="Lille", description="...", url="https://example.com",
        source="Indeed", published_at=datetime.now(timezone.utc),
        contract_type="alternance", score=55.0,
    )


def test_mailto_link_present_with_smtp_user_configured():
    with patch.dict(os.environ, {"SMTP_USER": "alex@example.com"}):
        html = render_email([_make_offer()], ["Data Analyst"], ["59"])

    assert "mailto:alex@example.com" in html, html
    assert "%5BJob%20Pipeline%20Feedback%5D%20indeed_abc123" in html, html
    print("OK: test_mailto_link_present_with_smtp_user_configured")


def test_mailto_link_omitted_without_smtp_user():
    with patch.dict(os.environ, {}, clear=True):
        html = render_email([_make_offer()], ["Data Analyst"], ["59"])

    assert "mailto:" not in html, html
    print("OK: test_mailto_link_omitted_without_smtp_user")


def main():
    test_mailto_link_present_with_smtp_user_configured()
    test_mailto_link_omitted_without_smtp_user()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd notifier && ../.venv/Scripts/python.exe test_formatter_feedback.py`
Expected: `AssertionError` on the first test (no mailto link rendered yet)

- [ ] **Step 3: Modify `notifier/formatter.py`**

Replace the imports block (lines 1-16):

```python
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    from sources.base_source import JobOffer
except ImportError:
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), ".."))
    from sources.base_source import JobOffer
```

Add this helper function right after `_score_class` (after line 26):

```python
def _mailto_feedback_link(offer: JobOffer) -> str:
    """
    Lien mailto pré-rempli pour signaler 'pas intéressé' (COM-13). Retourne
    une chaîne vide si SMTP_USER n'est pas configuré (l'email reste
    utilisable sans ce lien).
    """
    smtp_user = os.getenv("SMTP_USER")
    if not smtp_user:
        return ""

    subject = quote(f"[Job Pipeline Feedback] {offer.id}")
    body = quote("Pas intéressé.\n\nRaison (optionnel) : ")
    return f"mailto:{smtp_user}?subject={subject}&body={body}"
```

In `_format_offer`, replace the final line (`return f"""... <a class="cta" ...>Voir l'offre →</a>\n    </div>"""`, currently the last statement of the function):

```python
    mailto = _mailto_feedback_link(offer)
    feedback_link = (
        f'<a class="cta cta-secondary" href="{mailto}">Pas intéressé</a>'
        if mailto else ""
    )

    return f"""
    <div class="offer">
      <div class="offer-top">
        <div>
          <h2>{offer.title}</h2>
          <p class="company">{offer.company}{pub_str}</p>
        </div>
        <span class="{badge_cls}">Score {offer.score:.0f}</span>
      </div>
      <div class="tags">
        {tags_html}
      </div>
      {desc_html}
      {skills_html}
      <a class="cta" href="{offer.url}" target="_blank">Voir l'offre →</a>
      {feedback_link}
    </div>"""
```

- [ ] **Step 4: Add the CSS class**

In `notifier/templates/email.html`, replace line 32-33:

```css
    .cta        { display: inline-block; background: #4F46E5; color: #fff !important;
                  text-decoration: none; padding: 8px 18px; border-radius: 6px; font-size: 13px; font-weight: 600; }
```

with:

```css
    .cta        { display: inline-block; background: #4F46E5; color: #fff !important;
                  text-decoration: none; padding: 8px 18px; border-radius: 6px; font-size: 13px; font-weight: 600; }
    .cta-secondary { background: transparent; color: #9CA3AF !important; border: 1px solid #E5E7EB;
                  margin-left: 8px; }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd notifier && ../.venv/Scripts/python.exe test_formatter_feedback.py`
Expected: 2 `OK:` lines then `Tous les tests passent.`

Also re-run `../.venv/Scripts/python.exe test_notifier.py` and open `email_preview.html` — expected: preview renders, with a greyed-out "Pas intéressé" link next to "Voir l'offre →" (only if `SMTP_USER` is set in your shell; otherwise the link is silently omitted, which is also correct).

- [ ] **Step 6: Commit**

```bash
git add notifier/formatter.py notifier/templates/email.html notifier/test_formatter_feedback.py
git commit -m "Add mailto feedback link to offer emails (COM-13)"
```

---

### Task 5: Wire feedback into `run.py`

**Files:**
- Modify: `run.py:31-35` (imports), `run.py:80-138` (pipeline steps 0-2)
- Modify: `.env.example`
- Create: `notifier/test_imap_feedback.py` (manual smoke script, real network, not part of automated suite)

**Interfaces:**
- Consumes: `FeedbackStore` (Task 1), `fetch_feedback_emails` (Task 2), `filter_offers(..., company_penalties=..., extra_negative_keywords=...)` (Task 3).

- [ ] **Step 1: Add the imports**

In `run.py`, replace lines 31-35:

```python
from sources.france_travail import FranceTravailSource
from sources.indeed import IndeedSource
from pipeline.filter import filter_offers
from pipeline.dedup import DedupStore
from notifier.mailer import EmailNotifier
```

with:

```python
from sources.france_travail import FranceTravailSource
from sources.indeed import IndeedSource
from pipeline.filter import filter_offers
from pipeline.dedup import DedupStore
from pipeline.feedback import FeedbackStore
from notifier.imap_feedback import fetch_feedback_emails
from notifier.mailer import EmailNotifier
```

- [ ] **Step 2: Add the feedback-reading step and wire penalties into scoring**

In `run.py`, replace the body of `run()` from line 85 (`# Dossier storage`) through line 138 (the closing of the `[2/5] Filtrage et scoring...` block) with:

```python
    # Dossier storage
    storage_dir = Path(__file__).parent / "storage"
    storage_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # 0. Lecture du feedback ("pas intéressé") reçu depuis le dernier run
    # ------------------------------------------------------------------
    logger.info("[1/6] Lecture du feedback...")
    # DedupStore instancié ici (avant FeedbackStore) pour garantir que la
    # table seen_offers existe déjà : FeedbackStore.record() la lit pour
    # résoudre l'entreprise associée à un offer_id.
    store = DedupStore()
    feedback_store = FeedbackStore()

    try:
        feedback_emails = fetch_feedback_emails()
        for fb in feedback_emails:
            feedback_store.record(fb.offer_id, fb.reason)
        logger.info("Feedback : %d email(s) traité(s)", len(feedback_emails))
    except Exception as e:
        logger.error("Erreur lecture feedback : %s", e)

    feedback_store.purge_old(days=DEDUP_PURGE_DAYS)
    company_penalties = feedback_store.get_company_penalties()
    extra_negative_keywords = feedback_store.get_negative_keywords()

    # ------------------------------------------------------------------
    # 1. Collecte
    # ------------------------------------------------------------------
    logger.info("[2/6] Collecte des offres...")
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
        _alert_failure(f"Erreur lors de la collecte France Travail : {e}")

    try:
        indeed = IndeedSource(
            keywords=KEYWORDS,
            locations=LOCATIONS,
        )
        indeed_offers = indeed.fetch()
        all_offers.extend(indeed_offers)
        logger.info("Indeed : %d offres", len(indeed_offers))
    except Exception as e:
        logger.error("Erreur Indeed : %s", e)
        _alert_failure(f"Erreur lors de la collecte Indeed : {e}")

    # Ici on pourra ajouter d'autres sources plus tard :
    # all_offers.extend(WTTJSource(...).fetch())

    if not all_offers:
        logger.warning("Aucune offre collectée. Fin du pipeline.")
        return

    logger.info("Total collecté : %d offres", len(all_offers))

    # ------------------------------------------------------------------
    # 2. Filtrage et scoring
    # ------------------------------------------------------------------
    logger.info("[3/6] Filtrage et scoring...")
    filtered = filter_offers(
        all_offers,
        min_score=MIN_SCORE,
        alternance_only=alternance_only,
        company_penalties=company_penalties,
        extra_negative_keywords=extra_negative_keywords,
    )
    logger.info("%d offres après filtrage (seuil=%d)", len(filtered), MIN_SCORE)

    if not filtered:
        logger.info("Aucune offre pertinente. Fin du pipeline.")
        return
```

- [ ] **Step 3: Renumber the remaining step log prefixes**

In `run.py`, the three remaining step headers need their prefixes bumped from `/5` to `/6` (position unchanged, count changed):

Replace this whole block (the `store = DedupStore()` call here is now redundant — `store` was already created in Step 2 above — so it's removed, not just the log prefix):

```python
    logger.info("[3/5] Déduplication...")
    store = DedupStore()

    if reset_dedup:
```

with:

```python
    logger.info("[4/6] Déduplication...")

    if reset_dedup:
```

Replace:
```python
    logger.info("[4/5] Envoi de l'alerte email...")
```
with:
```python
    logger.info("[5/6] Envoi de l'alerte email...")
```

Replace:
```python
    logger.info("[5/5] Marquage des offres...")
```
with:
```python
    logger.info("[6/6] Marquage des offres...")
```

- [ ] **Step 4: Add the optional `IMAP_HOST` variable to `.env.example`**

In `.env.example`, after the existing SMTP block, append:

```
# -------------------------------------------------------
# Feedback loop (COM-13) - optionnel, réutilise SMTP_USER/SMTP_PASSWORD
# -------------------------------------------------------
# IMAP_HOST=imap.gmail.com
```

- [ ] **Step 5: Create the manual smoke test script**

Create `notifier/test_imap_feedback.py`:

```python
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
```

- [ ] **Step 6: Run the automated test suites to confirm nothing broke**

Run each from the project root:

```bash
.venv/Scripts/python.exe pipeline/test_feedback.py
.venv/Scripts/python.exe pipeline/test_filter_feedback.py
.venv/Scripts/python.exe notifier/test_imap_feedback_parsing.py
.venv/Scripts/python.exe notifier/test_formatter_feedback.py
```

Expected: all print `Tous les tests passent.`

- [ ] **Step 7: Run the full pipeline dry-run**

Run: `.venv/Scripts/python.exe run.py --dry-run`
Expected: no unhandled traceback. Log lines should show `[1/6] Lecture du feedback...` through `[6/6] Marquage des offres...`, with `Feedback : 0 email(s) traité(s)` (or more, if there happen to be real unread feedback replies waiting) since there's no feedback yet on a fresh setup.

- [ ] **Step 8: Commit**

```bash
git add run.py .env.example notifier/test_imap_feedback.py
git commit -m "Wire feedback loop into run.py pipeline (COM-13)"
```

---

### Task 6: Full regression check

**Files:**
- None (verification only)

**Interfaces:**
- None.

- [ ] **Step 1: Run every automated test file**

Run each of these from the project root and confirm each prints `Tous les tests passent.` with no traceback:

```bash
.venv/Scripts/python.exe sources/test_http_retry.py
.venv/Scripts/python.exe sources/test_indeed_parsing.py
.venv/Scripts/python.exe sources/test_indeed_fetch.py
.venv/Scripts/python.exe notifier/test_failure_alert.py
.venv/Scripts/python.exe notifier/test_imap_feedback_parsing.py
.venv/Scripts/python.exe notifier/test_formatter_feedback.py
.venv/Scripts/python.exe pipeline/test_feedback.py
.venv/Scripts/python.exe pipeline/test_filter_feedback.py
```

(`pipeline/test_dedup.py` is known to fail on this machine due to a pre-existing console-encoding issue unrelated to this work — skip it, or run with `PYTHONIOENCODING=utf-8` prefixed if you want to double check.)

- [ ] **Step 2: Run the full pipeline dry-run once more**

Run: `.venv/Scripts/python.exe run.py --dry-run`
Expected: same as Task 5 Step 7 — no traceback, all 6 steps logged.

- [ ] **Step 3: Update the Linear issue and push**

Mark COM-13 as Done in Linear (team "job pipeline", project "job pipeline").

```bash
git push
```
