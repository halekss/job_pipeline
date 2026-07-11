# Connecteur Indeed (COM-9)

## Contexte

Le pipeline ne collecte les offres que via l'API France Travail. COM-9 visait à l'origine deux connecteurs supplémentaires (Indeed, Welcome to the Jungle). L'exploration de WTTJ a montré qu'ils sont passés en 2026 à un système de "matching" nécessitant un compte connecté avec profil complet, sans recherche mots-clés publique — cette piste est abandonnée pour l'instant (voir décision ci-dessous). Ce document couvre uniquement **Indeed**.

## Décision : pourquoi pas WTTJ

Vérifié en direct (Playwright + recherche web, 2026-07-08) :
- `welcometothejungle.com/fr/jobs?query=...` ignore les paramètres de recherche et affiche une landing page générique.
- Voir des offres pertinentes nécessite un compte connecté ; l'algorithme de matching réduit volontairement le volume de résultats visibles ([Maddyness, avril 2026](https://www.maddyness.com/2026/04/15/welcome-to-the-jungle-change-de-braquet-pour-se-reinventer-sur-un-marche-du-recrutement-bouleverse-par-lia/)).
- Sans compte, seul le parcours par entreprise individuelle reste public — pas de recherche globale par mots-clés/localisation.

Construire un connecteur WTTJ demanderait d'automatiser une connexion avec le compte personnel d'Alex, ce qui est plus fragile et plus intrusif que le modèle "recherche publique" des autres sources. Reporté (piste à réévaluer si WTTJ rouvre une recherche publique, ou si Alex veut explicitement automatiser son compte).

## Vérifications techniques sur Indeed

Vérifié en direct (WebFetch + Playwright, 2026-07-08) :
- `fr.indeed.com/jobs?q=...&l=...` reste accessible sans compte et retourne une recherche mots-clés/localisation fonctionnelle.
- Le HTML brut (avant exécution JavaScript) contient déjà les offres complètes (titre, entreprise, lieu, salaire, type de contrat) — pas besoin de rendu client, un simple client HTTP suffit côté parsing.
- Risque connu : Indeed détecte agressivement le scraping automatisé, en particulier depuis des IP de datacenter (GitHub Actions). Le connecteur peut fonctionner en test local et être bloqué une fois en prod. **Risque accepté par Alex** : si ça casse, l'alerte d'échec (COM-6) le signalera, à réévaluer à ce moment-là.

## Approche retenue

Bibliothèque `scrapling`, via `Fetcher.get(url, params=..., stealthy_headers=True, impersonate="chrome")` : un client HTTP qui imite l'empreinte d'un vrai navigateur (via `curl_cffi`) sans lancer de navigateur complet. Choisie plutôt que :
- `requests` brut : empreinte TLS/en-têtes trivialement identifiable comme non-navigateur, bloqué plus vite.
- Playwright (navigateur headless complet) : plus robuste contre la détection mais coût CI nettement plus élevé (installation de Chromium, ~1-2 min et ~300 Mo par run) et éloigné du style du reste du pipeline. Escalade possible plus tard via `scrapling.fetchers.StealthyFetcher` (même librairie) si `Fetcher.get` s'avère insuffisant en pratique — non implémenté maintenant (YAGNI).

`scrapling` était déjà présent (à l'état de résidu) dans l'environnement Python du projet avant le nettoyage de `requirements.txt`, signe que ce besoin avait déjà été anticipé.

## Architecture

Nouveau `sources/indeed.py::IndeedSource(BaseSource)`, même structure que `FranceTravailSource` :
- `fetch()` boucle sur `keywords × locations`, appelle `_fetch_batch()` par combinaison, déduplique par id à l'intérieur de la source, retourne une liste de `JobOffer`.
- `_fetch_batch(keyword, location)` appelle `Fetcher.get(SEARCH_URL, params={"q": keyword, "l": location}, stealthy_headers=True, impersonate="chrome", timeout=15)`, passé dans `_request_with_retry`.
- `_normalize(card)` parse chaque carte d'offre (sélecteurs CSS via `page.css(...)`) vers `JobOffer` : id préfixé `indeed_...`, titre, entreprise, lieu, description, url, type de contrat si visible. La date de publication n'est pas toujours exposée par Indeed dans le listing ; si absente, `published_at=None` (le scoring existant applique déjà un malus léger de -10 pour date inconnue via `_score_freshness`, comportement inchangé).

## Refactor ciblé : retry partagé

`_request_with_retry` (ajoutée en COM-7) vit actuellement dans `sources/france_travail.py` et suppose `response.status_code` (attribut de la lib `requests`). `scrapling` expose `response.status` (nom différent). Plutôt que dupliquer la logique de retry pour Indeed, `_request_with_retry` est déplacée vers `sources/http_retry.py`, partagée entre les deux connecteurs, avec un paramètre `status_getter: Callable[[Response], int] = lambda r: r.status_code` pour s'adapter aux deux formats. Comportement inchangé pour France Travail ; les tests existants (`sources/test_retry.py`) sont déplacés/adaptés en conséquence.

## Flux de données

Identique au pipeline existant — c'est l'intérêt de l'abstraction `BaseSource`. Dans `run.py`, `IndeedSource(...)` est ajoutée à côté de `FranceTravailSource`, dans son propre bloc `try/except` suivant exactement le pattern existant (log + `_alert_failure` de COM-6 en cas d'exception). Les offres rejoignent ensuite `filter_offers` / `DedupStore` / `EmailNotifier` sans aucune modification de ces modules.

