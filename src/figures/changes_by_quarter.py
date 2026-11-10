"""
Figura: canvis per trimestre i perspectiva.
Pregunta: com evolucionen els canvis al llarg del temps, per perspectiva?
Mart: mart_changes_by_quarter.
"""

import matplotlib.pyplot as plt

from figures import common

NAME = "fig_changes_by_quarter"


def draw(con) -> plt.Figure:
    """
    Una columna per trimestre (de la versió nova), apilada per perspectiva, amb
    el total a sobre.

    :param con: connexió al magatzem.
    """
    df = common.query(con, """
        select year, quarter, year_quarter, perspective, n_changes
        from mart_changes_by_quarter
        order by year, quarter
    """)
    table = df.pivot_table(index=["year", "quarter", "year_quarter"], columns="perspective", values="n_changes",
                           aggfunc="sum", fill_value=0).reset_index()
    fig, ax = common.new_figure(7.5, 4.0)
    x = range(len(table))
    bottom = [0] * len(table)
    for perspective, color in zip(common.PERSPECTIVES, common.COLORS["series"]):
        if perspective not in table:
            continue
        values = table[perspective].tolist()
        ax.bar(x, values, bottom=bottom, width=0.45, color=color, edgecolor=common.COLORS["surface"], linewidth=1.5,
               label=common.PERSPECTIVE_LABELS[perspective])
        bottom = [b + v for b, v in zip(bottom, values)]
    for position, total in zip(x, bottom):
        ax.annotate(common.fmt.num(total), (position, total), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=9, color=common.COLORS["text"])
    ax.set_xticks(list(x), table["year_quarter"])
    ax.yaxis.set_major_formatter(common.thousands())
    ax.grid(axis="x", visible=False)
    ax.set_xlabel("Trimestre de la versió nova")
    ax.set_ylabel("Canvis")
    common.legend(ax, ncol=2)
    return fig
