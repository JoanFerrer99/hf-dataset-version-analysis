-- Els codis de cada versió respecte a l'anterior, desplegats de dim_differences:
-- una fila per versió i codi. És la base de les consultes amb filtres de la
-- interfície (dataset, criteri, perspectiva).

with version_codes as (
    select
        versions.version_key,
        versions.dataset_key,
        versions.commit_time_key,
        versions.dataset_id,
        versions.commit_sha,
        unnest(string_split(differences.differences, '+')) as code
    from {{ ref('fact_version') }} as versions
    inner join {{ ref('dim_differences') }} as differences
        on differences.differences_key = versions.differences_key
    where differences.differences_status = 'changed'
)

select
    version_codes.version_key,
    version_codes.dataset_key,
    version_codes.dataset_id,
    version_codes.commit_sha,
    datasets.eligibility_criterion,
    version_codes.code,
    kinds.name,
    kinds.perspective,
    kinds.level_1,
    times.year,
    times.quarter,
    times.year_quarter
from version_codes
inner join {{ ref('dim_dataset') }} as datasets
    on datasets.dataset_key = version_codes.dataset_key
inner join {{ ref('dim_kind_of_change') }} as kinds
    on kinds.code = version_codes.code
left join {{ ref('dim_time') }} as times
    on times.time_key = version_codes.commit_time_key
