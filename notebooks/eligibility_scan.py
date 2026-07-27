"""
Filtratge previ de datasets de HuggingFace amb versions reals (Fase 0).

Metodologia: Reservoir sampling (algoritme R de Vitter) sobre TOTA la població
de datasets, sense ordenar per popularitat. Això garanteix que cada dataset
de la població té igual probabilitat de ser seleccionat.

Estratègia per detectar "versions reals":
1. Es llisten tags/refs del repo (versionat explicit).
2. Si no hi ha tags, es miren els commits i es filtren per fitxers substantius.
3. Es considera "elegible" un dataset amb almenys 2 "punts de canvi" rellevants.

Totes les crides a l'API que poden patir rate limiting (HTTP 429) es
reintenten amb backoff exponencial + jitter (vegeu `errors.with_retry`).
Els errors definitius es classifiquen en categories (accés restringit,
no trobat, transitori esgotat, desconegut) i es registren de forma
estructurada a `data/failures.csv`, separats del report principal.

Ús:
  python eligibility_scan.py --sample-size 2000 --threads 4 --seed 42
  python eligibility_scan.py --sample-size 200 --max-scanned 5000  # prova ràpida, esbiaixada

Output:
  data/eligibility_report_<N>_<run_id>.csv, data/funnel_summary_<N>_<run_id>.json
  data/failures.csv (registre estructurat de fallades)
"""

import os
import sys
import json
import random
import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

import errors
from errors import ErrorCategory


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Fitxers que NO compten com a "canvi real de dataset".
# Basat en la taxonomia dels canvis de Metadata.
NON_SUBSTANTIVE_FILES = {
    "README.md",
    ".gitattributes",
    "dataset_infos.json",
    ".gitignore",
    "LICENSE",
    "LICENSE.md",
    "CITATION.cff",
    ".github",
    ".gitmodules",
    "setup.py",
    "setup.cfg",
}

# Paraules clau als títols de commits que indiquen canvi purament documental.
# S'utilitzen com a heurística quan no tenim accés directe a la llista de fitxers.
NON_SUBSTANTIVE_TITLE_KEYWORDS = {
    "readme", "metadata", ".gitattributes", "dataset_infos",
    "license", "citation", "typo", "fix typo", "update docs",
}

MIN_SUBSTANTIVE_GAP_HOURS = 24.0

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FAILURES_LOG_PATH = os.path.join(OUTPUT_DIR, "failures.csv")

# Configuració de reintent. Es llegeix des de classify_dataset() a cada crida,
# per això viu com a estat de mòdul en lloc de passar-se explícitament
# per tota la cadena de crides paral·leles.
RETRY_CONFIG: dict = {
    "max_retries": errors.DEFAULT_MAX_RETRIES,
    "base_wait_s": errors.DEFAULT_BASE_WAIT_S,
    "max_wait_s": errors.DEFAULT_MAX_WAIT_S,
}

# Inicialització de l'API
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
    sys.exit(1)

api = HfApi(token=HF_TOKEN)
log.info("Token HF carregat correctament.")

def iter_all_dataset_ids():
    """
    Itera TOTA la població de datasets de HF sense cap ordenació, retornant
    NOMÉS l'identificador (string) de cada dataset -- mai l'objecte
    `DatasetInfo` complet ni cap altre camp.

    S'usa `expand=["disabled"]` perquè `list_datasets()` només torni
    `id`/`disabled`/`trending_score` en lloc del payload complet per
    dataset (descripció, tags, card_data, sha, dates...), reduint
    dràsticament la transferència de dades durant un escaneig de ~950K
    datasets. Els datasets marcats com `disabled` es descarten aquí mateix,
    ja que `list_repo_refs`/`list_repo_commits` hi fallarien sempre.

    No pren paràmetres: itera tota la població disponible via l'`api`
    global (inicialitzada amb `HF_TOKEN` al carregar el mòdul).

    :return: generador que produeix un `str` (`dataset.id`, format
        `owner/name`) per cada dataset habilitat de la població. Si
        `list_datasets()` llança una excepció (p.e. error de xarxa durant
        la paginació), es registra amb `log.error` i el generador
        s'atura silenciosament (no la repropaga): el cridant rep tots els
        datasets vistos fins al moment del tall, no una excepció.
    """
    try:
        for dataset in api.list_datasets(limit=None, expand=["disabled"]):
            if dataset.disabled:
                continue
            yield dataset.id
    except Exception as exc:
        log.error(f"Error iterant datasets: {exc}")


