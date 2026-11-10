"""
Colors de la interfície (i de les figures de la memòria), validats amb les
sis comprovacions de daltonisme, contrast i separació: 4 categories en
gràfics de barres o apilats, 3 en qualsevol forma, i una rampa ordinal d'un
sol to per als passos de l'embut. El tema fosc té els seus propis tons, no
una inversió del clar.

El color segueix l'entitat, no la posició: cada perspectiva té sempre el
mateix color, encara que un filtre en tregui alguna.
"""

LIGHT = {
    "surface": "#ffffff",
    "text": "#0b0b0b",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "deemphasis": "#c3c2b7",
    "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
    "ordinal": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
}

DARK = {
    "surface": "#0e1117",
    "text": "#f0efec",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "deemphasis": "#52514e",
    "series": ["#3987e5", "#d95926", "#199e70", "#c98500"],
    "ordinal": ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"],
}

# Ordre fix de les perspectives de la taxonomia (categories del paper).
PERSPECTIVES = ["Columns Set", "Column Kind", "Rows Set", "Data Characteristics"]


def current() -> dict:
    """
    :return: la paleta del tema actiu de Streamlit (clar si no se sap).
    """
    import streamlit as st

    theme = getattr(getattr(st.context, "theme", None), "type", None)
    return DARK if theme == "dark" else LIGHT


def perspective_scale(palette: dict) -> tuple[list[str], list[str]]:
    """
    :param palette: `LIGHT` o `DARK`.
    :return: `(domini, colors)` per a una escala de color per perspectiva.
    """
    return PERSPECTIVES, palette["series"][:len(PERSPECTIVES)]
