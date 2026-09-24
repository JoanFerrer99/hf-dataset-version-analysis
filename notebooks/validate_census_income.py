"""
Re-validació d'extractibilitat contra el ground truth Census Income
(D1-D7) -- script AÏLLAT, mai part del pipeline principal
(`eligibility_scan.py`/`version_extractor.py`/`run_pipeline.py`): no els
importa, no en depèn, no el criden ni el criden.

Motiu: l'exercici original de validació (US-304, `docs/census_income_
validation_report.md`) es va fer ABANS d'implementar C410 (ordre de
files, Decisió T-14) -- els seus resultats congelats NO reflecteixen si
el motor detecta reordenacions de files sobre aquest ground truth. Aquest
script reexecuta la mateixa comparació D_i vs D0 amb el motor ACTUAL de
`change_diff.py`, reutilitzat SENSE CANVIS (el mateix `compute_all_diffs`/
`classify_diffs` que fa servir `eligibility_scan.classify_dataset` sobre
la població real) -- no reimplementa cap lògica de diffing/classificació,
NOMÉS l'adquisició de D0-D7.

El codi d'adquisició (baixar D0-D7) es va recuperar de l'historial de git
(commit `bd37bf9`, l'únic commit on aquest codi va arribar a existir --
vegeu `docs/census_income_validation_report.md`, "Estat i
reproduïbilitat") i s'adapta aquí perquè es pugui tornar a executar quan
calgui, sense haver-lo de revifar dins de `change_diff.py` (Decisió T-11:
aquest tipus de codi puntual NO ha de viure com a codi actiu del pipeline
principal).

Ús:
  python validate_census_income.py

Output (numerat per run -- MAI sobreescriu els originals congelats
`data/census_income_diff_report.csv`/`data/census_income_classification.
csv`, que segueixen sent el registre pre-C410, vegeu `docs/census_income_
validation_report.md`):
  data/census_income_diff_report_<run_id>.csv
  data/census_income_classification_<run_id>.csv
"""

import logging
import os

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download

import change_diff
import errors
from version_extractor import get_next_run_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

UCI_ADULT_DATA_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"

CENSUS_INCOME_COLUMN_NAMES = [
    "age", "workclass", "fnlwgt", "education", "education-num",
    "marital-status", "occupation", "relationship", "race", "sex",
    "capital-gain", "capital-loss", "hours-per-week", "native-country", "income",
]

# Estructura real dels 7 repositoris (inspeccionada amb `list_repo_files`
# durant la validació original -- vegeu `docs/census_income_validation_
# report.md`). D3/D4 comparteixen repo (`mstz/adult`) amb subcarpetes
# diferents; D2 és un Parquet amb sufix de hash propi de l'exportador
# `datasets` d'HF.
CENSUS_INCOME_SOURCES = {
    "D1": {"repo_id": "scikit-learn/adult-census-income", "filename": "adult.csv"},
    "D2": {"repo_id": "AiresPucrs/adult-census-income",
           "filename": "data/train-00000-of-00001-7e70ed54d8cbb057.parquet"},
    "D3": {"repo_id": "mstz/adult", "filename": "income/train.csv"},
    "D4": {"repo_id": "mstz/adult", "filename": "income-no race/train.csv"},
    "D5": {"repo_id": "Databoost/optimized_adult_census", "filename": "optimized_adult_census.csv"},
    "D6": {"repo_id": "ETdanR/adult_income", "filename": "train_data.csv"},
    "D7": {"repo_id": "kuldeepbishnoi29/adult-fairness", "filename": "adult_processed.csv"},
}

# Totals REALS extrets de la Taula 1 del paper -- només els totals per fila
# són fiables (vegeu la nota d'integritat a docs/census_income_validation_
# report.md, "Metodologia"). Es fan servir NOMÉS com a referència
# aproximada, mai com una mètrica de precisió exacta.
PAPER_ROW_TOTALS = {"D1": 3, "D2": 3, "D3": 7, "D4": 7, "D5": 4, "D6": 4, "D7": 5}


def download_uci_adult_baseline() -> pd.DataFrame:
    """
    Baseline D0: dataset original de la UCI (`adult.data`), sense capçalera
    -- 14 columnes de característiques + la columna objectiu `income`.
    Descàrrega directa, pública, sense autenticació.

    :return: `DataFrame` amb `CENSUS_INCOME_COLUMN_NAMES` com a columnes.
    """
    return pd.read_csv(
        UCI_ADULT_DATA_URL, header=None, names=CENSUS_INCOME_COLUMN_NAMES, skipinitialspace=True
    )


