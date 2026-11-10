-- Fet dels canvis. Gra: un codi de la taxonomia detectat en una taula, entre
-- dues versions consecutives d'un dataset; és una fila de change_classification.csv.
-- La data (`date_key`) és la de la versió nova. `age_days` són els dies entre la
-- creació del dataset i aquesta versió, si se sap quan es va crear.
{%- set run_id = var('run_dir').rstrip('/').split('/')[-1] %}

with changes as (
    select
        dataset_id,
        version_from,
        version_to,
        table_name,
        code,
        description
    from {{ ref('stg_change_classification') }}
),

new_versions as (
    select dataset_id, commit_sha, commit_date
    from {{ ref('dim_version') }}
),

datasets as (
    select dataset_id, created_at
    from {{ ref('dim_dataset') }}
)

select
    {{ surrogate_key(['changes.dataset_id', 'changes.version_from', 'changes.version_to', 'changes.table_name', 'changes.code']) }} as change_key,
    {{ surrogate_key(['changes.dataset_id']) }} as dataset_key,
    {{ surrogate_key(['changes.code']) }} as kind_key,
    {{ surrogate_key(['changes.dataset_id', 'changes.table_name']) }} as table_key,
    {{ surrogate_key(['changes.dataset_id', 'changes.version_from']) }} as version_from_key,
    {{ surrogate_key(['changes.dataset_id', 'changes.version_to']) }} as version_to_key,
    cast(strftime(cast(new_versions.commit_date as date), '%Y%m%d') as integer) as date_key,
    '{{ run_id }}' as run_id,
    changes.description,
    1 as change_count,
    date_diff('day', datasets.created_at, new_versions.commit_date) as age_days
from changes
left join new_versions
    on new_versions.dataset_id = changes.dataset_id
    and new_versions.commit_sha = changes.version_to
left join datasets
    on datasets.dataset_id = changes.dataset_id
