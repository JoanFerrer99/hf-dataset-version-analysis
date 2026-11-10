"""
L'estructura comuna de la interfície: la barra de navegació, la capçalera de
cada pàgina i les targetes de xifres. Són components HTML (`ui/components/*.js`)
amb Tailwind (`ui/static/tailwind.css`), que envien els clics a Python amb
`st.components.v2` (CCv2): sense iframes ni dependències noves. Cada component
viu dins d'un shadow root, de manera que el seu CSS no toca els elements natius
de Streamlit.

Les funcions `*_data` construeixen el que rep cada component; són pures, i es
poden provar sense navegador.
"""

import os

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = "Canvis en datasets de Hugging Face"

# Les pàgines, en l'ordre de la navegació: el títol és també l'identificador. La carpeta és
# app_pages/ i no pages/: Streamlit tracta pages/ com una aplicació antiga de diverses pàgines, i un
# enllaç directe (p.e. /coverage) obriria la pàgina sola, sense app.py (ni navegació ni capçalera).
PAGES = [
    {"path": "app_pages/home.py", "title": "Inici", "eyebrow": "Fase 3 · Panorama",
     "subtitle": "Com canvien els datasets publicats a Hugging Face d'una versió a la següent, i amb quina "
                 "freqüència apareix cada tipus de canvi?"},
    {"path": "app_pages/sampling.py", "title": "Mostreig i elegibilitat", "eyebrow": "Fase 0",
     "subtitle": "Quants datasets de la mostra passen cada filtre, i quina proporció té més d'una versió de "
                 "dades tabulars."},
    {"path": "app_pages/versions.py", "title": "Versions", "eyebrow": "Fase 1",
     "subtitle": "Les versions de cada dataset elegible al llarg del temps: tags o sessions de commits."},
    {"path": "app_pages/changes.py", "title": "Canvis", "eyebrow": "Fase 2",
     "subtitle": "Quins canvis surten, quants trenquen un pipeline i com evolucionen al llarg del temps."},
    {"path": "app_pages/explorer.py", "title": "Explorador", "eyebrow": "Fase 2 · Detall",
     "subtitle": "Un dataset, les seves comparacions, i a quines taules hi ha canvis i de quin tipus."},
]


def page(title: str) -> dict:
    """
    :param title: títol (identificador) de la pàgina.
    :return: la seva entrada a `PAGES`.
    :raises KeyError: si no és cap pàgina.
    """
    for entry in PAGES:
        if entry["title"] == title:
            return entry
    raise KeyError(title)


def _read(*parts: str) -> str:
    with open(os.path.join(HERE, *parts), encoding="utf-8") as f:
        return f.read()


# El CSS compilat és d'una sola línia: amb un comentari a sobre, CCv2 el llegeix
# com a CSS i no com la ruta d'un fitxer.
_TAILWIND = "/* Tailwind compilat: ui/static/tailwind.css */\n" + _read("static", "tailwind.css") + "\n"
_ROOT = "<div data-root></div>"

_NAV = st.components.v2.component("hf_nav", html=_ROOT, css=_TAILWIND, js=_read("components", "nav.js"))
_HEADER = st.components.v2.component("hf_header", html=_ROOT, css=_TAILWIND, js=_read("components", "header.js"))
_CARDS = st.components.v2.component("hf_cards", html=_ROOT, css=_TAILWIND, js=_read("components", "cards.js"))


def nav_data(pages: list[dict], active: str, badge: str) -> dict:
    """
    :param pages: `PAGES` (el títol fa d'identificador).
    :param active: títol de la pàgina oberta.
    :param badge: text petit sota la marca (p.e. l'execució i la data).
    :return: el que rep la barra de navegació.
    """
    return {"brand": BRAND, "badge": badge, "active": active,
            "pages": [{"id": page["title"], "title": page["title"]} for page in pages]}


def nav_bar(pages: list[dict], active: str, badge: str, key: str = "shell_nav") -> str | None:
    """
    Dibuixa la barra de navegació.

    :return: títol de la pàgina on s'ha fet clic en aquesta execució, o `None`.
    """
    result = _NAV(data=nav_data(pages, active, badge), key=key, on_page_change=lambda: None)
    return result.page


def page_header(eyebrow: str, title: str, subtitle: str, key: str = "shell_header") -> None:
    """Dibuixa la capçalera de la pàgina: la secció, el títol i una frase."""
    _HEADER(data={"eyebrow": eyebrow, "title": title, "subtitle": subtitle}, key=key)


def figure_cards_data(figures: dict, num) -> list[dict]:
    """
    Les quatre targetes de la pàgina d'inici.

    :param figures: `data.key_figures()`.
    :param num: funció de format dels números (`fmt.num`).
    :return: una targeta per xifra, amb la pàgina on porta.
    """
    return [
        {"label": "Datasets de la mostra", "value": num(figures["sample_size"]),
         "hint": f"{num(figures['classified'])} classificats", "target": "Mostreig i elegibilitat"},
        {"label": "Elegibles", "value": num(figures["eligible"]),
         "hint": f"Criteri A: {figures['eligible_a']} · Criteri B: {figures['eligible_b']}",
         "target": "Versions"},
        {"label": "Comparacions fetes", "value": f"{num(figures['n_compared_units'])} de {num(figures['n_units'])}",
         "hint": "Cada versió contra la següent", "target": "Explorador"},
        {"label": "Canvis detectats", "value": num(figures["n_changes"]),
         "hint": f"{figures['n_codes']} codis diferents de la taxonomia", "target": "Canvis"},
    ]


def figure_cards(cards: list[dict], key: str = "shell_cards") -> str | None:
    """
    Dibuixa les targetes de xifres.

    :return: la pàgina del botó on s'ha fet clic en aquesta execució, o `None`.
    """
    result = _CARDS(data={"cards": cards}, key=key, on_open_change=lambda: None)
    return result.open
