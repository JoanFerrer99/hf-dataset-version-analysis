"""Pàgina 1: la pregunta de recerca, les xifres clau, el pipeline i la taxonomia."""

import streamlit as st

import data
from fmt import num, pct

st.title("Com canvien els datasets de Hugging Face")
st.markdown(
    "> **Com canvien els datasets publicats a Hugging Face d'una versió a la següent, "
    "i amb quina freqüència apareix cada tipus de canvi?**"
)
st.markdown(
    "Molts sistemes d'aprenentatge automàtic s'entrenen amb datasets de tercers. Si el mantenidor "
    "reanomena una columna, afegeix files o reescala una variable, el pipeline de qui el consumeix pot "
    "fallar o seguir funcionant amb dades que ja no són les que esperava. Aquesta interfície mostra què "
    "ha trobat el pipeline en una mostra aleatòria de datasets."
)

run = data.run_info()
st.caption(f"Execució `{run['run_id']}`, del {run['run_date']:%d/%m/%Y}." if run["run_date"] is not None
           else "Execució sense data.")

figures = data.key_figures()
cols = st.columns(4)
cols[0].metric("Datasets de la mostra", num(figures["sample_size"]))
cols[1].metric("Elegibles (≥2 versions amb dades tabulars)", figures["eligible"],
               help=f"Criteri A (tags): {figures['eligible_a']}. Criteri B (sessions): {figures['eligible_b']}.")
cols[2].metric("Comparacions fetes", f"{figures['n_compared_units']} de {figures['n_units']}",
               help="Cada versió contra la següent. No es compten les que no s'han pogut fer.")
cols[3].metric("Canvis detectats", num(figures["n_changes"]), help=f"{figures['n_codes']} codis diferents de la taxonomia.")
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
