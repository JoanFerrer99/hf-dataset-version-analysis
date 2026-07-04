"""
Anàlisi de la població de datasets de HuggingFace per determinar l'elegibilitat.

DOS MODES D'EXECUCIÓ:

  MODE 1 — Mostreig (per defecte):
    Reservoir sampling (algorisme R de Vitter) sobre TOTA la població.
    Objectiu: estimar la proporció d'elegibles sense processar tothom.

    python random_sample_analysis.py --sample-size 1000 --threads 4 --seed 42

  MODE 2 — Escaneig complet (--full-scan):
    Itera TOTS els datasets de HF i guarda els elegibles directament.
    Objectiu: obtenir la llista exhaustiva un cop coneguda la proporció.
    Inclou checkpoint: si s'interromp, es pot reprendre des del punt on era.

    python random_sample_analysis.py --full-scan --threads 8
    python random_sample_analysis.py --full-scan --resume  # reprèn si s'havia interromput

Criteri d'elegibilitat:
  Criteri A (principal): el repositori té >= 2 tags de Git.
  Criteri B (fallback):  el repositori té >= 2 branches I >= 2 commits
                         el títol dels quals no és purament documental.

Output:
  data/eligibility_report_<N>_<run_id>.csv   (mode mostreig)
  data/funnel_summary_<N>_<run_id>.json      (mode mostreig)
  data/full_scan_eligible.csv                (mode escaneig complet)
  data/full_scan_checkpoint.txt              (reprèn si s'interromp)
"""

import os
import sys
import json
import random
import argparse
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Nota: NON_SUBSTANTIVE_FILES (per contingut real del commit) es reserva per
# a la fase 2 del TFG quan accedirem als fitxers concrets de cada commit.
NON_SUBSTANTIVE_TITLE_KEYWORDS = {
    "readme", "metadata", ".gitattributes", "dataset_infos",
    "license", "citation", "typo", "fix typo", "update docs",
}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "full_scan_checkpoint.txt")
FULL_SCAN_CSV   = os.path.join(OUTPUT_DIR, "full_scan_eligible.csv")

# ---------------------------------------------------------------------------
# Inicialització de l'API (un sol cop, global)
# ---------------------------------------------------------------------------
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
    sys.exit(1)

api = HfApi(token=HF_TOKEN)
log.info("Token HF carregat correctament.")


# ---------------------------------------------------------------------------
# Iteració de la població completa
# ---------------------------------------------------------------------------

def iter_all_datasets():
    """
    Itera TOTA la població de datasets de HF sense cap ordenació.
    list_datasets() sense limit fa paginació automàtica internament.
    Genera datasets un a un (generator) → mai carrega tot a memòria.
    """
    try:
        for dataset in api.list_datasets():
            yield dataset
    except Exception as exc:
        log.error(f"Error iterant datasets: {exc}")


# ---------------------------------------------------------------------------
# Classificació d'elegibilitat
# ---------------------------------------------------------------------------

def is_substantive_commit(title: str) -> bool:
    """Retorna True si el títol del commit NO és purament documental."""
    if not title:
        return False
    title_lower = title.lower()
    return not any(kw in title_lower for kw in NON_SUBSTANTIVE_TITLE_KEYWORDS)


def classify_dataset(dataset_id: str) -> dict:
    """
    Determina si un dataset és elegible.

    Criteri A: >= 2 tags de Git (versionat explícit).
    Criteri B: >= 2 branches I >= 2 commits substantius (fallback).
    """
    result = {
        "dataset_id": dataset_id,
        "num_tags": 0,
        "num_branches": 0,
        "num_commits_substantive": 0,
        "eligible": False,
        "eligibility_reason": "",
        "error": "",
    }

    try:
        refs = list_repo_refs(repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN)
        tags     = refs.tags     if refs.tags     else []
        branches = refs.branches if refs.branches else []
        result["num_tags"]     = len(tags)
        result["num_branches"] = len(branches)

        # Criteri A: ràpid, retorna immediatament si es compleix
        if len(tags) >= 2:
            result["eligible"]            = True
            result["eligibility_reason"]  = "Criteri A: tags>=2"
            return result

        # Criteri B: només si hi ha >= 2 branches; limitem a 50 commits sempre
        if len(branches) >= 2:
            substantive = 0
            for i, commit in enumerate(
                list_repo_commits(repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN)
            ):
                if i >= 50:
                    break
                if is_substantive_commit(commit.title):
                    substantive += 1
                if substantive >= 2:
                    result["eligible"]                   = True
                    result["eligibility_reason"]         = "Criteri B: branches>=2 i substantive_commits>=2"
                    result["num_commits_substantive"]    = substantive
                    return result
            result["num_commits_substantive"] = substantive

    except Exception as exc:
        result["error"] = str(exc)[:120]

    return result


