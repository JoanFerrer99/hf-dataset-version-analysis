-- Evolució temporal dels canvis per perspectiva: una fila per trimestre (del
-- commit de la versió nova) i perspectiva amb canvis. Les versions sense data
-- no hi surten.

with version_codes as (
    select
        versions.version_key,
        versions.dataset_key,
        versions.commit_time_key,
        unnest(string_split(differences.differences, '+')) as code
    from {{ ref('fact_version') }} as versions
    inner join {{ ref('dim_differences') }} as differences
        on differences.differences_key = versions.differences_key
    where differences.differences_status = 'changed'
)

select
    times.year,
    times.quarter,
    times.year_quarter,
    kinds.perspective,
    kinds.level_1,
    count(*) as n_changes,
    count(distinct version_codes.version_key) as n_units,
    count(distinct version_codes.dataset_key) as n_datasets
from version_codes
inner join {{ ref('dim_time') }} as times
    on times.time_key = version_codes.commit_time_key
inner join {{ ref('dim_kind_of_change') }} as kinds
    on kinds.code = version_codes.code
group by times.year, times.quarter, times.year_quarter, kinds.perspective, kinds.level_1
order by times.year, times.quarter, kinds.perspective
