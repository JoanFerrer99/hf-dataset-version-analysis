"""
El que comparteixen les figures: la connexió de només lectura al magatzem,
l'estil (la mateixa paleta i el mateix format de números que la interfície,
`ui/palette.py` i `ui/fmt.py`) i com es desen (PNG a 300 ppp).
"""

import os
import sys

import duckdb
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FIGURES_DIR = os.path.join(REPO_ROOT, "docs", "figures")
# L'execució de referència (decisió T-30); una altra amb WAREHOUSE_PATH.
DEFAULT_WAREHOUSE = os.path.join("data", "warehouse", "run_9.duckdb")
DPI = 300

sys.path.insert(0, os.path.join(REPO_ROOT, "ui"))
import fmt  # noqa: E402
import palette as palettes  # noqa: E402

COLORS = palettes.LIGHT
PERSPECTIVES = palettes.PERSPECTIVES
PERSPECTIVE_LABELS = palettes.PERSPECTIVE_LABELS


def warehouse_path() -> str:
    """
    :return: la ruta absoluta del magatzem (`WAREHOUSE_PATH`, o el de l'execució de referència).
    """
    path = os.environ.get("WAREHOUSE_PATH", DEFAULT_WAREHOUSE)
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def connect(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """
    :param path: fitxer del magatzem; per defecte, `warehouse_path()`.
    :return: una connexió de només lectura.
    """
    return duckdb.connect(path or warehouse_path(), read_only=True)


def query(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """
    :param con: connexió al magatzem.
    :param sql: consulta.
    :return: el resultat.
    """
    return con.execute(sql).df()


def new_figure(width: float = 7.0, height: float = 4.0) -> tuple[plt.Figure, plt.Axes]:
    """
    Una figura amb l'estil comú: fons blanc, eixos i quadrícula discrets, text en gris.

    :param width: amplada en polzades.
    :param height: alçada en polzades.
    :return: `(figura, eixos)`.
    """
    fig, ax = plt.subplots(figsize=(width, height))
    fig.patch.set_facecolor(COLORS["surface"])
    ax.set_facecolor(COLORS["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLORS["axis"])
    ax.tick_params(colors=COLORS["muted"], labelsize=9)
    ax.xaxis.label.set_color(COLORS["muted"])
    ax.yaxis.label.set_color(COLORS["muted"])
    ax.grid(color=COLORS["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    return fig, ax


def legend(ax: plt.Axes, ncol: int = 4, **kwargs) -> None:
    """Llegenda a dalt, sense marc, amb el text del color principal."""
    leg = ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=ncol, fontsize=9, **kwargs)
    for text in leg.get_texts():
        text.set_color(COLORS["text"])


def thousands() -> FuncFormatter:
    """Format dels eixos amb punt de milers (1.868)."""
    return FuncFormatter(lambda value, _: fmt.num(value))


def percent(decimals: int = 0) -> FuncFormatter:
    """Format dels eixos en percentatge amb coma decimal (0,4 %)."""
    return FuncFormatter(lambda value, _: fmt.pct(value, decimals))


def save(fig: plt.Figure, name: str, out_dir: str = FIGURES_DIR) -> str:
    """
    Desa la figura en PNG a 300 ppp i la tanca.

    :param fig: la figura.
    :param name: nom del fitxer, sense extensió.
    :param out_dir: carpeta de sortida (per defecte, `docs/figures/`).
    :return: la ruta del PNG.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path
