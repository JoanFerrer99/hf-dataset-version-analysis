-- Fase 2: una fila per taula, parell de versions i codi. La columna `table`
-- passa a `table_name` (`table` és una paraula reservada de SQL).

with classification as (
    select * from {{ source('bronze', 'change_classification') }}
),

typed as (
    select
        dataset_id,
        version_from,
        version_to,
        "table" as table_name,
        file_path,
        code,
        description,
        cast(is_breaking as boolean) as is_breaking
    from classification
)

select * from typed
