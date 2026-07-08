# Indeed Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `IndeedSource` connector (COM-9) so the pipeline also collects offers from Indeed's public job search, alongside France Travail.

**Architecture:** `sources/indeed.py::IndeedSource(BaseSource)` mirrors `FranceTravailSource`: loops `keywords × locations`, fetches each combination, parses HTML into `JobOffer`. Fetching uses `scrapling.fetchers.Fetcher.get()` (stealth HTTP client, no browser) instead of an API. The retry helper from COM-7 is extracted from `france_travail.py` into a shared `sources/http_retry.py` so both connectors reuse the same retry/backoff policy despite using different HTTP libraries (`requests` vs `scrapling`).

**Tech Stack:** Python 3.13, `scrapling` (new dependency) for stealth HTTP fetch + CSS/XPath parsing, existing `BaseSource`/`JobOffer` abstraction.

## Global Constraints

- Reuse `BaseSource`/`JobOffer` from `sources/base_source.py` — no changes to that file.
- No changes to `pipeline/filter.py`, `pipeline/dedup.py`, `notifier/*` — offers flow through the existing pipeline unmodified.
- `run.py`: Indeed collection wrapped in its own `try/except`, mirroring the existing France Travail block exactly, including a call to `_alert_failure()` (COM-6) on exception.
- Dependency: add `scrapling==0.4.8` to `requirements.txt` (version already known-compatible with this project's Python 3.13 venv).
- No browser install step in CI — use `Fetcher.get` (lightweight stealth HTTP), not `StealthyFetcher` (real browser).
- Tests follow this repo's existing convention: plain `assert`-based scripts with a `main()` function, run via `python <file>.py` (no pytest — not installed in this project's venv).
- All CSS/XPath selectors below were verified against real, live Indeed markup on 2026-07-08 (captured via Playwright) — not guessed.

---

### Task 1: Add `scrapling` dependency

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `scrapling` importable in the project venv for later tasks.

- [ ] **Step 1: Add the dependency**

Add this line to `requirements.txt` (after `python-dotenv==1.2.2`):

```
scrapling==0.4.8
```

- [ ] **Step 2: Install and verify**

Run: `C:/Projets/job_pipeline/.venv/Scripts/python.exe -m pip install -r requirements.txt`
Then run: `C:/Projets/job_pipeline/.venv/Scripts/python.exe -c "from scrapling.fetchers import Fetcher; from scrapling.parser import Selector; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "Add scrapling dependency for Indeed connector"
```

---

### Task 2: Extract shared retry helper into `sources/http_retry.py`

**Files:**
- Create: `sources/http_retry.py`
- Create: `sources/test_http_retry.py`
- Test: `sources/test_http_retry.py`

**Interfaces:**
- Produces: `_request_with_retry(request_func, max_attempts=3, base_delay=1.0, sleep_func=time.sleep, status_getter=lambda r: r.status_code, exception_types=(requests.RequestException,))` — generalized version of the COM-7 helper currently in `sources/france_travail.py`. `status_getter` reads the HTTP status off whatever response object `request_func()` returns; `exception_types` is the tuple of exception classes to catch and retry.

- [ ] **Step 1: Write the failing tests**

Create `sources/test_http_retry.py`:

