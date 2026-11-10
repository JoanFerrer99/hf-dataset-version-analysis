"""
Interfície de consulta del magatzem (Fase 3): sis pàgines, una per tema.

Ús (des de l'arrel del repositori):
  WAREHOUSE_PATH=data/warehouse/run_9.duckdb streamlit run ui/app.py
"""

import streamlit as st

import data

st.set_page_config(page_title="Canvis en datasets de Hugging Face", page_icon="📊", layout="wide")

if not data.warehouse_exists():
    st.error(
        f"No hi ha el magatzem a `{data.warehouse_path()}`. Construeix-lo amb "
        "`python src/build_warehouse.py --run-dir data/run_<id>` i indica'n el fitxer amb `WAREHOUSE_PATH`."
    )
    st.stop()

pages = [
    st.Page("pages/home.py", title="Inici", icon="🏠", default=True),
    st.Page("pages/sampling.py", title="Mostreig i elegibilitat", icon="🔎"),
    st.Page("pages/versions.py", title="Versions", icon="🕒"),
    st.Page("pages/changes.py", title="Canvis", icon="📈"),
    st.Page("pages/explorer.py", title="Explorador", icon="🗂️"),
    st.Page("pages/validation.py", title="Validació", icon="✅"),
]
st.navigation(pages).run()
