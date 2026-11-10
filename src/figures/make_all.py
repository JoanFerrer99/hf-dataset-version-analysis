"""
Genera totes les figures de la memòria (o les que es diguin) a `docs/figures/`,
a partir del magatzem de l'execució de referència.

Ús (des de l'arrel del repositori):
  python src/figures/make_all.py                      # totes, del magatzem de run_9
  python src/figures/make_all.py fig_funnel           # només una
  python src/figures/make_all.py --warehouse data/warehouse/run_10.duckdb --out /tmp/figs

Output:
  docs/figures/fig_*.png (300 ppp)
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from figures import (  # noqa: E402
    breaking_share,
    census_validation,
    changes_by_quarter,
    code_frequency,
    common,
    criterion_comparison,
    funnel,
    versions_timeline,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

FIGURES = [funnel, versions_timeline, code_frequency, breaking_share, changes_by_quarter, criterion_comparison,
           census_validation]


def make(names: list[str] | None = None, warehouse: str | None = None, out_dir: str = common.FIGURES_DIR) -> list[str]:
    """
    Dibuixa i desa les figures.

    :param names: noms de les figures (`fig_funnel`...); totes si és buit.
    :param warehouse: fitxer del magatzem; per defecte, `common.warehouse_path()`.
    :param out_dir: carpeta de sortida.
    :return: les rutes dels PNG escrits.
    :raises ValueError: si algun nom no és de cap figura.
    """
    known = {module.NAME: module for module in FIGURES}
    unknown = sorted(set(names or []) - set(known))
    if unknown:
        raise ValueError(f"Figures desconegudes: {', '.join(unknown)}. Hi ha: {', '.join(known)}")
    con = common.connect(warehouse)
    try:
        paths = [common.save(known[name].draw(con), name, out_dir) for name in (names or list(known))]
    finally:
        con.close()
    for path in paths:
        log.info(f"Figura escrita: {path}")
    return paths


def main(argv: list[str]) -> int:
    """
    :param argv: arguments de la CLI, sense el nom del programa.
    :return: codi de sortida.
    """
    parser = argparse.ArgumentParser(description="Genera les figures de la memòria a partir del magatzem.")
    parser.add_argument("names", nargs="*", help="Figures que es generen (per defecte, totes).")
    parser.add_argument("--warehouse", default=None, help="Fitxer del magatzem (per defecte, el de run_9).")
    parser.add_argument("--out", default=common.FIGURES_DIR, help="Carpeta de sortida.")
    args = parser.parse_args(argv)
    if not os.path.exists(args.warehouse or common.warehouse_path()):
        log.error(f"No hi ha el magatzem a {args.warehouse or common.warehouse_path()}: "
                  "python src/build_warehouse.py --run-dir data/run_<id>")
        return 1
    make(args.names, args.warehouse, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
