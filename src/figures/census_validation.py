"""
Figura: validació del motor amb Census Income, per codi.
Pregunta: com encerta el motor els codis de la Taula 1 del paper (Census Income)?
Mart: mart_census_validation.
"""

import matplotlib.pyplot as plt

from figures import common

NAME = "fig_census_validation"
MEASURES = {"precision": "Precisió", "recall": "Recall", "f1": "F1"}


def draw(con) -> plt.Figure:
    """
    Per codi, tres columnes: precisió, recall i F1. Les mesures sense
    denominador no es dibuixen.

    :param con: connexió al magatzem.
    """
    df = common.query(con, "select code, precision, recall, f1 from mart_census_validation order by code")
    fig, ax = common.new_figure(7.5, 3.6)
    width = 0.24
    x = range(len(df))
    for i, ((column, label), color) in enumerate(zip(MEASURES.items(), common.COLORS["series"])):
        ax.bar([p + (i - 1) * width for p in x], df[column].fillna(0), width=width * 0.85, color=color, label=label)
    ax.set_xticks(list(x), df["code"])
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(common.percent())
    ax.grid(axis="x", visible=False)
    common.legend(ax, ncol=3)
    return fig