def reservoir_sample_dataset_ids(
    dataset_iter: Iterable,
    sample_size: int,
    max_scanned: int | None = None,
    rng: random.Random | None = None,
    show_progress: bool = True,
) -> tuple[list[str], int]:
    """
    Algorisme R de Vitter: mostreig aleatori uniforme sobre tota la població.
    Cada dataset té igual probabilitat = sample_size / N de ser seleccionat.

    El reservori conté NOMÉS identificadors (strings), mai l'objecte
    complet: si `dataset_iter` produeix objectes amb atribut `.id` (com el
    `DatasetInfo` de `huggingface_hub`), se n'extreu l'id immediatament i
    la resta de l'objecte queda sense referències -- mantenir-los vius
    durant un escaneig de fins a ~950K datasets multiplicaria
    innecessàriament la memòria pic.

    :param dataset_iter: iterador/generador de datasets (objectes amb
        atribut `.id`) o ja d'ids (`str`); no es materialitza mai a una
        llista completa, es consumeix element a element.
    :param sample_size: mida del reservori final (nombre de datasets a
        seleccionar). Si la població té menys elements que `sample_size`,
        el reservori final els conté tots.
    :param max_scanned: límit opcional de datasets a escanejar abans
        d'aturar-se (proves ràpides). ``None`` (per defecte) escaneja tota
        la població, imprescindible per a un mostreig no esbiaixat.
    :param rng: font d'aleatorietat determinista opcional (`random.Random`
        amb llavor fixa, per tests reproduïbles); si no es passa, s'usa el
        mòdul `random` global (no determinista entre execucions sense
        `--seed`).
    :param show_progress: si `True` (per defecte), mostra una barra `tqdm`
        amb el progrés de l'escaneig. Es desactiva als tests unitaris per
        no acoblar l'algorisme pur a una dependència d'interfície.
    :return: tupla ``(reservoir, n_seen)`` on ``reservoir`` és la
        `list[str]` d'ids seleccionats (longitud `min(sample_size, n_seen)`)
        i ``n_seen`` és el nombre total de datasets escanejats (mida real
        de la població, o `max_scanned` si s'ha aturat abans).
    """
    rng = rng or random
    reservoir: list[str] = []
    n_seen = 0

    pbar = None
    if show_progress:
        pbar = tqdm(
            desc=f"Escaneig reservoir sampling (objectiu: {sample_size} datasets)",
            unit=" datasets", dynamic_ncols=True,
        )

    try:
        for item in dataset_iter:
            n_seen += 1
            dataset_id = item.id if hasattr(item, "id") else str(item)

            if len(reservoir) < sample_size:
                reservoir.append(dataset_id)
            else:
                j = rng.randint(0, n_seen - 1)
                if j < sample_size:
                    reservoir[j] = dataset_id

            if pbar is not None:
                pbar.update(1)
                pbar.set_postfix({"reservori": len(reservoir), "vist": n_seen})

            if max_scanned and n_seen >= max_scanned:
                break
    finally:
        if pbar is not None:
            pbar.close()

    log.info(f"Escaneig completat: {n_seen} datasets vistos, {len(reservoir)} a la mostra.")
    return reservoir, n_seen

