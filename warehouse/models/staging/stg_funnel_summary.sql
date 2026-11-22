-- Fase 0: el resum de l'embut (una sola fila), amb noms en snake_case.
-- `run_timestamp` és l'hora local en què es va escriure, sense zona.

with optional_columns as (
    -- durades (en segons) que els runs anteriors no tenen: hi queden buides
    select
        null::double as duration_sampling_s,
        null::double as duration_eligibility_s,
        null::double as duration_versions_s,
        null::double as duration_classification_s,
        null::double as duration_total_s
    where false
),

summary as (
    select * from optional_columns
    union all by name
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
        cast(attempts_per_eligible as double) as attempts_per_eligible,
        cast(duration_sampling_s as double) as duration_sampling_s,
        cast(duration_eligibility_s as double) as duration_eligibility_s,
        cast(duration_versions_s as double) as duration_versions_s,
        cast(duration_classification_s as double) as duration_classification_s,
        cast(duration_total_s as double) as duration_total_s
    from summary
)

select * from renamed
