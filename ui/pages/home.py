"""Pàgina 1: la pregunta de recerca, les xifres clau, el pipeline i la taxonomia."""

import streamlit as st

import data
import shell
from fmt import num, pct

st.markdown(
    "Molts sistemes d'aprenentatge automàtic s'entrenen amb datasets de tercers. Si el mantenidor "
    "reanomena una columna, afegeix files o reescala una variable, el pipeline de qui el consumeix pot "
    "fallar o seguir funcionant amb dades que ja no són les que esperava. Aquesta interfície mostra què "
    "ha trobat el pipeline en una mostra aleatòria de datasets."
)

figures = data.key_figures()
opened = shell.figure_cards(shell.figure_cards_data(figures, num))
if opened:
    st.switch_page(shell.page(opened)["path"])
st.markdown(
    f"Dels {num(figures['classified'])} datasets que s'han pogut classificar, el "
    f"**{pct(figures['eligible_share'])}** són elegibles (interval de confiança del 95%: "
    f"{pct(figures['eligible_low'])} a {pct(figures['eligible_high'])})."
)

st.subheader("El pipeline")
st.graphviz_chart("""
digraph {
    rankdir=LR;
    node [shape=box, style="rounded", fontname="Helvetica"];
    hf [label="Hugging Face\\n(~1 M datasets)"];
    f0 [label="Fase 0\\nMostreig i elegibilitat"];
    f1 [label="Fase 1\\nVersions"];
    f2 [label="Fase 2\\nClassificació de canvis"];
    f3 [label="Fase 3\\nMagatzem (dbt + DuckDB)"];
    ui [label="Interfície"];
    hf -> f0 -> f1 -> f2 -> f3 -> ui;
}
""")

st.subheader("La taxonomia de canvis")
st.markdown("Els 14 tipus de canvi tabulars (C100, metadades, és fora d'abast). "
            "Un canvi **trencador** fa fallar un pipeline que llegeix el dataset per nom, posició, tipus o ordre.")
st.dataframe(
    data.taxonomy().rename(columns={"code": "Codi", "name": "Canvi", "perspective": "Categoria (paper)",
                                    "level_1": "Perspectiva", "is_breaking": "Trencador"}),
    hide_index=True,
)
