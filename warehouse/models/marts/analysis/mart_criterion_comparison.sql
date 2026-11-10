-- Si els datasets del Criteri A (tags) i del B (sessions de commits) canvien de
-- manera diferent: una fila per criteri i perspectiva, amb la proporció de
-- comparacions fetes que tenen algun canvi d'aquella perspectiva i la part dels
-- canvis del criteri que hi corresponen.

with units as (
    select
        datasets.eligibility_criterion as criterion,
        count(distinct units.dataset_id) as n_datasets,
        count(*) filter (where units.is_compared) as n_compared_units
    from {{ ref('mart_change_units') }} as units
    inner join {{ ref('dim_dataset') }} as datasets
        on datasets.dataset_id = units.dataset_id
    group by datasets.eligibility_criterion
),

perspectives as (
    select distinct perspective, level_1
    from {{ ref('dim_kind_of_change') }}
),

changes as (
    select
        datasets.eligibility_criterion as criterion,
        kinds.perspective,
        sum(facts.change_count) as n_changes,
        count(distinct facts.version_to_key) as n_units
    from {{ ref('fact_change') }} as facts
    inner join {{ ref('dim_dataset') }} as datasets
        on datasets.dataset_key = facts.dataset_key
    inner join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.kind_key = facts.kind_key
    group by datasets.eligibility_criterion, kinds.perspective
),

grid as (
    select
        units.criterion,
        perspectives.perspective,
        perspectives.level_1,
        units.n_datasets,
        units.n_compared_units,
        coalesce(changes.n_changes, 0) as n_changes,
        coalesce(changes.n_units, 0) as n_units_with_perspective
    from units
    cross join perspectives
    left join changes
        on changes.criterion = units.criterion
        and changes.perspective = perspectives.perspective
)

select
    criterion,
    perspective,
    level_1,
    n_datasets,
    n_compared_units,
    n_changes,
    n_units_with_perspective,
    case when n_compared_units > 0 then n_units_with_perspective / n_compared_units end as share_of_compared_units,
    case when sum(n_changes) over (partition by criterion) > 0
        then n_changes / sum(n_changes) over (partition by criterion) end as share_of_criterion_changes
from grid
order by criterion, perspective
