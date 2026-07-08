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
