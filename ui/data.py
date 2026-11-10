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
UNIT_STATUS_LABELS = {
    "compared": "Comparada",
    "not_compared": "No comparada: massa gran, o no s'ha pogut baixar o llegir",
    "no_common_table": "Cap taula en comú: només taules afegides, eliminades o excloses",
    "no_tables": "Sense cap taula",
    "failed": "La Fase 2 va fallar en aquest dataset",
}


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


def code_frequency(filters=None) -> pd.DataFrame:
    """
    La freqüència de cada codi (com `mart_code_frequency`), amb els filtres
    de la barra lateral: es calcula sobre l'estrella. Sense filtres, dona el
    mateix que el mart.

    :param filters: filtres de dataset, criteri, perspectiva i trencador.
    :return: una fila per codi de les perspectives triades, també sense canvis.
    """
    units_where, units_params = _conditions(filters, dataset="d.dataset_id", criterion="d.eligibility_criterion")
    changes_where, changes_params = _conditions(filters, dataset="d.dataset_id", criterion="d.eligibility_criterion",
                                                perspective="k.perspective", breaking="k.is_breaking")
    kinds_where, kinds_params = _conditions(filters, perspective="k.perspective", breaking="k.is_breaking")
    return _query(f"""
        with compared as (
            select count(*) filter (where u.is_compared) as n_compared_units
            from mart_change_units as u
            inner join dim_dataset as d
                on d.dataset_id = u.dataset_id
            where {units_where}
        ),

        changes as (
            select f.kind_key, f.dataset_key, f.version_to_key, f.change_count
            from fact_change as f
            inner join dim_dataset as d
                on d.dataset_key = f.dataset_key
            inner join dim_kind_of_change as k
                on k.kind_key = f.kind_key
            where {changes_where}
        )

        select
            k.code,
            k.name,
            k.perspective,
            k.level_1,
            k.is_breaking,
            cast(coalesce(sum(c.change_count), 0) as bigint) as n_changes,
            count(distinct c.version_to_key) as n_units,
            count(distinct c.dataset_key) as n_datasets,
            any_value(compared.n_compared_units) as n_compared_units,
            case when any_value(compared.n_compared_units) > 0
                then count(distinct c.version_to_key) / any_value(compared.n_compared_units) end
                as share_of_compared_units
        from dim_kind_of_change as k
        left join changes as c
            on c.kind_key = k.kind_key
        cross join compared
        where {kinds_where}
        group by k.code, k.name, k.perspective, k.level_1, k.is_breaking
        order by k.code
    """, units_params + changes_params + kinds_params)


def breaking_share(filters=None) -> pd.DataFrame:
    """
    :param filters: s'hi aplica el filtre de criteri (el mart no és per dataset).
    :return: `mart_breaking_share`: per criteri i en total (`all`), amb l'interval de Wilson.
    """
    rows = _query("""
        select criterion, n_compared_units, n_units_with_change, n_units_with_breaking_change,
               share_with_change, share_with_breaking_change,
               share_with_breaking_change_low, share_with_breaking_change_high
        from mart_breaking_share
        order by criterion
    """)
    if filters is not None and filters.criteria:
        rows = rows[rows["criterion"].isin(filters.criteria)]
    labels = {"A": "Criteri A: tags", "B": "Criteri B: sessions", "all": "Tots"}
    return rows.assign(criterion_label=rows["criterion"].map(labels))


def changes_by_quarter(filters=None) -> pd.DataFrame:
    """
    :param filters: filtres de dataset, criteri, perspectiva i trencador.
    :return: canvis per trimestre (de la versió nova) i perspectiva, com `mart_changes_by_quarter`.
    """
    where, params = _conditions(filters, dataset="d.dataset_id", criterion="d.eligibility_criterion",
                                perspective="k.perspective", breaking="k.is_breaking")
    return _query(f"""
        select
            t.year,
            t.quarter,
            t.year_quarter,
            k.perspective,
            k.level_1,
            cast(sum(f.change_count) as bigint) as n_changes,
            count(*) filter (where k.is_breaking) as n_breaking_changes,
            count(distinct f.version_to_key) as n_units,
            count(distinct f.dataset_key) as n_datasets
        from fact_change as f
        inner join dim_date as t
            on t.date_key = f.date_key
        inner join dim_kind_of_change as k
            on k.kind_key = f.kind_key
        inner join dim_dataset as d
            on d.dataset_key = f.dataset_key
        where {where}
        group by t.year, t.quarter, t.year_quarter, k.perspective, k.level_1
        order by t.year, t.quarter, k.perspective
    """, params)