def download_census_income_version(version: str, hf_token: str | None) -> pd.DataFrame:
    """
    Descarrega UNA versió (D1-D7) segons `CENSUS_INCOME_SOURCES`.

    :param version: clau de `CENSUS_INCOME_SOURCES` (p.e. `"D1"`).
    :param hf_token: token HF (cap dels 7 repositoris és gated, però es
        passa igual per coherència amb la resta del pipeline).
    :return: `DataFrame` amb el contingut tal com el retorna `pandas`
        (CSV o Parquet segons l'extensió de `filename`).
    :raises KeyError: si `version` no és una clau vàlida.
    """
    source = CENSUS_INCOME_SOURCES[version]
    local_path = errors.with_retry(
        hf_hub_download, repo_id=source["repo_id"], repo_type="dataset",
        filename=source["filename"], token=hf_token, **errors.DEFAULT_RETRY_CONFIG,
    )
    if local_path.endswith(".parquet"):
        return pd.read_parquet(local_path)
    return pd.read_csv(local_path)


def run_validation(hf_token: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Descarrega D0 i D1-D7, calcula els diffs de cada D_i contra D0 amb el
    motor ACTUAL de `change_diff.py` (inclou C410, Decisió T-14), i
    retorna la taula de detectabilitat + les etiquetes de canvi reals.

    :param hf_token: token HF.
    :return: tupla `(detectability_df, labels_df)` -- `detectability_df`
        té una fila per versió (`version`, `codes_detected`,
        `paper_row_total`, i una columna booleana per codi); `labels_df`
        té una fila per etiqueta detectada (`dataset_id`, `version_from`,
        `version_to`, `code`, `is_breaking`), buida si cap D_i produeix
        cap senyal.
    """
    log.info("Descarregant D0 (baseline UCI)...")
    baseline = download_uci_adult_baseline()

    detectability_rows = []
    all_labels = []
    for version in CENSUS_INCOME_SOURCES:
        log.info(f"Descarregant i comparant {version}...")
        df = download_census_income_version(version, hf_token)
        diffs = change_diff.compute_all_diffs(baseline, df)

        codes_detected = sum(1 for code in change_diff.TABULAR_CODES if diffs.get(code))
        row = {"version": version, "codes_detected": codes_detected, "paper_row_total": PAPER_ROW_TOTALS[version]}
        row.update({code: diffs.get(code) for code in change_diff.TABULAR_CODES})
        detectability_rows.append(row)

        all_labels.extend(change_diff.classify_diffs(
            diffs, dataset_id=f"census_income_{version}", version_from="D0", version_to=version,
        ))

    detectability_df = pd.DataFrame(detectability_rows)
    labels_df = pd.DataFrame(
        [{"dataset_id": label.dataset_id, "version_from": label.version_from, "version_to": label.version_to,
          "code": label.code, "is_breaking": label.is_breaking} for label in all_labels],
        columns=["dataset_id", "version_from", "version_to", "code", "is_breaking"],
    )
    return detectability_df, labels_df


if __name__ == "__main__":
    load_dotenv()
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
        raise SystemExit(1)

    detectability_df, labels_df = run_validation(hf_token)

    run_id = get_next_run_id(OUTPUT_DIR, prefix="census_income_diff_report_")
    diff_report_path = os.path.join(OUTPUT_DIR, f"census_income_diff_report_{run_id}.csv")
    classification_path = os.path.join(OUTPUT_DIR, f"census_income_classification_{run_id}.csv")
    detectability_df.to_csv(diff_report_path, index=False)
    labels_df.to_csv(classification_path, index=False)

    print(f"\n{'=' * 65}")
    print("  RE-VALIDACIÓ CENSUS INCOME (motor actual, inclou C410)")
    print(f"{'=' * 65}")
    print(detectability_df[["version", "codes_detected", "paper_row_total", "C410"]].to_string(index=False))
    print(f"{'=' * 65}")
    print(f"\n  Detectabilitat: {diff_report_path}")
    print(f"  Classificació:  {classification_path}")
    print("\n  NOTA: aquests fitxers són una RE-validació (motor actual, amb C410),")
    print("  no substitueixen el registre històric original -- vegeu")
    print("  docs/census_income_validation_report.md.\n")
