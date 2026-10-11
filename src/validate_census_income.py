"""
Valida el motor de diffing contra el ground truth de Census Income:
compara cada versió D1-D7 (Hugging Face) amb l'original de la UCI (D0) i
contrasta els codis detectats amb la Taula 1 del paper. Script aïllat,
no el crida `run_pipeline.py`.

Ús:
  python validate_census_income.py

Output (numerat, mai sobreescriu):
  data/census_income_diff_report_<run_id>.csv
  data/census_income_classification_<run_id>.csv
  data/census_income_paper_comparison_<run_id>.csv
  data/census_income_paper_comparison_by_code_<run_id>.csv
"""

import logging
import os

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download

import errors
from diffengine.engine import diff_bytes
from diffengine.output import BREAKING_CODES, TABULAR_CODES
from version_extractor import get_next_run_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

UCI_ADULT_BASE_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/"

# D0 = `adult.data` (32.561 files), el fitxer de la UCI amb què compara el paper:
# la Taula 1 marca C421 o C422 segons si la versió té més o menys files que aquest
# (vegeu `docs/validacio_census_income.md`). La UCI també publica `adult.test`
# (16.281 files), que D3, D4, D6 i D7 barregen amb `adult.data`.
D0_FILES: tuple[str, ...] = ("adult.data",)
D0_STRIP_LABEL_DOT = True

CENSUS_INCOME_COLUMN_NAMES = [
    "age", "workclass", "fnlwgt", "education", "education-num",
    "marital-status", "occupation", "relationship", "race", "sex",
    "capital-gain", "capital-loss", "hours-per-week", "native-country", "income",
]

# Fitxer i revisió de cada versió (la més recent abans del paper; vegeu
# `experiments/census_variants/`).
CENSUS_INCOME_SOURCES = {
    "D1": {"repo_id": "scikit-learn/adult-census-income", "filename": "adult.csv",
           "revision": "2a7ff8e6a6cd74fa596ed6622937081c52255fcb"},
    "D2": {"repo_id": "AiresPucrs/adult-census-income",
           "filename": "data/train-00000-of-00001-7e70ed54d8cbb057.parquet",
           "revision": "c791a7936d9689a53efca18b97502a4a2a3946ad"},
    "D3": {"repo_id": "mstz/adult", "filename": "income/train.csv",
           "revision": "76f821640149ebd31ed2df3828a621fd4a914125"},
    "D4": {"repo_id": "mstz/adult", "filename": "income-no race/train.csv",
           "revision": "76f821640149ebd31ed2df3828a621fd4a914125"},
    "D5": {"repo_id": "Databoost/optimized_adult_census", "filename": "optimized_adult_census.csv",
           "revision": "afc71c89a14e07c1a2b12ca2b32a5dcf87d0abba"},
    # La targeta diu que és un sol dataset equilibrat partit en tres fitxers: es concatenen.
    "D6": {"repo_id": "ETdanR/adult_income", "filename": ("train_data.csv", "validation_data.csv", "experiment_data.csv"),
           "revision": "780110a9f38d16ea82392c2fd3a34c4a96441586"},
    "D7": {"repo_id": "kuldeepbishnoi29/adult-fairness", "filename": "adult_processed.csv",
           "revision": "58b25012704e7369b422e20c0d6933856ac78a17"},
}

# Taula 1 del paper, transcrita a mà (inclou C100, que el motor no detecta).
PAPER_GROUND_TRUTH: dict[str, frozenset[str]] = {
    "D1": frozenset({"C100", "C223", "C410"}),
    "D2": frozenset({"C100", "C223", "C410"}),
    "D3": frozenset({"C100", "C210", "C223", "C311", "C312", "C410", "C422"}),
    "D4": frozenset({"C100", "C210", "C222", "C223", "C311", "C312", "C422"}),
    "D5": frozenset({"C100", "C221", "C223", "C410"}),
    "D6": frozenset({"C100", "C223", "C422", "C530"}),
    "D7": frozenset({"C100", "C222", "C223", "C312", "C421"}),
}


def download_uci_adult(files: tuple[str, ...] = D0_FILES, strip_label_dot: bool = D0_STRIP_LABEL_DOT) -> bytes:
    """
    D0: fitxers de la UCI concatenats, amb una capçalera (no en tenen) escrita
    amb el mateix separador `, ` que les dades. Es treu la primera línia
    d'`adult.test` (`|1x3 Cross validator`) i les línies buides.

    :param strip_label_dot: treu el punt final de les etiquetes d'`adult.test` (`>50K.` → `>50K`).
    """
    import urllib.request

    lines = []
    for name in files:
        with urllib.request.urlopen(UCI_ADULT_BASE_URL + name) as response:
            text = response.read().decode("utf-8")
        for line in text.splitlines():
            if not line.strip() or line.startswith("|"):
                continue
            lines.append(line[:-1] if strip_label_dot and line.endswith(".") else line)
    return "\n".join([", ".join(CENSUS_INCOME_COLUMN_NAMES)] + lines).encode() + b"\n"