def explorer_datasets(filters=None) -> list[str]:
    """
    :param filters: filtres de dataset i criteri.
    :return: els datasets que es poden explorar amb aquests filtres.
    """
    where, params = _conditions(filters, dataset="dataset_id", criterion="eligibility_criterion")
    return _query(f"select dataset_id from dim_dataset where {where} order by dataset_id", params)["dataset_id"].tolist()


def explorer_units(dataset_id: str) -> pd.DataFrame:
    """
    :param dataset_id: el dataset.
    :return: les seves comparacions (una versió contra la següent), amb l'estat i els enllaços als dos commits.
    """
    df = _query(f"""
        select
            version_from,
            version_to,
            label_from,
            label_to,
            date_to,
            unit_status,
            n_tables,
            n_tables_compared,
            n_tables_not_compared,
            n_codes,
            n_breaking_codes,
            '{HF}' || dataset_id || '/commit/' || version_from as url_from,
            '{HF}' || dataset_id || '/commit/' || version_to as url_to
        from mart_change_units
        where dataset_id = ?
        order by date_to, label_to
    """, [dataset_id])
    df["status_label"] = df["unit_status"].map(UNIT_STATUS_LABELS)
    return df


def explorer_changes(dataset_id: str, version_from: str, version_to: str, filters=None) -> pd.DataFrame:
    """
    :param dataset_id: el dataset.
    :param version_from: SHA de la versió antiga.
    :param version_to: SHA de la versió nova.
    :param filters: filtres de perspectiva i trencador.
    :return: una fila per taula i codi detectat entre les dues versions, amb la descripció del codi.
    """
    where, params = _conditions(filters, perspective="k.perspective", breaking="k.is_breaking")
    return _query(f"""
        select
            t.table_path,
            t.format,
            k.code,
            k.name,
            k.level_1,
            k.is_breaking
        from fact_change as f
        inner join dim_dataset as d
            on d.dataset_key = f.dataset_key
        inner join dim_version as vf
            on vf.version_key = f.version_from_key
        inner join dim_version as vt
            on vt.version_key = f.version_to_key
        inner join dim_table as t
            on t.table_key = f.table_key
        inner join dim_kind_of_change as k
            on k.kind_key = f.kind_key
        where d.dataset_id = ? and vf.commit_sha = ? and vt.commit_sha = ? and {where}
        order by t.table_path, k.code
    """, [dataset_id, version_from, version_to] + params)


UNIT_STATUSES = ["compared", "not_compared", "no_common_table", "no_tables", "failed"]
SHORT_UNIT_STATUS = {"compared": "Feta", "not_compared": "No feta", "no_common_table": "Cap taula en comú",
                     "no_tables": "Sense taules", "failed": "Fallada"}
TABLE_STATUSES = {
    "ok": "Comparada",
    "identical_content": "Mateix contingut (no cal descarregar-la)",
    "absent_old": "Afegida sencera (no hi era a la versió antiga)",
    "absent_new": "Eliminada sencera (no hi és a la versió nova)",
    "too_large": "Massa gran (més de 500 MB entre les dues versions)",
    "parse_failed": "No s'ha pogut llegir com a taula",
    "download_failed": "No s'ha pogut descarregar",
    "excluded": "Fitxer tabular que no forma cap taula",
}


def coverage_by_dataset(filters=None) -> pd.DataFrame:
    """
    :param filters: filtres de dataset i criteri.
    :return: per dataset, les comparacions de cada estat i les taules de cada estat.
    """
    where, params = _conditions(filters, dataset="u.dataset_id", criterion="d.eligibility_criterion")
    unit_counts = ",\n            ".join(
        f"count(*) filter (where u.unit_status = '{status}') as units_{status}" for status in UNIT_STATUSES)
    table_counts = ",\n            ".join(f"cast(sum(u.n_tables_{status}) as bigint) as tables_{status}"
                                         for status in TABLE_STATUSES)
    return _query(f"""
        select
            u.dataset_id,
            d.eligibility_criterion,
            count(*) as n_units,
            {unit_counts},
            cast(sum(u.n_tables) as bigint) as n_tables,
            {table_counts}
        from mart_change_units as u
        inner join dim_dataset as d
            on d.dataset_id = u.dataset_id
        where {where}
        group by u.dataset_id, d.eligibility_criterion
        order by u.dataset_id
    """, params)


