"""
Validació d'extractibilitat contra el ground truth Census Income
(D1-D7) -- script AÏLLAT, mai part del pipeline principal


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

# Ground truth REAL de la Taula 1 del paper
PAPER_GROUND_TRUTH: dict[str, frozenset[str]] = {
    "D1": frozenset({"C100", "C223", "C410"}),
    "D2": frozenset({"C100", "C223", "C410"}),
    "D3": frozenset({"C100", "C210", "C223", "C311", "C312", "C410", "C422"}),
    "D4": frozenset({"C100", "C210", "C222", "C223", "C311", "C312", "C422"}),
    "D5": frozenset({"C100", "C221", "C223", "C410"}),
    "D6": frozenset({"C100", "C223", "C422", "C530"}),
    "D7": frozenset({"C100", "C222", "C223", "C312", "C421"}),
}


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
        row = {
            "version": version, "codes_detected": codes_detected,
            "paper_row_total": len(PAPER_GROUND_TRUTH[version]),
        }
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


def compare_detectability_with_paper(detectability_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compara la detectabilitat del nostre motor amb `PAPER_GROUND_TRUTH`,
    codi per codi, per a cada versió -- EXCLOENT C100 (el nostre motor
    mai el compta, vegeu `change_diff.py`). Funció PURA: no fa cap crida
    de xarxa, només processa `detectability_df` ja calculat.

    :param detectability_df: mateix format que retorna `run_validation`
        (una fila per versió, una columna booleana per codi de
        `change_diff.TABULAR_CODES`).
    :return: `DataFrame` amb una fila per versió: `version`,
        `paper_total` (15 codis, incl. C100), `paper_minus_c100`,
        `our_total`, `tp`, `fn`, `fp`, i `tp_codes`/`fn_codes`/`fp_codes`
        (strings separats per comes, `"-"` si el conjunt és buit).
    """
    rows = []
    for _, row in detectability_df.iterrows():
        version = row["version"]
        paper_codes = PAPER_GROUND_TRUTH[version] - {"C100"}
        our_codes = {code for code in change_diff.TABULAR_CODES if row.get(code)}
        tp, fn, fp = paper_codes & our_codes, paper_codes - our_codes, our_codes - paper_codes
        rows.append({
            "version": version,
            "paper_total": len(PAPER_GROUND_TRUTH[version]),
            "paper_minus_c100": len(paper_codes),
            "our_total": len(our_codes),
            "tp": len(tp), "fn": len(fn), "fp": len(fp),
            "tp_codes": ",".join(sorted(tp)) or "-",
            "fn_codes": ",".join(sorted(fn)) or "-",
            "fp_codes": ",".join(sorted(fp)) or "-",
        })
    return pd.DataFrame(rows)


def summarize_agreement_by_code(detectability_df: pd.DataFrame) -> pd.DataFrame:
    """
    Mateixa comparació que `compare_detectability_with_paper`, agregada
    per CODI en lloc de per versió -- per detectar patrons sistemàtics
    (un codi concret que sempre es perd, o que sempre es sobre-detecta).
    Funció PURA, mateixa entrada que `compare_detectability_with_paper`.

    :param detectability_df: mateix format que `compare_detectability_with_paper`.
    :return: `DataFrame` amb una fila per codi (`code`, `tp`, `fn`, `fp`),
        NOMÉS per als codis amb algun TP/FN/FP -- els codis que mai
        apareixen ni al paper ni al nostre motor es descarten.
    """
    counts = {code: {"tp": 0, "fn": 0, "fp": 0} for code in change_diff.TABULAR_CODES}
    for _, row in detectability_df.iterrows():
        version = row["version"]
        paper_codes = PAPER_GROUND_TRUTH[version] - {"C100"}
        our_codes = {code for code in change_diff.TABULAR_CODES if row.get(code)}
        for code in paper_codes & our_codes:
            counts[code]["tp"] += 1
        for code in paper_codes - our_codes:
            counts[code]["fn"] += 1
        for code in our_codes - paper_codes:
            counts[code]["fp"] += 1

    rows = [
        {"code": code, "tp": c["tp"], "fn": c["fn"], "fp": c["fp"]}
        for code, c in counts.items() if c["tp"] or c["fn"] or c["fp"]
    ]
    return pd.DataFrame(rows, columns=["code", "tp", "fn", "fp"])


def compute_agreement_metrics(comparison_df: pd.DataFrame) -> dict:
    """
    Precisió/Recall/F1 agregats a partir de `compare_detectability_with_
    paper`. Funció PURA.

    :param comparison_df: sortida de `compare_detectability_with_paper`
        (necessita només les columnes `tp`/`fn`/`fp`).
    :return: `dict` amb `tp`, `fn`, `fp` (`int`) i `precision`/`recall`/
        `f1` (`float`, `0.0` si el denominador corresponent és 0, per
        evitar divisió per zero).
    """
    tp, fn, fp = int(comparison_df["tp"].sum()), int(comparison_df["fn"].sum()), int(comparison_df["fp"].sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fn": fn, "fp": fp, "precision": precision, "recall": recall, "f1": f1}


if __name__ == "__main__":
    load_dotenv()
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
        raise SystemExit(1)

    detectability_df, labels_df = run_validation(hf_token)
    comparison_df = compare_detectability_with_paper(detectability_df)
    by_code_df = summarize_agreement_by_code(detectability_df)
    metrics = compute_agreement_metrics(comparison_df)

    run_id = get_next_run_id(OUTPUT_DIR, prefix="census_income_diff_report_")
    diff_report_path = os.path.join(OUTPUT_DIR, f"census_income_diff_report_{run_id}.csv")
    classification_path = os.path.join(OUTPUT_DIR, f"census_income_classification_{run_id}.csv")
    comparison_path = os.path.join(OUTPUT_DIR, f"census_income_paper_comparison_{run_id}.csv")
    by_code_path = os.path.join(OUTPUT_DIR, f"census_income_paper_comparison_by_code_{run_id}.csv")
    detectability_df.to_csv(diff_report_path, index=False)
    labels_df.to_csv(classification_path, index=False)
    comparison_df.to_csv(comparison_path, index=False)
    by_code_df.to_csv(by_code_path, index=False)

    print(f"\n{'=' * 65}")
    print("  RE-VALIDACIÓ CENSUS INCOME (motor actual, inclou C410)")
    print(f"{'=' * 65}")
    print(detectability_df[["version", "codes_detected", "paper_row_total", "C410"]].to_string(index=False))
    print(f"{'=' * 65}")
    print("\n  COMPARATIVA AMB LA TAULA 1 DEL PAPER (transcrita a mà, PAPER_GROUND_TRUTH)")
    print(f"{'=' * 65}")
    print(comparison_df.to_string(index=False))
    print("\n  Per codi:")
    print(by_code_df.to_string(index=False))
    print(f"\n  Precisió={metrics['precision']:.3f}  Recall={metrics['recall']:.3f}  F1={metrics['f1']:.3f}")
    print(f"{'=' * 65}")
    print(f"\n  Detectabilitat: {diff_report_path}")
    print(f"  Classificació:  {classification_path}")
    print(f"  Comparativa:    {comparison_path}")
    print(f"  Per codi:       {by_code_path}")
    print("\n  NOTA: aquests fitxers són una RE-validació (motor actual, amb C410),")
    print("  no substitueixen el registre històric original -- vegeu")
    print("  docs/census_income_validation_report.md.\n")
