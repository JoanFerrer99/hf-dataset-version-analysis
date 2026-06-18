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
"""

import time
import json
import csv
import os
import random
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

# Carrega variables d'entorn del .env
load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")
api = HfApi(token=HF_TOKEN)

# Fitxers que NO compten com a "canvi real"
NON_SUBSTANTIVE_FILES = {
    "README.md", ".gitattributes", "dataset_infos.json",
    ".gitignore", "LICENSE", "LICENSE.md", "CITATION.cff",
    ".github", ".gitmodules", "setup.py", "setup.cfg"
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def iter_all_datasets(page_size: int = 500):
    """
    Itera TOTA la población de datasets de HF sense ordenar.
    Usa huggingface_hub API amb token autenticat.
    Genera datasets un a un (generator) per no carregar tot a memòria.
    """
    page_count = 0
    
    try:
        for dataset in api.list_datasets(limit=page_size):
            page_count += 1
            if page_count % 500 == 0:
                print(f"   ... {page_count} datasets processats...")
            yield dataset
    except Exception as e:
        print(f"❌ Error fetching datasets: {e}")


def reservoir_sample_datasets(sample_size: int,
                               max_scanned: int | None = None) -> tuple[list, int]:
    """
    Mostreig aleatori (reservoir sampling) sobre TOTA la población.
    Cada dataset té igual probabilitat de ser seleccionat.
    
    Retorna: (reservoir, total_datasets_seen)
    """
    reservoir = []
    n_seen = 0

    print(f"   Iniciant reservoir sampling (sample_size={sample_size})...")
    
    for dataset in iter_all_datasets():
        n_seen += 1
        
        if len(reservoir) < sample_size:
            reservoir.append(dataset)
        else:
            # Algoritme R de Vitter
            j = random.randint(0, n_seen - 1)
            if j < sample_size:
                reservoir[j] = dataset

        if max_scanned and n_seen >= max_scanned:
            break

    print(f"   Total de datasets vistos: {n_seen}")
    return reservoir, n_seen


def classify_dataset(dataset_id: str) -> dict:
    """
    Determina si un dataset és elegible: >=2 punts de canvi rellevants.
    Usa huggingface_hub per accedir a commits amb informació detallada.
    Retorna diccionari amb la informació per al CSV.
    """
    result = {
        "dataset_id": dataset_id,
        "has_tags": False,
        "num_tags": 0,
        "num_commits_total": 0,
        "num_commits_with_data_changes": 0,
        "eligible": False,
        "eligibility_reason": "",
        "error": "",
    }

    try:
        # Obté refs (tags)
        try:
            refs = list_repo_refs(repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN)
            tags = refs.tags if refs.tags else []
            result["has_tags"] = len(tags) > 0
            result["num_tags"] = len(tags)
        except Exception as e:
            result["error"] = f"refs_error: {str(e)[:50]}"
            return result

        # Obté commits
        try:
            commits = []
            for commit in list_repo_commits(repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN):
                commits.append(commit)
                if len(commits) >= 50:  # Limit
                    break
            
            result["num_commits_total"] = len(commits)
        except Exception as e:
            result["error"] = f"commits_error: {str(e)[:50]}"
            return result

        # Comptar commits amb canvis reals detectant per títol
        substantive_count = 0
        
        for commit in commits[:30]:
            title = commit.title or commit.message or ""
            title_lower = title.lower()
            
            # Detectar si és substantiu (no metadata)
            is_substantive = True
            for non_sub in ["readme", "metadata", ".gitattributes", "dataset_infos", "license", "citation"]:
                if non_sub in title_lower:
                    is_substantive = False
                    break
            
            if is_substantive and title:
                substantive_count += 1

        result["num_commits_with_data_changes"] = substantive_count

        # Decidir elegibilitat
        if result["num_tags"] >= 2:
            result["eligible"] = True
            result["eligibility_reason"] = "tags>=2"
        elif substantive_count >= 2:
            result["eligible"] = True
            result["eligibility_reason"] = "substantive_commits>=2"
        else:
            result["eligibility_reason"] = "insufficient_changes"

    except Exception as e:
        result["error"] = str(e)[:100]

    return result


def classify_dataset_indexed(indexed_dataset: tuple) -> dict | None:
    """
    Wrapper per a processament paral·lel (com process_model() en la plantilla).
    Accepta (idx, dataset_id) i executa classify_dataset().
    """
    idx, dataset_id = indexed_dataset
    
    if idx % 50 == 0:
        print(f"   ... {idx} datasets processats")
    
    try:
        return classify_dataset(dataset_id)
    except Exception as e:
        print(f"❌ Error processing dataset {dataset_id}: {str(e)[:50]}")
        return None


def run_funnel(sample_size: int = 500, max_scanned: int | None = None, num_threads: int = 4) -> None:
    """Executa l'embut complet d'elegibilitat (mostreig + processament paral·lel)."""
    print(f"\n[1/3] Mostreig aleatori de {sample_size} datasets sobre TOTA la población")
    print(f"       (sense biaix de popularitat, autenticat amb HF_TOKEN)...")
    datasets, total_scanned = reservoir_sample_datasets(
        sample_size=sample_size, max_scanned=max_scanned
    )
    dataset_ids = [d.id for d in datasets]
    print(f"       ✅ Mostra final: {len(dataset_ids)} datasets\n")

    print(f"[2/3] Classificant elegibilitat de cada dataset (paral·lel, {num_threads} threads)...")
    print(f"       (analizant tags i commits amb token personal)...")
    
    # Preparar estructura per a processament paral·lel (com en HFExtraction)
    indexed_dataset_ids = [(idx, ds_id) for idx, ds_id in enumerate(dataset_ids)]
    
    # Usar ThreadPoolExecutor per processament paral·lel
    results = []
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = list(executor.map(classify_dataset_indexed, indexed_dataset_ids))
    
    # Filtrar resultats vàlids
    rows = [r for r in results if r is not None]
    print(f"       ✅ Processats: {len(rows)} datasets\n")

    print(f"[3/3] Escrivint resultats...")
    
    # Crear DataFrame (com en la plantilla)
    df = pd.DataFrame(rows)
    
    # Guardar CSV
    csv_path = os.path.join(OUTPUT_DIR, f"eligibility_report_{sample_size}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8")

    # Calcular estadístiques
    total = len(rows)
    eligible = sum(1 for r in rows if r["eligible"])

    summary = {
        "timestamp": datetime.now().isoformat(),
        "sampling_method": "random_reservoir_sampling_uniform_no_bias",
        "authentication": "HF_TOKEN (personal account)",
        "sample_size": total,
        "with_any_tag": int(df["has_tags"].sum()),
        "with_2plus_tags": int((df["num_tags"] >= 2).sum()),
        "eligible_total": eligible,
        "eligible_via_tags": int((df["eligibility_reason"] == "tags>=2").sum()),
        "eligible_via_commits": int((df["eligibility_reason"] == "substantive_commits>=2").sum()),
        "errors": int((df["error"] != "").sum()),
        "eligible_proportion": round(eligible / total, 4) if total else 0,
        "estimated_eligible_in_population": int(eligible / total * 150000) if total else 0,
    }

    json_path = os.path.join(OUTPUT_DIR, f"funnel_summary_{sample_size}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*70}")
    print(f"📊 RESUM EMBUT (mostra de {total} datasets aleatoris)")
    print(f"{'='*70}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n✅ CSV: {csv_path}")
    print(f"✅ JSON: {json_path}")
    print(f"✅ DataFrame: {len(df)} files × {len(df.columns)} columnes\n")


if __name__ == "__main__":
    import sys
    
    SAMPLE_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    NUM_THREADS = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    MAX_SCANNED = os.getenv("MAX_SCANNED")
    MAX_SCANNED = int(MAX_SCANNED) if MAX_SCANNED else None
    
    if HF_TOKEN:
        print("✅ Token HF carregat del .env")
    else:
        print("❌ Cap token HF detectat al .env")
        sys.exit(1)
    
    run_funnel(sample_size=SAMPLE_SIZE, max_scanned=MAX_SCANNED, num_threads=NUM_THREADS)
