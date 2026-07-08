# job_pipeline

Pipeline de veille emploi automatisé : collecte les offres sur France Travail, les filtre et les score selon ton profil, et t'envoie une alerte email quotidienne avec les meilleures alternances data.

---

## Fonctionnement

```
France Travail API
       ↓
   fetcher        → collecte les offres brutes
       ↓
   filter.py      → score chaque offre (mots-clés, contrat, fraîcheur)
       ↓
   dedup.py       → écarte les offres déjà envoyées
       ↓
   mailer.py      → génère et envoie l'email HTML
       ↓
   dedup.mark     → marque les offres comme vues
```

---

## Structure

```
job_pipeline/
├── run.py                        # Point d'entrée principal
├── .env                          # Credentials (ne pas versionner)
├── .env.example                  # Modèle de configuration
│
├── sources/
│   ├── base_source.py            # Classe abstraite + dataclass JobOffer
│   ├── france_travail.py         # Connecteur API France Travail
│   ├── test_france_travail.py    # Test unitaire du connecteur
│   └── test_filter.py            # Test du scoring sur offres réelles
│
├── pipeline/
│   ├── filter.py                 # Scoring et filtrage des offres
│   ├── dedup.py                  # Déduplication via SQLite
│   ├── test_dedup.py             # Test unitaire de la déduplication
│
├── notifier/
│   ├── formatter.py              # Génération du HTML de l'email
│   ├── mailer.py                 # Envoi SMTP
│   ├── test_notifier.py          # Génère un aperçu HTML sans envoyer
│   └── templates/
│       └── email.html            # Template de l'email
│
├── storage/
│   ├── jobs.db                   # Base SQLite (créée automatiquement)
│   └── pipeline.log              # Logs d'exécution
│
└── scheduler/
    └── cron.sh                   # Script d'automatisation Linux/Mac
```

---

## Installation

### 1. Cloner et installer les dépendances

```bash
git clone <ton-repo>
cd job_pipeline
pip install requests python-dotenv
```

### 2. Créer le fichier `.env`

Copie `.env.example` en `.env` et remplis les valeurs :

```dotenv
# France Travail API
# Inscription gratuite sur https://francetravail.io
FT_CLIENT_ID=ton_client_id
FT_CLIENT_SECRET=ton_client_secret

# Email (Gmail recommandé avec mot de passe d'application)
# Mot de passe d'application : https://myaccount.google.com/apppasswords
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=ton.email@gmail.com
SMTP_PASSWORD=mot_de_passe_application
ALERT_RECIPIENT=destinataire@email.com
```

### 3. Configurer tes critères dans `run.py`

```python
KEYWORDS  = ["Data Analyst", "Big Data", "alternance data", "data engineer"]
LOCATIONS = ["59", "80"]   # Codes départements INSEE
MIN_SCORE       = 20       # Seuil de pertinence (0-100+)
ALTERNANCE_ONLY = True     # False pour inclure CDI/CDD pertinents
```

Les codes département courants : `59` Nord, `75` Paris, `69` Rhône, `80` Somme, `13` Bouches-du-Rhône, `33` Gironde.

---

## Utilisation

### Test à blanc (sans email, sans marquage)
```bash
python run.py --dry-run
```

### Exécution complète
```bash
python run.py
```

### Réinitialiser la déduplication (renvoie toutes les offres connues)
```bash
python run.py --reset-dedup
```

### Inclure les CDI/CDD en plus des alternances
```bash
python run.py --no-alternance
```

### Aperçu de l'email sans exécuter le pipeline
```bash
python notifier/test_notifier.py
# Ouvre email_preview.html dans ton navigateur
```

---

## Automatisation

### Windows — Planificateur de tâches

1. Ouvre le **Planificateur de tâches** (`taskschd.msc`)
2. Créer une tâche de base
3. Déclencheur : tous les jours à 08h00, du lundi au vendredi
4. Action : démarrer un programme
   - Programme : `python`
   - Arguments : `C:\Projets\job_pipeline\run.py`
   - Démarrer dans : `C:\Projets\job_pipeline`

### Linux / Mac — cron

```bash
crontab -e
# Ajouter cette ligne (exécution lundi-vendredi à 8h) :
0 8 * * 1-5 /chemin/vers/job_pipeline/scheduler/cron.sh
```

---

## Scoring des offres

Chaque offre reçoit un score calculé sur plusieurs critères :

| Critère | Points |
|---|---|
| Mot-clé "python" dans la description | +10 |
| Mot-clé "airflow" | +10 |
| Mot-clé "alternance" dans le texte | +25 |
| Mot-clé "apprentissage" | +25 |
| Contrat alternance/apprentissage | +30 |
| Contrat CDI | -5 |
| Télétravail total | +10 |
| Télétravail partiel | +5 |
| Offre publiée aujourd'hui | 0 |
| Offre publiée il y a 7-14 jours | -15 |
| Offre publiée il y a +30 jours | -40 |
| Mots négatifs ("directeur", "10 ans") | -15 à -30 |

Les offres sous le seuil `MIN_SCORE` (défaut 20) sont écartées. Avec `alternance_only=True`, seules les offres dont le titre ou le contrat contient "alternance", "apprentissage" ou "apprenti" sont conservées.

Pour ajuster les poids, modifie les constantes en haut de `pipeline/filter.py`.

---

## Ajouter une source

Pour ajouter Indeed, Welcome to the Jungle ou une autre plateforme, crée un fichier `sources/nom_source.py` qui hérite de `BaseSource` :

```python
from .base_source import BaseSource, JobOffer

class MaSource(BaseSource):

    @property
    def name(self) -> str:
        return "Ma Source"

    def fetch(self) -> list[JobOffer]:
        # Récupère les offres et retourne une liste de JobOffer
        ...
```

Puis ajoute-la dans `run.py` :

```python
from sources.ma_source import MaSource

ma_source = MaSource(keywords=KEYWORDS, locations=LOCATIONS)
all_offers.extend(ma_source.fetch())
```

---

## Dépendances

```
requests
python-dotenv
```

Toutes deux installables via `pip install requests python-dotenv`. Le reste (`sqlite3`, `smtplib`, `logging`) fait partie de la bibliothèque standard Python.

---

## Limitations connues

- France Travail ne renseigne pas toujours le champ télétravail, donc le filtre remote est peu fiable.
- Les descriptions d'offres sont parfois tronquées par l'API, ce qui peut faire baisser le score d'offres pourtant pertinentes.
- Le scraping Indeed/WTTJ n'est pas encore implémenté.