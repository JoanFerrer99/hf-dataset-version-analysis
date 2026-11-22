"""Pàgina: quins canvis surten, en quins datasets, quantes comparacions en tenen i com evolucionen al llarg del temps."""

import streamlit as st

import charts
import data
import filters
import palette
from fmt import num, pct

st.markdown(
    "Cada canvi és un codi de la taxonomia detectat entre una versió d'un dataset i la següent. Una "
    "**comparació** és un parell de versions consecutives; només compten les que s'han pogut fer. "
    "S'apliquen tots els filtres de la barra lateral (a la proporció de comparacions amb canvis, només el de criteri)."
)

selected = filters.current()
colors = palette.current()

st.subheader("Freqüència de cada codi")
frequency = data.code_frequency(selected)
# Un codi surt com a molt un cop per comparació (es compara el dataset sencer, T-37): comptar canvis o
# comparacions afectades dona el mateix.
MEASURES = {"Comparacions afectades": ("n_units", "Comparacions amb el codi"),
            "Datasets afectats": ("n_datasets", "Datasets amb el codi")}
measure = st.segmented_control("Mesura", list(MEASURES), default="Comparacions afectades", key="changes_measure")
column, title = MEASURES[measure or "Comparacions afectades"]
if frequency.empty:
    st.info("Cap codi amb aquests filtres.")
else:
    st.altair_chart(charts.code_bars(frequency, column, title, colors), width="stretch")
    st.caption("Una barra per codi, en l'ordre de la taxonomia i del color de la seva perspectiva. Comparacions: "
               "quantes versions contra la següent tenen el codi. Datasets: quants el tenen en alguna comparació.")
    st.dataframe(
        frequency[["code", "name", "level_1", "n_units", "n_datasets", "share_of_compared_units"]],
        hide_index=True,
        column_config={
            "code": "Codi", "name": "Canvi", "level_1": "Perspectiva",
            "n_units": "Comparacions", "n_datasets": "Datasets",
            "share_of_compared_units": st.column_config.NumberColumn("De les comparacions fetes", format="percent"),
        },
    )

st.subheader("Per dataset")
by_dataset = data.changes_by_dataset(selected)
if by_dataset.empty:
    st.info("Cap canvi amb aquests filtres.")
else:
    st.altair_chart(charts.heatmap(by_dataset, "n_units", "Comparacions", colors, list(frequency["code"])),
                    width="stretch")
    st.caption("Una fila per dataset amb algun canvi i una columna per codi: quantes de les seves comparacions "
               "tenen el codi. Com més fosca, més comparacions. Els datasets sense cap canvi no hi surten "
               "(vegeu la pàgina de cobertura).")
    st.dataframe(
        by_dataset[["dataset_id", "code", "name", "level_1", "n_units"]],
        hide_index=True,
        column_config={"dataset_id": "Dataset", "code": "Codi", "name": "Canvi", "level_1": "Perspectiva",
                       "n_units": "Comparacions"},
    )

st.subheader("Comparacions amb algun canvi")
shares = data.change_share(selected)
if shares.empty:
    st.info("Cap comparació amb aquests filtres.")
else:
    total = shares.set_index("criterion").loc["all"] if "all" in set(shares["criterion"]) else None
    if total is not None:
        st.markdown(
            f"De les {num(total['n_compared_units'])} comparacions fetes, **{num(total['n_units_with_change'])}** "
            f"tenen algun canvi (**{pct(total['share_with_change'], 1)}**, interval del 95%: "
            f"{pct(total['share_with_change_low'], 1)} a {pct(total['share_with_change_high'], 1)})."
        )
    st.altair_chart(
        charts.share_with_interval(shares, "criterion_label", "share_with_change",
                                   "share_with_change_low", "share_with_change_high", colors,
                                   category_title="Criteri", share_title="Comparacions amb algun canvi",
                                   order=list(shares["criterion_label"])),
        width="stretch",
    )
    st.caption("El punt és la proporció de comparacions fetes amb algun canvi, i la línia, l'interval de "
               "confiança del 95% (Wilson). Amb poques comparacions, l'interval és ample.")
    st.dataframe(
        shares[["criterion_label", "n_compared_units", "n_units_with_change", "share_with_change",
                "share_with_change_low", "share_with_change_high"]],
        hide_index=True,
        column_config={
            "criterion_label": "Criteri", "n_compared_units": "Comparacions fetes",
            "n_units_with_change": "Amb canvis",
            "share_with_change": st.column_config.NumberColumn("Proporció", format="percent"),
            "share_with_change_low": st.column_config.NumberColumn("Interval: des de", format="percent"),
            "share_with_change_high": st.column_config.NumberColumn("fins a", format="percent"),
        },
    )

st.subheader("Evolució per trimestre")
quarters = data.changes_by_quarter(selected)
if quarters.empty:
    st.info("Cap canvi amb aquests filtres.")
else:
    st.altair_chart(charts.stacked_by_quarter(quarters, colors), width="stretch")
    st.caption("Canvis per trimestre de la versió nova, apilats per perspectiva. Només hi surten els trimestres "
               "amb algun canvi.")
    st.dataframe(
        quarters[["year_quarter", "level_1", "n_changes", "n_units", "n_datasets"]],
        hide_index=True,
        column_config={"year_quarter": "Trimestre", "level_1": "Perspectiva", "n_changes": "Canvis",
                       "n_units": "Comparacions", "n_datasets": "Datasets"},
    )