def classify_dataset(dataset_id: str, tags_only: bool = False) -> dict:
    """
    Determina si un dataset és elegible per a l'estudi (>=2 "versions
    reals") segons dos criteris independents:

    Criteri A: >= 2 tags de Git (versionat explícit, com en el paper dels
               LLM) I >= 2 commits substantius (mateix llindar que el
               Criteri B). El segon requisit cobreix el cas (improbable)
               d'un dataset amb >=2 tags on els commits associats només
               toquen README/metadades: sense prou commits substantius,
               els tags no representen canvis reals de dataset i no
               compten com a Criteri A. Excepció: en mode `tags_only=True`
               només es demana >=2 tags (vegeu més avall).
    Criteri B: >= 2 branches I >= 2 commits substancials (canvis reals de
               dataset, no purament documentals) SEPARATS EN EL TEMPS per
               almenys `MIN_SUBSTANTIVE_GAP_HOURS` hores

    Els commits es consideren substancials si el títol no conté paraules
    clau de pur manteniment/documentació (`is_substantive_commit`).

    Si `tags_only=True`, només s'avalua el Criteri A ORIGINAL (>=2 tags,
    sense verificar commits substantius; una sola crida a l'API): útil per
    fer un escaneig complet més ràpid i amb molt menys risc de rate
    limiting quan només interessa una estimació ràpida.

    :param dataset_id: identificador del dataset a classificar, format
        `owner/name` (p.e. `"allenai/c4"`).
    :param tags_only: si `True`, avalua només el Criteri A original (>=2
        tags, sense verificar commits substantius ni consultar el Criteri
        B): una sola crida a l'API (`list_repo_refs`), sense la crida
        addicional a `list_repo_commits`. Pensat per a escanejos on
        interessa minimitzar el rate limiting a costa de perdre precisió
        (no detecta elegibilitat via Criteri B, ni verifica que els tags
        estiguin backats per canvis reals).
    :return: diccionari amb els camps del CSV final:
        - dataset_id (str): l'id rebut per paràmetre.
        - num_tags (int): nombre de tags trobats (0 si ha fallat abans
          d'obtenir-los).
        - num_branches (int): nombre de branches trobades.
        - num_commits_substantive (int): nombre de commits substantius
          comptats fins al moment de decidir l'elegibilitat (o fins a 50
          commits revisats si no s'ha trobat prou evidència).
        - eligible (bool): `True` si compleix el Criteri A o el B.
        - eligibility_reason (str): text explicant per quin criteri
          (o per què no) s'ha decidit l'elegibilitat.
        - status (str): "classified" (èxit, elegible o no),
          "access_restricted" (403) o "error" (qualsevol altra
          fallada definitiva). SEMPRE present, també en cas d'èxit: si cap
          fila d'un lot tingués aquesta clau absent, `pd.DataFrame(rows)`
          no tindria la columna "status" i `write_results` fallaria amb
          `KeyError` en fer-hi `df["status"] == ...`.
        - error_category (str): valor de `errors.ErrorCategory` si hi
          ha hagut una fallada; `""` en cas d'èxit.
        - error (str): missatge d'excepció truncat a 120 caràcters
          (el missatge complet es registra a `data/failures.csv` via
          `errors.append_failure_row`); `""` en cas d'èxit.
    """
    result = {
        "dataset_id": dataset_id,
        "num_tags": 0,
        "num_branches": 0,
        "num_commits_substantive": 0,
        "eligible": False,
        "eligibility_reason": "",
        "status": "classified",
        "error_category": "",
        "error": "",
    }

    try:
        refs = errors.with_retry(
            list_repo_refs, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
            **RETRY_CONFIG,
        )
        tags = refs.tags if refs.tags else []
        branches = refs.branches if refs.branches else []
        result["num_tags"] = len(tags)
        result["num_branches"] = len(branches)

        if len(tags) >= 2 and tags_only:
            result["eligible"] = True
            result["eligibility_reason"] = "Criteri A: tags>=2"
            return result

        if tags_only:
            result["eligibility_reason"] = "ineligible: tags<2 (tags_only, Criteri B omès)"
            return result

        commits_scanned = 0
        num_commits_substantive = 0
        substantive_commit_times: list[datetime | None] = []

        # NOTA: només consultem els commits si tenim >=2 tags (Criteri A) o
        # >=2 branches (Criteri B), evitant una crida i iteració senceres
        # quan no poden canviar el resultat. Per al Criteri A, no n'hi ha
        # prou amb tenir >=2 tags: cal que almenys un commit sigui
        # substantiu, per cobrir el cas (improbable) d'un dataset amb
        # versions etiquetades on tots els commits només toquen
        # README/metadades.
        if len(tags) >= 2 or len(branches) >= 2:
            commits_iter = errors.with_retry(
                list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
                **RETRY_CONFIG,
            )
            for commit in commits_iter:
                commits_scanned += 1

                if is_substantive_commit(commit.title):
                    num_commits_substantive += 1
                    substantive_commit_times.append(getattr(commit, "created_at", None))

                if len(tags) >= 2 and num_commits_substantive >= 2:
                    result["eligible"] = True
                    result["eligibility_reason"] = "Criteri A: tags>=2 amb commits substantius"
                    result["num_commits_substantive"] = num_commits_substantive
                    return result

                if len(branches) >= 2 and has_time_dispersed_substantive_commits(
                    substantive_commit_times
                ):
                    result["eligible"] = True
                    result["eligibility_reason"] = (
                        "Criteri B: substantive_commits>=2 dispersos "
                        f">={MIN_SUBSTANTIVE_GAP_HOURS}h"
                    )
                    result["num_commits_substantive"] = num_commits_substantive
                    return result

                if commits_scanned >= 50:
                    break

        result["num_commits_substantive"] = num_commits_substantive
        result["eligibility_reason"] = (
            "ineligible: tags<2 i "
            f"(branches<2 o substantive_commits<2 amb {commits_scanned} commits revisats)"
        )

    except Exception as exc:
        category = errors.classify_error(exc)
        retries_attempted = RETRY_CONFIG["max_retries"] if category in errors.RETRIED_CATEGORIES else 0

        result["error_category"] = category.value
        result["error"] = str(exc)[:120]
        result["status"] = (
            "access_restricted" if category == ErrorCategory.ACCESS_RESTRICTED else "error"
        )

        errors.append_failure_row(
            FAILURES_LOG_PATH,
            dataset_id=dataset_id,
            category=category,
            message=str(exc),
            retries_attempted=retries_attempted,
            source="sampling",
        )

    return result


