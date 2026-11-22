-- Fet de les versions (Star_Versions). Gra: una versió d'un dataset elegible
-- (un tag, o el commit més recent d'una sessió). Les diferències respecte a la
-- versió anterior són a `dim_differences`. `commit_sha`, `version_label` i
-- `version_order` són dimensions degenerades.
{%- set run_id = var('run_dir').rstrip('/').split('/')[-1] %}

select
    {{ surrogate_key(['versions.dataset_id', 'versions.commit_sha']) }} as version_key,
    {{ surrogate_key(['versions.dataset_id']) }} as dataset_key,
    {{ surrogate_key(['versions.differences']) }} as differences_key,
    cast(strftime(versions.commit_date, '%Y%m%d%H') as integer) as commit_time_key,
    {{ surrogate_key(['versions.version_kind']) }} as version_kind_key,
    {{ surrogate_key(['versions.version_position']) }} as version_order_key,
    '{{ run_id }}' as run_id,
    versions.dataset_id,
    versions.commit_sha,
    versions.version_label,
    versions.version_order,
    versions.commit_date,
    versions.comparison_status,
    versions.lifespan_days,
    versions.conception_days,
    versions.data_size_bytes,
    versions.metadata_size_bytes,
    versions.n_data_files,
    versions.n_metadata_files,
    versions.session_commit_count,
    versions.n_rows,
    versions.n_columns
from {{ ref('int_version_measures') }} as versions
