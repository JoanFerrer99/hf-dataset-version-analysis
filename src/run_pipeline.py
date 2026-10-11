"""
Orquestrador del pipeline: Fase 0 (`eligibility_scan.run_sampling`),
Fase 1 (`version_extractor.run_extraction`) i Fase 2
(`eligibility_scan.run_classification`) en una sola execució, amb el
mateix CSV d'elegibilitat per a les tres. Les Fases 1 i 2 només
processen els datasets elegibles.

Ús:
  python run_pipeline.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova ràpida
  python run_pipeline.py --sample-size 2000 --threads 4 --seed 42                    # execució principal
  python run_pipeline.py --input-csv ../data/run_12/eligibility_report.csv           # salta la Fase 0, reutilitza un CSV existent
  python run_pipeline.py --sample-size 2000 --skip-classification                    # només Fase 0-1/1b

Output: tot dins d'una carpeta nova, `data/run_<id>/` (mai sobreescriu):
  eligibility_report.csv, funnel_summary.json (Fase 0)
  versions.csv (Fase 1)
  change_classification.csv (Fase 2)
  failures.csv (si hi ha fallades)
Al final s'imprimeix la llista de fitxers generats per fase.
"""

import argparse
import logging
import os
import random
import sys

import pandas as pd

import errors
import eligibility_scan as es
import version_extractor as ve

log = logging.getLogger(__name__)


def run_full_pipeline(
    sample_size: int,
    max_scanned: int | None,
    num_threads: int,
    tags_only: bool,
    input_csv: str | None,
    skip_version_extraction: bool,
    skip_classification: bool,
    skip_size: bool,
) -> dict:
    """
    Executa Fase 0 -> 1 -> 2 dins d'una carpeta `run_<id>` nova
    (`es.new_run_dir`).

    :param sample_size, max_scanned, num_threads, tags_only: per a la Fase 0.
    :param input_csv: si es dona, salta la Fase 0 i usa aquest CSV.
    :param skip_version_extraction: omet la Fase 1.
    :param skip_classification: omet la Fase 2.
    :param skip_size: no calcula la mida de cada versió a la Fase 1.
    :return: `run_dir`, `eligibility_csv`, `eligible`, `versions_csv`,
        `change_classification_csv` (`None` si la fase no s'ha executat) i
        `generated_files` (rutes agrupades per fase).
    """
    run_dir = es.new_run_dir()
    ve.FAILURES_LOG_PATH = es.FAILURES_LOG_PATH
    log.info(f"Carpeta d'aquesta execució: {run_dir}")

    generated_files: dict[str, list[str]] = {"Fase 0-1 (mostreig+elegibilitat)": [], "Fase 1b (versions)": [],
                                              "Fase 2 (classificació de canvis)": []}
    outputs = {
        "run_dir": run_dir, "eligibility_csv": None, "eligible": 0,
        "versions_csv": None, "change_classification_csv": None, "generated_files": generated_files,
    }

    if input_csv:
        log.info(f"Fase 0-1 saltada -- reutilitzant {input_csv}")
        eligibility_csv = input_csv
        eligible = int(pd.read_csv(eligibility_csv)["eligible"].sum())
    else:
        eligibility_csv, funnel_summary_json, summary = es.run_sampling(
            sample_size=sample_size, max_scanned=max_scanned, num_threads=num_threads, tags_only=tags_only,
        )
        eligible = summary["eligible"]
        generated_files["Fase 0-1 (mostreig+elegibilitat)"] += [eligibility_csv, funnel_summary_json]

    outputs["eligibility_csv"] = eligibility_csv
    outputs["eligible"] = eligible

    if eligible == 0:
        log.info("Cap dataset elegible -- s'omet Fase 1b (extracció de versions) i Fase 2 (classificació de canvis).")
        return outputs

    if skip_version_extraction:
        log.info("FASE 1b saltada (--skip-version-extraction).")
    else:
        log.info(f"FASE 1b: Extraient versions dels {eligible} datasets elegibles...")
        versions_csv = os.path.join(run_dir, "versions.csv")
        ve.run_extraction(eligibility_csv, versions_csv, es.HF_TOKEN, ve.RETRY_CONFIG, compute_size=not skip_size)
        outputs["versions_csv"] = versions_csv
        generated_files["Fase 1b (versions)"].append(versions_csv)

    if skip_classification:
        log.info("FASE 2 saltada (--skip-classification).")
    else:
        log.info(f"FASE 2: Classificant canvis dels {eligible} datasets elegibles...")
        change_classification_csv = es.run_classification(eligibility_csv)
        outputs["change_classification_csv"] = change_classification_csv
        generated_files["Fase 2 (classificació de canvis)"].append(change_classification_csv)

    if os.path.exists(es.FAILURES_LOG_PATH):
        generated_files["Fallades (totes les fases)"] = [es.FAILURES_LOG_PATH]

    return outputs


