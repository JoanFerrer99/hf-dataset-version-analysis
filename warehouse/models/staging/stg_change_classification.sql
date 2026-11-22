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
        description
    from classification
)

select * from typed
