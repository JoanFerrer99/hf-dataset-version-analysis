-- Fase 2: l'estat de cada parell de taules i parell de versions, també dels
-- que no tenen cap codi.

with comparisons as (
    select * from {{ source('bronze', 'comparison_status') }}
),

typed as (
    select
        dataset_id,
        version_from,
        version_to,
        "table" as table_name,
        file_path,
        status,
        cast(n_codes as integer) as n_codes
    from comparisons
)

select * from typed