```python
"""
Test de _request_with_retry (sources/http_retry.py) - retry avec backoff
sur erreurs réseau et codes 429/5xx, généralisé pour être réutilisable
entre connecteurs (France Travail utilise `.status_code`, Indeed utilise
`.status` via scrapling).

Usage (depuis sources/) :
    python test_http_retry.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from http_retry import _request_with_retry


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeScraplingResponse:
    def __init__(self, status):
        self.status = status


def test_retries_on_network_error_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def request_func():
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ConnectionError("boom")
        return FakeResponse(200)

    response = _request_with_retry(
        request_func, max_attempts=3, base_delay=0.01, sleep_func=sleeps.append
    )

    assert response.status_code == 200, f"attendu 200, obtenu {response.status_code}"
    assert calls["n"] == 3, f"attendu 3 appels, obtenu {calls['n']}"
    assert len(sleeps) == 2, f"attendu 2 pauses, obtenu {len(sleeps)}"
    print("OK: test_retries_on_network_error_then_succeeds")


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def request_func():
        calls["n"] += 1
        if calls["n"] < 2:
            return FakeResponse(429)
        return FakeResponse(200)

    response = _request_with_retry(
        request_func, max_attempts=3, base_delay=0.01, sleep_func=lambda s: None
    )

    assert response.status_code == 200
    assert calls["n"] == 2, f"attendu 2 appels, obtenu {calls['n']}"
    print("OK: test_retries_on_429_then_succeeds")


def test_does_not_retry_on_client_error():
    calls = {"n": 0}

    def request_func():
        calls["n"] += 1
        return FakeResponse(400)

    response = _request_with_retry(
        request_func, max_attempts=3, base_delay=0.01, sleep_func=lambda s: None
    )

    assert response.status_code == 400
    assert calls["n"] == 1, f"attendu 1 seul appel (pas de retry sur 400), obtenu {calls['n']}"
    print("OK: test_does_not_retry_on_client_error")


def test_raises_after_exhausting_retries_on_network_error():
    calls = {"n": 0}

    def request_func():
        calls["n"] += 1
        raise requests.exceptions.Timeout("timeout")

    try:
        _request_with_retry(
            request_func, max_attempts=3, base_delay=0.01, sleep_func=lambda s: None
        )
        raised = False
    except requests.exceptions.Timeout:
        raised = True

    assert raised, "attendu une exception Timeout après épuisement des tentatives"
    assert calls["n"] == 3, f"attendu 3 tentatives, obtenu {calls['n']}"
    print("OK: test_raises_after_exhausting_retries_on_network_error")


def test_returns_last_response_after_exhausting_retries_on_5xx():
    calls = {"n": 0}

    def request_func():
        calls["n"] += 1
        return FakeResponse(503)

    response = _request_with_retry(
        request_func, max_attempts=3, base_delay=0.01, sleep_func=lambda s: None
    )

    assert response.status_code == 503
    assert calls["n"] == 3, f"attendu 3 tentatives, obtenu {calls['n']}"
    print("OK: test_returns_last_response_after_exhausting_retries_on_5xx")


def test_supports_custom_status_getter_and_exception_types():
    calls = {"n": 0}

    def request_func():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("erreur générique côté lib scraping")
        return FakeScraplingResponse(200)

    response = _request_with_retry(
        request_func,
        max_attempts=3,
        base_delay=0.01,
        sleep_func=lambda s: None,
        status_getter=lambda r: r.status,
        exception_types=(ValueError,),
    )

    assert response.status == 200, f"attendu 200, obtenu {response.status}"
    assert calls["n"] == 2, f"attendu 2 appels, obtenu {calls['n']}"
    print("OK: test_supports_custom_status_getter_and_exception_types")


def main():
    test_retries_on_network_error_then_succeeds()
    test_retries_on_429_then_succeeds()
    test_does_not_retry_on_client_error()
    test_raises_after_exhausting_retries_on_network_error()
    test_returns_last_response_after_exhausting_retries_on_5xx()
    test_supports_custom_status_getter_and_exception_types()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd sources && ../.venv/Scripts/python.exe test_http_retry.py`
Expected: `ModuleNotFoundError: No module named 'http_retry'`

- [ ] **Step 3: Create `sources/http_retry.py`**

```python
"""
http_retry.py - Retry générique avec backoff exponentiel pour les connecteurs.

Partagé entre les sources (France Travail utilise `requests`, Indeed utilise
`scrapling`) via les paramètres `status_getter` et `exception_types`, qui
s'adaptent aux objets de réponse et exceptions propres à chaque bibliothèque.
"""

import time
import logging
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# Codes HTTP transitoires : on retente plutôt que d'abandonner immédiatement
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _request_with_retry(
    request_func: Callable[[], object],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep_func: Callable[[float], None] = time.sleep,
    status_getter: Callable[[object], int] = lambda r: r.status_code,
    exception_types: tuple = (requests.RequestException,),
) -> object:
    """
    Appelle request_func() avec retry et backoff exponentiel.

    Retente sur exception_types (erreurs réseau) et sur les codes
    RETRYABLE_STATUS_CODES (429/5xx), lus via status_getter. Les autres
    statuts HTTP sont retournés tels quels dès le premier appel.
    """
    last_exception: Optional[Exception] = None
    response: Optional[object] = None

    for attempt in range(max_attempts):
        try:
            response = request_func()
        except exception_types as e:
            last_exception = e
            if attempt < max_attempts - 1:
                sleep_func(base_delay * (2 ** attempt))
                continue
            raise
        else:
            if status_getter(response) in RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                sleep_func(base_delay * (2 ** attempt))
                continue
            return response

    return response
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd sources && ../.venv/Scripts/python.exe test_http_retry.py`
Expected: 6 `OK:` lines then `Tous les tests passent.`

