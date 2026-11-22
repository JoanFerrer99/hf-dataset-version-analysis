-- Freqüència de cada codi de la taxonomia: en nombre de canvis (files de
-- fact_change) i de comparacions afectades (unitats de canvi), sobre les
-- comparacions fetes. Com que cada comparació és d'un dataset sencer (T-37),
-- un codi surt com a molt un cop per comparació: les dues xifres coincideixen. Una fila per codi, també els que no surten mai.

with changes as (
    select kind_key, dataset_key, version_to_key, change_count
    from {{ ref('fact_change') }}
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
        coalesce(sum(changes.change_count), 0) as n_changes,
        count(distinct changes.version_to_key) as n_units,
        count(distinct changes.dataset_key) as n_datasets
    from {{ ref('dim_kind_of_change') }} as kinds
    left join changes
        on changes.kind_key = kinds.kind_key
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