def incomplete_units(filters=None) -> pd.DataFrame:
    """
    :param filters: filtres de dataset i criteri.
    :return: les comparacions que no s'han pogut fer, o que tenen alguna taula sense comparar, amb el motiu.
    """
    where, params = _conditions(filters, dataset="u.dataset_id", criterion="d.eligibility_criterion")
    df = _query(f"""
        select
            u.dataset_id,
            u.label_from,
            u.label_to,
            u.date_to,
            u.unit_status,
            u.n_tables,
            u.n_tables_compared,
            u.n_tables_too_large,
            u.n_tables_parse_failed,
            u.n_tables_download_failed,
            u.n_tables_absent_old,
            u.n_tables_absent_new,
            u.n_tables_excluded,
            '{HF}' || u.dataset_id || '/commit/' || u.version_to as url_to
        from mart_change_units as u
        inner join dim_dataset as d
            on d.dataset_id = u.dataset_id
        where (u.unit_status <> 'compared' or u.n_tables_not_compared > 0) and {where}
        order by u.dataset_id, u.date_to
    """, params)
    df["status_label"] = df["unit_status"].map(SHORT_UNIT_STATUS)
    df["reason"] = df.apply(_reason, axis=1)
    return df


def _reason(unit: pd.Series) -> str:
    """El motiu d'una comparació incompleta, a partir de les seves taules de cada estat."""
    parts = [(unit["n_tables_too_large"], "massa gran", "massa grans"),
             (unit["n_tables_parse_failed"], "que no s'ha pogut llegir", "que no s'han pogut llegir"),
             (unit["n_tables_download_failed"], "que no s'ha pogut descarregar", "que no s'han pogut descarregar"),
             (unit["n_tables_absent_old"], "afegida sencera", "afegides senceres"),
             (unit["n_tables_absent_new"], "eliminada sencera", "eliminades senceres"),
             (unit["n_tables_excluded"], "exclosa", "excloses")]
    text = "; ".join(f"{n} {'taula' if n == 1 else 'taules'} {one if n == 1 else many}"
                     for n, one, many in parts if n)
    return f"{text} (de {unit['n_tables']})"


def changes_by_dataset(filters=None) -> pd.DataFrame:
    """
    :param filters: filtres de dataset, criteri, perspectiva i trencador.
    :return: per dataset i codi, les comparacions afectades i els canvis (taules).
    """
    where, params = _conditions(filters, dataset="d.dataset_id", criterion="d.eligibility_criterion",
                                perspective="k.perspective", breaking="k.is_breaking")
    return _query(f"""
        select
            d.dataset_id,
            k.code,
            k.name,
            k.level_1,
            count(distinct f.version_to_key) as n_units,
            cast(sum(f.change_count) as bigint) as n_changes
        from fact_change as f
        inner join dim_dataset as d
            on d.dataset_key = f.dataset_key
        inner join dim_kind_of_change as k
            on k.kind_key = f.kind_key
        where {where}
        group by d.dataset_id, k.code, k.name, k.level_1
        order by d.dataset_id, k.code
    """, params)


def highlights() -> dict:
    """
    Els destacats de la pàgina d'inici, tots de la capa gold.

    :return: el codi que surt a més comparacions, la proporció de comparacions amb canvis trencadors (amb
        l'interval), les comparacions no fetes i el dataset amb més canvis.
    """
    top_code = _query("""
        select code, name, n_units, n_compared_units
        from mart_code_frequency
        order by n_units desc, n_changes desc, code
        limit 1
    """).iloc[0]
    breaking = _query("""
        select n_compared_units, n_units_with_breaking_change, share_with_breaking_change,
               share_with_breaking_change_low, share_with_breaking_change_high
        from mart_breaking_share
        where criterion = 'all'
    """).iloc[0]
    coverage = _query("""
        select count(*) as n_units, count(*) filter (where not is_compared) as n_not_compared
        from mart_change_units
    """).iloc[0]
    busiest = _query("""
        select dataset_id, cast(n_changes as bigint) as n_changes,
               cast(sum(n_changes) over () as bigint) as total_changes
        from mart_dataset_profile
        order by n_changes desc, dataset_id
        limit 1
    """).iloc[0]
    return {"top_code": top_code.to_dict(), "breaking": breaking.to_dict(), "coverage": coverage.to_dict(),
            "busiest": busiest.to_dict()}
