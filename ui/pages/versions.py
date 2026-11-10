"""Pàgina 3: les versions de cada dataset elegible al llarg del temps (tags o sessions de commits)."""

import streamlit as st

import charts
import data
import filters
import palette

st.title("Versions")
st.markdown(
    "Què és una versió depèn del criteri que fa elegible el dataset: amb el **Criteri A**, cada tag; amb el "
    "**Criteri B**, cada sessió de commits que toquen dades tabulars, representada pel seu commit més recent. "
    "S'apliquen els filtres de dataset i de criteri."
)

selected = filters.current()
versions = data.versions(selected)
if versions.empty:
    st.info("Cap versió amb aquests filtres.")
    st.stop()

st.subheader("Línia temporal")
st.altair_chart(charts.timeline(versions, palette.current()), width="stretch")
st.caption("Cada fila és un dataset i cada punt, una versió: rodona si és un tag, quadrat si és una sessió de "
           "commits. La línia va de la primera versió a l'última.")
st.dataframe(
    versions[["dataset_id", "version_order", "version_label", "source_label", "commit_date", "commit_url"]],
    hide_index=True,
    column_config={
        "dataset_id": "Dataset",
        "version_order": st.column_config.NumberColumn("Ordre", format="%d"),
        "version_label": "Versió",
        "source_label": "Tipus",
        "commit_date": st.column_config.DatetimeColumn("Data (UTC)", format="DD/MM/YYYY HH:mm"),
        "commit_url": st.column_config.LinkColumn("Commit a Hugging Face", display_text=r"commit/([0-9a-f]{7})"),
    },
)

st.subheader("Resum per dataset")
profiles = data.dataset_profiles(selected)
st.dataframe(
    profiles,
    hide_index=True,
    column_config={
        "dataset_id": "Dataset",
        "dataset_url": st.column_config.LinkColumn("Hugging Face", display_text="obre"),
        "eligibility_criterion": "Criteri",
        "n_versions": "Versions",
        "first_version_at": st.column_config.DatetimeColumn("Primera", format="DD/MM/YYYY"),
        "last_version_at": st.column_config.DatetimeColumn("Última", format="DD/MM/YYYY"),
        "n_units": "Comparacions",
        "n_compared_units": "Fetes",
        "n_units_with_change": "Amb canvis",
        "n_tables": "Taules",
        "n_changes": "Canvis",
        "n_breaking_changes": "Trencadors",
        "codes": "Codis",
    },
)
st.caption("Comparacions: cada versió contra la següent. Fetes: les que tenen alguna taula comparada (les altres "
           "eren massa grans, no s'han pogut llegir o no tenien cap taula en comú).")
