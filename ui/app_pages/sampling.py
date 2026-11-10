"""Pàgina 2: l'embut de la Fase 0, la proporció d'elegibles amb l'interval i el Criteri A contra el B."""

import streamlit as st

import charts
import data
import palette
from fmt import num, pct

st.markdown(
    "La Fase 0 agafa una mostra aleatòria uniforme de tots els datasets de Hugging Face i hi aplica tres "
    "filtres, del més barat al més car. Un dataset és **elegible** si té almenys dues versions amb canvis "
    "a les dades tabulars. Els filtres de la barra lateral no s'apliquen aquí: l'embut és de tota la mostra."
)

colors = palette.current()
funnel = data.funnel()
by_stage = funnel.set_index("stage")

st.subheader("Quants datasets passen cada filtre")
st.altair_chart(charts.funnel(funnel, colors), width="stretch")
st.caption(
    "Cada barra és un pas de l'embut: quants datasets hi arriben. L'escala és logarítmica perquè la mostra "
    "és de milers i els elegibles, una desena. Els inaccessibles (403) i els que van donar error no es "
    "classifiquen: no se sap si serien elegibles."
)
st.dataframe(
    funnel[["stage_label", "n_datasets", "n_dropped"]].rename(
        columns={"stage_label": "Pas", "n_datasets": "Hi arriben", "n_dropped": "S'hi queden"}),
    hide_index=True,
)

st.subheader("Quina proporció és elegible")
eligible = by_stage.loc["eligible"]
st.markdown(
    f"Dels {num(by_stage.loc['classified', 'n_datasets'])} datasets classificats, **{num(eligible['n_datasets'])}** "
    f"són elegibles: el **{pct(eligible['share_of_classified'])}**, amb un interval de confiança del 95% "
    f"(Wilson) de {pct(eligible['share_low'])} a {pct(eligible['share_high'])}."
)
shares = funnel[funnel["stage_order"] >= 3]
st.altair_chart(
    charts.share_with_interval(shares, "stage_label", "share_of_classified", "share_low", "share_high", colors,
                               category_title="Pas", share_title="Proporció dels classificats",
                               order=list(shares["stage_label"]), full_scale=False),
    width="stretch",
)
st.caption("El punt és la proporció dels classificats que arriben a cada filtre, i la línia, el seu interval de "
           "confiança del 95% (Wilson).")
st.dataframe(
    shares[["stage_label", "share_of_classified", "share_low", "share_high"]].rename(
        columns={"stage_label": "Pas", "share_of_classified": "Proporció", "share_low": "Interval: des de",
                 "share_high": "fins a"}),
    hide_index=True,
    column_config={c: st.column_config.NumberColumn(format="percent")
                   for c in ("Proporció", "Interval: des de", "fins a")},
)

st.subheader("Criteri A contra Criteri B")
cols = st.columns(2)
cols[0].metric("Criteri A: tags", num(eligible["n_criterion_a"]),
               help="2 tags com a mínim, i 2 commits que toquen dades tabulars com a mínim.")
cols[1].metric("Criteri B: sessions de commits", num(eligible["n_criterion_b"]),
               help="2 branques com a mínim, i commits tabulars en 2 sessions separades més de 6 hores.")
