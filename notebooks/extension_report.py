"""
Report d'extensions de fitxers als repositoris elegibles (feedback del
director, reunió): estadístiques AGREGADES (no una taula per dataset) de
quants fitxers hi ha per extensió entre els datasets JA elegibles i quin
percentatge del total representa cadascuna -- i quants d'aquests
elegibles tenen almenys un fitxer tabular (és a dir, sobre quants
s'aplicarà realment la classificació de canvis, Fase 2) -- PRÈVIA a
qualsevol exclusió de fitxers binaris de l'estudi (vegeu `docs/
decisions_tfg.txt`).

DISSENY -- cens SNAPSHOT, no historial de commits: per cada dataset
elegible, `version_extractor.fetch_tree_paths` llista els fitxers de la
revisió MÉS RECENT (HEAD), no els fitxers realment tocats pels commits
substantius analitzats a la Fase 0-1. És una aproximació deliberadament
barata (una sola crida `list_repo_tree` per dataset, sense clonar ni
iterar l'historial) -- suficient per respondre "quin percentatge dels
fitxers d'aquests repositoris és tabular", la pregunta concreta del
director; NO pretén ser un recompte exacte de "fitxers tocats per
commits substantius" (per això, vegeu `eligibility_scan.classify_
commit_tabular_changes`, que sí opera commit a commit, però NOMÉS sobre
els fitxers ja tabulars).

Ús:
  python extension_report.py --input ../data/eligibility_report_<sample_id>_<run_id>.csv

Output:
  data/extension_report_<run_id>.csv (una fila per extensió, agregada
    sobre TOTS els datasets elegibles: extension, file_count, pct_of_total, is_tabular)
  data/extension_report_summary_<run_id>.json (totals globals +
    n_eligible_with_tabular_files -- el nombre d'elegibles sobre els
    quals s'aplicarà la classificació de canvis -- + recompte de fitxers
    tabulars per dataset, que alimenta la investigació de repositoris
    amb múltiples fitxers tabulars, feedback del director)
  data/failures.csv (fallades de dataset sencer, source="extension_report")
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

import change_diff
import errors
import version_extractor as ve

log = logging.getLogger(__name__)

RETRY_CONFIG: dict = dict(errors.DEFAULT_RETRY_CONFIG)


def _file_extension(path: str) -> str:
    """
    Extensió d'una ruta, en minúscules, amb un cas especial per a
    extensions compostes conegudes (`.tar.gz`/`.tar`, igual que
    `eligibility_scan.SUBSTANTIVE_DATA_EXTENSIONS` les tracta com una
    unitat) -- `os.path.splitext` per si sol donaria `.gz` per a
    `data.tar.gz`, cosmèticament confús encara que la classificació
    tabular/substantiva (que opera sobre la ruta completa, no aquesta
    etiqueta) sigui correcta de totes maneres.

    :param path: ruta relativa dins del repositori.
    :return: extensió en minúscules (p.e. `".csv"`, `".tar.gz"`), o
        `"(sense extensio)"` si no n'hi ha cap.
    """
    lower = path.lower()
    if lower.endswith(".tar.gz"):
        return ".tar.gz"
    ext = os.path.splitext(lower)[1]
    return ext or "(sense extensio)"


def build_extension_report(input_csv: str, hf_token: str | None, retry_config: dict) -> tuple[pd.DataFrame, dict]:
    """
    Llegeix els datasets elegibles de `input_csv` i agrega, PER EXTENSIÓ
    (sobre TOTS els elegibles junts, no un desglossament per dataset),
    quants fitxers hi ha a la seva revisió més recent.

    :param input_csv: ruta del CSV de datasets elegibles (`eligibility_
        report_*.csv`, amb columnes `dataset_id`/`eligible`).
    :param hf_token: token HF.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :return: tupla `(report_df, summary)`. `report_df` té una fila per
        extensió (`extension`, `file_count`, `pct_of_total`, `is_tabular`).
        `summary` té `timestamp`, `source_csv`, `n_eligible`, `n_dataset_
        level_failures`, `total_files`, `total_tabular_files`,
        `pct_tabular`, `n_eligible_with_tabular_files` (quants elegibles
        tenen almenys un fitxer tabular -- el nombre d'elegibles sobre
        els quals s'aplicarà realment la classificació de canvis, Fase
        2), i `tabular_files_per_dataset` (`dict[str, int]`, alimenta la
        investigació de repositoris amb múltiples fitxers tabulars).
    """
    df = pd.read_csv(input_csv)
    eligible = df[df["eligible"] == True]  # noqa: E712

    ext_counts: dict[str, int] = {}
    tabular_files_per_dataset: dict[str, int] = {}
    total_files = 0
    total_tabular = 0
    n_failed = 0

    for _, row in eligible.iterrows():
        dataset_id = row["dataset_id"]
        log.info(f"Llistant fitxers: {dataset_id}")
        try:
            paths = ve.fetch_tree_paths(dataset_id, hf_token, retry_config)
        except Exception as exc:
            n_failed += 1
            category = errors.classify_error(exc)
            retries_attempted = retry_config["max_retries"] if category in errors.RETRIED_CATEGORIES else 0
            errors.append_failure_row(
                ve.FAILURES_LOG_PATH, dataset_id=dataset_id, category=category,
                message=str(exc), retries_attempted=retries_attempted, source="extension_report",
            )
            log.warning(f"build_extension_report: fallada de dataset sencer {dataset_id}: {exc}")
            continue

        tabular_files_per_dataset[dataset_id] = 0
        for path in paths:
            ext = _file_extension(path)
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            total_files += 1
            if change_diff.is_tabular_path(path):
                total_tabular += 1
                tabular_files_per_dataset[dataset_id] += 1

    rows = sorted(
        (
            {
                "extension": ext, "file_count": n,
                "pct_of_total": round(100 * n / total_files, 2) if total_files else 0.0,
                "is_tabular": ext in change_diff.TABULAR_EXTENSIONS,
            }
            for ext, n in ext_counts.items()
        ),
        key=lambda r: r["file_count"], reverse=True,
    )
    report_df = pd.DataFrame(rows, columns=["extension", "file_count", "pct_of_total", "is_tabular"])

    n_eligible_with_tabular_files = sum(1 for n in tabular_files_per_dataset.values() if n > 0)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "source_csv": os.path.abspath(input_csv),
        "n_eligible": len(eligible),
        "n_dataset_level_failures": n_failed,
        "total_files": total_files,
        "total_tabular_files": total_tabular,
        "pct_tabular": round(100 * total_tabular / total_files, 2) if total_files else 0.0,
        "n_eligible_with_tabular_files": n_eligible_with_tabular_files,
        "tabular_files_per_dataset": tabular_files_per_dataset,
    }
    return report_df, summary


def parse_args() -> argparse.Namespace:
    """
    Defineix i parseja els arguments de la CLI. Sense arguments, mostra
    l'ajuda i surt (mateix guard que `eligibility_scan.parse_args`).

    :return: `argparse.Namespace` amb `input`, `retry_max_attempts`,
        `retry_base_wait`, `retry_max_wait`.
    """
    parser = argparse.ArgumentParser(
        description="Cens d'extensions de fitxers dels datasets elegibles (feedback del director).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", default=ve.DEFAULT_INPUT,
        help="CSV de datasets elegibles (eligibility_report_*.csv).",
    )
    parser.add_argument(
        "--retry-max-attempts", type=int, default=errors.DEFAULT_MAX_RETRIES,
        help="Nombre màxim de reintents davant rate limiting (429) o errors transitoris.",
    )
    parser.add_argument(
        "--retry-base-wait", type=float, default=errors.DEFAULT_BASE_WAIT_S,
        help="Espera inicial (segons) abans del primer reintent; es duplica a cada intent.",
    )
    parser.add_argument(
        "--retry-max-wait", type=float, default=errors.DEFAULT_MAX_WAIT_S,
        help="Espera màxima (segons) entre reintents (topall del backoff exponencial).",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    load_dotenv()
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx", file=sys.stderr)
        sys.exit(1)

    RETRY_CONFIG.update(
        max_retries=args.retry_max_attempts,
        base_wait_s=args.retry_base_wait,
        max_wait_s=args.retry_max_wait,
    )

    print(f"Censant extensions de fitxer dels datasets elegibles de {args.input}...")
    report_df, summary = build_extension_report(args.input, hf_token, RETRY_CONFIG)

    run_id = ve.get_next_run_id(ve.OUTPUT_DIR, prefix="extension_report_")
    report_path = os.path.join(ve.OUTPUT_DIR, f"extension_report_{run_id}.csv")
    summary_path = os.path.join(ve.OUTPUT_DIR, f"extension_report_summary_{run_id}.json")
    report_df.to_csv(report_path, index=False, encoding="utf-8")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 65}")
    print("  RESUM CENS D'EXTENSIONS DE FITXER")
    print(f"{'=' * 65}")
    for k, v in summary.items():
        if k != "tabular_files_per_dataset":
            print(f"  {k:<25} {v}")
    print(f"{'=' * 65}")
    print(f"\n  CSV:  {report_path}")
    print(f"  JSON: {summary_path}\n")