- [ ] **Step 5: Commit**

```bash
git add sources/http_retry.py sources/test_http_retry.py
git commit -m "Extract generalized retry helper into sources/http_retry.py"
```

---

### Task 3: Migrate `france_travail.py` to the shared retry helper

**Files:**
- Modify: `sources/france_travail.py`
- Delete: `sources/test_retry.py` (superseded by `sources/test_http_retry.py`)

**Interfaces:**
- Consumes: `_request_with_retry` from `sources/http_retry.py` (Task 2).

- [ ] **Step 1: Remove the local retry implementation from `france_travail.py`**

In `sources/france_travail.py`, delete these lines (currently lines 48-83):

```python
# Codes HTTP transitoires : on retente plutôt que d'abandonner immédiatement
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _request_with_retry(
    request_func: Callable[[], requests.Response],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep_func: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """
    Appelle request_func() avec retry et backoff exponentiel.

    Retente sur requests.RequestException (erreurs réseau) et sur les
    codes RETRYABLE_STATUS_CODES (429/5xx). Les autres statuts HTTP sont
    retournés tels quels dès le premier appel.
    """
    last_exception: Optional[requests.RequestException] = None
    response: Optional[requests.Response] = None

    for attempt in range(max_attempts):
        try:
            response = request_func()
        except requests.RequestException as e:
            last_exception = e
            if attempt < max_attempts - 1:
                sleep_func(base_delay * (2 ** attempt))
                continue
            raise
        else:
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                sleep_func(base_delay * (2 ** attempt))
                continue
            return response

    return response
```

- [ ] **Step 2: Add the import**

In `sources/france_travail.py`, replace the import block:

```python
try:
    from .base_source import BaseSource, JobOffer
except ImportError:
    from base_source import BaseSource, JobOffer
```

with:

```python
try:
    from .base_source import BaseSource, JobOffer
    from .http_retry import _request_with_retry
except ImportError:
    from base_source import BaseSource, JobOffer
    from http_retry import _request_with_retry
```

Also remove `import time` and the `Callable` entry from `from typing import Callable, Optional` (now unused in this file — leave `Optional`).

- [ ] **Step 3: Delete the superseded test file**

```bash
git rm sources/test_retry.py
```

- [ ] **Step 4: Verify nothing broke**

Run: `cd sources && ../.venv/Scripts/python.exe test_http_retry.py`
Expected: all pass (unchanged from Task 2).

Run: `cd sources && ../.venv/Scripts/python.exe -c "from france_travail import FranceTravailSource; print('import ok')"`
Expected: `import ok`

- [ ] **Step 5: Commit**

```bash
git add sources/france_travail.py
git commit -m "Migrate france_travail.py to shared http_retry helper"
```

---

### Task 4: Indeed HTML fixture + result parsing

**Files:**
- Create: `sources/fixtures/indeed_sample.html`
- Create: `sources/indeed.py` (parsing portion only in this task)
- Create: `sources/test_indeed_parsing.py`
- Test: `sources/test_indeed_parsing.py`

**Interfaces:**
- Consumes: `JobOffer`, `BaseSource` from `sources/base_source.py`.
- Produces: `_parse_results(page) -> list[JobOffer]` — `page` is any object exposing `.css()`/`.xpath()` (a `scrapling.parser.Selector` or a `scrapling` `Fetcher` response, which exposes the same interface). Later tasks (5, 6) call this.

- [ ] **Step 1: Create the HTML fixture**

