-- Fase 2: l'estat de la comparació de cada parell de versions d'un dataset,
-- també de les que no tenen cap codi.

with comparisons as (
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
        cast(size_bytes as bigint) as size_bytes
    from comparisons
)

select * from typed
