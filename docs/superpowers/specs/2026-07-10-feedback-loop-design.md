# Feedback loop sur le scoring (COM-13)

## Contexte

Les poids de scoring dans `pipeline/filter.py` (`TECH_KEYWORDS`, `CONTRACT_BONUS`, `NEGATIVE_KEYWORDS`...) sont des constantes figées, jamais ajustées à partir de l'usage réel.

Problème concret observé par Alex : le bonus alternance (+25 `TECH_KEYWORDS` pour le mot "alternance" + jusqu'à +30 `CONTRACT_BONUS` pour `contract_type` contenant "alternance") suffit à lui seul (+55) à faire passer une offre totalement hors-métier (ex. "Alternance Comptable") au-dessus du seuil `MIN_SCORE=20`, même sans aucun mot-clé technique et malgré le malus fraîcheur. `NEGATIVE_KEYWORDS` ne couvre aujourd'hui que des signaux de séniorité (`directeur`, `manager`, `responsable`, `X ans`), pas les domaines métier hors-cible (comptabilité, RH, marketing...) — il est impossible de lister à l'avance tous les domaines à exclure.

COM-13 vise un mécanisme simple pour capturer un retour d'Alex sur les offres reçues et l'utiliser pour affiner le scoring dans le temps.

## Contrainte d'architecture

Le pipeline tourne exclusivement en batch planifié (GitHub Actions, cron quotidien, cf. `.github/workflows/job_pipeline.yml`) et communique uniquement par email sortant (`notifier/mailer.py`, SMTP). Il n'existe aucun serveur web capable de recevoir un clic en temps réel (pas de hosting, pas de endpoint HTTP). Toute captation de feedback doit donc soit passer par un canal déjà existant (email), soit ajouter une nouvelle pièce d'infrastructure hébergée.

**Décision (validée par Alex) :** rester sur les canaux existants. Chaque offre dans l'email contient un lien `mailto:` ; Alex répond (ou non) depuis son client mail habituel ; le pipeline lit ces réponses par IMAP au run suivant, sur le même compte Gmail déjà utilisé pour l'envoi (mêmes identifiants `SMTP_USER`/`SMTP_PASSWORD` — un mot de passe d'application Gmail fonctionne aussi bien en IMAP qu'en SMTP). Zéro nouvelle infra, zéro nouveau secret. Contrepartie assumée : le feedback n'est pris en compte qu'au run suivant, pas en temps réel.

## Ce que le feedback change dans le scoring

Deux mécanismes, alimentés par le même geste (répondre "pas intéressé" à une offre) :

1. **Pénalité par entreprise** — si une entreprise reçoit ≥ 2 "pas intéressé" (tous motifs confondus), ses offres futures reçoivent un malus de -20. Seuil à 2 pour éviter qu'une seule offre mal ciblée d'une entreprise par ailleurs pertinente ne la pénalise injustement.
2. **Mots-clés négatifs appris** — le corps du mail de réponse contient une ligne pré-remplie `Raison (optionnel) : `. Si Alex tape un mot avant d'envoyer (ex. "comptabilité"), ce mot est ajouté aux mots-clés négatifs dès la première occurrence (signal volontaire et explicite d'Alex, pas besoin de répétition pour lui faire confiance), avec une pénalité de -40 — suffisant pour repasser sous `MIN_SCORE=20` une offre qui ne doit son score qu'au bonus alternance (55 pts : +25 mot-clé +30 contrat). *Correction post-implémentation (Task 3) : la valeur initialement documentée ici, -30, ne suffisait pas (55-30=25, toujours ≥ 20) — vérifié par calcul direct sur `pipeline/filter.py::score_offer`. Portée à -40 dans `pipeline/feedback.py::DEFAULT_KEYWORD_PENALTY`.*

Ces deux mécanismes sont indépendants et cumulables (un même feedback peut incrémenter le compteur entreprise ET ajouter un mot-clé négatif si une raison est fournie).

## Architecture

```
notifier/formatter.py     → ajoute le lien mailto dans chaque carte d'offre
        ↓ (email envoyé, Alex répond depuis son client mail)
notifier/imap_feedback.py → lit les réponses (IMAP), parse offer_id + raison
        ↓
pipeline/feedback.py      → FeedbackStore : persiste, calcule pénalités/mots-clés
        ↓
pipeline/filter.py        → score_offer()/filter_offers() appliquent les pénalités
```