Create `sources/fixtures/indeed_sample.html` (captured and trimmed from a real Indeed search results page, 2026-07-08, for `q=data+analyst+alternance&l=Lille`):

```html
<ul>
<li class="css-1ac2h1w eu4oa1w0">
  <div class="job_seen_beacon">
    <table class="mainContentTable" role="presentation"><tbody><tr><td class="resultContent">
      <div><h3 class="jobTitle" tabindex="-1"><a id="sj_406bba8701d62c9c" data-jk="406bba8701d62c9c" class="jcs-JobTitle" href="/pagead/clk?mo=r&amp;ad=xyz">
        <span title="Alternance - Data Analyst H/F - LILLE - 59 (H/F)" id="jobTitle-406bba8701d62c9c">Alternance - Data Analyst H/F - LILLE - 59 (H/F)</span>
      </a></h3></div>
      <div class="css-u74ql7"><div class="company_location">
        <div><span data-testid="company-name">Studi CFA</span></div>
        <div data-testid="text-location">59000 Lille</div>
      </div>
      <div class="jobMetaDataGroup"><ul class="heading6 tapItem-gutter metadataContainer">
        <li class="salary-snippet-container" data-testid="attribute_snippet_testid salary-snippet-container"><div><div><span>De 504,09 € à 1 867,02 € par mois</span></div></div></li>
        <li data-testid="attribute_snippet_testid"><div><div><span>Contrat d'apprentissage</span></div></div></li>
      </ul></div>
      </div>
    </td></tr></tbody></table>
  </div>
  <ul style="list-style-type:circle;margin-top: 0px;margin-bottom: 0px;padding-left:20px;">
    <li style="margin-bottom:0px;">Cette offre d'alternance est à pourvoir IMMEDIATEMENT.</li>
    <li>Concevoir des tableaux de bord dynamiques sur Excel et Power BI.</li>
  </ul>
</li>
<li class="css-1ac2h1w eu4oa1w0">
  <div class="job_seen_beacon">
    <table class="mainContentTable" role="presentation"><tbody><tr><td class="resultContent">
      <div><h3 class="jobTitle" tabindex="-1"><a id="sj_dd5e5bbcdc58578b" data-jk="dd5e5bbcdc58578b" class="jcs-JobTitle" href="/pagead/clk?mo=r&amp;ad=abc">
        <span title="STAGE / ALTERNANCE: Junior Financial Controller &amp; Data Analyst (H/F)" id="jobTitle-dd5e5bbcdc58578b">STAGE / ALTERNANCE: Junior Financial Controller &amp; Data Analyst (H/F)</span>
      </a></h3></div>
      <div class="css-u74ql7"><div class="company_location">
        <div><span data-testid="company-name">Biospringer</span></div>
        <div data-testid="text-location">59700 Marcq-en-Barœul</div>
      </div>
      <div class="jobMetaDataGroup"><ul class="heading6 tapItem-gutter metadataContainer">
        <li data-testid="attribute_snippet_testid"><div><div><span>Stage</span><span>+1</span></div></div></li>
      </ul></div>
      </div>
    </td></tr></tbody></table>
  </div>
  <ul style="list-style-type:circle;margin-top: 0px;margin-bottom: 0px;padding-left:20px;">
    <li style="margin-bottom:0px;">Acteur mondial de référence dans le domaine des levures et de la fermentation, Lesaffre conçoit, produit et apporte des solutions innovantes pour la…</li>
  </ul>
</li>
</ul>
```

- [ ] **Step 2: Write the failing tests**

Create `sources/test_indeed_parsing.py`:

