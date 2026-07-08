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
