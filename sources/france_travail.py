"""
Connecteur France Travail (ex Pôle Emploi)
API officielle : https://francetravail.io/data/api/offres-emploi

Inscription gratuite sur https://francetravail.io pour obtenir
un CLIENT_ID et CLIENT_SECRET.

Variables d'env requises :
    FT_CLIENT_ID
    FT_CLIENT_SECRET
"""

import os
import logging
import requests
from datetime import datetime
from typing import Optional

try:
    from .base_source import BaseSource, JobOffer
except ImportError:
    from base_source import BaseSource, JobOffer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes API
# ---------------------------------------------------------------------------
AUTH_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"

# Codes ROME utiles pour profils Data / Big Data
ROME_DATA = [
    "M1805",  # Études et développement informatique
    "M1802",  # Expertise et support en systèmes d'information
    "M1803",  # Direction des systèmes d'information
]

# Mapping télétravail API → format interne
REMOTE_MAP = {
    "1": "none",
    "2": "partial",
    "3": "full",
}


class FranceTravailSource(BaseSource):
    """
    Récupère les offres via l'API officielle France Travail.

    L'authentification utilise le flux client_credentials (OAuth2).
    Le token est mis en cache pour la durée de vie de l'instance.
    """

    def __init__(self, keywords: list[str], locations: list[str],
                 client_id: Optional[str] = None,
                 client_secret: Optional[str] = None,
                 max_results: int = 100):
        super().__init__(keywords, locations)
        self.client_id = client_id or os.getenv("FT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("FT_CLIENT_SECRET")
        self.max_results = max_results
        self._token: Optional[str] = None

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "FT_CLIENT_ID et FT_CLIENT_SECRET sont requis. "
                "Crée un compte sur https://francetravail.io"
            )

    @property
    def name(self) -> str:
        return "France Travail"

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Obtient (ou réutilise) un token OAuth2 client_credentials."""
        if self._token:
            return self._token

        resp = requests.post(
            AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if not resp.ok:
            raise ValueError(
                f"Erreur auth {resp.status_code} : {resp.text}"
            )
        self._token = resp.json()["access_token"]
        logger.debug("Token France Travail obtenu.")
        return self._token

    # ------------------------------------------------------------------
    # Récupération des offres
    # ------------------------------------------------------------------

    def fetch(self) -> list[JobOffer]:
        """Point d'entrée principal : collecte toutes les offres."""
        token = self._get_token()
        offers: list[JobOffer] = []

        for location in self.locations:
            for keyword in self.keywords:
                batch = self._fetch_batch(token, keyword, location)
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

    def _fetch_batch(self, token: str, keyword: str, location: str) -> list[JobOffer]:
        """Appelle l'API pour un couple (keyword, location) et retourne les offres."""
        params = self._build_params(keyword, location)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(
                SEARCH_URL,
                params=params,
                headers=headers,
                timeout=15,
            )

            if resp.status_code not in (200, 206):
                logger.warning(
                    "[%s] Réponse inattendue %d pour '%s' / '%s' : %s",
                    self.name, resp.status_code, keyword, location, resp.text[:200]
                )
                return []

            data = resp.json()
            raw_offers = data.get("resultats", [])
            return [self._normalize(o) for o in raw_offers]

        except requests.RequestException as e:
            logger.error("[%s] Erreur réseau : %s", self.name, e)
            return []

    def _build_params(self, keyword: str, location: str) -> dict:
        """Construit les paramètres de recherche de l'API.

        L'API France Travail attend :
        - departement : code département sur 2 chiffres (ex: "59" pour le Nord)
        - commune     : code INSEE commune sur 5 chiffres (ex: "59350" pour Lille)
        - On évite le libellé qui n'est pas accepté.
        """
        params: dict = {
            "motsCles": keyword,
            "nbResultats": min(self.max_results, 150),
        }

        # Si c'est un code département (2 chiffres) → departement
        # Si c'est un code INSEE commune (5 chiffres) → commune
        # Sinon on cherche dans le département via le mapping
        DEPT_MAP = {
            "lille": "59",
            "amiens": "80",
            "paris": "75",
            "lyon": "69",
            "marseille": "13",
            "bordeaux": "33",
            "toulouse": "31",
            "nantes": "44",
            "remote": None,
            "télétravail": None,
        }

        loc = location.strip()
        if loc.isdigit() and len(loc) == 2:
            params["departement"] = loc
        elif loc.isdigit() and len(loc) == 5:
            params["commune"] = loc
        elif loc.lower() in DEPT_MAP:
            dept = DEPT_MAP[loc.lower()]
            if dept:
                params["departement"] = dept
        # remote/télétravail : pas de filtre géographique, on laisse vide

        # Pas de filtre ROME ni natureContrat pour maximiser les résultats
        # Ces filtres seront appliqués par filter.py avec le scoring

        return params

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalize(self, raw: dict) -> JobOffer:
        """Convertit une offre brute de l'API au format interne JobOffer."""

        published_at = None
        date_str = raw.get("dateCreation") or raw.get("dateActualisation")
        if date_str:
            try:
                published_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        lieu = raw.get("lieuTravail", {})
        location = lieu.get("libelle", "Non précisé")

        context = raw.get("contexteTravail", {})
        remote = REMOTE_MAP.get(str(context.get("presenceTeleTravail", "")))

        competences = raw.get("competences", [])
        skills = [c.get("libelle", "") for c in competences if c.get("libelle")]

        salaire = raw.get("salaire", {})
        salary_str = salaire.get("libelle")

        type_contrat = raw.get("typeContratLibelle") or raw.get("typeContrat")

        entreprise = raw.get("entreprise", {})
        company = entreprise.get("nom") or "Entreprise non communiquée"

        return JobOffer(
            id=f"ft_{raw.get('id', '')}",
            title=raw.get("intitule", "Sans titre"),
            company=company,
            location=location,
            description=raw.get("description", ""),
            url=raw.get("origineOffre", {}).get("urlOrigine")
                or f"https://candidat.francetravail.fr/offres/recherche/detail/{raw.get('id', '')}",
            source=self.name,
            published_at=published_at,
            contract_type=type_contrat,
            remote=remote,
            salary=salary_str,
            skills=skills,
        )