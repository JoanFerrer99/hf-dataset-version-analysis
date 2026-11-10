-- Fase 1: una fila per versió de cada elegible, amb tipus.

with versions as (
    select * from {{ source('bronze', 'versions') }}
),

typed as (
    select
        dataset_id,
        version_label,
        cast(version_order as integer) as version_order,
        version_source,
        commit_sha,
        {{ to_utc('commit_date') }} as commit_date,
        authors,
        cast(cast(approx_size_bytes as double) as bigint) as approx_size_bytes,
        cast(session_commit_count as integer) as session_commit_count,
        status
    from versions
)

select * from typed
