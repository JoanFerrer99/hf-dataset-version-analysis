-- Fase 1: una fila per versió de cada elegible, amb tipus. Les execucions
-- anteriors no tenen la mida de dades i de metadades: surten buides.
{%- set present = bronze_columns(source('bronze', 'versions')) %}

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
        status,
        {{ optional_column(present, 'data_size_bytes', 'cast(cast(data_size_bytes as double) as bigint)', 'bigint') }} as data_size_bytes,
        {{ optional_column(present, 'metadata_size_bytes', 'cast(cast(metadata_size_bytes as double) as bigint)', 'bigint') }} as metadata_size_bytes,
        {{ optional_column(present, 'n_data_files', 'cast(cast(n_data_files as double) as integer)', 'integer') }} as n_data_files,
        {{ optional_column(present, 'n_metadata_files', 'cast(cast(n_metadata_files as double) as integer)', 'integer') }} as n_metadata_files
    from versions
)

select * from typed
