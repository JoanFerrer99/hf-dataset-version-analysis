-- Dimensió de les versions: una fila per commit (dataset, SHA). Fa dos rols a
-- fact_change: la versió antiga i la nova. Hi són les versions de versions.csv
-- i, si n'hi hagués, els commits que surten a les comparacions sense ser-hi
-- (`version_source` = 'commit'). Si dos tags apunten al mateix commit, són una
-- sola versió amb les dues etiquetes.

with listed as (
    select
        dataset_id,
        commit_sha,
        string_agg(version_label, ', ' order by version_order) as version_label,
        min(version_order) as version_order,
        min(version_source) as version_source,
        min(commit_date) as commit_date
    from {{ ref('stg_versions') }}
    group by dataset_id, commit_sha
),

compared as (
    select dataset_id, version_from as commit_sha from {{ ref('stg_comparison_status') }}
    union
    select dataset_id, version_to from {{ ref('stg_comparison_status') }}
    union
    select dataset_id, version_from from {{ ref('stg_change_classification') }}
    union
    select dataset_id, version_to from {{ ref('stg_change_classification') }}
),

only_compared as (
    select
        compared.dataset_id,
        compared.commit_sha,
        cast(null as varchar) as version_label,
        cast(null as integer) as version_order,
        'commit' as version_source,
        cast(null as timestamp) as commit_date
    from compared
    anti join listed
        on listed.dataset_id = compared.dataset_id
        and listed.commit_sha = compared.commit_sha
),

all_versions as (
    select dataset_id, commit_sha, version_label, version_order, version_source, commit_date from listed
    union all
    select dataset_id, commit_sha, version_label, version_order, version_source, commit_date from only_compared
)

select
    {{ surrogate_key(['dataset_id', 'commit_sha']) }} as version_key,
    dataset_id,
    commit_sha,
    version_label,
    version_order,
    version_source,
    commit_date
from all_versions