`pipeline/filter.py` reste pur : il ne fait aucune I/O, il reçoit les pénalités déjà calculées en paramètres. C'est `run.py` qui orchestre la lecture IMAP, l'enregistrement, et le passage des pénalités au scoring — même pattern que l'orchestration existante des sources et de `DedupStore`.

## Composants

### `notifier/formatter.py` (modifié)

Dans `_format_offer(offer)`, ajout d'un second lien à côté de "Voir l'offre →" :

```python
mailto = (
    f"mailto:{SMTP_USER}"
    f"?subject={quote('[Job Pipeline Feedback] ' + offer.id)}"
    f"&body={quote('Pas intéressé.\n\nRaison (optionnel) : ')}"
)
```

`SMTP_USER` est lu depuis l'environnement (comme dans `mailer.py`) au moment du rendu ; si absent, le lien "pas intéressé" est simplement omis (dégradation silencieuse, l'email reste utilisable).

### `notifier/imap_feedback.py` (nouveau)

```python
@dataclass
class FeedbackEmail:
    offer_id: str
    reason: Optional[str]

def fetch_feedback_emails(
    host: str = None,   # défaut IMAP_HOST ou "imap.gmail.com"
    port: int = 993,
    user: str = None,   # défaut SMTP_USER
    password: str = None,  # défaut SMTP_PASSWORD
) -> list[FeedbackEmail]:
    ...
```

- Connexion IMAP SSL, recherche des mails `UNSEEN` dont le sujet contient `[Job Pipeline Feedback]`.
- Sujet parsé avec `r"\[Job Pipeline Feedback\]\s*(\S+)"` → `offer_id`.
- Corps parsé avec `r"raison\s*(?:\(optionnel\))?\s*:\s*(.+)"` (case-insensitive) → `reason` ; si le groupe capturé est vide ou égal au texte pré-rempli, `reason=None`.
- Chaque mail traité (offer_id trouvé ou non) est marqué `\Seen` pour ne jamais le retraiter en boucle. Un mail sans `offer_id` reconnaissable est ignoré (loggé en `warning`) mais marqué lu quand même.
- Toute exception (connexion IMAP, credentials manquants, timeout) est catchée : log `error`, retourne `[]`. Ne bloque jamais le run (même politique que `IndeedSource.fetch()`).

### `pipeline/feedback.py` (nouveau)

Mirroir de `pipeline/dedup.py` : même fichier SQLite (`storage/jobs.db`), nouvelle table.

```sql
CREATE TABLE IF NOT EXISTS feedback (
    offer_id    TEXT NOT NULL,
    company     TEXT,
    reason      TEXT,
    created_at  TEXT NOT NULL
)
```

```python
class FeedbackStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH): ...

    def record(self, offer_id: str, reason: Optional[str] = None):
        """Enregistre un feedback. Résout `company` via seen_offers (DedupStore)
        sur le même offer_id ; NULL si l'offre n'est plus en base (purgée)."""

    def get_company_penalties(self, threshold: int = 2, penalty: float = -20) -> dict[str, float]:
        """{company.lower(): penalty} pour chaque entreprise avec >= threshold feedbacks."""

    def get_negative_keywords(self, penalty: float = -40) -> list[tuple[str, float]]:
        """[(reason, penalty), ...] dédupliqué, pour chaque raison non vide distincte."""

    def purge_old(self, days: int = 60):
        """Même politique que DedupStore.purge_old, appelée depuis run.py."""
```

`record()` résout `company` par une requête directe sur la table `seen_offers` (celle de `DedupStore`) dans le même fichier `storage/jobs.db` — couplage assumé et documenté ici : les deux stores partagent la même base physique, `seen_offers` sert de source de vérité pour "quelle entreprise correspond à cet `offer_id`".

### `pipeline/filter.py` (modifié)

`score_offer()` et `filter_offers()` gagnent deux paramètres optionnels :

