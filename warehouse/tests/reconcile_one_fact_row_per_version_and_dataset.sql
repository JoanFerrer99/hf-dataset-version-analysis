-- Conciliació 5: fact_version té una fila per versió de versions.csv (dos tags
-- al mateix commit són una sola versió) i fact_dataset, una per dataset de
-- eligibility_report.csv. Retorna el que no quadra.

with versions as (
    select distinct dataset_id, commit_sha
    from {{ ref('stg_versions') }}
    where commit_sha is not null and commit_sha <> ''
),

facts as (
    select dataset_id, commit_sha from {{ ref('fact_version') }}
)

select 'versió' as grain, * from (select * from versions except select * from facts)
union all
select 'versió', * from (select * from facts except select * from versions)
union all
select 'dataset', dataset_id, null
from (
    select dataset_id from {{ ref('stg_eligibility_report') }}
    except
    select dataset_id from {{ ref('fact_dataset') }}
)
