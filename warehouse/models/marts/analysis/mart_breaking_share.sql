-- Quina proporció de les comparacions fetes té almenys un canvi trencador (i
-- almenys un canvi de qualsevol tipus), per criteri d'elegibilitat i en total,
-- amb l'interval de Wilson al 95%. Només compten les unitats `is_compared`.

with units as (
    select
        units.dataset_id,
        datasets.eligibility_criterion,
        units.has_change,
        units.has_breaking_change
    from {{ ref('mart_change_units') }} as units
    inner join {{ ref('dim_dataset') }} as datasets
        on datasets.dataset_id = units.dataset_id
    where units.is_compared
),

by_criterion as (
    select
        coalesce(eligibility_criterion, 'all') as criterion,
        count(*) as n_compared_units,
        count(*) filter (where has_change) as n_units_with_change,
        count(*) filter (where has_breaking_change) as n_units_with_breaking_change
    from units
    group by rollup (eligibility_criterion)
)

select
    criterion,
    n_compared_units,
    n_units_with_change,
    n_units_with_breaking_change,
    n_units_with_change / n_compared_units as share_with_change,
    n_units_with_breaking_change / n_compared_units as share_with_breaking_change,
    {{ wilson_low('n_units_with_breaking_change', 'n_compared_units') }} as share_with_breaking_change_low,
    {{ wilson_high('n_units_with_breaking_change', 'n_compared_units') }} as share_with_breaking_change_high
from by_criterion
order by criterion
