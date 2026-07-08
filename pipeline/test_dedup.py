"""
Test de dedup.py - Pas besoin de credentials, on utilise des offres fictives.

Usage (depuis pipeline/) :
    python test_dedup.py
"""

import sys, os, tempfile
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sources.base_source import JobOffer
from dedup import DedupStore


def make_offer(id: str, title: str) -> JobOffer:
    return JobOffer(
        id=id, title=title, company="Test SA", location="Lille",
        description="...", url="https://example.com", source="test",
        published_at=datetime.now(timezone.utc),
    )


def main():
    # Utilise un fichier temporaire pour ne pas polluer la vraie base
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    store = DedupStore(db_path=db_path)

    print("=" * 55)
    print("Test DedupStore")
    print("=" * 55)

    # Lot 1 : 4 offres nouvelles
    lot1 = [
        make_offer("ft_001", "Alternance Data Analyst"),
        make_offer("ft_002", "Apprenti Data Engineer"),
        make_offer("ft_003", "Junior Data Analyst"),
        make_offer("ft_004", "Data Consultant"),
    ]

    print(f"\n[Lot 1] {len(lot1)} offres entrantes")
    new1 = store.filter_new(lot1)
    print(f"  → {len(new1)} nouvelles (attendu : 4)")
    store.mark_seen(new1)
    print(f"  Base : {store.count()} entrée(s)")

    # Lot 2 : 2 offres déjà vues + 2 nouvelles
    lot2 = [
        make_offer("ft_001", "Alternance Data Analyst"),   # déjà vue
        make_offer("ft_002", "Apprenti Data Engineer"),    # déjà vue
        make_offer("ft_005", "Alternance Big Data"),       # nouvelle
        make_offer("ft_006", "Data Analyst Junior"),       # nouvelle
    ]

    print(f"\n[Lot 2] {len(lot2)} offres entrantes (2 déjà vues, 2 nouvelles)")
    new2 = store.filter_new(lot2)
    print(f"  → {len(new2)} nouvelles (attendu : 2)")
    assert len(new2) == 2, f"Erreur : attendu 2, obtenu {len(new2)}"
    assert new2[0].id == "ft_005"
    assert new2[1].id == "ft_006"
    store.mark_seen(new2)
    print(f"  Base : {store.count()} entrée(s)")

    # Test purge
    print(f"\n[Purge] Suppression des entrées > 0 jours (toutes)")
    deleted = store.purge_old(days=0)
    print(f"  → {deleted} entrée(s) supprimée(s)")
    print(f"  Base : {store.count()} entrée(s)")

    # Nettoyage (fermeture explicite avant suppression, nécessaire sur Windows)
    store._conn().close()
    import gc; gc.collect()
    db_path.unlink(missing_ok=True)

    print("\n" + "=" * 55)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()