def parse_args() -> argparse.Namespace:
    """Arguments de la CLI. Sense cap argument mostra l'ajuda i surt."""
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline complet: mostreig+elegibilitat, extracció de versions, "
            "i classificació de canvis dels elegibles, en una sola execució."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-csv", default=None, metavar="CSV",
        help=(
            "Salta la Fase 0-1 (mostreig+elegibilitat) i reutilitza aquest CSV "
            "(eligibility_report_*.csv) per a la Fase 1b/2 -- ignora "
            "--sample-size/--max-scanned/--threads/--seed/--tags-only."
        ),
    )
    parser.add_argument(
        "--skip-version-extraction", action="store_true",
        help="Omet la Fase 1b (extracció de versions dels elegibles).",
    )
    parser.add_argument(
        "--skip-classification", action="store_true",
        help="Omet la Fase 2 (classificació de canvis dels elegibles).",
    )
    parser.add_argument(
        "--skip-size", action="store_true",
        help="Es passa a la Fase 1b: no calcular approx_size_bytes (estalvia una crida list_repo_tree per versió).",
    )
    parser.add_argument(
        "--tags-only", action="store_true",
        help="Es passa a la Fase 0-1 (vegeu eligibility_scan.py --tags-only).",
    )
    parser.add_argument(
        "--sample-size", "-n", type=int, default=2000,
        help="Mida de la mostra per a la Fase 0-1 (ignorat amb --input-csv).",
    )
    parser.add_argument(
        "--max-scanned", "-m", type=int, default=None,
        help="Límit de datasets a escanejar a la Fase 0-1 (proves ràpides; ignorat amb --input-csv).",
    )
    parser.add_argument(
        "--threads", "-t", type=int, default=4,
        help="Threads per al processament paral·lel de la Fase 0-1 (ignorat amb --input-csv).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Llavor aleatòria per a reproduïbilitat (ignorat amb --input-csv).",
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

    if args.seed is not None:
        random.seed(args.seed)
        log.info(f"Llavor aleatòria fixada a {args.seed} per a reproduïbilitat.")

    for retry_config in (es.RETRY_CONFIG, ve.RETRY_CONFIG):
        retry_config.update(
            max_retries=args.retry_max_attempts,
            base_wait_s=args.retry_base_wait,
            max_wait_s=args.retry_max_wait,
        )

    result = run_full_pipeline(
        sample_size=args.sample_size,
        max_scanned=args.max_scanned,
        num_threads=args.threads,
        tags_only=args.tags_only,
        input_csv=args.input_csv,
        skip_version_extraction=args.skip_version_extraction,
        skip_classification=args.skip_classification,
        skip_size=args.skip_size,
    )

    print(f"\n{'=' * 65}")
    print("  RESUM PIPELINE COMPLET")
    print(f"{'=' * 65}")
    print(f"  Carpeta d'aquesta execució: {result['run_dir']}")
    print(f"  Datasets elegibles:         {result['eligible']}")
    print(f"{'=' * 65}")
    print("  Fitxers generats, per fase:")
    for phase, paths in result["generated_files"].items():
        if not paths:
            continue
        print(f"\n  {phase}")
        for path in paths:
            print(f"    - {os.path.basename(path)}")
    print(f"\n{'=' * 65}\n")
