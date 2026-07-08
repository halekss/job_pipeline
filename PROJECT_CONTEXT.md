# PROJECT_CONTEXT.md — job_pipeline

Ce fichier sert de mémoire de reprise pour continuer le projet dans une nouvelle conversation avec Claude.

---

## Qui, quoi, où

Alex, profil data/Big Data en reconversion, étudiant à Epitech Lille (alternance Big Data 2026), cherche un contrat d'alternance dans le Nord (59) principalement, ouvert à Paris (75), Lyon (69), et au remote.

Projet : `C:\Projets\job_pipeline`, Windows, Python 3.13, terminal Git Bash.

But : automatiser entièrement la recherche d'alternance — collecte des offres, scoring de pertinence, déduplication, alerte email quotidienne. Étape suivante envisagée : génération automatique de lettres de motivation adaptées par offre.

---

## État actuel : fonctionnel de bout en bout

Le pipeline tourne en local, déclenché manuellement ou via le Planificateur de tâches Windows. Reçoit déjà de vraies alertes email avec de vraies offres pertinentes (testé et confirmé par Alex).

### Arborescence

```
job_pipeline/
├── run.py                        # Orchestrateur principal, CLI --dry-run / --reset-dedup / --no-alternance
├── .env                          # Credentials (FT_CLIENT_ID, FT_CLIENT_SECRET, SMTP_*)
├── .env.example
├── README.md                     # Doc complète installation/usage
│
├── sources/
│   ├── base_source.py            # JobOffer (dataclass) + BaseSource (ABC)
│   ├── france_travail.py         # Connecteur API France Travail (OAuth2 client_credentials)
│   ├── test_france_travail.py
│   └── test_filter.py
│
├── pipeline/
│   ├── filter.py                 # score_offer(), filter_offers(min_score, alternance_only)
│   ├── dedup.py                  # DedupStore (SQLite) : filter_new(), mark_seen(), purge_old(), reset()
│   └── test_dedup.py
│
├── notifier/
│   ├── formatter.py               # render_email() → HTML
│   ├── mailer.py                  # EmailNotifier.send() via smtplib
│   ├── test_notifier.py           # génère email_preview.html sans envoyer
│   └── templates/email.html
│
├── storage/
│   ├── jobs.db                    # SQLite, créée automatiquement
│   └── pipeline.log
│
└── scheduler/
    └── cron.sh                    # pour Linux/Mac, non utilisé actuellement (Alex est sur Windows)
```

### Config actuelle dans `run.py`

```python
KEYWORDS  = ["Data Analyst", "Big Data", "alternance data", "data engineer", "remote", "télétravail"]
LOCATIONS = ["59", "80", "69"]   # Nord, Somme, Rhône
MIN_SCORE       = 20
ALTERNANCE_ONLY = True
DEDUP_PURGE_DAYS = 60
```

### Email : Gmail comme expéditeur

Outlook/hotmail.fr a posé trop de problèmes d'authentification SMTP (essayé `smtp.office365.com` et `smtp-mail.outlook.com`, tous deux en échec malgré mot de passe d'application généré). Solution retenue : envoyer via un compte Gmail (`SMTP_HOST=smtp.gmail.com`), avec `ALERT_RECIPIENT=alex_2c@hotmail.fr` pour recevoir sur l'adresse habituelle. Fonctionne.

---

## Apprentissages clés (à ne pas refaire)

### France Travail API
- URL d'auth correcte : `https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire` (le `?realm=%2Fpartenaire` est obligatoire, sinon 400 `invalid_client`)
- Scope obligatoire : `api_offresdemploiv2 o2dsoffre` (sans lui : 400 `invalid_scope`)
- Paramètre de localisation : `departement` (2 chiffres, ex `"59"`) ou `commune` (code INSEE 5 chiffres). **Jamais de libellé** comme `"Lille"` → 400 `Valeur du paramètre commune incorrecte`
- Combiner `codeROME` + `natureContrat=E2` dans la même requête → 0 résultat systématique. Ces filtres ont été retirés de `_build_params()`, le filtrage se fait maintenant entièrement côté `filter.py` après récupération
- HTTP 204 = succès sans résultat, pas une erreur
- Max 150 résultats par requête (`nbResultats`)

### Windows / Git Bash
- `email.py` est un nom interdit (conflit avec le module stdlib) → renommé `mailer.py`
- Les imports relatifs (`from .base_source import`) cassent si le script est lancé directement (`python fichier.py`) plutôt qu'importé comme module. Pattern utilisé partout : `try: from .x import Y / except ImportError: from x import Y`
- `Path(__file__).parent` peut produire des chemins avec `..` redondants selon comment le script est lancé → toujours utiliser `.resolve()` après `.parent`
- SQLite garde le fichier verrouillé même après usage en `with` ; sur Windows, `unlink()` juste après échoue. Fermer explicitement la connexion + `gc.collect()` avant suppression dans les tests

### Scoring (`pipeline/filter.py`)
- Bonus alternance/apprentissage : 25 pts dans `TECH_KEYWORDS`, +30 pts dans `CONTRACT_BONUS`. CDI : -5 pts (pénalité légère, pas exclusion)
- `alternance_only=True` filtre dur sur titre/contrat contenant alternance/apprentissage/apprenti — c'est ce qui est actif par défaut
- Une offre CDI très riche techniquement (ex. MONDIAL RELAY, score 106) peut dépasser une alternance moins riche en mots-clés (score 60) si on ne filtre pas en dur — normal et accepté, le filtre dur règle ça

### Limites connues, non résolues
- Champ `remote` souvent `None` car France Travail ne le renseigne pas systématiquement → le mot-clé `"télétravail"`/`"remote"` dans la recherche texte est un palliatif, pas un vrai filtre géographique
- Descriptions parfois tronquées par l'API → peut faire sous-scorer des offres pertinentes
- Scraping Indeed et Welcome to la Jungle jamais implémenté (prévu dans l'architecture initiale, abandonné en cours de route faute de temps, France Travail API a suffi)

---

## Pistes pour la suite (non démarrées)

1. **Lettre de motivation automatique** adaptée par offre, probablement via l'API Claude (Alex a un compte Anthropic) avec un prompt template injectant titre/entreprise/description de l'offre + le CV d'Alex
2. **Hébergement cloud** pour ne plus dépendre du PC allumé. Pistes évoquées : GitHub Actions avec workflow `cron` (gratuit, tourne même PC éteint, probablement la meilleure option pour Alex), Oracle Cloud Free Tier, PythonAnywhere
3. **Connecteurs Indeed / WTTJ** si l'API France Travail seule ne suffit pas en couverture
4. **Dashboard Streamlit** comme alternative/complément à l'email, pour visualiser les offres scorées dans le temps

---

## CV d'Alex (résumé pour personnalisation future)

Data Analyst Junior en reconversion. Formation : Maîtrise Big Data Epitech Lille (10/2026), Data Analyst RNCP6 Wild Code School (09/2025-02/2026), DUT GMO Amiens. Stack : Python, SQL, Power BI, Pandas, NumPy, Seaborn, API REST, Machine Learning, Airflow, Docker. Projets perso notables : "Oracle des Loyers" (scraping + carte React + chatbot LLM, Airflow/Docker), "Senechal Movie" (système de recommandation sur 7M de films, Streamlit), "Toys & Models" (dashboard Power BI/SQL). Expérience antérieure : 4 ans conseiller en insertion professionnelle chez France Travail (donne une légitimité particulière à utiliser leur API). Permis B véhiculé, anglais opérationnel (séjour 5 mois en Australie).
