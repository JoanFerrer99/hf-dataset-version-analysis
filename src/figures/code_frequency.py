"""
Figura: freqüència de cada codi de la taxonomia.
Pregunta: amb quina freqüència surt cada codi i cada perspectiva?
Mart: mart_code_frequency.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from figures import common

NAME = "fig_code_frequency"


def draw(con) -> plt.Figure:
    """
    Una barra horitzontal per codi (canvis, un per taula), en l'ordre de la
    taxonomia i del color de la seva perspectiva. Els trencadors ho diuen a l'etiqueta.

    :param con: connexió al magatzem.
    """
    df = common.query(con, """
        select code, name, perspective, is_breaking, n_changes
        from mart_code_frequency
        order by code
    """)
    colors = dict(zip(common.PERSPECTIVES, common.COLORS["series"]))
    labels = df["code"] + " " + df["name"] + df["is_breaking"].map({True: " (trencador)", False: ""})
    fig, ax = common.new_figure(7.5, 5.2)
    y = range(len(df))[::-1]
    ax.barh(list(y), df["n_changes"], height=0.55, color=df["perspective"].map(colors))
    ax.set_yticks(list(y), labels)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_formatter(common.thousands())
    ax.set_xlabel("Canvis (taules amb el codi)")
    present = [p for p in common.PERSPECTIVES if p in set(df["perspective"])]
    common.legend(ax, handles=[Patch(color=colors[p], label=common.PERSPECTIVE_LABELS[p]) for p in present], ncol=2)
    return fig
