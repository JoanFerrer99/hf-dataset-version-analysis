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


HF = "https://huggingface.co/datasets/"
SOURCE_LABELS = {"tag": "Tag", "commit_session": "Sessió de commits", "commit": "Commit"}


def _conditions(filters, dataset: str | None = None, criterion: str | None = None, perspective: str | None = None,
                breaking: str | None = None) -> tuple[str, list]:
    """
    Les condicions SQL dels filtres de la barra lateral que s'apliquen a una consulta.

    :param filters: un `filters.Filters`, o `None` (sense filtres).
    :param dataset: columna del dataset a la consulta, si s'hi filtra.
    :param criterion: columna del criteri d'elegibilitat, si s'hi filtra.
    :param perspective: columna de la perspectiva, si s'hi filtra.
    :param breaking: columna de si és trencador, si s'hi filtra.
    :return: `(condició, paràmetres)`; `true` si no n'hi ha cap.
    """
    clauses, params = [], []
    if filters is not None:
        for column, values in ((dataset, filters.datasets), (criterion, filters.criteria),
                               (perspective, filters.perspectives)):
            if column and values:
                clauses.append(f"{column} in ({', '.join('?' * len(values))})")
                params += list(values)
        if breaking and filters.breaking is not None:
            clauses.append(f"{breaking} = ?")
            params.append(filters.breaking)
    return (" and ".join(clauses) or "true"), params


def dataset_ids() -> list[str]:
    """
    :return: els datasets elegibles, per ordre alfabètic.
    """
    return _query("select dataset_id from dim_dataset order by dataset_id")["dataset_id"].tolist()


def perspectives() -> dict[str, str]:
    """
    :return: perspectiva (nom del paper) -> etiqueta en català, en l'ordre dels codis.
    """
    df = _query("""
        select perspective, any_value(level_1) as label
        from dim_kind_of_change
        group by perspective
        order by min(code)
    """)
    return dict(zip(df["perspective"], df["label"]))


def run_info() -> dict:
    """
    :return: `run_id` (la carpeta de l'execució) i `run_date` (el dia de l'execució).
    """
    row = _query("""
        select
            (select any_value(run_id) from fact_change) as run_id,
            (select max(snapshot_date) from dim_dataset) as run_date
    """).iloc[0]
    return {"run_id": row["run_id"], "run_date": row["run_date"]}


def key_figures() -> dict:
    """
    Les xifres de la pàgina d'inici.

    :return: mida de la mostra, classificats, elegibles (i per criteri), proporció
        d'elegibles amb l'interval de Wilson, comparacions (fetes i totals) i canvis.
    """
    funnel = _query("""
        select stage, n_datasets, n_criterion_a, n_criterion_b, share_of_classified, share_low, share_high
        from mart_funnel
    """).set_index("stage")
    units = _query("""
        select count(*) as n_units, count(*) filter (where is_compared) as n_compared_units
        from mart_change_units
    """).iloc[0]
    changes = _query("""
        select count(*) as n_changes, count(distinct kind_key) as n_codes
        from fact_change
    """).iloc[0]
    eligible = funnel.loc["eligible"]
    return {
        "sample_size": int(funnel.loc["sample", "n_datasets"]),
        "classified": int(funnel.loc["classified", "n_datasets"]),
        "eligible": int(eligible["n_datasets"]),
        "eligible_a": int(eligible["n_criterion_a"]),
        "eligible_b": int(eligible["n_criterion_b"]),
        "eligible_share": float(eligible["share_of_classified"]),
        "eligible_low": float(eligible["share_low"]),
        "eligible_high": float(eligible["share_high"]),
        "n_units": int(units["n_units"]),
        "n_compared_units": int(units["n_compared_units"]),
        "n_changes": int(changes["n_changes"]),
        "n_codes": int(changes["n_codes"]),
    }


def taxonomy() -> pd.DataFrame:
    """
    :return: els 14 codis de la taxonomia, amb la perspectiva i si trenquen.
    """
    return _query("""
        select code, name, perspective, level_1, is_breaking
        from dim_kind_of_change
        order by code
    """)


def funnel() -> pd.DataFrame:
    """
    :return: `mart_funnel`: un pas de la Fase 0 per fila, amb la proporció sobre els classificats.
    """
    return _query("""
        select stage_order, stage, stage_label, n_datasets, n_dropped, n_criterion_a, n_criterion_b,
               share_of_classified, share_low, share_high
        from mart_funnel
        order by stage_order
    """)


def versions(filters=None) -> pd.DataFrame:
    """
    :param filters: filtres de dataset i criteri.
    :return: una fila per versió, amb l'enllaç al commit a Hugging Face.
    """
    where, params = _conditions(filters, dataset="v.dataset_id", criterion="d.eligibility_criterion")
    df = _query(f"""
        select
            v.dataset_id,
            d.eligibility_criterion,
            v.version_label,
            v.version_order,
            v.version_source,
            v.commit_date,
            v.commit_sha,
            '{HF}' || v.dataset_id || '/commit/' || v.commit_sha as commit_url
        from dim_version as v
        inner join dim_dataset as d
            on d.dataset_id = v.dataset_id
        where {where}
        order by v.dataset_id, v.version_order
    """, params)
    df["source_label"] = df["version_source"].map(SOURCE_LABELS)
    return df


def dataset_profiles(filters=None) -> pd.DataFrame:
    """
    :param filters: filtres de dataset i criteri.
    :return: `mart_dataset_profile`, amb l'enllaç al dataset a Hugging Face.
    """
    where, params = _conditions(filters, dataset="dataset_id", criterion="eligibility_criterion")
    return _query(f"""
        select
            dataset_id,
            '{HF}' || dataset_id as dataset_url,
            eligibility_criterion,
            n_versions,
            first_version_at,
            last_version_at,
            n_units,
            n_compared_units,
            n_units_with_change,
            n_tables,
            n_changes,
            n_breaking_changes,
            codes
        from mart_dataset_profile
        where {where}
        order by dataset_id
    """, params)
