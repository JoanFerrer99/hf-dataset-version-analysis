"""Pàgina 3: les versions de cada dataset elegible al llarg del temps (tags o sessions de commits)."""

import streamlit as st

import charts
import data
import filters
import palette

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

st.subheader("Mesures de cada versió")
st.dataframe(
    versions[["dataset_id", "version_label", "position_label", "differences", "conception_days", "lifespan_days",
              "data_size_bytes", "metadata_size_bytes", "n_data_files", "n_metadata_files", "session_commit_count",
              "n_rows", "n_columns"]],
    hide_index=True,
    column_config={
        "dataset_id": "Dataset",
        "version_label": "Versió",
        "position_label": "Posició",
        "differences": "Canvis respecte a l'anterior",
        "conception_days": st.column_config.NumberColumn("Dies des de l'anterior", format="%d"),
        "lifespan_days": st.column_config.NumberColumn("Dies fins a la següent", format="%d"),
        "data_size_bytes": st.column_config.NumberColumn("Dades (bytes)", format="%d"),
        "metadata_size_bytes": st.column_config.NumberColumn("Metadades (bytes)", format="%d"),
        "n_data_files": "Fitxers de dades",
        "n_metadata_files": "Fitxers de metadades",
        "session_commit_count": "Commits de la sessió",
        "n_rows": st.column_config.NumberColumn("Files", format="%d"),
        "n_columns": "Columnes",
    },
)
st.caption("Canvis: els codis respecte a la versió anterior; `first_version` és la primera, `no_changes` una "
           "comparació sense canvis i `not_compared` una que no s'ha pogut fer. Les files i columnes són buides si "
           "el dataset no s'ha llegit (p.e. massa gran).")

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
        "n_units_not_compared": "No fetes",
        "n_changes": "Canvis",
        "codes": "Codis",
    },
)
st.caption("Comparacions: cada versió contra la següent. Fetes: les que s'han pogut comparar (vegeu la pàgina de "
           "cobertura per saber per què no les altres).")

st.subheader("Intervals de cada dataset")
st.dataframe(
    data.dataset_bands(selected),
    hide_index=True,
    column_config={
        "dataset_id": "Dataset",
        "downloads_band": "Descàrregues",
        "initial_size_band": "Mida inicial",
        "initial_rows_band": "Files inicials",
        "initial_columns_band": "Columnes inicials",
        "n_versions_band": "Versions",
        "n_tabular_commits_band": "Commits tabulars",
    },
)
st.caption("Intervals calculats amb k-means (3 clústers sobre el logaritme del valor): Few, Medium i Many per a "
           "les descàrregues, de tota la mostra; Low, Medium i High per a la resta, entre els elegibles.")