def is_substantive_commit(commit_title: str) -> bool:
    """
    Avalua si un commit representa un canvi real de dataset (no purament
    documental/de manteniment), a partir d'una heurística sobre el títol:
    `False` si el títol (en minúscules) conté alguna de les paraules clau
    de `NON_SUBSTANTIVE_TITLE_KEYWORDS` (p.e. "readme", "typo", "license").

    :param commit_title: títol del commit tal com el retorna l'API de HF
        (`commit.title`). Pot ser `None` o buit.
    :return: `True` si el commit sembla substantiu (cap paraula clau de
        manteniment/documentació al títol); `False` si el títol és buit/
        `None` o conté alguna d'aquestes paraules clau.
    """
    if not commit_title:
        return False

    title_lower = commit_title.lower()

    for keyword in NON_SUBSTANTIVE_TITLE_KEYWORDS:
        if keyword in title_lower:
            return False

    return True


def has_time_dispersed_substantive_commits(
    commit_times: list[datetime | None], min_gap_hours: float = MIN_SUBSTANTIVE_GAP_HOURS
) -> bool:
    """
    Determina si una llista de dates de commits substantius (segons
    `is_substantive_commit`) representa actualitzacions prou separades en
    el temps per considerar-se "versions" diferenciades, en lloc d'una
    única sessió de pujada/creació.

    :param commit_times: dates (`datetime`) dels commits ja considerats
        substantius, en qualsevol ordre. Els elements `None` (l'API no
        sempre proporciona `created_at`) s'ignoren.
    :param min_gap_hours: separació mínima, en hores, exigida entre el
        commit substantiu més antic i el més recent de la llista.
    :return: `True` si hi ha almenys 2 dates vàlides I la diferència entre
        la més antiga i la més recent és >= `min_gap_hours`; `False` en
        cas contrari (incloent-hi el cas de menys de 2 dates vàlides).
    """
    valid_times = [t for t in commit_times if t is not None]
    if len(valid_times) < 2:
        return False

    span = max(valid_times) - min(valid_times)
    return span >= timedelta(hours=min_gap_hours)


