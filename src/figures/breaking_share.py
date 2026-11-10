"""
Figura: comparacions amb algun canvi trencador.
Pregunta: quina proporció de les comparacions fetes té almenys un canvi trencador?
Mart: mart_breaking_share.
"""

import matplotlib.pyplot as plt

from figures import common

NAME = "fig_breaking_share"
LABELS = {"A": "Criteri A: tags", "B": "Criteri B: sessions", "all": "Tots"}


def draw(con) -> plt.Figure:
    """
    Per criteri i en total: la proporció (punt) i el seu interval de Wilson al 95% (línia).

    :param con: connexió al magatzem.
    """
    df = common.query(con, """
        select criterion, n_compared_units, share_with_breaking_change,
               share_with_breaking_change_low, share_with_breaking_change_high
        from mart_breaking_share
        order by case criterion when 'A' then 1 when 'B' then 2 else 3 end
    """)
    fig, ax = common.new_figure(7.0, 2.6)
    blue = common.COLORS["series"][0]
    y = list(range(len(df)))[::-1]
    ax.hlines(y, df["share_with_breaking_change_low"], df["share_with_breaking_change_high"], color=blue, linewidth=2)
    ax.scatter(df["share_with_breaking_change"], y, s=60, color=blue, edgecolor=common.COLORS["surface"],
               linewidth=2, zorder=3)
    for position, share, n in zip(y, df["share_with_breaking_change"], df["n_compared_units"]):
        ax.annotate(f"{common.fmt.pct(share, 1)} (n = {n})", (share, position), xytext=(-4, 8),
                    textcoords="offset points", ha="left", fontsize=9, color=common.COLORS["text"])
    ax.set_yticks(y, df["criterion"].map(LABELS))
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(df) - 0.3)
    ax.xaxis.set_major_formatter(common.percent())
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Comparacions fetes amb algun canvi trencador (interval de confiança del 95%)")
    return fig
