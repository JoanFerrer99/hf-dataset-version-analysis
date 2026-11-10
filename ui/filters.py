"""
Filtres de la barra lateral, comuns a totes les pàgines: dataset, criteri
d'elegibilitat, perspectiva i si el canvi és trencador. Es dibuixen a
`app.py` a cada execució, de manera que es conserven en canviar de pàgina
(`st.session_state`). Cada pàgina aplica els que tenen sentit per a les seves dades.
"""

from dataclasses import dataclass

import streamlit as st

import data

CRITERIA = {"A": "A: tags", "B": "B: sessions de commits"}
BREAKING = {"Tots els canvis": None, "Només trencadors": True, "Només no trencadors": False}


@dataclass(frozen=True)
class Filters:
    """
    :ivar datasets: datasets triats (buit = tots).
    :ivar criteria: criteris triats, `A` i/o `B` (buit = tots).
    :ivar perspectives: perspectives triades (buit = totes).
    :ivar breaking: `True` només trencadors, `False` només no trencadors, `None` tots.
    """

    datasets: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()
    perspectives: tuple[str, ...] = ()
    breaking: bool | None = None


def sidebar() -> None:
    """Dibuixa els filtres a la barra lateral."""
    perspectives = data.perspectives()
    with st.sidebar:
        st.header("Filtres")
        st.multiselect("Dataset", data.dataset_ids(), key="filter_datasets", placeholder="Tots")
        st.multiselect("Criteri d'elegibilitat", list(CRITERIA), format_func=CRITERIA.get,
                       key="filter_criteria", placeholder="Tots")
        st.multiselect("Perspectiva", list(perspectives), format_func=perspectives.get,
                       key="filter_perspectives", placeholder="Totes")
        st.radio("Canvis", list(BREAKING), key="filter_breaking")


def current() -> Filters:
    """
    :return: els filtres triats ara.
    """
    state = st.session_state
    return Filters(
        datasets=tuple(state.get("filter_datasets", [])),
        criteria=tuple(state.get("filter_criteria", [])),
        perspectives=tuple(state.get("filter_perspectives", [])),
        breaking=BREAKING.get(state.get("filter_breaking", "Tots els canvis")),
    )
