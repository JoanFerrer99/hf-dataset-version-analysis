"""
Filtres comuns a totes les pàgines (dataset, criteri d'elegibilitat i
perspectiva), en una barra plegable sota la
capçalera. Es dibuixen a `app.py` a cada execució, de manera que es conserven
en canviar de pàgina (`st.session_state`). Cada pàgina aplica els que tenen
sentit per a les seves dades.
"""

from dataclasses import dataclass

import streamlit as st

import data

CRITERIA = {"A": "A: tags", "B": "B: sessions de commits"}


@dataclass(frozen=True)
class Filters:
    """
    :ivar datasets: datasets triats (buit = tots).
    :ivar criteria: criteris triats, `A` i/o `B` (buit = tots).
    :ivar perspectives: perspectives triades (buit = totes).
    """

    datasets: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()
    perspectives: tuple[str, ...] = ()


def active_count() -> int:
    """
    :return: quants filtres estan triats ara (per dir-ho a l'etiqueta de la barra).
    """
    selected = current()
    return sum([bool(selected.datasets), bool(selected.criteria), bool(selected.perspectives)])


def bar() -> None:
    """Dibuixa la barra de filtres, plegada; l'etiqueta diu quants n'hi ha d'actius."""
    perspectives = data.perspectives()
    count = active_count()
    label = f"Filtres ({count} actius)" if count else "Filtres"
    with st.expander(label, icon=":material/filter_list:"):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
            st.multiselect("Dataset", data.dataset_ids(), key="filter_datasets", placeholder="Tots", width=360)
            st.pills("Criteri d'elegibilitat", list(CRITERIA), format_func=CRITERIA.get, selection_mode="multi",
                     key="filter_criteria")
            st.pills("Perspectiva", list(perspectives), format_func=perspectives.get, selection_mode="multi",
                     key="filter_perspectives")


def current() -> Filters:
    """
    :return: els filtres triats ara.
    """
    state = st.session_state
    return Filters(
        datasets=tuple(state.get("filter_datasets", [])),
        criteria=tuple(state.get("filter_criteria", [])),
        perspectives=tuple(state.get("filter_perspectives", [])),
    )
