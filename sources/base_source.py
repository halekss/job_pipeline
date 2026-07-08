from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class JobOffer:
    """Format normalisé d'une offre d'emploi, quelle que soit la source."""
    id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    contract_type: Optional[str] = None   # CDI, CDD, alternance...
    remote: Optional[str] = None          # "full", "partial", "none"
    salary: Optional[str] = None
    skills: list[str] = field(default_factory=list)
    score: float = 0.0                    # rempli par filter.py

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "contract_type": self.contract_type,
            "remote": self.remote,
            "salary": self.salary,
            "skills": self.skills,
            "score": self.score,
        }


class BaseSource(ABC):
    """Interface commune à tous les connecteurs de sources d'offres."""

    def __init__(self, keywords: list[str], locations: list[str]):
        self.keywords = keywords
        self.locations = locations

    @abstractmethod
    def fetch(self) -> list[JobOffer]:
        """Récupère les offres et les retourne au format normalisé JobOffer."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom lisible de la source (ex: 'France Travail')."""
        ...