"""
Reintent i classificació d'errors davant crides a l'API de Hugging Face.

Aquest mòdul només tracta d'una cosa: què fer quan una crida a l'API falla.

Conté:
  - `with_retry`: reintent amb backoff exponencial + jitter davant 429 i
    errors de xarxa transitoris.
  - `ErrorCategory` / `classify_error`: classificació d'excepcions en
    categories semàntiques (rate limit, accés restringit, no trobat,
    transitori, desconegut).
  - `append_failure_row`: registre estructurat de fallades a un CSV.

===============================================================================
DISSENY: com es tracta l'HTTP 429 (Too Many Requests / rate limiting)
===============================================================================

Problema observat: sense cap mecanisme de reintent, una execució real amb
1000 datasets classificats va donar un 59.1% d'errors (591/1000), gairebé
tots HTTP 429. L'API de `huggingface_hub` NO reintenta automàticament les
peticions davant rate limiting -- `list_repo_refs`/`list_repo_commits`
propaguen `HfHubHTTPError` directament. Sense un compte de pagament, HF
imposa un límit de peticions per segon que es xoca constantment quan es
classifiquen centenars/milers de datasets en paral·lel.

Alternatives considerades (per ordre en què es van descartar):

  1. Cap reintent (l'estat original del projecte). Descartat: inutilitzable,
     ~59% de la mostra es perdia com a "error" en lloc de classificar-se.

  2. Espera fixa (p.e. "sempre espera 10s i reintenta"). Descartada: no
     s'adapta a la severitat del throttling. Si el servidor està sota
     pressió sostinguda, una espera curta fixa manté el "martelleig" de
     peticions (allarga la recuperació); si és massa llarga, malgasta temps
     quan el límit ja hauria desaparegut.

  3. Backoff exponencial SENSE jitter (10s -> 20s -> 40s -> 80s -> 120s,
     igual per a tots els threads). Millor que l'espera fixa, però amb
     `--threads` > 1 introdueix un problema nou: com el 429 sol ser un
     límit compartit (per IP/token, no per thread), diversos threads hi
     xoquen alhora i, sense jitter, TAMBÉ desperten i reintenten alhora,
     recreant una punta de peticions sincronitzada ("thundering herd") que
     pot tornar a disparar el 429 immediatament.

  4. Backoff exponencial AMB jitter (la implementada, `with_retry`). Afegeix
     un component aleatori (`jitter_fn`, per defecte uniforme [0,1]s) a
     cada espera, esglaonant quan reintenta cada thread i evitant la
     ressonància del cas 3. És el patró recomanat per les guies de bones
     pràctiques d'AWS/Google Cloud per a rate limiting distribuït, i
     l'únic dels quatre que, validat empíricament en aquest projecte,
     redueix els errors 429 a pràcticament 0 en execucions reals
     (verificat: mostres de centenars de datasets amb `errors: 0` al
     resum final).

  Complementàriament (no substitutiu del backoff+jitter, ja que HF no
  publica el llindar exacte del límit): es va reduir el nombre de threads
  per defecte (`--threads 4`, no 8) i el payload per petició a
  `list_datasets` (`expand=["disabled"]`), disminuint la pressió global
  sobre l'API sense dependre'n com a única defensa.

Justificació de la decisió final: backoff exponencial + jitter és l'única
opció de les considerades que (a) s'adapta a la duració real del
throttling en lloc d'assumir-la, (b) evita la sincronització entre threads
concurrents, i (c) és configurable en temps d'execució
(`--retry-max-attempts`, `--retry-base-wait`, `--retry-max-wait`) sense
tocar codi, cosa necessària perquè el llindar real de HF no és conegut ni
constant.

===============================================================================
DISSENY: com es tracta l'HTTP 403 (Forbidden / accés restringit)
===============================================================================

Problema: un 403 de `list_repo_refs`/`list_repo_commits` significa que el
dataset és gated o privat i el token actual no hi té accés. A diferència
del 429, aquesta condició NO és transitòria: reintentar no la resol mai
(no canvia amb el temps, només si algú concedeix accés manualment al
token).

Diagnosi descartada -- rol del token (read vs write): alguns fils del
fòrum de HF (p.e. discuss.huggingface.co/t/error-403-what-to-do-about-it)
atribueixen un 403 a fer servir un token amb rol "read" en lloc de
"write". S'ha investigat aquesta hipòtesi per als 403 d'aquest projecte i
es descarta, amb evidència en ambdós sentits:

  - El fil en qüestió: el 403 original s'hi produeix a `POST
    /api/repos/create` -- una operació d'ESCRIPTURA (crear un repositori)
    amb un token de només lectura. Aquest projecte no escriu mai res a
    l'API (`list_repo_refs`, `list_repo_commits`, `list_datasets` són
    totes operacions de lectura), així que aquesta causa concreta no hi
    és aplicable.
  - Evidència empírica pròpia: de les 626 files amb
    `error_category == "access_restricted"` acumulades a
    `data/failures.csv` en aquest projecte, el 100% contenen el mateix
    missatge oficial de HF, "Cannot access gated repo for url ...
    Access to dataset ... is restricted and you are not in the
    authorized list" -- cap conté cap referència a permisos o abast del
    token (cap "permission"/"scope"/"write" al missatge). L'accés a un
    dataset gated és un consentiment per compte i per dataset (cal
    "Agree"/sol·licitar accés a la pàgina del dataset), no un abast del
    token: un token amb rol "write" del mateix compte xocaria amb el
    mateix mur.
  - Una resposta secundària d'aquell mateix fil sí que descriu el nostre
    cas real ("per accedir a CompVis/stable-diffusion-v1-4 cal acceptar
    la llicència a la pàgina del dataset primer"), però aquesta solució
    (sol·licitar accés manualment, dataset a dataset) no és aplicable a
    un mostreig aleatori de la població: no té sentit sol·licitar accés
    a desenes/centenars de datasets gated escollits a l'atzar dels quals
    no se sap per endavant si formaran part de la mostra.

  Conclusió: mantenir el token amb rol "Read" és correcte i suficient 
  per a aquest projecte; un token "write" no canviaria el resultat dels 403 observats.

Alternatives considerades (per tractar el 403 un cop identificat, no per
evitar-lo -- l'accés gated no es pot "evitar" des del codi):

  1. Reintentar-lo igual que qualsevol altre error. Descartada: malgasta
     tot el pressupost de reintents (fins a `max_retries` intents amb
     backoff creixent, uns quants minuts) en una condició que fallarà
     sempre, alentint l'escaneig sencer sense cap benefici possible.

  2. Descartar-lo en silenci, sense registrar-lo enlloc. Descartada:
     encongiria el denominador de datasets realment avaluats sense
     deixar-ne rastre, impossibilitant auditar-ho més tard: quants
     datasets de la mostra eren, de fet, inaccessibles és una
     característica real de la població, no un artefacte a amagar.

  3. Comptar-lo com a "no elegible" (mateix bucket que un dataset
     classificat amb èxit que no compleix els criteris). Descartada:
     confon "no hem pogut determinar l'elegibilitat" amb "hem determinat
     que no compleix els criteris", esbiaixant `eligible_proportion` per
     un motiu equivocat (com si en sabéssim el resultat).

  4. Categoria pròpia `ErrorCategory.ACCESS_RESTRICTED`, SENSE reintent
     (`with_retry` repropaga immediatament qualsevol `HfHubHTTPError` amb
     status != 429; vegeu el codi de `with_retry` més avall), exclosa tant
     del numerador com del denominador "no elegible", però comptabilitzada
     i reportada explícitament (`status="access_restricted"`,
     `access_restricted` a `compute_funnel_stats`, fila completa a
     `data/failures.csv`). Aquesta és l'opció implementada.

Justificació: l'opció 4 és l'única que és alhora honesta metodològicament
(no assumeix un resultat d'elegibilitat que no s'ha pogut comprovar) i
eficient (no malgasta temps reintentant una condició permanent). El
denominador d'`eligible_proportion` queda restringit als datasets que s'han
pogut classificar amb èxit, amb l'amenaça a la validesa corresponent
documentada explícitament a `eligibility_scan.compute_funnel_stats`
(s'assumeix que els datasets amb accés restringit tenen, en proporció,
una elegibilitat similar als que sí s'han pogut avaluar).

El cas 404 (Not Found, p.e. un dataset esborrat/renombrat després de ser
llistat) es tracta de manera anàloga: tampoc es reintenta (no és
transitori) i queda registrat amb la seva pròpia categoria
(`ErrorCategory.NOT_FOUND`), encara que actualment es compta dins del
bucket genèric "errors" de l'embut en lloc de tenir columna pròpia, ja que
empíricament ha estat un cas molt més infreqüent que el 403.
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

# Excepcions de xarxa transitòries (a banda del 429) que també val la pena
# reintentar: talls de connexió o timeouts puntuals no impliquen que el
# dataset sigui inaccessible, només que la crida concreta ha fallat.
#
# NOTA: huggingface_hub (>=1.x) fa servir httpx com a client HTTP intern
# (HfHubHTTPError mateix hereta de httpx.HTTPError), per això capturem
# excepcions de httpx i no de `requests` tot i que aquest últim encara és
# una dependència transitiva del projecte. httpx.TransportError és la
# classe base de tots els errors de transport (connexió, timeout, DNS...),
# incloent httpx.TimeoutException.
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
    Executa ``fn(*args, **kwargs)`` amb reintent automàtic davant HTTP 429
    (Too Many Requests) i errors de xarxa transitoris, usant backoff
    exponencial amb jitter (vegeu la secció "DISSENY: 429" al capçal
    d'aquest fitxer per a l'anàlisi completa d'alternatives i la
    justificació d'aquest disseny concret).

    Backoff: l'espera abans del intent N+1 és
    ``min(base_wait_s * 2**N, max_wait_s) + jitter_fn()`` (per defecte
    10s, 20s, 40s, 80s, 120s + soroll aleatori [0,1)s). Qualsevol altre
    error HTTP (403 accés restringit, 404 no trobat, etc.) NO es
    reintenta: es considera un resultat definitiu i es propaga
    immediatament perquè el cridant el classifiqui amb `classify_error`.

    :param fn: funció a executar (típicament una crida a l'API de HF, p.e.
        `huggingface_hub.list_repo_refs`). Es crida com ``fn(*args, **kwargs)``.
    :param args: arguments posicionals que es passen tal qual a `fn`.
    :param max_retries: nombre màxim d'intents totals (incloent el primer).
        Si tots fallen amb un error reintentable, es repropaga l'última
        excepció capturada.
    :param base_wait_s: espera (segons) abans del primer reintent; es
        duplica a cada intent successiu fins a `max_wait_s`.
    :param max_wait_s: topall (segons) del backoff exponencial.
    :param sleep_fn: funció cridada com ``sleep_fn(segons)`` per esperar
        entre reintents. Injectable per fer la funció testejable sense
        esperes reals (vegeu `tests/test_errors.py`).
    :param jitter_fn: funció sense arguments que retorna els segons de
        soroll aleatori afegits a cada espera, per esglaonar els
        reintents de threads concurrents i evitar que tots despertin
        exactament al mateix instant.
    :param kwargs: arguments amb nom que es passen tal qual a `fn`.
    :return: el valor retornat per ``fn(*args, **kwargs)`` en la primera
        crida que tingui èxit.
    :raises Exception: repropaga la darrera excepció capturada si
        s'exhaureixen els `max_retries` intents, o immediatament si `fn`
        llança una excepció no reintentable (qualsevol `HfHubHTTPError`
        amb status diferent de 429, o qualsevol excepció que no sigui de
        les categories de xarxa transitòria contemplades).
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

    # Inabastable en la pràctica (el bucle sempre retorna o llança abans),
    # es manté per satisfer el type-checker.
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Classificació d'errors
# ---------------------------------------------------------------------------


class ErrorCategory(str, Enum):
    """
    Categories semàntiques per a excepcions capturades durant l'escaneig.

    :cvar RATE_LIMITED: HTTP 429 esgotat després de tots els reintents de
        `with_retry`. Vegeu "DISSENY: 429" al capçal del fitxer.
    :cvar ACCESS_RESTRICTED: HTTP 403 -- dataset gated/privat, el token
        actual no hi té accés. No es reintenta (condició permanent).
        Vegeu "DISSENY: 403" al capçal del fitxer.
    :cvar NOT_FOUND: HTTP 404 -- dataset esborrat o renombrat després de
        ser llistat. No es reintenta (condició permanent).
    :cvar TRANSIENT: error de xarxa (timeout, connexió tallada) que ha
        esgotat els reintents de `with_retry`.
    :cvar UNKNOWN: qualsevol altra excepció no prevista explícitament.
    """

    RATE_LIMITED = "rate_limited"
    ACCESS_RESTRICTED = "access_restricted"
    NOT_FOUND = "not_found"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


def classify_error(exc: Exception) -> ErrorCategory:
    """
    Classifica una excepció capturada en una categoria d'error útil, en
    lloc de tractar-les totes com un "error" genèric indistingible.

      - 429 (rate limit esgotat després de tots els reintents) -> RATE_LIMITED
      - 403 (dataset gated/privat)                              -> ACCESS_RESTRICTED
      - 404 (dataset esborrat/renombrat)                        -> NOT_FOUND
      - Timeout / error de connexió                             -> TRANSIENT
      - Qualsevol altra cosa                                    -> UNKNOWN

    Distingir ACCESS_RESTRICTED de la resta és important perquè no és un
    fallo de l'scan: és un fet estructural del dataset (gated/privat) que
    no hauria de comptar com a "no elegible" ni com a "error" al
    denominador de l'embut (això ho fa servir `eligibility_scan.py`; vegeu
    "DISSENY: 403" al capçal d'aquest fitxer per a la justificació
    completa).

    :param exc: excepció capturada (típicament propagada per `with_retry`
        després d'exhaurir els reintents, o una excepció no reintentable
        com `HfHubHTTPError` amb status 403/404).
    :return: la `ErrorCategory` corresponent. Mai llança: qualsevol
        excepció no reconeguda es classifica com `ErrorCategory.UNKNOWN`.
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


