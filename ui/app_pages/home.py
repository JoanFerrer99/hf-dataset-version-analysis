"""Pàgina d'inici: el resum de l'execució, amb les xifres clau i els destacats, que porten a cada pàgina."""

import streamlit as st

import data
import shell
from fmt import num, pct

opened = shell.figure_cards(shell.figure_cards_data(data.key_figures(), num))

st.subheader("Destacats")
highlighted = shell.figure_cards(shell.highlight_cards_data(data.highlights(), num, pct), key="home_highlights")

for target in (opened, highlighted):
    if target:
        st.switch_page(shell.page(target)["path"])

with st.expander("Els 14 codis de la taxonomia", icon=":material/menu_book:"):
    st.markdown("C100 (metadades) és fora d'abast. Un canvi **trencador** fa fallar un pipeline que llegeix el "
                "dataset per nom, posició, tipus o ordre.")
    st.dataframe(
        data.taxonomy().rename(columns={"code": "Codi", "name": "Canvi", "perspective": "Categoria (paper)",
                                        "level_1": "Perspectiva", "is_breaking": "Trencador"}),
        hide_index=True,
    )
