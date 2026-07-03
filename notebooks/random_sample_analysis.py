"""
Mostreig aleatori correcte de datasets de HuggingFace.

Metodologia: Reservoir sampling (algoritme R de Vitter) sobre TOTA la población
de datasets, sense ordenar per popularitat. Això garanteix que cada dataset
de la población té igual probabilitat de ser seleccionat.

Estratègia per detectar "versions reals":
1. Es llisten tags/refs del repo (versionat explicit).
2. Si no hi ha tags, es miren els commits i es filtren per fitxers substantius.
3. Es considera "elegible" un dataset amb almenys 2 "punts de canvi" rellevants.

Output: data/eligibility_report.csv + data/funnel_summary.json

Estratègia de detecció de "versions reals":
  - El repositori té >= 2 tags de Git
    que NO són purament documentals (README, llicències, metadades)
 
Ús:
  python random_sample_analysis.py --sample-size 500 --threads 4
  python random_sample_analysis.py --sample-size 1000 --max-scanned 50000 --threads 8
  python random_sample_analysis.py --sample-size 200 --max-scanned 5000  # prova ràpida
 
Output:
  data/eligibility_report_<N>.csv   -> fila per dataset explorat
  data/funnel_summary_<N>.json      -> xifres agregades de l'embut
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
 
# Fitxers que NO compten com a "canvi real de dataset".
# Basat en la taxonomia els canvis de Metadata

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

#Inicialització de l'API
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
    sys.exit(1)
 
api = HfApi(token=HF_TOKEN)
log.info("Token HF carregat correctament.")


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Fase 1: Iteració i reservoir sampling
# ---------------------------------------------------------------------------
 
def iter_all_datasets(page_size: int = 500):
    """
    Itera TOTA la població de datasets de HF sense cap ordenació.
    Genera datasets un a un (generator) per no carregar tot a memòria.
    """
    try:
        # IMPORTANT: no posem `limit=page_size` perquè això només retornaria
        # els primers datasets. Amb `limit=None` iterem tota la població real.
        for dataset in api.list_datasets(limit=None):
            yield dataset
    except Exception as exc:
        log.error(f"Error iterant datasets: {exc}")
 
 
def reservoir_sample_datasets(
    sample_size: int, max_scanned: int | None = None
) -> tuple[list, int]:
    """
    Algorisme R de Vitter: mostreig aleatori uniforme sobre tota la població.
    Cada dataset té igual probabilitat = sample_size / N de ser seleccionat.
 
    Args:
        sample_size:  Mida de la mostra final desitjada.
        max_scanned:  Límit opcional de datasets a escanejar (per a proves ràpides).
 
    Returns:
        (reservoir, n_seen): mostra final i total de datasets escanejats.
    """
    reservoir: list = []
    n_seen = 0
 
    desc = f"Escaneig reservoir sampling (objectiu: {sample_size} datasets)"

    with tqdm(desc=desc, unit=" datasets", dynamic_ncols=True) as pbar:
        for dataset in iter_all_datasets():
            n_seen += 1
            if len(reservoir) < sample_size:
                reservoir.append(dataset)
            else:
                j = random.randint(0, n_seen - 1)
                if j < sample_size:
                    reservoir[j] = dataset
 
            pbar.update(1)
            pbar.set_postfix({"reservori": len(reservoir), "vist": n_seen})
 
            if max_scanned and n_seen >= max_scanned:
                log.info(f"Límit max_scanned={max_scanned} assolit. Aturant escaneig.")
                break
 
    log.info(f"Escaneig completat: {n_seen} datasets vistos, {len(reservoir)} a la mostra.")
    return reservoir, n_seen
 
 
# ---------------------------------------------------------------------------
# Fase 2: Classificació d'elegibilitat per dataset
# ---------------------------------------------------------------------------
 
def classify_dataset(dataset_id: str) -> dict:
    """ 
    Criteri: >= 2 tags de Git (versionat explícit, com en el paper dels LLM).
 
    Retorna un diccionari amb tots els camps per al CSV final.
    """
    result = {
        "dataset_id": dataset_id,
        "has_tags": False,
        "num_tags": 0,
        "num_commits_total": 0,
        "num_commits_substantive": 0,
        "eligible": False,
        "eligibility_reason": "",
        "error": "",
    }
 
    try:
        refs = list_repo_refs(repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN)
        tags = refs.tags if refs.tags else []
        result["has_tags"] = len(tags) > 0
        result["num_tags"] = len(tags)
 
        commits = []
        for commit in list_repo_commits(
            repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN
        ):
            commits.append(commit)
            if len(commits) >= 50:
                break
 
        result["num_commits_total"] = len(commits)
 
    except Exception as exc:
        result["error"] = str(exc)[:120]
 
    return result
 
 
def classify_dataset_safe(args: tuple) -> dict | None:
    """Wrapper segur per a execució paral·lela amb ThreadPoolExecutor."""
    idx, dataset_id = args
    try:
        return classify_dataset(dataset_id)
    except Exception as exc:
        log.warning(f"[{idx}] Error classificant {dataset_id}: {exc}")
        return None
 
 
# ---------------------------------------------------------------------------
# Fase 3: Escriptura de resultats
# ---------------------------------------------------------------------------
 
def write_results(rows: list[dict], sample_size: int, total_scanned: int) -> tuple[str, str, dict]:
    """Escriu el CSV i el JSON de resultats. Retorna les rutes dels fitxers."""
    df = pd.DataFrame(rows)
 
    csv_path = os.path.join(OUTPUT_DIR, f"eligibility_report_{sample_size}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8")
 
    total = len(rows)
    eligible = int(df["eligible"].sum())
 
    summary = {
        "timestamp": datetime.now().isoformat(),
        "sampling_method": "reservoir_sampling_R_Vitter_uniform_no_bias",
        "authentication": "HF_TOKEN",
        "eligibility_definition": "multiple_versions_only (tags>=2)",
        "sample_size": total,
        "population_scanned": total_scanned,
        "with_any_tag": int(df["has_tags"].sum()),
        "with_2plus_tags": int((df["num_tags"] >= 2).sum()),
        "eligible_total": eligible,
        "eligible_via_tags": int((df["eligibility_reason"] == "tags>=2").sum()),
        "eligible_via_commits": int(
            (df["eligibility_reason"] == "substantive_commits>=2").sum()
        ),
        "ineligible": int((df["eligibility_reason"] == "insufficient_changes").sum()),
        "errors": int((df["error"] != "").sum()),
        "eligible_proportion": round(eligible / total, 4) if total else 0,
        "estimated_eligible_in_population": int(round((eligible / total) * total_scanned)) if total else 0,
    }
 
    json_path = os.path.join(OUTPUT_DIR, f"funnel_summary_{sample_size}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
 
    return csv_path, json_path, summary
 
 
# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------
 
def run_funnel(sample_size: int, max_scanned: int | None, num_threads: int) -> None:
    """Executa l'embut complet: mostreig → classificació paral·lela → resultats."""
 
    # --- Fase 1: Mostreig ---
    log.info(f"FASE 1: Reservoir sampling (objectiu={sample_size}, max_scanned={max_scanned})")
    datasets, total_scanned = reservoir_sample_datasets(sample_size, max_scanned)
    dataset_ids = [d.id for d in datasets]
    log.info(f"Mostra obtinguda: {len(dataset_ids)} datasets de {total_scanned} escanejats.")
 
    # --- Fase 2: Classificació paral·lela ---
    log.info(f"FASE 2: Classificant elegibilitat ({num_threads} threads)...")
    indexed = list(enumerate(dataset_ids))
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
    csv_path, json_path, summary = write_results(rows, sample_size, total_scanned)
 
    # Imprimir resum final
    print(f"\n{'='*65}")
    print(f"  RESUM EMBUT — mostra de {summary['sample_size']} datasets aleatoris")
    print(f"{'='*65}")
    for k, v in summary.items():
        print(f"  {k:<40} {v}")
    print(f"{'='*65}")
    print(f"\n  CSV:  {csv_path}")
    print(f"  JSON: {json_path}\n")
 
 
# ---------------------------------------------------------------------------
# Punt d'entrada amb argparse
# ---------------------------------------------------------------------------
 
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filtratge previ de datasets de HF amb versions reals.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
    return parser.parse_args()
 
 
if __name__ == "__main__":
    args = parse_args()
 
    if args.seed is not None:
        random.seed(args.seed)
        log.info(f"Llavor aleatòria fixada a {args.seed} per a reproduïbilitat.")
 
    run_funnel(
        sample_size=args.sample_size,
        max_scanned=args.max_scanned,
        num_threads=args.threads,
    )
 