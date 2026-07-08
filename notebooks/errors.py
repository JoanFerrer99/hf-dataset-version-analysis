"""
Reintent i classificació d'errors davant crides a l'API de Hugging Face.

Conté:
  - Reintent amb backoff exponencial + jitter davant 429 i
    errors de xarxa transitoris.
  - Classificació d'excepcions en categories semàntiques 
    (rate limit, accés restringit, no trobat, transitori, desconegut).
  - Registre estructurat de fallades a un CSV.
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
    Executa `fn(*args, **kwargs)` amb reintent automàtic en cas de:
      - HTTP 429 (Too Many Requests) de l'API de Hugging Face.
      - Errors de xarxa transitoris (timeout, connexió tallada).

    Backoff exponencial (per defecte 10s -> 20s -> 40s -> 80s -> 120s) amb
    jitter afegit a cada espera perquè diversos threads no reintentin
    exactament al mateix instant ("thundering herd").

    `sleep_fn`/`jitter_fn` són injectables per fer la funció testejable
    sense esperes reals ni aleatorietat no determinista.
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

    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Classificació d'errors
# ---------------------------------------------------------------------------


class ErrorCategory(str, Enum):
    """Categories semàntiques per a excepcions capturades durant l'escaneig."""

    RATE_LIMITED = "rate_limited"
    ACCESS_RESTRICTED = "access_restricted"
    NOT_FOUND = "not_found"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


def classify_error(exc: Exception) -> ErrorCategory:
    """
    Classifica una excepció capturada en una categoria d'error.

      - 429 (rate limit esgotat després de tots els reintents)  -> RATE_LIMITED
      - 403 (dataset gated/privat)                              -> ACCESS_RESTRICTED
      - 404 (dataset esborrat/renombrat)                        -> NOT_FOUND
      - Timeout / error de connexió                             -> TRANSIENT
      - Qualsevol altra cosa                                    -> UNKNOWN
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
    Afegeix una fila estructurada al fitxer de fallades (CSV compartit entre
    execucions), creant-lo amb capçalera si encara no existeix.

    Aquest fitxer conserva el missatge complet (fins a 500 caràcters) i metadades (categoria,
    reintents, font) per poder diagnosticar o reprocessar fallades més
    endavant sense haver de re-executar tot l'escaneig.

    `source` és una etiqueta lliure (p.e. "sampling"/"full_scan") que
    aquest mòdul no interpreta -- només l'escriu tal qual.
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
