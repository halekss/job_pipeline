"""
filter.py - Scoring et filtrage des offres d'emploi

Chaque offre reçoit un score entre 0 et 100 basé sur :
  - La présence de mots-clés techniques dans le titre/description
  - Le type de contrat (alternance/apprentissage boosté)
  - Le télétravail
  - La fraîcheur de l'offre

Les offres sous le seuil MIN_SCORE sont écartées.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional

try:
    from sources.base_source import JobOffer
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from sources.base_source import JobOffer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration du scoring
# ---------------------------------------------------------------------------

# Seuil minimum pour conserver une offre (sur 100)
MIN_SCORE = 20

# Mots-clés techniques : (pattern, points)
# Les patterns sont insensibles à la casse et cherchent des mots entiers
TECH_KEYWORDS: list[tuple[str, float]] = [
    # Stack data core
    (r"python",             10),
    (r"sql",                 8),
    (r"power\s*bi",          8),
    (r"big\s*data",          8),
    (r"data\s*analyst",     10),
    (r"data\s*engineer",     8),
    (r"data\s*science",      7),
    # Outils présents sur le CV
    (r"airflow",            10),
    (r"docker",              8),
    (r"pandas",              8),
    (r"spark",               7),
    (r"kafka",               6),
    (r"dbt",                 6),
    (r"machine\s*learning",  6),
    (r"mlflow",              6),
    (r"tableau",             5),
    (r"looker",              5),
    (r"streamlit",           5),
    # Cloud / infra data
    (r"aws",                 5),
    (r"azure",               5),
    (r"gcp",                 5),
    (r"databricks",          6),
    (r"snowflake",           6),
    # Bonus alternance explicite dans le titre/description
    (r"alternance",         25),
    (r"apprentissage",      25),
    (r"apprenti",           20),
]

# Bonus contrat (appliqué sur le champ contract_type)
CONTRACT_BONUS: dict[str, float] = {
    "alternance":    30,
    "apprentissage": 30,
    "cdd":            3,
    "cdi":           -5,   # pénalité légère car on cherche de l'alternance
}

# Bonus télétravail
REMOTE_BONUS: dict[str, float] = {
    "full":    10,
    "partial":  5,
    "none":     0,
}

# Pénalité ancienneté (en jours → malus)
AGE_PENALTIES: list[tuple[int, float]] = [
    (3,  0),    # < 3 jours  : aucun malus
    (7,  5),    # 3-7 jours  : -5
    (14, 15),   # 7-14 jours : -15
    (30, 25),   # 14-30 jours: -25
    (999, 40),  # > 30 jours : -40
]

# Mots qui signalent une offre hors-cible (pénalité forte)
NEGATIVE_KEYWORDS: list[tuple[str, float]] = [
    (r"directeur",   30),
    (r"director",    30),
    (r"manager",     15),
    (r"responsable", 10),
    (r"10\s*ans",    20),
    (r"8\s*ans",     15),
]


# ---------------------------------------------------------------------------
# Fonctions de scoring
# ---------------------------------------------------------------------------

def _score_text(text: str) -> float:
    """Score les mots-clés positifs et négatifs dans un texte."""
    text_lower = text.lower()
    score = 0.0

    for pattern, points in TECH_KEYWORDS:
        if re.search(pattern, text_lower):
            score += points

    for pattern, penalty in NEGATIVE_KEYWORDS:
        if re.search(pattern, text_lower):
            score -= penalty

    return score


def _score_contract(contract_type: Optional[str]) -> float:
    """Bonus selon le type de contrat."""
    if not contract_type:
        return 0.0
    ct = contract_type.lower()
    for key, bonus in CONTRACT_BONUS.items():
        if key in ct:
            return bonus
    return 0.0


def _score_remote(remote: Optional[str]) -> float:
    """Bonus selon le télétravail."""
    return REMOTE_BONUS.get(remote or "none", 0.0)


def _score_freshness(published_at: Optional[datetime]) -> float:
    """Malus selon l'ancienneté de l'offre."""
    if not published_at:
        return -10  # date inconnue, léger malus

    now = datetime.now(timezone.utc)
    # S'assurer que published_at est timezone-aware
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    age_days = (now - published_at).days

    for threshold, penalty in AGE_PENALTIES:
        if age_days < threshold:
            return -penalty

    return -AGE_PENALTIES[-1][1]


def score_offer(offer: JobOffer) -> float:
    """
    Calcule et retourne le score total d'une offre (0-100, peut dépasser).

    Le score est la somme de :
      - mots-clés dans titre + description
      - bonus type de contrat
      - bonus télétravail
      - malus ancienneté
    """
    full_text = f"{offer.title} {offer.description} {' '.join(offer.skills)}"

    text_score     = _score_text(full_text)
    contract_score = _score_contract(offer.contract_type)
    remote_score   = _score_remote(offer.remote)
    freshness_score = _score_freshness(offer.published_at)

    total = text_score + contract_score + remote_score + freshness_score
    return round(max(0.0, total), 1)


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

# Mots indiquant une alternance dans le type de contrat ou le titre
ALTERNANCE_MARKERS = ["alternance", "apprentissage", "apprenti", "apprenticeship"]


def _is_alternance(offer: JobOffer) -> bool:
    """Retourne True si l'offre est clairement une alternance."""
    ct = (offer.contract_type or "").lower()
    title = offer.title.lower()
    return any(m in ct or m in title for m in ALTERNANCE_MARKERS)


def filter_offers(
    offers: list[JobOffer],
    min_score: float = MIN_SCORE,
    alternance_only: bool = False,
) -> list[JobOffer]:
    """
    Score toutes les offres, écarte celles sous le seuil, trie par score décroissant.

    Args:
        offers          : liste brute de JobOffer
        min_score       : seuil minimum (défaut MIN_SCORE)
        alternance_only : si True, garde uniquement les offres en alternance

    Returns:
        Liste filtrée et triée, score rempli dans chaque JobOffer.
    """
    logger.info("Scoring de %d offres (seuil=%d)...", len(offers), min_score)

    for offer in offers:
        offer.score = score_offer(offer)

    before = len(offers)
    filtered = [o for o in offers if o.score >= min_score]

    if alternance_only:
        filtered = [o for o in filtered if _is_alternance(o)]
        logger.info("Filtre alternance_only : %d offres conservées.", len(filtered))

    filtered.sort(key=lambda o: o.score, reverse=True)

    logger.info(
        "%d offres conservées sur %d (seuil=%d)",
        len(filtered), before, min_score
    )
    return filtered