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

MODES D'EXECUCIÓ:
  Mostreig (estimar proporció de la població):
    python eligibility_scan.py --sample-size 1000 --threads 4 --seed 42
    python eligibility_scan.py --sample-size 200 --max-scanned 5000

  Escaneig complet (llista exhaustiva, amb checkpoint/resume):
    python eligibility_scan.py --full-scan --threads 4
    python eligibility_scan.py --full-scan --resume
    python eligibility_scan.py --full-scan --tags-only --threads 4  # Criteri A únicament

Output:
  Mostreig:      data/eligibility_report_<N>_<run_id>.csv, data/funnel_summary_<N>_<run_id>.json
  Escaneig total: data/full_scan_eligible.csv, data/full_scan_stats.json, data/full_scan_checkpoint.txt
  Ambdós modes:  data/failures.csv (registre estructurat de fallades, compartit entre execucions)
"""

import os
import sys
import json
import random
import argparse
import logging
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
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

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "full_scan_checkpoint.txt")
FULL_SCAN_CSV = os.path.join(OUTPUT_DIR, "full_scan_eligible.csv")
FULL_SCAN_STATS = os.path.join(OUTPUT_DIR, "full_scan_stats.json")
FAILURES_LOG_PATH = os.path.join(OUTPUT_DIR, "failures.csv")

# Configuració de reintent. Es llegeix des de classify_dataset() a cada crida,
# per això viu com a estat de mòdul en lloc de passar-se explícitament
# per tota la cadena de crides paral·leles.
RETRY_CONFIG: dict = {
    "max_retries": errors.DEFAULT_MAX_RETRIES,
    "base_wait_s": errors.DEFAULT_BASE_WAIT_S,
    "max_wait_s": errors.DEFAULT_MAX_WAIT_S,
}

# "sampling" o "full_scan"; només s'usa per etiquetar les files del registre
# de fallades i saber de quin mode d'execució provenen.
CURRENT_SOURCE = "sampling"

# Inicialització de l'API
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
    sys.exit(1)

api = HfApi(token=HF_TOKEN)
log.info("Token HF carregat correctament.")


# ---------------------------------------------------------------------------
# Fase 1: Iteració i reservoir sampling (només ids, no objectes complets)
# ---------------------------------------------------------------------------

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
    Args:
        dataset_iter: iterador/generador de datasets o ids (no es
            materialitza mai a una llista completa).
        sample_size: mida del reservori final.
        max_scanned: límit opcional de datasets a escanejar (proves ràpides).
        rng: font d'aleatorietat determinista opcional (per tests
            reproduïbles); si no es passa, s'usa el mòdul `random` global.
        show_progress: mostra una barra `tqdm`. Es desactiva als tests per
            no acoblar l'algorisme a una dependència d'interfície.

    Returns:
        (reservoir, n_seen): mostra final (ids) i total de datasets escanejats.
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


# ---------------------------------------------------------------------------
# Fase 2: Classificació d'elegibilitat per dataset
# ---------------------------------------------------------------------------

def classify_dataset(dataset_id: str, tags_only: bool = False) -> dict:
    """
    Criteri A: >= 2 tags de Git (versionat explícit, com en el paper dels LLM).
    Criteri B: >= 2 branches I >= 2 commits substancials (canvis reals de
               dataset, no purament documentals). Els commits es consideren
               substancials si el títol no conté paraules clau de pur
               manteniment/documentació.

    Si `tags_only=True`, només s'avalua el Criteri A (una sola crida a
    l'API): útil per fer un escaneig complet més ràpid i amb molt menys risc
    de rate limiting quan només interessa una estimació ràpida.

    Totes les crides a l'API es reintenten automàticament amb backoff
    exponencial davant rate limiting (`errors.with_retry`). Si després
    d'exhaurir els reintents (o davant un error no reintentable com 403/404)
    la crida falla definitivament, l'excepció es classifica amb
    `errors.classify_error` i es registra a `data/failures.csv`.

    Retorna un diccionari amb tots els camps per al CSV final. `status` és
    sempre present ("classified", "access_restricted" o "error"): cal
    fixar-lo explícitament també en el cas d'èxit, perquè si CAP fila d'un
    lot té un error, `pd.DataFrame(rows)["status"]` no existiria (columna
    absent -> KeyError a `write_results`).
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

        if len(tags) >= 2:
            result["eligible"] = True
            result["eligibility_reason"] = "Criteri A: tags>=2"
            return result

        if tags_only:
            result["eligibility_reason"] = "ineligible: tags<2 (tags_only, Criteri B omès)"
            return result

        commits_scanned = 0
        num_commits_substantive = 0

        # NOTA: només consultem els commits si ja sabem que hi ha prou
        # branches per considerar-los "versions reals" (Criteri B), evitant
        # una crida i iteració senceres quan no poden canviar el resultat.
        if len(branches) >= 2:
            commits_iter = errors.with_retry(
                list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
                **RETRY_CONFIG,
            )
            for commit in commits_iter:
                commits_scanned += 1

                if is_substantive_commit(commit.title):
                    num_commits_substantive += 1

                if num_commits_substantive >= 2:
                    result["eligible"] = True
                    result["eligibility_reason"] = "Criteri B: substantive_commits>=2"
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
            source=CURRENT_SOURCE,
        )

    return result