```python
"""
Test de _parse_results (sources/indeed.py) - parsing des offres à partir
d'un fixture HTML sauvegardé (aucun appel réseau).

Usage (depuis sources/) :
    python test_indeed_parsing.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapling.parser import Selector
from indeed import _parse_results

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "indeed_sample.html"


def _load_fixture():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    return Selector(html)


def test_parses_two_offers_from_fixture():
    page = _load_fixture()
    offers = _parse_results(page)

    assert len(offers) == 2, f"attendu 2 offres, obtenu {len(offers)}"
    print("OK: test_parses_two_offers_from_fixture")


def test_parses_offer_with_salary():
    page = _load_fixture()
    offers = _parse_results(page)
    first = offers[0]

    assert first.id == "indeed_406bba8701d62c9c", first.id
    assert first.title == "Alternance - Data Analyst H/F - LILLE - 59 (H/F)", first.title
    assert first.company == "Studi CFA", first.company
    assert first.location == "59000 Lille", first.location
    assert first.salary == "De 504,09 € à 1 867,02 € par mois", first.salary
    assert first.contract_type == "Contrat d'apprentissage", first.contract_type
    assert "IMMEDIATEMENT" in first.description, first.description
    assert first.url == "https://fr.indeed.com/viewjob?jk=406bba8701d62c9c", first.url
    assert first.source == "Indeed"
    print("OK: test_parses_offer_with_salary")


def test_parses_offer_without_salary():
    page = _load_fixture()
    offers = _parse_results(page)
    second = offers[1]

    assert second.id == "indeed_dd5e5bbcdc58578b", second.id
    assert second.company == "Biospringer", second.company
    assert second.salary is None, f"attendu pas de salaire, obtenu {second.salary}"
    assert second.contract_type == "Stage", second.contract_type
    print("OK: test_parses_offer_without_salary")


def main():
    test_parses_two_offers_from_fixture()
    test_parses_offer_with_salary()
    test_parses_offer_without_salary()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd sources && ../.venv/Scripts/python.exe test_indeed_parsing.py`
Expected: `ModuleNotFoundError: No module named 'indeed'`

- [ ] **Step 4: Create `sources/indeed.py` (parsing only)**

```python
"""
Connecteur Indeed (scraping public, sans compte).

Utilise scrapling.fetchers.Fetcher pour imiter l'empreinte d'un vrai
navigateur sans lancer de navigateur complet. Cf.
docs/superpowers/specs/2026-07-08-indeed-connector-design.md pour le
contexte et les alternatives évaluées (dont l'abandon de Welcome to the
Jungle, passé en 2026 à un système de matching nécessitant un compte).
"""

import logging
from typing import Optional

try:
    from .base_source import BaseSource, JobOffer
except ImportError:
    from base_source import BaseSource, JobOffer

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
            for m in card.css('li[data-testid~="attribute_snippet_testid"] span::text').getall()
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
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd sources && ../.venv/Scripts/python.exe test_indeed_parsing.py`
Expected: 3 `OK:` lines then `Tous les tests passent.`

- [ ] **Step 6: Commit**

```bash
git add sources/indeed.py sources/test_indeed_parsing.py sources/fixtures/indeed_sample.html
git commit -m "Add Indeed HTML parsing with verified selectors"
```

---

### Task 5: `IndeedSource` fetch loop and network call

**Files:**
- Modify: `sources/indeed.py`
- Create: `sources/test_indeed_fetch.py`
- Test: `sources/test_indeed_fetch.py`

**Interfaces:**
- Consumes: `_request_with_retry` from `sources/http_retry.py` (Task 2), `_parse_results` from `sources/indeed.py` (Task 4).
- Produces: `IndeedSource(BaseSource)` with `.name`, `.fetch() -> list[JobOffer]`, `._fetch_batch(keyword, location) -> list[JobOffer]`. Consumed by `run.py` in Task 6.

- [ ] **Step 1: Write the failing tests**

Create `sources/test_indeed_fetch.py`:

