-- Fase 0: el resum de l'embut (una sola fila), amb noms en snake_case.
-- `run_timestamp` és l'hora local en què es va escriure, sense zona.

with summary as (
    select * from {{ source('bronze', 'funnel_summary') }}
),

renamed as (
    select
        cast("timestamp" as timestamp) as run_timestamp,
        cast(sampling_method as varchar) as sampling_method,
        cast(sample_size as integer) as sample_size,
        cast(population_scanned as bigint) as population_scanned,
        cast("eligible_Criteri_A" as integer) as eligible_criterion_a,
        cast("eligible_Criteri_B" as integer) as eligible_criterion_b,
        cast(eligible as integer) as eligible,
        cast(ineligible as integer) as ineligible,
        cast(access_restricted as integer) as access_restricted,
        cast(errors as integer) as errors,
        cast(eligible_proportion as double) as eligible_proportion,
        cast(eligible_proportion_of_attempts as double) as eligible_proportion_of_attempts,
        cast(estimated_eligible_in_scanned_population as bigint) as estimated_eligible_in_scanned_population,
        cast(attempts_per_eligible as double) as attempts_per_eligible
    from summary
)

select * from renamed
