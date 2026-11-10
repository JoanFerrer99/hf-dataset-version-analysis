"""Pàgina 6: la validació del motor amb Census Income, codi per codi, contra la Taula 1 del paper."""

import streamlit as st

import charts
import data
import palette
from fmt import num, pct

st.title("Validació")
st.markdown(
    "El paper etiqueta a mà els canvis de 7 versions del dataset Census Income publicades a Hugging Face "
    "(D1-D7) respecte a l'original de la UCI (D0). El motor fa el mateix, i aquí es compara el seu resultat "
    "amb la taula del paper, codi per codi: **encert** si tots dos marquen el codi en una versió, **fals "
    "negatiu** si només el paper, i **fals positiu** si només el motor. Els filtres de la barra lateral no "
    "s'apliquen aquí."
)

totals = data.census_totals()
cols = st.columns(3)
cols[0].metric("Precisió", pct(totals["precision"], 1), help=f"{num(totals['tp'])} encerts i {num(totals['fp'])} falsos positius.")
cols[1].metric("Recall", pct(totals["recall"], 1), help=f"{num(totals['fn'])} falsos negatius.")
cols[2].metric("F1", pct(totals["f1"], 1))

st.subheader("Per codi")
by_code = data.census_validation()
measures = {"precision": "Precisió", "recall": "Recall", "f1": "F1"}
st.altair_chart(charts.grouped_measures(by_code, measures, palette.current()), width="stretch")
st.caption("Tres columnes per codi: precisió, recall i F1. Una mesura sense denominador (p.e. el recall d'un codi "
           "que el paper no marca mai) no es dibuixa, i una de 0 no té alçada: a C510, el motor el marca dues vegades "
           "i el paper cap (precisió 0, recall sense definir). La taula en té els recomptes.")
st.dataframe(
    by_code,
    hide_index=True,
    column_config={
        "code": "Codi", "name": "Canvi", "perspective": "Categoria (paper)", "true_positives": "Encerts",
        "false_negatives": "Falsos negatius", "false_positives": "Falsos positius",
        "precision": st.column_config.NumberColumn("Precisió", format="percent"),
        "recall": st.column_config.NumberColumn("Recall", format="percent"),
        "f1": st.column_config.NumberColumn("F1", format="percent"),
    },
)

st.subheader("Per què hi ha falsos positius")
st.markdown(
    "El motor troba tots els codis del paper. Cap dels falsos positius és un error del motor: són canvis reals "
    "que el paper no compta.\n\n"
    "- **C421** (afegir fila): D3, D4 i D6 tenen files d'`adult.test`; el paper compta files i no les veu.\n"
    "- **C410** (ordre de files): D4 i D6 tenen les files en un ordre aleatori real (a D3, amb les mateixes "
    "files que D4, el paper sí que el marca).\n"
    "- **C222, C311, C422, C510**: columnes eliminades que la fitxa no esmenta, el canvi de tipus de D7 (a D3 i "
    "D4 el paper el marca), files amb `?` eliminades a D7, i els `?` que desapareixen a D6 i D7.\n\n"
    "Cada cas, explicat amb les dades, és a `docs/validacio_census_income.md`. El magatzem només té el "
    "resultat per codi; el detall per versió és al mateix document."
)