# Categories que impliquen que `with_retry` ja ha exhaurit els reintents
# configurats abans de propagar l'excepció final.
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
    Afegeix una fila estructurada al fitxer de fallades (CSV compartit
    entre execucions), creant-lo amb capçalera si encara no existeix.

    A diferència del camp `error` (curt, truncat) que es guarda inline al
    report principal per a lectura ràpida, aquest fitxer conserva el
    missatge complet (fins a 500 caràcters) i metadades (categoria,
    reintents, font) per poder diagnosticar o reprocessar fallades més
    endavant sense haver de re-executar tot l'escaneig.

    :param path: ruta del fitxer CSV de fallades (p.e.
        `eligibility_scan.FAILURES_LOG_PATH`). Es crea, junt amb els
        directoris pares, si no existeix.
    :param dataset_id: identificador del dataset que ha fallat
        (`owner/name`).
    :param category: `ErrorCategory` retornada per `classify_error` per a
        aquesta excepció.
    :param message: missatge complet de l'excepció (`str(exc)`); es
        trunca a 500 caràcters abans d'escriure's.
    :param retries_attempted: nombre de reintents que `with_retry` ha fet
        abans de rendir-se (0 si l'error no era reintentable, com un 403).
    :param source: etiqueta lliure (p.e. "sampling") que aquest mòdul no
        interpreta -- només l'escriu tal qual, útil per saber de quina
        execució/mode prové la fila quan el fitxer és compartit entre
        diverses execucions.
    :return: None. Efecte: afegeix una línia al fitxer CSV a `path`
        (escriptura amb `mode="a"`, append-only).
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
