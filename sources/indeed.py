"""
Connecteur Indeed (scraping public, sans compte).

Utilise scrapling.fetchers.Fetcher pour imiter l'empreinte d'un vrai
navigateur sans lancer un navigateur complet. Cf.
docs/superpowers/specs/2026-07-08-indeed-connector-design.md pour le
contexte et les alternatives évaluées (dont l'abandon de Welcome to the
Jungle, passé en 2026 à un système de matching nécessitant un compte).
"""

import logging
from typing import Optional

from scrapling.fetchers import Fetcher

try:
    from .base_source import BaseSource, JobOffer
except ImportError:
    from base_source import BaseSource, JobOffer

try:
    from .http_retry import _request_with_retry
except ImportError:
    from http_retry import _request_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://fr.indeed.com"
SEARCH_URL = f"{BASE_URL}/jobs"

# Indeed attend un nom de ville/code postal dans son paramètre `l`, pas un
# code département comme France Travail. Mapping pour les départements déjà
# utilisés dans LOCATIONS (run.py) ; sinon la valeur est passée telle quelle.
LOCATION_LABELS = {
    "59": "Lille",
    "80": "Amiens",
    "69": "Lyon",
    "75": "Paris",
}

CONTRACT_KEYWORDS = (
    "alternance", "apprentissage", "apprenti", "stage",
    "cdi", "cdd", "intérim", "contrat",
)


def _extract_contract_type(metadata: list[str]) -> Optional[str]:
    """Retourne le premier badge de métadonnées qui ressemble à un type de contrat."""
    for item in metadata:
        if any(keyword in item.lower() for keyword in CONTRACT_KEYWORDS):
            return item
    return None


def _parse_results(page) -> list[JobOffer]:
    """
    Parse une page de résultats Indeed (Selector ou réponse scrapling,
    les deux exposent .css()/.xpath()) en liste de JobOffer.
    """
    offers = []
    for card in page.css(".job_seen_beacon"):
        job_id = card.css("a[data-jk]::attr(data-jk)").get()
        if not job_id:
            continue

        title = (card.css("h3.jobTitle span::text").get("") or "").strip()
        company = (card.css('[data-testid="company-name"]::text').get("") or "").strip()
        location = (card.css('[data-testid="text-location"]::text').get("") or "").strip()
        salary = card.css('li[data-testid~="salary-snippet-container"] span::text').get()
        metadata = [
            m.strip()
            for m in card.css(
                'li[data-testid~="attribute_snippet_testid"]:not(.salary-snippet-container) span::text'
            ).getall()
            if m.strip()
        ]
        highlights = card.xpath("following-sibling::ul[1]//li/text()").getall()

        offers.append(JobOffer(
            id=f"indeed_{job_id}",
            title=title or "Sans titre",
            company=company or "Entreprise non communiquée",
            location=location or "Non précisé",
            description=" ".join(h.strip() for h in highlights if h.strip()),
            url=f"{BASE_URL}/viewjob?jk={job_id}",
            source="Indeed",
            published_at=None,
            contract_type=_extract_contract_type(metadata),
            remote=None,
            salary=salary,
            skills=[],
        ))
    return offers


class IndeedSource(BaseSource):
    """Récupère les offres via scraping public d'Indeed (sans compte)."""

    @property
    def name(self) -> str:
        return "Indeed"

    def fetch(self) -> list[JobOffer]:
        """Point d'entrée principal : collecte toutes les offres."""
        offers: list[JobOffer] = []

        for location in self.locations:
            for keyword in self.keywords:
                batch = self._fetch_batch(keyword, location)
                offers.extend(batch)
                logger.info(
                    "[%s] %d offres pour '%s' à '%s'",
                    self.name, len(batch), keyword, location
                )

        # Déduplication immédiate par id dans cette source
        seen: set[str] = set()
        unique = []
        for o in offers:
            if o.id not in seen:
                seen.add(o.id)
                unique.append(o)

        logger.info("[%s] %d offres uniques récupérées.", self.name, len(unique))
        return unique

    def _fetch_batch(self, keyword: str, location: str) -> list[JobOffer]:
        """Appelle Indeed pour un couple (keyword, location) et retourne les offres."""
        params = self._build_params(keyword, location)

        try:
            resp = _request_with_retry(
                lambda: Fetcher.get(
                    SEARCH_URL,
                    params=params,
                    stealthy_headers=True,
                    impersonate="chrome",
                    timeout=15,
                ),
                status_getter=lambda r: r.status,
                exception_types=(Exception,),
            )

            if resp.status != 200:
                logger.warning(
                    "[%s] Réponse inattendue %d pour '%s' / '%s'",
                    self.name, resp.status, keyword, location,
                )
                return []

            return _parse_results(resp)

        except Exception as e:
            logger.error("[%s] Erreur réseau (après tentatives) : %s", self.name, e)
            return []

    def _build_params(self, keyword: str, location: str) -> dict:
        """Construit les paramètres de recherche (q=mots-clés, l=localisation)."""
        loc = location.strip()
        label = LOCATION_LABELS.get(loc, loc)
        return {"q": keyword, "l": label}