## Gestion des erreurs

- Erreurs réseau/HTTP transitoires : `_request_with_retry` (3 tentatives, backoff exponentiel) — même politique que France Travail.
- Blocage persistant (403/429 après épuisement des tentatives, ou page de challenge anti-bot) : log `warning`, le batch retourne une liste vide, le run continue avec les autres sources et les autres combinaisons keyword/location. Un blocage partiel d'Indeed ne doit pas empêcher l'envoi de l'email avec les offres France Travail.
- Si `IndeedSource.fetch()` lève une exception non gérée : capturée dans `run.py` exactement comme pour France Travail, déclenche l'alerte email COM-6 (Alex est prévenu si Indeed cesse de fonctionner silencieusement).

## Tests (TDD)

- `sources/test_http_retry.py` : tests de retry déplacés depuis `test_retry.py` et généralisés (couvre `.status_code` et `.status` via `status_getter`).
- `sources/test_indeed_parsing.py` : tests de `_normalize()`/parsing sur un fixture HTML sauvegardé localement (pas d'appel réseau réel dans les tests automatisés, cohérent avec les conventions existantes de `test_dedup.py`).
- `sources/test_indeed.py` : script de vérification manuelle sur le vrai site (même esprit que `test_france_travail.py`), pas dans la suite automatisée, credentials/réseau réel.
- `requirements.txt` : ajout de `scrapling`.
- Vérification finale : `run.py --dry-run` réel pour confirmer le câblage bout en bout, comme pour COM-6/COM-7.

## Hors scope

- Connecteur WTTJ (reporté, voir Décision ci-dessus).
- Pagination au-delà de la première page de résultats Indeed (hors scope, comme la pagination France Travail dans COM-12).

## Addendum (2026-07-09) : escalade vers StealthyFetcher

Le risque décrit ci-dessus s'est matérialisé dès la première exécution en prod : 100% des requêtes Indeed (24/24, tous couples keyword/location) ont reçu un 403 immédiat depuis le runner GitHub Actions, alors que France Travail fonctionnait normalement. Diagnostic confirmé par test direct : `Fetcher.get(..., stealthy_headers=True, impersonate="chrome")` reste bloqué (empreinte TLS/en-têtes imitée mais pas un vrai navigateur), tandis que `StealthyFetcher.fetch(...)` (Chromium headless piloté par `patchright`) passe (200, offres parsées) sur la même URL.

`sources/indeed.py` utilise maintenant `StealthyFetcher.fetch` à la place de `Fetcher.get`. Conséquences :
- CI : nouvelle étape `python -m patchright install --with-deps chromium` avant `python run.py` (coût ~1-2 min / run, navigateur pas mis en cache pour l'instant).
- `_build_params` inchangé ; l'URL est construite manuellement (`urlencode`) car `StealthyFetcher.fetch` prend une URL complète, pas de `params=`.
- Gestion des erreurs inchangée (`_request_with_retry`, blocage → liste vide, pas d'exception qui remonterait à l'alerte COM-6).

## Addendum (2026-07-11) : blocage IP confirmé, Indeed retiré du cron cloud

L'escalade vers `StealthyFetcher` (ci-dessus) a corrigé le blocage par **empreinte** (un vrai Chromium headless passe là où `Fetcher.get` échouait — vérifié aussi depuis une IP résidentielle, donc ce n'était pas un problème d'IP à l'époque). Mais le premier run cloud réel après ce correctif (2026-07-10 17:39) a de nouveau reçu 403 sur 24/24 requêtes (précédées d'un redirect 307), alors que le même code depuis une IP résidentielle reçoit 200 de façon fiable et reproductible (re-testé le 2026-07-11). Diagnostic : le blocage restant est basé sur la **réputation de l'IP** des runners GitHub Actions (plages datacenter connues), au niveau réseau/edge — un navigateur headless, aussi convaincant soit-il, ne peut rien y faire.

Décision (validée par Alex, contrainte budget zéro — pas de proxy résidentiel payant) : Indeed est retiré du cron cloud planifié. `run.py` gagne un flag `--no-indeed` (défaut : Indeed actif) ; le workflow GitHub Actions l'appelle avec `--no-indeed`, et l'étape d'installation de Chromium est retirée de la CI (plus nécessaire). Indeed reste pleinement fonctionnel en local : `python run.py` (sans le flag) depuis le PC d'Alex passe par son IP résidentielle et fait tourner le pipeline complet (collecte + scoring + dédup + email), à lancer ponctuellement quand il veut inclure Indeed.

Pistes non retenues (budget zéro) : proxy résidentiel payant (coût récurrent écarté), runner self-hosted sur le PC d'Alex (réintroduit la contrainte "PC allumé à l'heure du cron" que le passage à GitHub Actions visait justement à éviter), proxies gratuits publics (peu fiables, souvent déjà sur IP datacenter blacklistées, risque de sécurité).
