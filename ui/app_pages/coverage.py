"""Pàgina: quines comparacions s'han pogut fer, i per què no les altres."""

import streamlit as st

import charts
import data
import filters
import palette
import shell
from fmt import num, size

st.markdown(
    "Una **comparació** és una versió d'un dataset contra la següent. Es compara el dataset sencer, amb tots els "
    "seus fitxers de dades. Les que no s'han pogut fer no entren a les proporcions de la pàgina de canvis: no se "
    "sap si tenen canvis. S'apliquen els filtres de dataset i criteri."
)

selected = filters.current()
coverage = data.coverage_by_dataset(selected)
if coverage.empty:
    st.info("Cap comparació amb aquests filtres.")
    st.stop()

shell.figure_cards([
    {"label": "Comparacions fetes", "value": f"{num(coverage['units_compared'].sum())} de {num(coverage['n_units'].sum())}",
     "hint": "El dataset sencer, comparat"},
    {"label": "No fetes", "value": num(coverage["units_not_compared"].sum()),
     "hint": "Massa grans, o no s'han pogut baixar o llegir"},
    {"label": "Sense dades", "value": num(coverage["units_no_data"].sum()),
     "hint": "Una de les versions no té cap fitxer de dades"},
    {"label": "Fallades o sense estat", "value": num(coverage["units_failed"].sum() + coverage["units_not_run"].sum()),
     "hint": "La Fase 2 va fallar en el dataset o no hi va arribar"},
], key="coverage_cards")

st.subheader("Comparacions de cada dataset")
st.altair_chart(charts.units_by_status(coverage, data.UNIT_STATUSES, data.SHORT_UNIT_STATUS, palette.current()),
                width="stretch")
st.caption("Cada barra és un dataset, i cada segment, les seves comparacions d'un estat. Un dataset amb moltes "
           "versions té moltes comparacions.")
st.dataframe(
    coverage[["dataset_id", "eligibility_criterion", "n_units", "units_compared", "units_not_compared",
              "units_no_data"]],
    hide_index=True,
    column_config={"dataset_id": "Dataset", "eligibility_criterion": "Criteri", "n_units": "Comparacions",
                   "units_compared": "Fetes", "units_not_compared": "No fetes", "units_no_data": "Sense dades"},
)

st.subheader("Comparacions que no s'han pogut fer")
incomplete = data.incomplete_units(selected)
if incomplete.empty:
    st.success("Totes les comparacions s'han pogut fer.")
else:
    incomplete["size"] = incomplete["size_bytes"].map(size)
    st.dataframe(
        incomplete[["dataset_id", "label_to", "url_to", "date_to", "status_label", "reason", "n_files_to", "size"]],
        hide_index=True,
        column_config={
            "dataset_id": "Dataset", "label_to": "Versió nova",
            "url_to": st.column_config.LinkColumn("Commit", display_text=r"commit/([0-9a-f]{7})"),
            "date_to": st.column_config.DatetimeColumn("Data (UTC)", format="DD/MM/YYYY"),
            "status_label": "Comparació", "reason": "Motiu", "n_files_to": "Fitxers (versió nova)",
            "size": "Mida (les dues versions)",
        },
    )

with st.expander("Què vol dir cada estat d'una comparació", icon=":material/info:"):
    totals = {status: int(coverage[f"status_{status}"].sum()) for status in data.COMPARISON_STATUSES}
    st.table({"Estat": list(data.COMPARISON_STATUSES.values()),
              "Comparacions": [num(totals[s]) for s in data.COMPARISON_STATUSES]})
