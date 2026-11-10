"""
Interfície de consulta del magatzem (Fase 3): sis pàgines, una per tema.

La navegació nativa de Streamlit està amagada (`position="hidden"`): la fa la
barra de `shell.nav_bar`, un component HTML amb Tailwind que envia la pàgina
triada a Python. Sota, la capçalera de la pàgina i els filtres.

Ús (des de l'arrel del repositori):
  WAREHOUSE_PATH=data/warehouse/run_9.duckdb streamlit run ui/app.py
"""

import streamlit as st

import data
import filters
import shell

st.set_page_config(page_title=shell.BRAND, page_icon=":material/query_stats:", layout="wide")

if not data.warehouse_exists():
    st.error(
        f"No hi ha el magatzem a `{data.warehouse_path()}`. Construeix-lo amb "
        "`python src/build_warehouse.py --run-dir data/run_<id>` i indica'n el fitxer amb `WAREHOUSE_PATH`."
    )
    st.stop()

pages = {entry["title"]: st.Page(entry["path"], title=entry["title"], default=i == 0)
         for i, entry in enumerate(shell.PAGES)}
current = st.navigation(list(pages.values()), position="hidden")

run = data.run_info()
badge = f"Execució {run['run_id']} · {run['run_date']:%d/%m/%Y}" if run["run_date"] is not None else "Execució"
clicked = shell.nav_bar(shell.PAGES, current.title, badge)
if clicked and clicked in pages:
    st.switch_page(pages[clicked])

entry = shell.page(current.title)
shell.page_header(entry["eyebrow"], entry["title"], entry["subtitle"])
filters.bar()
current.run()
