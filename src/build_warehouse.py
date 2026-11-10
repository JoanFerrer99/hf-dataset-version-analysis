"""
Fase 3: construeix el magatzem (DuckDB + dbt, `docs/warehouse.md`) a partir
d'una carpeta `data/run_<id>/`.

Executa `dbt build` (models i tests) amb la carpeta com a variable `run_dir`, i
desa el fitxer `.duckdb` fora de la carpeta, que és immutable:
`data/warehouse/run_<id>.duckdb`. El crida `run_pipeline.py` després de la Fase
2, i també es pot executar sol.

Ús:
  python build_warehouse.py --run-dir ../data/run_9

Output:
  data/warehouse/run_<id>.duckdb
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROJECT_DIR = os.path.join(REPO_ROOT, "warehouse")
WAREHOUSE_DIR = os.path.join(REPO_ROOT, "data", "warehouse")
REQUIRED_FILES = ("eligibility_report.csv", "funnel_summary.json", "versions.csv", "change_classification.csv",
                  "comparison_status.csv")


def warehouse_path(run_dir: str) -> str:
    """
    :param run_dir: carpeta de l'execució.
    :return: on es desa el magatzem d'aquesta execució (`data/warehouse/run_<id>.duckdb`).
    """
    return os.path.join(WAREHOUSE_DIR, f"{os.path.basename(os.path.abspath(run_dir))}.duckdb")


def missing_files(run_dir: str) -> list[str]:
    """
    :param run_dir: carpeta de l'execució.
    :return: els fitxers que el magatzem necessita i no hi són (`failures.csv` és opcional).
    """
    return [f for f in REQUIRED_FILES if not os.path.exists(os.path.join(run_dir, f))]


def dbt_executable() -> str:
    """
    :return: el `dbt` del mateix entorn que aquest Python (venv o imatge Docker), o el del PATH.
    """
    beside = os.path.join(os.path.dirname(sys.executable), "dbt")
    return beside if os.path.exists(beside) else (shutil.which("dbt") or "dbt")


def build_warehouse(run_dir: str) -> str:
    """
    Executa `dbt build` sobre la carpeta de l'execució.

    :param run_dir: carpeta de l'execució (`data/run_<id>`).
    :return: la ruta del fitxer `.duckdb`.
    :raises FileNotFoundError: si a la carpeta li falta algun fitxer de les Fases 0-2.
    :raises subprocess.CalledProcessError: si falla algun model o algun test de dbt.
    """
    run_dir = os.path.abspath(run_dir)
    missing = missing_files(run_dir)
    if missing:
        raise FileNotFoundError(f"A {run_dir} hi falten {', '.join(missing)}")
    path = warehouse_path(run_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    command = [dbt_executable(), "build", "--project-dir", PROJECT_DIR, "--profiles-dir", PROJECT_DIR,
               "--vars", json.dumps({"run_dir": run_dir})]
    log.info(f"FASE 3: construint el magatzem de {os.path.basename(run_dir)} a {path}")
    subprocess.run(command, cwd=REPO_ROOT, env={**os.environ, "WAREHOUSE_PATH": path}, check=True)
    return path


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Arguments de la CLI. Sense cap argument mostra l'ajuda i surt."""
    parser = argparse.ArgumentParser(
        description="Fase 3: construeix el magatzem (dbt build) d'una carpeta data/run_<id>/.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run-dir", required=True, metavar="DIR", help="Carpeta de l'execució (data/run_<id>).")
    if not argv:
        parser.print_help()
        sys.exit(0)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """
    :param argv: arguments de la CLI, sense el nom del programa.
    :return: codi de sortida: 0 si el magatzem s'ha construït, 1 si no.
    """
    args = parse_args(argv)
    try:
        path = build_warehouse(args.run_dir)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        log.error(f"No s'ha pogut construir el magatzem: {exc}")
        return 1
    log.info(f"Magatzem escrit a {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