def classify_dataset_safe(args: tuple) -> dict | None:
    """
    Wrapper de `classify_dataset` segur per a execució paral·lela amb
    `ThreadPoolExecutor`: captura qualsevol excepció NO prevista per
    `classify_dataset` (que ja gestiona internament els errors esperats
    de l'API) perquè un fallo inesperat en un thread no aturi tot el pool.

    :param args: tupla ``(idx, dataset_id, tags_only)`` on ``idx`` és un
        índex només per a fins de logging (identificar quin element del
        lot ha fallat), ``dataset_id`` és l'id a classificar i
        ``tags_only`` es passa tal qual a `classify_dataset`.
    :return: el `dict` retornat per `classify_dataset`, o `None` si s'ha
        capturat una excepció inesperada (es registra amb `log.warning`;
        el cridant (`run_sampling`) descarta les files `None` del resultat
        final).
    """
    idx, dataset_id, tags_only = args
    try:
        return classify_dataset(dataset_id, tags_only=tags_only)
    except Exception as exc:
        log.warning(f"[{idx}] Error inesperat classificant {dataset_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Estadístiques agregades de l'embut d'elegibilitat
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FunnelCounts:
    """
    Recompte brut d'un escaneig/mostreig, abans de calcular proporcions.
    Entrada de `compute_funnel_stats`.

    :ivar total_scanned: mida de la població escanejada durant la Fase 1
        (reservoir sampling), no la mida de la mostra classificada.
    :ivar eligible: nombre de datasets classificats amb èxit i elegibles
        (Criteri A o B).
    :ivar ineligible: nombre de datasets classificats amb èxit però NO
        elegibles.
    :ivar access_restricted: nombre de datasets amb `status ==
        "access_restricted"` (403; vegeu "DISSENY: 403" a `errors.py`).
    :ivar errors: nombre de datasets amb `status == "error"` (qualsevol
        altra fallada definitiva: 429 esgotat, 404, transitori esgotat,
        desconegut).
    """

    total_scanned: int
    eligible: int
    ineligible: int
    access_restricted: int
    errors: int


def compute_funnel_stats(counts: FunnelCounts) -> dict:
    """
    Calcula les mètriques agregades de l'embut d'elegibilitat amb els
    denominadors correctes.

    `eligible_proportion` EXCLOU els datasets amb accés restringit i els que
    han fallat definitivament (errors) del denominador, ja que cap dels dos
    representa una classificació d'elegibilitat vàlida: incloure'ls
    esbiaixa a la baixa l'estimació de la proporció real d'elegibles (era
    exactament el bug abans d'aquest disseny: `errors` es comptava dins
    del `total` usat per calcular la proporció).

    `eligible_proportion_of_attempts` és una mètrica secundària que SÍ
    inclou tots els intents (útil per veure quin percentatge de la mostra
    es pot classificar amb èxit, és a dir, la taxa d'èxit de l'scan).

    `estimated_eligible_in_population` extrapola `eligible_proportion` a
    tota la població escanejada (`total_scanned`), assumint que els
    datasets amb accés restringit o error tenen, en proporció,
    elegibilitat similar als que sí s'han pogut classificar (amenaça a la
    validesa a documentar a la memòria: no hi ha manera de verificar-ho
    sense poder-hi accedir).

    :param counts: recompte brut (`FunnelCounts`) d'un escaneig o mostreig.
    :return: diccionari amb les claus ``eligible``, ``ineligible``,
        ``access_restricted``, ``errors`` (còpia directa dels camps de
        `counts`), més les mètriques derivades ``eligible_proportion``,
        ``eligible_proportion_of_attempts`` i
        ``estimated_eligible_in_population`` descrites més amunt. Totes
        les proporcions retornen ``0.0``/``0`` (en lloc de llançar
        `ZeroDivisionError`) quan el denominador corresponent és 0.
    """
    denom_valid = counts.eligible + counts.ineligible
    denom_attempts = denom_valid + counts.access_restricted + counts.errors

    eligible_proportion = round(counts.eligible / denom_valid, 4) if denom_valid else 0.0

    return {
        "eligible": counts.eligible,
        "ineligible": counts.ineligible,
        "access_restricted": counts.access_restricted,
        "errors": counts.errors,
        "eligible_proportion": eligible_proportion,
        "eligible_proportion_of_attempts": (
            round(counts.eligible / denom_attempts, 4) if denom_attempts else 0.0
        ),
        "estimated_eligible_in_population": (
            int(round(eligible_proportion * counts.total_scanned)) if denom_valid else 0
        ),
    }

def get_next_run_id(output_dir: str, sample_size: int) -> int:
    """
    Determina el següent número de run per a un `sample_size` donat,
    inspeccionant els fitxers `funnel_summary_<sample_size>_<run_id>.json`
    ja existents a `output_dir`, perquè cada execució amb la mateixa mida
    de mostra generi sortides numerades sense sobreescriure les anteriors.

    :param output_dir: directori on es guarden els resultats (`OUTPUT_DIR`).
    :param sample_size: mida de mostra de l'execució actual; només es
        consideren els fitxers amb aquest `sample_size` al nom.
    :return: el `run_id` més alt trobat + 1 (o ``1`` si no hi ha cap
        fitxer previ amb aquest `sample_size`).
    """
    max_id = 0
    prefix = f"funnel_summary_{sample_size}_"

    for filename in os.listdir(output_dir):
        if filename.startswith(prefix) and filename.endswith(".json"):
            try:
                id_str = filename[len(prefix):-5]
                current_id = int(id_str)
                if current_id > max_id:
                    max_id = current_id
            except ValueError:
                pass

    return max_id + 1


def write_results(rows: list[dict], run_id: int, sample_size: int, total_scanned: int) -> tuple[str, str, dict]:
    """
    Escriu el CSV amb una fila per dataset classificat i el JSON amb el
    resum agregat de l'embut d'elegibilitat.

    :param rows: llista de diccionaris retornats per `classify_dataset`
        (un per dataset classificat amb èxit dins del pool de threads; les
        entrades `None` de `classify_dataset_safe` ja s'han filtrat abans
        de cridar aquesta funció).
    :param run_id: número de run (de `get_next_run_id`), s'incorpora al
        nom dels fitxers de sortida per no sobreescriure execucions
        prèvies amb el mateix `sample_size`.
    :param sample_size: mida de mostra sol·licitada (s'incorpora al nom
        dels fitxers de sortida; pot diferir de ``len(rows)`` si la
        població real era més petita que la mostra sol·licitada).
    :param total_scanned: mida de la població escanejada a la Fase 1
        (reservoir sampling), usada com a denominador per a
        `estimated_eligible_in_population`.
    :return: tupla ``(csv_path, json_path, summary)`` on ``csv_path`` i
        ``json_path`` són les rutes absolutes dels fitxers escrits
        (`data/eligibility_report_<sample_size>_<run_id>.csv` i
        `data/funnel_summary_<sample_size>_<run_id>.json`) i ``summary``
        és el diccionari de resum (el mateix que s'escriu al JSON):
        metadades de l'execució (`timestamp`, `sampling_method`,
        `sample_size`, `population_scanned`), recomptes per criteri
        (`eligible_total`, `eligible_Criteri_A`, `eligible_Criteri_B`) i
        totes les mètriques de `compute_funnel_stats`.
    """
    df = pd.DataFrame(rows)

    csv_path = os.path.join(OUTPUT_DIR, f"eligibility_report_{sample_size}_{run_id}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8")

    total = len(rows)
    eligible = int(df["eligible"].sum())
    access_restricted = int((df["status"] == "access_restricted").sum())
    error_count = int((df["status"] == "error").sum())
    ineligible = total - eligible - access_restricted - error_count

    counts = FunnelCounts(
        total_scanned=total_scanned,
        eligible=eligible,
        ineligible=ineligible,
        access_restricted=access_restricted,
        errors=error_count,
    )

    summary = {
        "timestamp": datetime.now().isoformat(),
        "sampling_method": "reservoir_sampling_R_Vitter_uniform_no_bias",
        "sample_size": total,
        "population_scanned": total_scanned,
        "eligible_total": eligible,
        "eligible_Criteri_A": int(df["eligibility_reason"].str.startswith("Criteri A").sum()),
        "eligible_Criteri_B": int(df["eligibility_reason"].str.startswith("Criteri B").sum()),
        **compute_funnel_stats(counts),
    }

    json_path = os.path.join(OUTPUT_DIR, f"funnel_summary_{sample_size}_{run_id}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return csv_path, json_path, summary


# ---------------------------------------------------------------------------
# Orquestrador — Mode mostreig
# ---------------------------------------------------------------------------

def run_sampling(sample_size: int, max_scanned: int | None, num_threads: int, tags_only: bool = False) -> None:
    """
    Orquestrador principal: executa l'embut complet en tres fases --
    (1) reservoir sampling sobre tota la població, (2) classificació
    paral·lela de la mostra amb `classify_dataset_safe`, (3) escriptura
    de resultats amb `write_results` -- i n'imprimeix un resum per
    consola.

    :param sample_size: mida de la mostra a classificar (mida del
        reservori; vegeu `reservoir_sample_dataset_ids`).
    :param max_scanned: límit opcional de datasets a escanejar a la Fase 1
        (proves ràpides, esbiaixat). ``None`` per a un mostreig complet i
        no esbiaixat (recomanat per a l'estimació principal).
    :param num_threads: nombre de threads del `ThreadPoolExecutor` per a
        la Fase 2 (classificació). Més threads = més paral·lelisme però
        més pressió sobre l'API i més risc de 429 (vegeu "DISSENY: 429" a
        `errors.py`).
    :param tags_only: es passa tal qual a `classify_dataset` per a cada
        dataset de la mostra (vegeu la documentació d'aquest paràmetre a
        `classify_dataset`).
    :return: None. Efectes: escriu `data/eligibility_report_*.csv` i
        `data/funnel_summary_*.json` (via `write_results`), pot escriure
        `data/failures.csv` (via `classify_dataset`/`errors.append_failure_row`
        per cada fallada), i imprimeix un resum de l'embut per consola.
    """
    log.info(f"FASE 1: Reservoir sampling (objectiu={sample_size}, max_scanned={max_scanned})")
    dataset_ids, total_scanned = reservoir_sample_dataset_ids(
        iter_all_dataset_ids(), sample_size, max_scanned
    )
    log.info(f"Mostra obtinguda: {len(dataset_ids)} datasets de {total_scanned} escanejats.")

    log.info(f"FASE 2: Classificant elegibilitat ({num_threads} threads, tags_only={tags_only})...")
    indexed = [(i, ds_id, tags_only) for i, ds_id in enumerate(dataset_ids)]
    rows: list[dict] = []

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(classify_dataset_safe, item): item for item in indexed}
        with tqdm(total=len(indexed), desc="Classificant datasets", unit=" ds") as pbar:
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    rows.append(result)
                pbar.update(1)
                pbar.set_postfix({"elegibles": sum(1 for r in rows if r["eligible"])})

    log.info(f"Classificació completada: {len(rows)} datasets processats.")

    log.info("FASE 3: Escrivint resultats...")
    run_id = get_next_run_id(OUTPUT_DIR, sample_size)
    csv_path, json_path, summary = write_results(rows, run_id, sample_size, total_scanned)

    print(f"\n{'='*65}")
    print(f"  RESUM EMBUT — mostra de {summary['sample_size']} datasets aleatoris")
    print(f"{'='*65}")
    for k, v in summary.items():
        print(f"  {k:<40} {v}")
    print(f"{'='*65}")
    print(f"\n  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")
    print(f"  Fallades (detall): {FAILURES_LOG_PATH}\n")


# ---------------------------------------------------------------------------
# Punt d'entrada amb argparse
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """
    Defineix i parseja els arguments de la CLI. Sense arguments, mostra
    l'ajuda i surt (`sys.exit(0)`) en lloc d'executar amb els valors per
    defecte, perquè una crida accidental sense arguments no encengui una
    execució llarga per error. `-h`/`--help` ja el gestiona `argparse`
    automàticament (no cal cap comprovació manual addicional).

    Cada flag es documenta al seu `help=` (visible amb `--help`); no es
    repeteix aquí per no duplicar-ho en dos llocs.

    :return: `argparse.Namespace` amb tots els arguments parsejats
        (`tags_only`, `sample_size`, `max_scanned`, `threads`, `seed`,
        `retry_max_attempts`, `retry_base_wait`, `retry_max_wait`).
    """
    parser = argparse.ArgumentParser(
        description="Filtratge de datasets de HF mitjançant mostreig (reservoir sampling).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--tags-only", action="store_true",
        help="Avalua només el Criteri A (tags). Una crida per dataset, molt menys rate limiting.",
    )
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=2000,
        help=(
            "Nombre de datasets a incloure a la mostra final (reservoir size). "
            "Per defecte 2000: marge d'error ±0.51pp a 95%% de confiança, "
            "assumint p=0.0137 (proporció real observada, vegeu README)."
        ),
    )
    parser.add_argument(
        "--max-scanned", "-m",
        type=int,
        default=None,
        help=(
            "Límit de datasets a escanejar en total. "
            "Útil per a proves ràpides. Sense valor = escaneig complet."
        ),
    )
    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=4,
        help="Nombre de threads per al processament paral·lel de la classificació.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Llavor aleatòria per a reproduïbilitat (opcional).",
    )
    parser.add_argument(
        "--retry-max-attempts",
        type=int,
        default=errors.DEFAULT_MAX_RETRIES,
        help="Nombre màxim de reintents davant rate limiting (429) o errors transitoris.",
    )
    parser.add_argument(
        "--retry-base-wait",
        type=float,
        default=errors.DEFAULT_BASE_WAIT_S,
        help="Espera inicial (segons) abans del primer reintent; es duplica a cada intent.",
    )
    parser.add_argument(
        "--retry-max-wait",
        type=float,
        default=errors.DEFAULT_MAX_WAIT_S,
        help="Espera màxima (segons) entre reintents (topall del backoff exponencial).",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        log.info(f"Llavor aleatòria fixada a {args.seed} per a reproduïbilitat.")

    RETRY_CONFIG.update(
        max_retries=args.retry_max_attempts,
        base_wait_s=args.retry_base_wait,
        max_wait_s=args.retry_max_wait,
    )

    run_sampling(
        sample_size=args.sample_size,
        max_scanned=args.max_scanned,
        num_threads=args.threads,
        tags_only=args.tags_only,
    )
