-- Fase 2: una fila per parell de versions d'un dataset i codi.

with classification as (
    select * from {{ source('bronze', 'change_classification') }}
),

typed as (
    select
        dataset_id,
        version_from,
        version_to,
        code,
        description,
        cast(is_breaking as boolean) as is_breaking
    from classification
)

select * from typed
