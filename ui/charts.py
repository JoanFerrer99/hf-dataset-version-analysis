"""
Gràfics de la interfície (Altair), amb les mateixes regles a tots: barres
primes (màxim 24 px) amb l'extrem arrodonit, línies de quadrícula fines, el
color segons l'entitat i sempre amb llegenda, etiqueta o taula al costat, de
manera que el color no és mai l'única manera de llegir una categoria.
"""

import altair as alt
import pandas as pd

import palette as palettes

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


def timeline(df: pd.DataFrame, palette: dict) -> alt.Chart:
    """
    Línia temporal de versions: una fila per dataset, un punt per versió (color
    i forma segons si és un tag o una sessió) i una línia fina de la primera a
    l'última.

    :param df: `data.versions` (dataset_id, commit_date, source_label, version_label, commit_sha).
    """
    # El color i la forma segueixen el tipus de versió; a la llegenda, només els que hi ha.
    styles = {"Tag": (palette["series"][0], "circle"), "Sessió de commits": (palette["series"][1], "square"),
              "Commit": (palette["series"][2], "triangle-up")}
    present = [source for source in styles if source in set(df["source_label"])]
    y = alt.Y("dataset_id:N", title=None, axis=alt.Axis(labelLimit=320))
    span = alt.Chart(df).mark_rule(strokeWidth=1, color=palette["deemphasis"]).encode(
        y=y, x="min(commit_date):T", x2="max(commit_date):T")
    points = alt.Chart(df).mark_point(filled=True, size=90, opacity=1, stroke=palette["surface"], strokeWidth=2).encode(
        y=y,
        x=alt.X("commit_date:T", title="Data del commit", scale=alt.Scale(padding=14)),
        color=alt.Color("source_label:N", title="Versió",
                        scale=alt.Scale(domain=present, range=[styles[p][0] for p in present])),
        shape=alt.Shape("source_label:N", title="Versió",
                        scale=alt.Scale(domain=present, range=[styles[p][1] for p in present])),
        tooltip=[alt.Tooltip("dataset_id:N", title="Dataset"), alt.Tooltip("version_label:N", title="Versió"),
                 alt.Tooltip("source_label:N", title="Tipus"), alt.Tooltip("commit_date:T", title="Data"),
                 alt.Tooltip("commit_sha:N", title="Commit")],
    )
    return _axes((span + points).properties(height=max(df["dataset_id"].nunique(), 1) * 40 + 30), palette)


def _perspective_color(palette: dict, present: set[str]) -> alt.Color:
    """Color per perspectiva (`level_1`, en català), sempre el mateix per a cada una; a la llegenda, només les presents."""
    domain, colors = palettes.perspective_scale(palette)
    pairs = [(d, c) for d, c in zip(domain, colors) if d in present]
    return alt.Color("level_1:N", title="Perspectiva",
                     scale=alt.Scale(domain=[d for d, _ in pairs], range=[c for _, c in pairs]))


def code_bars(df: pd.DataFrame, measure: str, measure_title: str, palette: dict) -> alt.Chart:
    """
    Una barra horitzontal per codi, en l'ordre de la taxonomia, del color de la
    seva perspectiva. Els codis trencadors ho diuen a l'etiqueta.

    :param df: `data.code_frequency`.
    :param measure: columna del valor (`n_changes` o `n_units`).
    """
    df = df.assign(label=df["code"] + " " + df["name"] + df["is_breaking"].map({True: " (trencador)", False: ""}))
    return _axes(alt.Chart(df).mark_bar(size=BAR, cornerRadiusEnd=4).encode(
        y=alt.Y("label:N", sort=list(df["label"]), title=None, axis=alt.Axis(labelLimit=360)),
        x=alt.X(f"{measure}:Q", title=measure_title, axis=alt.Axis(format=",d", tickMinStep=1)),
        color=_perspective_color(palette, set(df["level_1"])),
        tooltip=[alt.Tooltip("code:N", title="Codi"), alt.Tooltip("name:N", title="Canvi"),
                 alt.Tooltip("level_1:N", title="Perspectiva"), alt.Tooltip("n_changes:Q", title="Canvis", format=",d"),
                 alt.Tooltip("n_units:Q", title="Comparacions"),
                 alt.Tooltip("share_of_compared_units:Q", title="De les comparacions fetes", format=".1%")],
    ).properties(height=len(df) * 30 + 20), palette)


def stacked_by_quarter(df: pd.DataFrame, palette: dict) -> alt.Chart:
    """
    Canvis per trimestre, apilats per perspectiva, amb 2 px del color del fons entre segments.

    :param df: `data.changes_by_quarter`.
    """
    quarters = sorted(df["year_quarter"].unique(), key=lambda q: (int(q[:4]), int(q[-1])))
    x = alt.X("year_quarter:O", sort=quarters, title="Trimestre de la versió nova",
              axis=alt.Axis(labelAngle=0, labelOverlap="greedy"))
    bars = alt.Chart(df).mark_bar(size=24, stroke=palette["surface"], strokeWidth=2).encode(
        x=x,
        y=alt.Y("sum(n_changes):Q", title="Canvis", axis=alt.Axis(format=",d", tickMinStep=1)),
        color=_perspective_color(palette, set(df["level_1"])),
        order=alt.Order("perspective_order:Q"),
        tooltip=[alt.Tooltip("year_quarter:O", title="Trimestre"), alt.Tooltip("level_1:N", title="Perspectiva"),
                 alt.Tooltip("sum(n_changes):Q", title="Canvis", format=",d"),
                 alt.Tooltip("sum(n_units):Q", title="Comparacions")],
    ).transform_calculate(
        perspective_order=f"indexof({palettes.PERSPECTIVES!r}, datum.perspective)"
    )
    # El total de cada trimestre a sobre de la columna: també es llegeixen els trimestres amb pocs canvis.
    totals = alt.Chart(df).mark_text(dy=-8, color=palette["text"]).encode(
        x=x, y="sum(n_changes):Q", text=alt.Text("sum(n_changes):Q", format=",d"))
    return _axes((bars + totals).properties(height=320), palette)


def grouped_measures(df: pd.DataFrame, measures: dict[str, str], palette: dict) -> alt.Chart:
    """
    Tres mesures entre 0 i 1 per codi (p.e. precisió, recall i F1), una columna
    de cada al costat de l'altra. Les mesures buides (denominador 0) no es dibuixen.

    :param df: una fila per codi, amb una columna per mesura.
    :param measures: columna -> nom de la mesura, en l'ordre de la llegenda.
    """
    long = df.melt(id_vars=["code", "name"], value_vars=list(measures), var_name="measure", value_name="value")
    long = long.assign(measure=long["measure"].map(measures)).dropna(subset=["value"])
    names = list(measures.values())
    return _axes(alt.Chart(long).mark_bar(size=10, cornerRadiusEnd=4).encode(
        x=alt.X("code:N", title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("measure:N", sort=names),
        y=alt.Y("value:Q", title=None, scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
        color=alt.Color("measure:N", title="Mesura", sort=names,
                        scale=alt.Scale(domain=names, range=palette["series"][:len(names)])),
        tooltip=[alt.Tooltip("code:N", title="Codi"), alt.Tooltip("name:N", title="Canvi"),
                 alt.Tooltip("measure:N", title="Mesura"), alt.Tooltip("value:Q", title="Valor", format=".1%")],
    ).properties(height=300), palette)