```python
"""
Test de IndeedSource._fetch_batch / fetch() (sources/indeed.py) avec
Fetcher.get mocké (aucun appel réseau réel).

Usage (depuis sources/) :
    python test_indeed_fetch.py
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indeed import IndeedSource
from base_source import JobOffer


class FakeScraplingResponse:
    def __init__(self, status):
        self.status = status

    def css(self, selector):
        return []


def test_fetch_batch_returns_empty_list_on_non_200():
    source = IndeedSource(keywords=["data analyst"], locations=["59"])

    with patch("indeed.Fetcher.get", return_value=FakeScraplingResponse(403)):
        offers = source._fetch_batch("data analyst", "59")

    assert offers == [], f"attendu liste vide sur 403, obtenu {offers}"
    print("OK: test_fetch_batch_returns_empty_list_on_non_200")


def test_fetch_batch_returns_empty_list_on_exception():
    source = IndeedSource(keywords=["data analyst"], locations=["59"])

    with patch("indeed.Fetcher.get", side_effect=RuntimeError("bloqué")):
        offers = source._fetch_batch("data analyst", "59")

    assert offers == [], f"attendu liste vide sur exception, obtenu {offers}"
    print("OK: test_fetch_batch_returns_empty_list_on_exception")


def test_fetch_deduplicates_across_keyword_location_combinations():
    source = IndeedSource(keywords=["data analyst", "big data"], locations=["59"])
    duplicate_offer = JobOffer(
        id="indeed_same", title="Data Analyst", company="ACME",
        location="Lille", description="", url="https://fr.indeed.com/viewjob?jk=same",
        source="Indeed",
    )

    with patch.object(IndeedSource, "_fetch_batch", return_value=[duplicate_offer]):
        offers = source.fetch()

    assert len(offers) == 1, f"attendu 1 offre dédupliquée, obtenu {len(offers)}"
    print("OK: test_fetch_deduplicates_across_keyword_location_combinations")


def test_build_params_maps_known_department_to_city_label():
    source = IndeedSource(keywords=["data analyst"], locations=["59"])
    params = source._build_params("data analyst", "59")

    assert params == {"q": "data analyst", "l": "Lille"}, params
    print("OK: test_build_params_maps_known_department_to_city_label")


def test_build_params_passes_through_unknown_location():
    source = IndeedSource(keywords=["data analyst"], locations=["Toulouse"])
    params = source._build_params("data analyst", "Toulouse")

    assert params == {"q": "data analyst", "l": "Toulouse"}, params
    print("OK: test_build_params_passes_through_unknown_location")


def main():
    test_fetch_batch_returns_empty_list_on_non_200()
    test_fetch_batch_returns_empty_list_on_exception()
    test_fetch_deduplicates_across_keyword_location_combinations()
    test_build_params_maps_known_department_to_city_label()
    test_build_params_passes_through_unknown_location()
    print("\nTous les tests passent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd sources && ../.venv/Scripts/python.exe test_indeed_fetch.py`
