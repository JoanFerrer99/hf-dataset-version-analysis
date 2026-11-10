-- Evolució temporal dels canvis per perspectiva: una fila per trimestre i
-- perspectiva amb canvis. La data és la de la versió nova; els canvis d'una
-- versió sense data no hi surten.

with changes as (
    select
        facts.change_count,
        facts.version_to_key,
        facts.dataset_key,
        dates.year,
        dates.quarter,
        dates.year_quarter,
        kinds.perspective,
        kinds.level_1,
        kinds.is_breaking
    from {{ ref('fact_change') }} as facts
    inner join {{ ref('dim_date') }} as dates
        on dates.date_key = facts.date_key
    inner join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.kind_key = facts.kind_key
)

select
    year,
    quarter,
    year_quarter,
    perspective,
    level_1,
    sum(change_count) as n_changes,
    count(*) filter (where is_breaking) as n_breaking_changes,
    count(distinct version_to_key) as n_units,
    count(distinct dataset_key) as n_datasets
from changes
group by year, quarter, year_quarter, perspective, level_1
order by year, quarter, perspective
