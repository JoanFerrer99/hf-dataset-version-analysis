"""
Gestió d'errors de les crides a l'API de Hugging Face.

  - `with_retry`: reintent amb backoff exponencial + jitter davant 429 i
    errors de xarxa transitoris.
  - `ErrorCategory` / `classify_error`: categoria semàntica d'una excepció.
  - `append_failure_row`: registre de fallades a `failures.csv`.

Per què backoff+jitter i per què el 403 no es reintenta: `docs/
decisions_tfg.txt`, T-02.
"""

from __future__ import annotations

import csv
import logging
import random as random_module
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar

import httpx
from huggingface_hub.utils import HfHubHTTPError

log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Reintent amb backoff exponencial + jitter
# ---------------------------------------------------------------------------

DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_WAIT_S = 10.0
DEFAULT_MAX_WAIT_S = 120.0

# Cada script amb CLI en fa una còpia (`dict(DEFAULT_RETRY_CONFIG)`) i la
# muta amb els seus `--retry-*`; mai s'ha de mutar aquest dict compartit.
DEFAULT_RETRY_CONFIG: dict = {
    "max_retries": DEFAULT_MAX_RETRIES,
    "base_wait_s": DEFAULT_BASE_WAIT_S,
    "max_wait_s": DEFAULT_MAX_WAIT_S,
}

# huggingface_hub fa servir httpx internament: TransportError cobreix
# connexió tallada, timeout, DNS...
_RETRYABLE_NETWORK_EXCEPTIONS = (httpx.TransportError,)


def with_retry(
    fn: Callable[..., T],
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_wait_s: float = DEFAULT_BASE_WAIT_S,
    max_wait_s: float = DEFAULT_MAX_WAIT_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[], float] = lambda: random_module.uniform(0, 1),
    **kwargs,
) -> T:
    """
    Executa `fn(*args, **kwargs)` reintentant NOMÉS davant HTTP 429 i
    errors de xarxa. Espera abans de l'intent N+1:
    `min(base_wait_s * 2**N, max_wait_s) + jitter_fn()`. Qualsevol altre
    error HTTP (403, 404...) es propaga a la primera.

    :param fn: funció a executar (normalment una crida a l'API de HF).
    :param max_retries: intents totals, incloent el primer.
    :param base_wait_s: espera abans del primer reintent (es duplica).
    :param max_wait_s: topall de l'espera.
    :param sleep_fn: injectable per als tests.
    :param jitter_fn: soroll aleatori afegit a cada espera.
    :return: el resultat de la primera crida amb èxit.
    :raises Exception: l'última excepció si s'esgoten els intents, o
        immediatament si l'error no és reintentable.
    """
    wait = base_wait_s
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except HfHubHTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status != 429:
                raise
            last_exc = exc
        except _RETRYABLE_NETWORK_EXCEPTIONS as exc:
            last_exc = exc

        if attempt == max_retries:
            raise last_exc

        actual_wait = min(wait, max_wait_s) + jitter_fn()
        log.warning(
            f"Error transitori ({type(last_exc).__name__}). "
            f"Reintent {attempt}/{max_retries} en {actual_wait:.1f}s..."
        )
        sleep_fn(actual_wait)
        wait = min(wait * 2, max_wait_s)

    # Inabastable (el bucle sempre retorna o llança); per al type-checker.
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Classificació d'errors
# ---------------------------------------------------------------------------


class ErrorCategory(str, Enum):
    """
    Categoria d'una fallada definitiva.

    :cvar RATE_LIMITED: 429 després d'esgotar els reintents.
    :cvar ACCESS_RESTRICTED: 403, dataset gated/privat (no es reintenta).
    :cvar NOT_FOUND: 404, dataset esborrat o renombrat (no es reintenta).
    :cvar TRANSIENT: error de xarxa després d'esgotar els reintents.
    :cvar UNKNOWN: qualsevol altra excepció.
    """

    RATE_LIMITED = "rate_limited"
    ACCESS_RESTRICTED = "access_restricted"
    NOT_FOUND = "not_found"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


def classify_error(exc: Exception) -> ErrorCategory:
    """
    Tradueix una excepció a la seva `ErrorCategory` (per codi HTTP, o per
    tipus si és un error de xarxa). Mai llança.

    :param exc: excepció capturada.
    :return: la categoria; `UNKNOWN` si no es reconeix.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else None

    if status == 429:
        return ErrorCategory.RATE_LIMITED
    if status == 403:
        return ErrorCategory.ACCESS_RESTRICTED
    if status == 404:
        return ErrorCategory.NOT_FOUND
    if isinstance(exc, _RETRYABLE_NETWORK_EXCEPTIONS):
        return ErrorCategory.TRANSIENT
    return ErrorCategory.UNKNOWN


# Categories on `with_retry` ja ha esgotat els reintents abans de propagar.
RETRIED_CATEGORIES = (ErrorCategory.RATE_LIMITED, ErrorCategory.TRANSIENT)


# ---------------------------------------------------------------------------
# Registre estructurat de fallades
# ---------------------------------------------------------------------------

FAILURE_LOG_FIELDS = [
    "timestamp",
    "source",
    "dataset_id",
    "error_category",
    "error_message",
    "retries_attempted",
]


def append_failure_row(
    path: str | Path,
    dataset_id: str,
    category: ErrorCategory,
    message: str,
    retries_attempted: int = 0,
    source: str = "",
) -> None:
    """
    Afegeix una fila al CSV de fallades (el crea amb capçalera si no
    existeix). Guarda el missatge complet (fins a 500 caràcters), a
    diferència del camp `error` truncat del report principal.

    :param path: ruta del CSV de fallades.
    :param dataset_id: dataset que ha fallat.
    :param category: categoria de `classify_error`.
    :param message: `str(exc)`.
    :param retries_attempted: reintents fets (0 si no era reintentable).
    :param source: fase d'origen (p.e. `"sampling"`, `"version_extraction"`).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FAILURE_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "dataset_id": dataset_id,
                "error_category": category.value,
                "error_message": message[:500],
                "retries_attempted": retries_attempted,
            }
        )
