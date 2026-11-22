-- Freqüència de cada codi de la taxonomia: les versions que el tenen respecte
-- a l'anterior (fact_version × dim_differences), sobre les comparacions fetes.
-- Cada comparació és d'un dataset sencer: un codi surt com a molt un cop per
-- versió, i `n_changes` coincideix amb `n_units`. Una fila per codi, també els
-- que no surten mai.

with version_codes as (
    select versions.version_key, versions.dataset_key, unnest(string_split(differences.differences, '+')) as code
    from {{ ref('fact_version') }} as versions
    inner join {{ ref('dim_differences') }} as differences
        on differences.differences_key = versions.differences_key
    where differences.differences_status = 'changed'
),

compared_units as (
    select count(*) filter (where is_compared) as n_compared_units
    from {{ ref('mart_change_units') }}
),

by_code as (
    select
        kinds.code,
        kinds.name,
        kinds.perspective,
        kinds.level_1,
        count(version_codes.version_key) as n_changes,
        count(distinct version_codes.version_key) as n_units,
        count(distinct version_codes.dataset_key) as n_datasets
    from {{ ref('dim_kind_of_change') }} as kinds
    left join version_codes
        on version_codes.code = kinds.code
    group by kinds.code, kinds.name, kinds.perspective, kinds.level_1
)

select
    by_code.code,
    by_code.name,
    by_code.perspective,
    by_code.level_1,
    by_code.n_changes,
    by_code.n_units,
    by_code.n_datasets,
    compared_units.n_compared_units,
    case when compared_units.n_compared_units > 0
        then by_code.n_units / compared_units.n_compared_units end as share_of_compared_units
from by_code
cross join compared_units
order by by_code.code