def is_substantive_commit(commit_title: str) -> bool:
    """
    Avalua si un commit és substancial.
    Retorna False si el títol conté paraules clau de pur manteniment/documentació.
    """
    if not commit_title:
        return False

    title_lower = commit_title.lower()

    for keyword in NON_SUBSTANTIVE_TITLE_KEYWORDS:
        if keyword in title_lower:
            return False

    return True


def classify_dataset_safe(args: tuple) -> dict | None:
    """Wrapper segur per a execució paral·lela amb ThreadPoolExecutor."""
    idx, dataset_id, tags_only = args
    try:
        return classify_dataset(dataset_id, tags_only=tags_only)
    except Exception as exc:
        log.warning(f"[{idx}] Error inesperat classificant {dataset_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Checkpoint i persistència incremental (per a l'escaneig complet)
# ---------------------------------------------------------------------------

def load_checkpoint(path: str | Path) -> set[str]:
    """Retorna el conjunt d'ids ja processats en una execució anterior."""
    path = Path(path)
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def append_checkpoint(path: str | Path, dataset_id: str) -> None:
    """Marca un dataset com a processat (una línia per id, append-only)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(dataset_id + "\n")


def append_result_row(path: str | Path, row: dict) -> None:
    """Afegeix una fila de resultat a un CSV, escrivint la capçalera si cal."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    pd.DataFrame([row]).to_csv(path, mode="a", header=not exists, index=False, encoding="utf-8")


def save_scan_stats(path: str | Path, stats: dict) -> None:
    """Sobreescriu el fitxer d'estadístiques amb l'estat agregat actual."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Estadístiques agregades de l'embut d'elegibilitat
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FunnelCounts:
    """Recompte brut d'un escaneig/mostreig, abans de calcular proporcions."""

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
    esbiaixa a la baixa l'estimació de la proporció real d'elegibles.

    `eligible_proportion_of_attempts` és una mètrica secundària, de
    transparència, que SÍ inclou tots els intents (útil per veure quin
    percentatge de la mostra es va poder classificar amb èxit).
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


# ---------------------------------------------------------------------------
# Fase 3: Escriptura de resultats
# ---------------------------------------------------------------------------

def get_next_run_id(output_dir: str, sample_size: int) -> int:
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
    """Escriu el CSV i el JSON de resultats. Retorna les rutes dels fitxers."""
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
        "eligible_Criteri_A": int((df["eligibility_reason"] == "Criteri A: tags>=2").sum()),
        "eligible_Criteri_B": int(
            (df["eligibility_reason"] == "Criteri B: substantive_commits>=2").sum()
        ),
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
    """Executa l'embut complet: mostreig -> classificació paral·lela -> resultats."""
    global CURRENT_SOURCE
    CURRENT_SOURCE = "sampling"

    # --- Fase 1: Mostreig ---
    log.info(f"FASE 1: Reservoir sampling (objectiu={sample_size}, max_scanned={max_scanned})")
    dataset_ids, total_scanned = reservoir_sample_dataset_ids(
        iter_all_dataset_ids(), sample_size, max_scanned
    )
    log.info(f"Mostra obtinguda: {len(dataset_ids)} datasets de {total_scanned} escanejats.")

    # --- Fase 2: Classificació paral·lela ---
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

    # --- Fase 3: Resultats ---
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
# Orquestrador — Mode escaneig complet (amb checkpoint/resume)
# ---------------------------------------------------------------------------

def run_full_scan(num_threads: int, resume: bool, tags_only: bool = False) -> None:
    """
    Itera TOTS els datasets de HF, amb el mateix criteri d'elegibilitat que
    el mode mostreig (`classify_dataset`), però sense reservoir sampling.

    Persisteix incrementalment (checkpoint d'ids processats, CSV d'elegibles
    i JSON d'estadístiques actualitzat cada batch) per poder-se interrompre
    i reprendre sense perdre feina ni tornar a processar datasets ja fets.
    Només es guarden al CSV els datasets elegibles (el denominador real es
    manté a `full_scan_stats.json`) per no materialitzar centenars de
    milers de files quan només interessen els positius.
    """
    global CURRENT_SOURCE
    CURRENT_SOURCE = "full_scan"

    already_done = load_checkpoint(CHECKPOINT_FILE) if resume else set()
    if not resume:
        for path in (CHECKPOINT_FILE, FULL_SCAN_CSV, FULL_SCAN_STATS):
            if os.path.exists(path):
                os.remove(path)

    mode_str = "tags-only" if tags_only else "tags + commits"
    log.info(f"MODE ESCANEIG COMPLET (threads={num_threads}, mode={mode_str}, resume={resume})")

    n_total = n_eligible = n_ineligible = n_access_restricted = n_errors = 0
    if resume and os.path.exists(FULL_SCAN_STATS):
        with open(FULL_SCAN_STATS, encoding="utf-8") as f:
            prev = json.load(f)
        n_total = prev.get("n_total_scanned", 0)
        n_eligible = prev.get("eligible", 0)
        n_ineligible = prev.get("ineligible", 0)
        n_access_restricted = prev.get("access_restricted", 0)
        n_errors = prev.get("errors", 0)
        log.info(f"Reprèn des de: {n_total} processats, {n_eligible} elegibles.")

    BATCH_SIZE = num_threads * 8
    batch: list[tuple] = []

    def flush_batch(items: list[tuple]) -> None:
        nonlocal n_eligible, n_ineligible, n_access_restricted, n_errors
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {executor.submit(classify_dataset_safe, item): item for item in items}
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue
                append_checkpoint(CHECKPOINT_FILE, result["dataset_id"])
                if result["status"] == "access_restricted":
                    n_access_restricted += 1
                elif result["status"] == "error":
                    n_errors += 1
                elif result["eligible"]:
                    n_eligible += 1
                    append_result_row(FULL_SCAN_CSV, result)
                else:
                    n_ineligible += 1

        counts = FunnelCounts(
            total_scanned=n_total,
            eligible=n_eligible,
            ineligible=n_ineligible,
            access_restricted=n_access_restricted,
            errors=n_errors,
        )
        stats = {
            "timestamp": datetime.now().isoformat(),
            "completed": False,
            "tags_only": tags_only,
            "n_total_scanned": n_total,
            **compute_funnel_stats(counts),
        }
        save_scan_stats(FULL_SCAN_STATS, stats)

    with tqdm(desc="Escaneig complet", unit=" ds", dynamic_ncols=True) as pbar:
        for dataset_id in iter_all_dataset_ids():
            n_total += 1
            if dataset_id in already_done:
                pbar.update(1)
                continue

            batch.append((n_total, dataset_id, tags_only))

            if len(batch) >= BATCH_SIZE:
                flush_batch(batch)
                batch = []
                pbar.set_postfix({"elegibles": n_eligible, "total": n_total})
            pbar.update(1)

        if batch:
            flush_batch(batch)

    counts = FunnelCounts(
        total_scanned=n_total,
        eligible=n_eligible,
        ineligible=n_ineligible,
        access_restricted=n_access_restricted,
        errors=n_errors,
    )
    final_stats = {
        "timestamp": datetime.now().isoformat(),
        "completed": True,
        "tags_only": tags_only,
        "n_total_scanned": n_total,
        **compute_funnel_stats(counts),
    }
    save_scan_stats(FULL_SCAN_STATS, final_stats)

    log.info(f"Escaneig complet. Total: {n_total}, Elegibles: {n_eligible}")
    print(f"\n  Elegibles: {FULL_SCAN_CSV}")
    print(f"  Stats (denominador real): {FULL_SCAN_STATS}")
    print(f"  Fallades (detall): {FAILURES_LOG_PATH}\n")


# ---------------------------------------------------------------------------
# Punt d'entrada amb argparse
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filtratge de datasets de HF: mostreig o escaneig complet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--full-scan", action="store_true",
        help="Processa TOTS els datasets de HF en lloc de fer un mostreig.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="(Només amb --full-scan) Reprèn un escaneig interromput des del checkpoint.",
    )
    parser.add_argument(
        "--tags-only", action="store_true",
        help="Avalua només el Criteri A (tags). Una crida per dataset, molt menys rate limiting.",
    )
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=1000,
        help="Nombre de datasets a incloure a la mostra final (reservoir size).",
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

    if args.full_scan:
        run_full_scan(num_threads=args.threads, resume=args.resume, tags_only=args.tags_only)
    else:
        run_sampling(
            sample_size=args.sample_size,
            max_scanned=args.max_scanned,
            num_threads=args.threads,
            tags_only=args.tags_only,
        )
