"""
formatter.py - Mise en forme HTML des offres pour l'email d'alerte

Prend une liste de JobOffer et génère le HTML complet à injecter
dans le template email.html.
"""

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

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "email.html"


def _score_class(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return ""


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


def _format_offer(offer: JobOffer) -> str:
    """Génère le bloc HTML d'une seule offre."""

    # Tags metadata
    tags = []
    if offer.contract_type:
        tags.append(f'<span class="tag tag-contrat">{offer.contract_type}</span>')
    if offer.location:
        tags.append(f'<span class="tag tag-lieu">📍 {offer.location}</span>')
    if offer.remote and offer.remote != "none":
        label = "Télétravail total" if offer.remote == "full" else "Télétravail partiel"
        tags.append(f'<span class="tag tag-remote">🏠 {label}</span>')
    if offer.salary:
        tags.append(f'<span class="tag tag-salaire">💶 {offer.salary}</span>')
    tags.append(f'<span class="tag tag-source">{offer.source}</span>')
    tags_html = "\n        ".join(tags)

    # Description (tronquée à 300 caractères)
    desc = (offer.description or "").strip()
    if len(desc) > 300:
        desc = desc[:297] + "..."
    desc_html = f'<p class="description">{desc}</p>' if desc else ""

    # Compétences
    skills_html = ""
    if offer.skills:
        skill_items = "".join(
            f'<span class="skill">{s}</span>'
            for s in offer.skills[:8]
        )
        skills_html = f'<div class="skills">{skill_items}</div>'

    # Date de publication
    pub_str = ""
    if offer.published_at:
        if offer.published_at.tzinfo is None:
            offer.published_at = offer.published_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - offer.published_at).days
        pub_str = f" · Publiée il y a {age} jour(s)" if age > 0 else " · Publiée aujourd'hui"

    score_cls = _score_class(offer.score)
    badge_cls = f"score-badge {score_cls}".strip()

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


def render_email(
    offers: list[JobOffer],
    keywords: list[str],
    locations: list[str],
) -> str:
    """
    Génère le HTML complet de l'email à partir du template et des offres.

    Args:
        offers    : liste des offres à afficher (déjà filtrées et triées)
        keywords  : mots-clés utilisés pour la recherche
        locations : localisations utilisées

    Returns:
        Chaîne HTML complète prête à envoyer.
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    offers_html = "".join(_format_offer(o) for o in offers)
    date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    html = template
    html = html.replace("{{date}}", date_str)
    html = html.replace("{{nb_offers}}", str(len(offers)))
    html = html.replace("{{keywords}}", ", ".join(keywords))
    html = html.replace("{{locations}}", ", ".join(locations))
    html = html.replace("{{offers_html}}", offers_html)
    html = html.replace("{{unsubscribe_url}}", "#")

    # Gestion du bloc conditionnel {{#if offers}} ... {{else}} ... {{/if}}
    if offers:
        # Supprimer le bloc {{else}}...{{/if}}
        import re
        html = re.sub(
            r"\{\{#if offers\}\}(.*?)\{\{else\}\}.*?\{\{/if\}\}",
            r"\1",
            html,
            flags=re.DOTALL,
        )
    else:
        # Garder le bloc {{else}}
        import re
        html = re.sub(
            r"\{\{#if offers\}\}.*?\{\{else\}\}(.*?)\{\{/if\}\}",
            r"\1",
            html,
            flags=re.DOTALL,
        )

    return html