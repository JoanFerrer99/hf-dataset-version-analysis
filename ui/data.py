"""
Accés al magatzem per a la interfície. Una sola connexió DuckDB de només
lectura, compartida entre sessions, i una funció per consulta: cap pàgina no
escriu SQL, i només es llegeix de la capa gold (estrella i marts).

El fitxer surt de `WAREHOUSE_PATH` (per defecte, `warehouse/hf_changes.duckdb`;
una ruta relativa ho és a l'arrel del repositori).
"""

import os

import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_WAREHOUSE = os.path.join("warehouse", "hf_changes.duckdb")


def warehouse_path() -> str:
    """
    :return: la ruta absoluta del fitxer del magatzem.
    """
    path = os.environ.get("WAREHOUSE_PATH", DEFAULT_WAREHOUSE)
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def warehouse_exists() -> bool:
    """
    :return: si hi ha el fitxer del magatzem.
    """
    return os.path.exists(warehouse_path())


@st.cache_resource
def connection() -> duckdb.DuckDBPyConnection:
    """
    :return: la connexió de només lectura al magatzem (una per procés).
    """
    return duckdb.connect(warehouse_path(), read_only=True)


def _query(sql: str, params: list | None = None) -> pd.DataFrame:
    """
    Executa una consulta amb un cursor propi: la connexió es comparteix entre
    sessions, i cada consulta en fa servir un de nou.

    :param sql: la consulta.
    :param params: paràmetres (`?`) de la consulta.
    :return: el resultat.
    """
    cursor = connection().cursor()
    try:
        return cursor.execute(sql, params or []).df()
    finally:
        cursor.close()

