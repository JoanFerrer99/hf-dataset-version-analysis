"""
Gràfics de la interfície (Altair), amb les mateixes regles a tots: barres
primes (màxim 24 px) amb l'extrem arrodonit, línies de quadrícula fines, el
color segons l'entitat i sempre amb llegenda, etiqueta o taula al costat, de
manera que el color no és mai l'única manera de llegir una categoria.
"""

import altair as alt
import pandas as pd

BAR = 18  # gruix de les barres (px)
# Números a la catalana a tots els gràfics (1.868; 0,42%).
LOCALE = alt.Locale(number=alt.NumberLocale(decimal=",", thousands=".", grouping=[3], currency=["", " €"]))


def _axes(chart: alt.Chart, palette: dict) -> alt.Chart:
    """Eixos i quadrícula discrets, del color del text secundari."""
    return (chart
            .configure(locale=LOCALE)
            .configure_axis(gridColor=palette["grid"], gridWidth=1, domainColor=palette["axis"],
                            tickColor=palette["axis"], labelColor=palette["muted"], titleColor=palette["muted"],
                            labelFontSize=12, titleFontSize=12)
            .configure_legend(labelColor=palette["text"], titleColor=palette["muted"], orient="top")
            .configure_view(stroke=None))


def funnel(df: pd.DataFrame, palette: dict) -> alt.Chart:
    """
    Embut de la Fase 0: una barra horitzontal per pas, en escala logarítmica
    (de 2.000 a una desena), amb el valor a l'extrem.

    :param df: `mart_funnel` (stage_order, stage_label, n_datasets).
    """
    top = 10 ** len(str(int(df["n_datasets"].max())))
    base = alt.Chart(df).encode(
        y=alt.Y("stage_label:N", sort=alt.SortField("stage_order"), title=None, axis=alt.Axis(labelLimit=340)),
        x=alt.X("n_datasets:Q", title="Datasets (escala logarítmica)",
                scale=alt.Scale(type="log", domain=[1, top]),
                axis=alt.Axis(values=[10 ** i for i in range(len(str(top)))], format=",d")),
    )
    # En escala logarítmica, les barres comencen a 1 (no hi ha zero).
    bars = base.mark_bar(size=BAR, cornerRadiusEnd=4).encode(
        x2=alt.datum(1),
        color=alt.Color("stage_label:N", sort=alt.SortField("stage_order"),
                        scale=alt.Scale(range=palette["ordinal"]), legend=None),
        tooltip=[alt.Tooltip("stage_label:N", title="Pas"), alt.Tooltip("n_datasets:Q", title="Datasets"),
                 alt.Tooltip("n_dropped:Q", title="S'hi queden")],
    )
    labels = base.mark_text(align="left", dx=6, color=palette["text"]).encode(
        text=alt.Text("n_datasets:Q", format=",d"))
    return _axes((bars + labels).properties(height=5 * 44), palette)


def share_with_interval(df: pd.DataFrame, category: str, share: str, low: str, high: str, palette: dict,
                        category_title: str, share_title: str, order: list[str] | None = None,
                        full_scale: bool = True) -> alt.Chart:
    """
    Una proporció per categoria amb el seu interval de confiança: un punt i una
    línia horitzontal fina de `low` a `high`, i el valor a l'esquerra.

    :param df: una fila per categoria.
    :param full_scale: l'eix va de 0 a 1; si no, de 0 al màxim de l'interval.
    """
    base = alt.Chart(df).encode(y=alt.Y(f"{category}:N", sort=order, title=None, axis=alt.Axis(labelLimit=340)))
    interval = base.mark_rule(strokeWidth=2, color=palette["series"][0]).encode(
        x=alt.X(f"{low}:Q", axis=alt.Axis(format="%"), title=share_title,
                scale=alt.Scale(domain=[0, 1]) if full_scale else alt.Scale(zero=True)),
        x2=f"{high}:Q",
    )
    points = base.mark_point(filled=True, size=90, color=palette["series"][0],
                             stroke=palette["surface"], strokeWidth=2).encode(
        x=f"{share}:Q",
        tooltip=[alt.Tooltip(f"{category}:N", title=category_title),
                 alt.Tooltip(f"{share}:Q", title=share_title, format=".1%"),
                 alt.Tooltip(f"{low}:Q", title="Interval 95%: des de", format=".1%"),
                 alt.Tooltip(f"{high}:Q", title="fins a", format=".1%")],
    )
    labels = base.mark_text(align="left", dx=10, dy=-10, color=palette["text"]).encode(
        x=f"{share}:Q", text=alt.Text(f"{share}:Q", format=".2%" if not full_scale else ".1%"))
    return _axes((interval + points + labels).properties(height=max(len(df), 1) * 48), palette)