def classify_dataset_safe(args: tuple) -> dict | None:
    """Wrapper per a execució paral·lela. Captura excepcions inesperades."""
    idx, dataset_id = args
    try:
        return classify_dataset(dataset_id)
    except Exception as exc:
        log.warning(f"[{idx}] Error inesperat a {dataset_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Gestió de runs i resultats
# ---------------------------------------------------------------------------

def get_next_run_id(sample_size: int) -> int:
    """Retorna el pròxim run_id per evitar sobreescriure execucions anteriors."""
    max_id = 0
    prefix = f"funnel_summary_{sample_size}_"
    for fn in os.listdir(OUTPUT_DIR):
        if fn.startswith(prefix) and fn.endswith(".json"):
            try:
                max_id = max(max_id, int(fn[len(prefix):-5]))
            except ValueError:
                pass
    return max_id + 1


def write_results(
    rows: list[dict], run_id: int, sample_size: int, total_scanned: int
) -> tuple[str, str, dict]:
    """Escriu CSV + JSON de resultats del mode mostreig."""
    df = pd.DataFrame(rows)

    csv_path  = os.path.join(OUTPUT_DIR, f"eligibility_report_{sample_size}_{run_id}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"funnel_summary_{sample_size}_{run_id}.json")

    df.to_csv(csv_path, index=False, encoding="utf-8")

    total    = len(rows)
    eligible = int(df["eligible"].sum())

    summary = {
        "timestamp":            datetime.now().isoformat(),
        "mode":                 "sampling",
        "sampling_method":      "reservoir_sampling_R_Vitter_uniform_no_bias",
        "eligibility_criteria": "Criteri A: tags>=2 | Criteri B: branches>=2 AND substantive_commits>=2",
        "sample_size":          total,
        "population_scanned":   total_scanned,
        "with_any_tag":         int((df["num_tags"] > 0).sum()),
        "with_2plus_tags":      int((df["num_tags"] >= 2).sum()),
        "eligible_total":       eligible,
        "eligible_via_tags":    int((df["eligibility_reason"] == "Criteri A: tags>=2").sum()),
        "eligible_via_commits": int((df["eligibility_reason"].str.startswith("Criteri B")).sum()),
        "ineligible":           total - eligible - int((df["error"] != "").sum()),
        "errors":               int((df["error"] != "").sum()),
        "eligible_proportion":  round(eligible / total, 4) if total else 0,
        "estimated_eligible_in_population": (
            int(round((eligible / total) * total_scanned)) if total else 0
        ),
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return csv_path, json_path, summary


# ---------------------------------------------------------------------------
# MODE 1: Reservoir sampling
# ---------------------------------------------------------------------------

def reservoir_sample_datasets(
    sample_size: int, max_scanned: int | None = None
) -> tuple[list, int]:
    """Algorisme R de Vitter sobre la població completa."""
    reservoir: list = []
    n_seen = 0

    with tqdm(
        desc=f"Reservoir sampling (objectiu: {sample_size})",
        unit=" ds", dynamic_ncols=True
    ) as pbar:
        for dataset in iter_all_datasets():
            n_seen += 1
            if len(reservoir) < sample_size:
                reservoir.append(dataset)
            else:
                j = random.randint(0, n_seen - 1)
                if j < sample_size:
                    reservoir[j] = dataset

            pbar.update(1)
            pbar.set_postfix({"reservori": len(reservoir), "vistos": n_seen})

            if max_scanned and n_seen >= max_scanned:
                log.info(f"max_scanned={max_scanned} assolit.")
                break

    return reservoir, n_seen


def run_sampling(sample_size: int, max_scanned: int | None, num_threads: int) -> None:
    """Executa el mode mostreig complet."""
    log.info(f"MODE MOSTREIG: sample_size={sample_size}, max_scanned={max_scanned}")

    datasets, total_scanned = reservoir_sample_datasets(sample_size, max_scanned)
    dataset_ids = [d.id for d in datasets]
    log.info(f"Mostra: {len(dataset_ids)} datasets de {total_scanned} escanejats.")

    log.info(f"Classificant ({num_threads} threads)...")
    indexed = list(enumerate(dataset_ids))
    rows: list[dict] = []

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(classify_dataset_safe, item): item for item in indexed}
        with tqdm(total=len(indexed), desc="Classificant", unit=" ds") as pbar:
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    rows.append(result)
                pbar.update(1)
                pbar.set_postfix({"elegibles": sum(1 for r in rows if r["eligible"])})

    run_id = get_next_run_id(sample_size)
    csv_path, json_path, summary = write_results(rows, run_id, sample_size, total_scanned)

    print(f"\n{'='*65}")
    print(f"  RESUM — mostra de {summary['sample_size']} datasets aleatoris")
    print(f"{'='*65}")
    for k, v in summary.items():
        print(f"  {k:<45} {v}")
    print(f"{'='*65}")
    print(f"\n  CSV:  {csv_path}")
    print(f"  JSON: {json_path}\n")


# ---------------------------------------------------------------------------
# MODE 2: Escaneig complet amb checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint() -> set[str]:
    """Carrega els dataset_ids ja processats en una execució anterior."""
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE, encoding="utf-8") as f:
        ids = {line.strip() for line in f if line.strip()}
    log.info(f"Checkpoint: {len(ids)} datasets ja processats. Es reprèn des d'aquí.")
    return ids


def append_checkpoint(dataset_id: str) -> None:
    """Afegeix un dataset_id al fitxer de checkpoint (append, no sobreescriu)."""
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(dataset_id + "\n")


def append_eligible_row(row: dict) -> None:
    """Afegeix una fila elegible al CSV de resultats de forma incremental."""
    file_exists = os.path.exists(FULL_SCAN_CSV)
    df = pd.DataFrame([row])
    df.to_csv(FULL_SCAN_CSV, mode="a", header=not file_exists, index=False, encoding="utf-8")


def run_full_scan(num_threads: int, resume: bool) -> None:
    """
    Itera TOTS els datasets de HF i guarda els elegibles.

    La diferència clau respecte al mostreig és que aquí no hi ha reservori:
    processem cada dataset a mesura que arriba del generador, en blocs
    de `num_threads * 4` datasets, per no acumular massa futures en memòria.

    El checkpoint permet reprendre si l'execució s'interromp.
    """
    already_done: set[str] = load_checkpoint() if resume else set()
    if not resume and os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    if not resume and os.path.exists(FULL_SCAN_CSV):
        os.remove(FULL_SCAN_CSV)

    log.info(f"MODE ESCANEIG COMPLET (resume={resume}, threads={num_threads})")
    log.info("Iterant tota la població de HF sense límit...")

    # Mida del bloc de processament paral·lel
    BATCH_SIZE = num_threads * 8

    n_total   = 0
    n_eligible = 0
    batch: list[tuple[int, str]] = []

    def process_batch(b: list[tuple[int, str]]) -> None:
        nonlocal n_eligible
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {executor.submit(classify_dataset_safe, item): item for item in b}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    append_checkpoint(result["dataset_id"])
                    if result["eligible"]:
                        append_eligible_row(result)
                        n_eligible += 1

    with tqdm(desc="Escaneig complet", unit=" ds", dynamic_ncols=True) as pbar:
        for dataset in iter_all_datasets():
            ds_id = dataset.id
            n_total += 1

            if ds_id in already_done:
                pbar.update(1)
                continue

            batch.append((n_total, ds_id))

            if len(batch) >= BATCH_SIZE:
                process_batch(batch)
                batch = []
                pbar.set_postfix({"elegibles": n_eligible, "total": n_total})

            pbar.update(1)

        # Processar el darrer batch parcial
        if batch:
            process_batch(batch)

    log.info(f"Escaneig complet. Total: {n_total}, Elegibles: {n_eligible}")
    print(f"\n  Resultats guardats a: {FULL_SCAN_CSV}")
    print(f"  Checkpoint a: {CHECKPOINT_FILE}\n")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filtratge de datasets de HF: mostreig o escaneig complet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--full-scan", action="store_true",
        help="Mode escaneig complet: processa TOTS els datasets de HF.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="(Només --full-scan) Reprèn un escaneig complet interromput.",
    )
    parser.add_argument(
        "--sample-size", "-n", type=int, default=1000,
        help="(Mode mostreig) Mida de la mostra final.",
    )
    parser.add_argument(
        "--max-scanned", "-m", type=int, default=None,
        help="(Mode mostreig) Límit de datasets a escanejar. Sense valor = tot.",
    )
    parser.add_argument(
        "--threads", "-t", type=int, default=4,
        help="Nombre de threads paral·lels per a la classificació.",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="(Mode mostreig) Llavor aleatòria per a reproduïbilitat.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        log.info(f"Llavor aleatòria: {args.seed}")

    if args.full_scan:
        run_full_scan(num_threads=args.threads, resume=args.resume)
    else:
        run_sampling(
            sample_size=args.sample_size,
            max_scanned=args.max_scanned,
            num_threads=args.threads,
        )