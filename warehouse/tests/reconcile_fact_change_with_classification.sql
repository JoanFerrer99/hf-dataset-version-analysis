-- Conciliació 1: fact_change té exactament una fila per cada fila de
-- change_classification.csv, per la clau natural (dataset, versions, taula i codi),
-- en els dos sentits. Retorna les files que són a un costat i no a l'altre.

with classification as (
    select dataset_id, version_from, version_to, table_name, code
    from {{ ref('stg_change_classification') }}
),

facts as (
    select
        datasets.dataset_id,
        versions_from.commit_sha as version_from,
        versions_to.commit_sha as version_to,
        tables.table_path as table_name,
        kinds.code
    from {{ ref('fact_change') }} as facts
    inner join {{ ref('dim_dataset') }} as datasets
        on datasets.dataset_key = facts.dataset_key
    inner join {{ ref('dim_version') }} as versions_from
        on versions_from.version_key = facts.version_from_key
    inner join {{ ref('dim_version') }} as versions_to
        on versions_to.version_key = facts.version_to_key
    inner join {{ ref('dim_table') }} as tables
        on tables.table_key = facts.table_key
    inner join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.kind_key = facts.kind_key
),

only_in_classification as (
    select 'només a change_classification.csv' as side, * from classification
    except all
    select 'només a change_classification.csv', * from facts
),

only_in_facts as (
    select 'només a fact_change' as side, * from facts
    except all
    select 'només a fact_change', * from classification
)

select * from only_in_classification
union all
select * from only_in_facts
