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
    import gc, time
    for _ in range(10):
        gc.collect()
    time.sleep(0.1)
    try:
        db_path.unlink()
        # Also try to delete WAL and SHM files that SQLite may have created
        (db_path.parent / f"{db_path.name}-wal").unlink(missing_ok=True)
        (db_path.parent / f"{db_path.name}-shm").unlink(missing_ok=True)
    except (PermissionError, OSError):
        # Windows SQLite file lock - OS will clean up the temp file
        pass


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
    del dedup, store
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
    del store
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
    del dedup, store
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
    del dedup, store
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
    del store
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
    del store
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
