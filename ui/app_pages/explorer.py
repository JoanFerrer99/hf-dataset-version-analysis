"""Pàgina 5: un dataset, les seves comparacions i els codis de cada una, amb enllaços a Hugging Face."""

import streamlit as st

import data
import filters
from fmt import num, size

st.markdown(
    "Tria un dataset i una de les seves comparacions (una versió contra la següent) per veure quins canvis hi "
    "ha. S'apliquen els filtres de dataset, criteri i perspectiva."
)

selected = filters.current()
datasets = data.explorer_datasets(selected)
if not datasets:
    st.info("Cap dataset amb aquests filtres.")
    st.stop()

dataset_id = st.selectbox("Dataset", datasets, key="explorer_dataset")
st.markdown(f"[{dataset_id} a Hugging Face]({data.HF}{dataset_id})")

units = data.explorer_units(dataset_id)
if units.empty:
    st.info("Aquest dataset no té cap comparació: només té una versió.")
    st.stop()

cols = st.columns(3)
cols[0].metric("Comparacions", num(len(units)))
cols[1].metric("Fetes", num((units["unit_status"] == "compared").sum()))
cols[2].metric("Amb canvis", num((units["n_codes"] > 0).sum()))

st.subheader("Comparacions")
st.dataframe(
    units[["label_from", "url_from", "label_to", "url_to", "date_to", "status_label", "format_to", "n_files_to",
           "n_codes"]],
    hide_index=True,
    column_config={
        "label_from": "Versió antiga",
        "url_from": st.column_config.LinkColumn("Commit antic", display_text=r"commit/([0-9a-f]{7})"),
        "label_to": "Versió nova",
        "url_to": st.column_config.LinkColumn("Commit nou", display_text=r"commit/([0-9a-f]{7})"),
        "date_to": st.column_config.DatetimeColumn("Data (UTC)", format="DD/MM/YYYY"),
        "status_label": "Estat",
        "format_to": "Format",
        "n_files_to": "Fitxers",
        "n_codes": "Canvis",
    },
)

options = list(range(len(units)))
choice = st.selectbox(
    "Comparació", options, key="explorer_unit",
    format_func=lambda i: f"{units.loc[i, 'label_from']} → {units.loc[i, 'label_to']}  ({num(units.loc[i, 'n_codes'])} canvis)",
)
unit = units.loc[choice]
st.markdown(f"De [{unit['label_from']}]({unit['url_from']}) a [{unit['label_to']}]({unit['url_to']}): "
            f"{unit['status_label'].lower()}. El dataset passa de {num(unit['n_files_from'])} a "
            f"{num(unit['n_files_to'])} fitxers ({size(unit['size_bytes'])} entre les dues versions).")

st.subheader("Codis")
changes = data.explorer_changes(dataset_id, unit["version_from"], unit["version_to"], selected)
if changes.empty:
    if unit["unit_status"] != "compared":
        st.info("No hi ha codis perquè aquesta comparació no s'ha pogut fer.")
    elif unit["n_codes"] > 0:
        st.info("Aquesta comparació té canvis, però cap amb els filtres de perspectiva triats.")
    else:
        st.info("El dataset no ha canviat entre aquestes dues versions.")
else:
    st.caption(f"{num(len(changes))} codis.")
    st.dataframe(
        changes,
        hide_index=True,
        column_config={"code": "Codi", "name": "Canvi", "level_1": "Perspectiva"},
    )