```python
def filter_offers(
    offers: list[JobOffer],
    min_score: float = MIN_SCORE,
    alternance_only: bool = False,
    company_penalties: dict[str, float] = None,
    extra_negative_keywords: list[tuple[str, float]] = None,
) -> list[JobOffer]:
```

- `company_penalties` : appliqué par égalité case-insensitive sur `offer.company` (pas de fuzzy matching — cf. Hors scope).
- `extra_negative_keywords` : chaque `(reason, penalty)` appliqué comme les entrées de `NEGATIVE_KEYWORDS` (`re.search` sur le texte complet), avec `re.escape(reason)` puisque le texte vient d'une saisie libre d'Alex et ne doit pas être interprété comme un pattern regex.
- Défauts à `None`/`{}` : comportement inchangé si le feedback loop n'a rien à appliquer (aucune régression sur le scoring existant).

### `run.py` (modifié)

Nouvelle étape 0, avant la collecte :

```python
logger.info("[0/5] Lecture du feedback...")
feedback_store = FeedbackStore()
try:
    for fb in fetch_feedback_emails():
        feedback_store.record(fb.offer_id, fb.reason)
    logger.info("Feedback : %d email(s) traité(s)", len(...))
except Exception as e:
    logger.error("Erreur lecture feedback : %s", e)
feedback_store.purge_old(days=DEDUP_PURGE_DAYS)
```

Étape 2 (scoring), pénalités injectées :

```python
filtered = filter_offers(
    all_offers,
    min_score=MIN_SCORE,
    alternance_only=alternance_only,
    company_penalties=feedback_store.get_company_penalties(),
    extra_negative_keywords=feedback_store.get_negative_keywords(),
)
```

Les étapes existantes (dédup, envoi, marquage) sont inchangées dans leur logique ; seuls les préfixes de log sont renumérotés de `[1/5]`..`[5/5]` à `[1/6]`..`[6/6]` pour inclure la nouvelle étape de lecture du feedback en première position.

## Gestion des erreurs

- IMAP indisponible/mal configuré : log + run continue sans feedback (dégradation silencieuse, pas d'`_alert_failure` — ce n'est pas critique comme une source d'offres qui tombe).
- Mail sans `offer_id` reconnaissable : ignoré, marqué lu.
- `offer_id` introuvable dans `seen_offers` (offre purgée entre-temps) : feedback quand même enregistré avec `company=NULL`, ignoré par `get_company_penalties()` mais toujours pris en compte par `get_negative_keywords()` si une raison est fournie.
- Raison contenant des caractères spéciaux regex : neutralisés via `re.escape()`.

## Tests

- `pipeline/test_feedback.py` : `FeedbackStore` sur SQLite temporaire (même pattern que `pipeline/test_dedup.py`), y compris résolution `company` via `seen_offers` et purge.
- `notifier/test_imap_feedback_parsing.py` : parsing sujet/corps sur des mails simulés (pas de vrai réseau, `imaplib` mocké), comme `sources/test_indeed_parsing.py`.
- `pipeline/test_filter.py` (existant, étendu) : nouveaux cas pour `company_penalties`/`extra_negative_keywords`, y compris le cas "alternance comptable" repassant sous le seuil.
- `notifier/test_imap_feedback.py` : script de smoke test manuel (vrai compte IMAP), comme `sources/test_indeed.py` — pas dans la suite automatisée.

## Hors scope

- Pas de fuzzy matching sur les noms d'entreprise (égalité case-insensitive stricte).
- Pas d'extraction automatique de mots-clés depuis le texte de l'offre si aucune raison n'est fournie (option écartée en brainstorming — trop de risque de faux positifs pour la valeur ajoutée, cf. discussion COM-13).
- Pas de décroissance dans le temps des mots-clés négatifs appris (contrairement à `seen_offers`/`feedback`, purgés à 60 jours, un mot-clé négatif appris reste actif tant que des entrées `feedback` récentes le portent).
- Pas d'ajustement automatique des poids de `TECH_KEYWORDS` eux-mêmes (le ticket l'évoquait comme piste ; la pénalité par mot-clé négatif appris atteint le même objectif — repousser les offres hors-cible sous le seuil — sans toucher aux poids positifs existants, plus simple et plus sûr).