Expected: `ImportError: cannot import name 'Fetcher'` or `AttributeError: 'IndeedSource' object has no attribute '_fetch_batch'` (class doesn't have fetch machinery yet).

- [ ] **Step 3: Add fetch machinery to `sources/indeed.py`**

Add this import near the top of `sources/indeed.py` (after the existing imports):

```python
from scrapling.fetchers import Fetcher

try:
    from .http_retry import _request_with_retry
except ImportError:
    from http_retry import _request_with_retry
```

Add this class at the end of `sources/indeed.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd sources && ../.venv/Scripts/python.exe test_indeed_fetch.py`
Expected: 5 `OK:` lines then `Tous les tests passent.`

Also re-run Task 4's test to make sure nothing broke: `../.venv/Scripts/python.exe test_indeed_parsing.py` — expected: still passes.

- [ ] **Step 5: Commit**

```bash
git add sources/indeed.py sources/test_indeed_fetch.py
git commit -m "Add IndeedSource fetch loop with retry and dedup"
```

---

### Task 6: Wire `IndeedSource` into `run.py` and add manual smoke test

**Files:**
- Modify: `run.py`
- Create: `sources/test_indeed.py` (manual smoke script, real network, not part of automated suite)

**Interfaces:**
- Consumes: `IndeedSource` from `sources/indeed.py` (Task 5), `_alert_failure` already defined in `run.py` (COM-6).

- [ ] **Step 1: Add the import**

In `run.py`, change:

```python
from sources.france_travail import FranceTravailSource
from pipeline.filter import filter_offers
from pipeline.dedup import DedupStore
from notifier.mailer import EmailNotifier
```

to:

```python
from sources.france_travail import FranceTravailSource
from sources.indeed import IndeedSource
from pipeline.filter import filter_offers
from pipeline.dedup import DedupStore
from notifier.mailer import EmailNotifier
```

- [ ] **Step 2: Add the collection block**

In `run.py`, after the existing France Travail block (currently ending at the comment `# all_offers.extend(WTTJSource(...).fetch())`), replace:

```python
    # Ici on pourra ajouter d'autres sources plus tard :
    # all_offers.extend(IndeedSource(...).fetch())
    # all_offers.extend(WTTJSource(...).fetch())
```

with:

```python
    try:
        indeed = IndeedSource(
            keywords=KEYWORDS,
            locations=LOCATIONS,
        )
        indeed_offers = indeed.fetch()
        all_offers.extend(indeed_offers)
        logger.info("Indeed : %d offres", len(indeed_offers))
    except Exception as e:
        logger.error("Erreur Indeed : %s", e)
        _alert_failure(f"Erreur lors de la collecte Indeed : {e}")

    # Ici on pourra ajouter d'autres sources plus tard :
    # all_offers.extend(WTTJSource(...).fetch())
```

- [ ] **Step 3: Create the manual smoke test script**

Create `sources/test_indeed.py`:

```python
"""
Script de test rapide pour le connecteur Indeed (appel réseau réel).

Usage :
    python test_indeed.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indeed import IndeedSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main():
    print("=" * 60)
    print("Test du connecteur Indeed")
    print("=" * 60)

    source = IndeedSource(
        keywords=["Data Analyst", "Big Data", "alternance data"],
        locations=["59"],
    )

    print(f"\nSource : {source.name}")
    print(f"Mots-clés : {source.keywords}")
    print(f"Localisations : {source.locations}")
    print("\nRecherche en cours...\n")

    offers = source.fetch()

    if not offers:
        print("Aucune offre trouvée (ou Indeed a bloqué la requête).")
        return

    print(f"{len(offers)} offre(s) récupérée(s)\n")
    print("-" * 60)

    for i, offer in enumerate(offers[:5], 1):
        print(f"\n[{i}] {offer.title}")
        print(f"    Entreprise : {offer.company}")
        print(f"    Lieu       : {offer.location}")
        print(f"    Contrat    : {offer.contract_type or 'N/A'}")
        print(f"    Salaire    : {offer.salary or 'N/A'}")
        print(f"    URL        : {offer.url}")

    if len(offers) > 5:
        print(f"\n... et {len(offers) - 5} autre(s) offre(s).")

    print("\n" + "=" * 60)
    print("Test terminé.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the manual smoke test**

Run: `cd sources && ../.venv/Scripts/python.exe test_indeed.py`
Expected: either real offers printed, or "Aucune offre trouvée (ou Indeed a bloqué la requête)." — both are acceptable outcomes at this stage (per the spec, blocking risk was explicitly accepted). What must NOT happen: an unhandled Python traceback. If there is one, fix the underlying bug before continuing.

- [ ] **Step 5: Commit**

```bash
git add run.py sources/test_indeed.py
git commit -m "Wire IndeedSource into run.py pipeline"
```

---

### Task 7: Full regression check

**Files:**
- None (verification only)

**Interfaces:**
- None.

- [ ] **Step 1: Run every automated test file**

Run each of these from the project root and confirm each prints `Tous les tests passent.` with no traceback:

```bash
.venv/Scripts/python.exe sources/test_http_retry.py
.venv/Scripts/python.exe sources/test_indeed_parsing.py
.venv/Scripts/python.exe sources/test_indeed_fetch.py
.venv/Scripts/python.exe notifier/test_failure_alert.py
```

(`pipeline/test_dedup.py` is known to fail on this machine due to a pre-existing console-encoding issue unrelated to this work — skip it, or run with `PYTHONIOENCODING=utf-8` prefixed if you want to double check: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe pipeline/test_dedup.py`.)

- [ ] **Step 2: Run the full pipeline dry-run**

Run: `.venv/Scripts/python.exe run.py --dry-run`
Expected: no unhandled traceback. Log lines should show both `France Travail : N offres` and `Indeed : N offres` (N can be 0 if Indeed got blocked — that's an acceptable outcome per the spec, not a bug).

- [ ] **Step 3: Update the Linear issue and push**

Mark COM-9 as Done in Linear (team "job pipeline", project "job pipeline").

```bash
git push
```
