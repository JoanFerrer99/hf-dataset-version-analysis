-- Fase 2: l'estat de la comparació de cada parell de versions d'un dataset,
-- també de les que no tenen cap codi.

with optional_columns as (
    -- columnes que els runs anteriors a T-44 no tenen: hi queden buides
    select
        null::varchar as n_files_dropped_from,
        null::varchar as n_files_dropped_to,
        null::varchar as n_rows_from,
        null::varchar as n_rows_to,
        null::varchar as n_columns_from,
        null::varchar as n_columns_to
    where false
),

comparisons as (
    select * from optional_columns
    union all by name
    select * from {{ source('bronze', 'comparison_status') }}
),

typed as (
    select
        dataset_id,
        version_from,
        version_to,
        status,
        cast(n_codes as integer) as n_codes,
        nullif(format_from, '') as format_from,
        nullif(format_to, '') as format_to,
        cast(n_files_from as integer) as n_files_from,
        cast(n_files_to as integer) as n_files_to,
        coalesce(cast(nullif(n_files_dropped_from, '') as integer), 0) as n_files_dropped_from,
        coalesce(cast(nullif(n_files_dropped_to, '') as integer), 0) as n_files_dropped_to,
        cast(nullif(n_rows_from, '') as bigint) as n_rows_from,
        cast(nullif(n_rows_to, '') as bigint) as n_rows_to,
        cast(nullif(n_columns_from, '') as integer) as n_columns_from,
        cast(nullif(n_columns_to, '') as integer) as n_columns_to,
        cast(size_bytes as bigint) as size_bytes
    from comparisons
)

select * from typed