def download_census_income_version(version: str, hf_token: str | None, filename: str | None = None,
                                   revision: str | None = None) -> tuple[bytes, str]:
    """
    :param version: clau de `CENSUS_INCOME_SOURCES` (`"D1"`...`"D7"`).
    :param filename: un altre fitxer del mateix repositori (per defecte, el de la font).
    :param revision: commit del repositori (per defecte, `main`).
    :return: `(contingut del fitxer, extensió)`.
    """
    source = CENSUS_INCOME_SOURCES[version]
    names = filename or source["filename"]
    names = (names,) if isinstance(names, str) else names
    parts = []
    for name in names:
        local_path = errors.with_retry(
            hf_hub_download, repo_id=source["repo_id"], repo_type="dataset", filename=name,
            revision=revision or source.get("revision"), token=hf_token, **errors.DEFAULT_RETRY_CONFIG,
        )
        with open(local_path, "rb") as f:
            parts.append(f.read())
    if len(parts) == 1:
        return parts[0], os.path.splitext(names[0])[1]
    # Diversos CSV del mateix dataset: es concatenen sense repetir la capçalera.
    parts = [p if p.endswith(b"\n") else p + b"\n" for p in parts]
    return parts[0] + b"".join(p.split(b"\n", 1)[1] for p in parts[1:]), os.path.splitext(names[0])[1]


def run_validation(hf_token: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compara cada D_i amb D0 amb el motor v2 (`diffengine`), fitxer cru contra fitxer cru.

    :return: `(detectability_df, labels_df)`: una fila per versió amb un
        booleà per codi, i una fila per canvi detectat.
    """
    log.info("Descarregant D0 (baseline UCI)...")
    baseline = download_uci_adult()

    detectability_rows = []
    all_labels = []
    for version in CENSUS_INCOME_SOURCES:
        log.info(f"Descarregant i comparant {version}...")
        data, ext = download_census_income_version(version, hf_token)
        result = diff_bytes(baseline, ".csv", data, ext)

        row = {
            "version": version, "codes_detected": len(result.codes),
            "paper_row_total": len(PAPER_GROUND_TRUTH[version]),
        }
        row.update({code: code in result.codes for code in TABULAR_CODES})
        detectability_rows.append(row)
        for c in result.changes:
            all_labels.append({
                "dataset_id": f"census_income_{version}", "version_from": "D0", "version_to": version,
                "code": c.code, "subtype": c.subtype, "column": c.column, "old_column": c.old_column,
                "is_breaking": c.code in BREAKING_CODES,
            })

    detectability_df = pd.DataFrame(detectability_rows)
    labels_df = pd.DataFrame(all_labels, columns=["dataset_id", "version_from", "version_to", "code", "subtype",
                                                  "column", "old_column", "is_breaking"])
    return detectability_df, labels_df


def compare_detectability_with_paper(detectability_df: pd.DataFrame) -> pd.DataFrame:
    """
    TP/FN/FP per versió contra `PAPER_GROUND_TRUTH`, sense C100.

    :param detectability_df: sortida de `run_validation`.
    :return: una fila per versió amb els recomptes i els codis de cada
        conjunt (`"-"` si és buit).
    """
    rows = []
    for _, row in detectability_df.iterrows():
        version = row["version"]
        paper_codes = PAPER_GROUND_TRUTH[version] - {"C100"}
        our_codes = {code for code in TABULAR_CODES if row.get(code)}
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
    La mateixa comparació, agregada per codi.

    :return: una fila per codi amb algun TP/FN/FP (`code`, `tp`, `fn`, `fp`).
    """
    counts = {code: {"tp": 0, "fn": 0, "fp": 0} for code in TABULAR_CODES}
    for _, row in detectability_df.iterrows():
        version = row["version"]
        paper_codes = PAPER_GROUND_TRUTH[version] - {"C100"}
        our_codes = {code for code in TABULAR_CODES if row.get(code)}
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
    :param comparison_df: sortida de `compare_detectability_with_paper`.
    :return: `tp`, `fn`, `fp` totals i `precision`, `recall`, `f1` (0.0 si
        el denominador és 0).
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
