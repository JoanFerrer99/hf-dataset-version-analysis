"""
Orquestrador del pipeline complet: encadena Fase 0-1 (`eligibility_scan.
run_sampling` -- mostreig + classificació d'elegibilitat), Fase 1b
(`version_extractor.run_extraction` -- seqüència de versions) i Fase 2
(`eligibility_scan.run_classification` -- classificació de canvis dels
elegibles) en una sola execució, reutilitzant el MATEIX CSV d'elegibilitat
entre totes tres fases -- sense pas manual d'un run a l'altre.

Substitueix el disseny previ (Fase 2 encadenada directament dins de
`eligibility_scan.run_sampling`, vegeu `docs/decisions_tfg.txt` Decisió
T-13): cada script manté una única responsabilitat (mostreig/
elegibilitat, extracció de versions, classificació de canvis) i aquest
mòdul és qui les compon -- `eligibility_scan.py`/`version_extractor.py`
segueixen sent invocables per separat per a proves/depuració granulars.

Cap fase de contingut real (Fase 1b/2) s'aplica mai a tota la mostra
escanejada -- només al subconjunt ja filtrat com a elegible (`eligible ==
True`), exactament igual que quan `eligibility_scan.py --classify-eligible`
s'invocava manualment (vegeu `docs/architecture.md`, "Cost, per què és
opt-in"): encadenar-ho no canvia QUÈ es processa, només elimina el pas
manual entremig.

Ús:
  python run_pipeline.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova ràpida
  python run_pipeline.py --sample-size 2000 --threads 4 --seed 42                    # execució principal
  python run_pipeline.py --input-csv ../data/eligibility_report_2000_5.csv           # salta Fase 0-1, reutilitza un CSV existent
  python run_pipeline.py --sample-size 2000 --skip-classification                    # només Fase 0-1/1b

Output:
  data/eligibility_report_<N>_<run_id>.csv, data/funnel_summary_<N>_<run_id>.json (Fase 0-1)
  data/versions_<run_id>.csv, data/versions_summary_<run_id>.json (Fase 1b)
  data/change_classification_<run_id>.csv (Fase 2)
"""

import argparse
import json
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
    Executa el pipeline complet: Fase 0-1 (o la salta si `input_csv` es
    dona), Fase 1b, Fase 2 -- en aquest ordre, totes dues últimes llegint
    el MATEIX CSV d'elegibilitat de la Fase 0-1 (mai un CSV diferent).

    :param sample_size: es passa a `eligibility_scan.run_sampling`
        (ignorat si `input_csv` és donat).
    :param max_scanned: es passa a `eligibility_scan.run_sampling`
        (ignorat si `input_csv` és donat).
    :param num_threads: es passa a `eligibility_scan.run_sampling`
        (ignorat si `input_csv` és donat).
    :param tags_only: es passa a `eligibility_scan.run_sampling`
        (ignorat si `input_csv` és donat).
    :param input_csv: si es dona, salta la Fase 0-1 i reutilitza aquest
        CSV (`eligibility_report_*.csv`) per a la Fase 1b/2 -- anàleg a
        `eligibility_scan.py --classify-eligible` però per a tot el
        pipeline. ``None`` per fer un mostreig nou.
    :param skip_version_extraction: si `True`, omet la Fase 1b.
    :param skip_classification: si `True`, omet la Fase 2.
    :param skip_size: es passa a `version_extractor.run_extraction`
        (`compute_size=not skip_size`).
    :return: `dict` amb `eligibility_csv`, `eligible_total`, i
        `versions_csv` (ruta, o `None` si la Fase 1b s'ha saltat o no hi
        havia cap elegible). La ruta del CSV de la Fase 2 no es retorna
        (`run_classification` no la retorna -- ja la imprimeix ella
        mateixa, vegeu la seva pròpia sortida per consola).
    """
    if input_csv:
        log.info(f"Fase 0-1 saltada -- reutilitzant {input_csv}")
        eligibility_csv = input_csv
        eligible_total = int(pd.read_csv(eligibility_csv)["eligible"].sum())
    else:
        eligibility_csv, _json_path, summary = es.run_sampling(
            sample_size=sample_size, max_scanned=max_scanned, num_threads=num_threads, tags_only=tags_only,
        )
        eligible_total = summary["eligible_total"]

    outputs = {"eligibility_csv": eligibility_csv, "eligible_total": eligible_total, "versions_csv": None}

    if eligible_total == 0:
        log.info("Cap dataset elegible -- s'omet Fase 1b (extracció de versions) i Fase 2 (classificació de canvis).")
        return outputs

    if skip_version_extraction:
        log.info("FASE 1b saltada (--skip-version-extraction).")
    else:
        log.info(f"FASE 1b: Extraient versions dels {eligible_total} datasets elegibles...")
        run_id = ve.get_next_run_id(ve.OUTPUT_DIR)
        versions_csv = os.path.join(ve.OUTPUT_DIR, f"versions_{run_id}.csv")
        version_summary = ve.run_extraction(
            eligibility_csv, versions_csv, es.HF_TOKEN, ve.RETRY_CONFIG, compute_size=not skip_size,
        )
        summary_path = os.path.join(ve.OUTPUT_DIR, f"versions_summary_{run_id}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(version_summary, f, indent=2, ensure_ascii=False)
        outputs["versions_csv"] = versions_csv

    if skip_classification:
        log.info("FASE 2 saltada (--skip-classification).")
    else:
        log.info(f"FASE 2: Classificant canvis dels {eligible_total} datasets elegibles...")
        es.run_classification(eligibility_csv)

    return outputs


def parse_args() -> argparse.Namespace:
    """
    Defineix i parseja els arguments de la CLI. Sense arguments, mostra
    l'ajuda i surt (mateix guard que `eligibility_scan.parse_args`).

    :return: `argparse.Namespace` amb `input_csv`, `skip_version_extraction`,
        `skip_classification`, `skip_size`, `tags_only`, `sample_size`,
        `max_scanned`, `threads`, `seed`, `retry_max_attempts`,
        `retry_base_wait`, `retry_max_wait`.
    """
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
    for k, v in result.items():
        print(f"  {k:<20} {v}")
    print(f"{'=' * 65}\n")
