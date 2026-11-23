"""
Figura: les versions de cada dataset elegible al llarg del temps.
Pregunta: quantes versions té cada dataset elegible, i quan es van publicar?
Mart: fact_version (amb dim_version_kind), de l'estrella de les versions.
"""

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from figures import common

NAME = "fig_versions_timeline"
STYLES = {"tag": ("Tag", "o", 0), "commit": ("Sessió de commits", "s", 1)}


def draw(con) -> plt.Figure:
    """
    Una fila per dataset, un punt per versió (rodona si és un tag, quadrat si és
    una sessió) i una línia fina de la primera a l'última.

    :param con: connexió al magatzem.
    """
    df = common.query(con, """
        select v.dataset_id, k.version_kind as version_source, v.commit_date
        from fact_version as v
        inner join dim_version_kind as k
            on k.version_kind_key = v.version_kind_key
        where v.commit_date is not null
        order by v.dataset_id, v.commit_date
    """)
    datasets = sorted(df["dataset_id"].unique(), reverse=True)
    rows = {dataset: i for i, dataset in enumerate(datasets)}
    fig, ax = common.new_figure(7.5, 0.45 * len(datasets) + 1.2)
    for dataset, group in df.groupby("dataset_id"):
        ax.hlines(rows[dataset], group["commit_date"].min(), group["commit_date"].max(),
                  color=common.COLORS["deemphasis"], linewidth=1, zorder=1)
    handles = []
    for source, (label, marker, slot) in STYLES.items():
        points = df[df["version_source"] == source]
        if points.empty:
            continue
        color = common.COLORS["series"][slot]
        ax.scatter(points["commit_date"], points["dataset_id"].map(rows), marker=marker, s=40, color=color,
                   edgecolor=common.COLORS["surface"], linewidth=1, zorder=2)
        handles.append(Line2D([], [], marker=marker, linestyle="", color=color, label=label))
    ax.set_yticks(list(rows.values()), list(rows))
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Data del commit")
    common.legend(ax, handles=handles)
    return fig
