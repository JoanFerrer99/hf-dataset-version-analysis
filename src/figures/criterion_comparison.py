"""
Figura: Criteri A contra Criteri B, per perspectiva.
Pregunta: els datasets del Criteri A (tags) i del B (sessions) canvien de manera diferent?
Mart: mart_criterion_comparison.
"""

import matplotlib.pyplot as plt

from figures import common

NAME = "fig_criterion_comparison"
LABELS = {"A": "Criteri A: tags", "B": "Criteri B: sessions"}


def draw(con) -> plt.Figure:
    """
    Per perspectiva, la proporció de comparacions fetes amb algun canvi
    d'aquella perspectiva: una barra per criteri.

    :param con: connexió al magatzem.
    """
    df = common.query(con, """
        select criterion, perspective, n_compared_units, share_of_compared_units
        from mart_criterion_comparison
        order by criterion, perspective
    """)
    fig, ax = common.new_figure(7.5, 3.6)
    perspectives = [p for p in common.PERSPECTIVES if p in set(df["perspective"])]
    y = list(range(len(perspectives)))[::-1]
    height = 0.32
    for offset, (criterion, color) in zip((height / 2, -height / 2), zip(("A", "B"), common.COLORS["series"])):
        rows = df[df["criterion"] == criterion].set_index("perspective").reindex(perspectives)
        if rows["share_of_compared_units"].isna().all():
            continue
        n = int(rows["n_compared_units"].dropna().iloc[0])
        shares = rows["share_of_compared_units"].fillna(0)
        positions = [p + offset for p in y]
        ax.barh(positions, shares, height=height * 0.9, color=color, label=f"{LABELS[criterion]} ({n} comparacions)")
        for position, share in zip(positions, shares):
            ax.annotate(common.fmt.pct(share, 0), (share, position), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=8, color=common.COLORS["text"])
    ax.set_yticks(y, [common.PERSPECTIVE_LABELS[p] for p in perspectives])
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(common.percent())
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Comparacions fetes amb algun canvi de la perspectiva")
    common.legend(ax, ncol=2)
    return fig
