"""Pàgina: quines comparacions s'han pogut fer, i per què no les altres."""

import streamlit as st

import charts
import data
import filters
import palette
import shell
from fmt import num

st.markdown(
    "Una **comparació** és una versió d'un dataset contra la següent. Es fa taula a taula: una comparació "
    "compta com a feta si almenys una taula s'ha pogut comparar. Les que no s'han pogut fer no entren a les "
    "proporcions de la pàgina de canvis: no se sap si tenen canvis. S'apliquen els filtres de dataset i criteri."
)

selected = filters.current()
coverage = data.coverage_by_dataset(selected)
if coverage.empty:
    st.info("Cap comparació amb aquests filtres.")
    st.stop()

unreadable = int(coverage["tables_parse_failed"].sum() + coverage["tables_download_failed"].sum())
shell.figure_cards([
    {"label": "Comparacions fetes", "value": f"{num(coverage['units_compared'].sum())} de {num(coverage['n_units'].sum())}",
     "hint": "Almenys una taula comparada"},
    {"label": "No fetes", "value": num(coverage["units_not_compared"].sum()),
     "hint": "Cap taula comparada: massa grans o il·legibles"},
    {"label": "Sense cap taula en comú", "value": num(coverage["units_no_common_table"].sum()),
     "hint": "Només taules afegides, eliminades o excloses"},
    {"label": "Taules il·legibles", "value": num(unreadable),
     "hint": "Dins de comparacions fetes o no"},
], key="coverage_cards")

st.subheader("Comparacions de cada dataset")
st.altair_chart(charts.units_by_status(coverage, data.UNIT_STATUSES, data.SHORT_UNIT_STATUS, palette.current()),
                width="stretch")
st.caption("Cada barra és un dataset, i cada segment, les seves comparacions d'un estat. Un dataset amb moltes "
           "versions té moltes comparacions.")
st.dataframe(
    coverage[["dataset_id", "eligibility_criterion", "n_units", "units_compared", "units_not_compared",
              "units_no_common_table", "n_tables"]],
    hide_index=True,
    column_config={"dataset_id": "Dataset", "eligibility_criterion": "Criteri", "n_units": "Comparacions",
                   "units_compared": "Fetes", "units_not_compared": "No fetes",
                   "units_no_common_table": "Cap taula en comú", "n_tables": "Parells de taules"},
)

st.subheader("Comparacions incompletes")
incomplete = data.incomplete_units(selected)
if incomplete.empty:
    st.success("Totes les comparacions s'han pogut fer senceres.")
else:
    st.markdown("Les comparacions que no s'han pogut fer, i les fetes amb alguna taula que no s'ha pogut comparar.")
    st.dataframe(
        incomplete[["dataset_id", "label_to", "url_to", "date_to", "status_label", "reason"]],
        hide_index=True,
        column_config={
            "dataset_id": "Dataset", "label_to": "Versió nova",
            "url_to": st.column_config.LinkColumn("Commit", display_text=r"commit/([0-9a-f]{7})"),
            "date_to": st.column_config.DatetimeColumn("Data (UTC)", format="DD/MM/YYYY"),
            "status_label": "Comparació", "reason": "Taules sense comparar",
        },
    )

with st.expander("Què vol dir cada estat d'una taula", icon=":material/info:"):
    totals = {status: int(coverage[f"tables_{status}"].sum()) for status in data.TABLE_STATUSES}
    st.table({"Estat": list(data.TABLE_STATUSES.values()), "Taules": [num(totals[s]) for s in data.TABLE_STATUSES]})
