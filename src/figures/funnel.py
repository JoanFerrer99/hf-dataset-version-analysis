"""
Figura: l'embut de la Fase 0.
Pregunta: quants datasets passen cada filtre de la Fase 0?
Mart: mart_funnel.
"""

import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator

from figures import common

NAME = "fig_funnel"


def draw(con) -> plt.Figure:
    """
    Una barra horitzontal per pas, en escala logarítmica, amb el valor a l'extrem.

    :param con: connexió al magatzem.
    """
    df = common.query(con, "select stage_order, stage_label, n_datasets from mart_funnel order by stage_order")
    fig, ax = common.new_figure(7.5, 3.2)
    y = range(len(df))[::-1]
    ax.barh(list(y), df["n_datasets"], left=1, height=0.5, color=common.COLORS["ordinal"][:len(df)])
    ax.set_xscale("log")
    ax.set_xlim(1, 10 ** len(str(int(df["n_datasets"].max()))))
    ax.xaxis.set_major_locator(LogLocator(base=10))
    ax.xaxis.set_major_formatter(common.thousands())
    ax.xaxis.set_minor_locator(LogLocator(base=10, subs=()))
    ax.set_yticks(list(y), df["stage_label"])
    ax.grid(axis="y", visible=False)
    for position, value in zip(y, df["n_datasets"]):
        ax.annotate(common.fmt.num(value), (value, position), xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=9, color=common.COLORS["text"])
    ax.set_xlabel("Datasets (escala logarítmica)")
    return fig
