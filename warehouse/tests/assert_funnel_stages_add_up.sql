-- Cada pas de l'embut té els datasets del pas anterior menys els que s'hi queden,
-- i els elegibles són els del Criteri A més els del B. Retorna els passos que no quadren.

with stages as (
    select
        stage_order,
        stage,
        n_datasets,
        n_dropped,
        n_criterion_a,
        n_criterion_b,
        lag(n_datasets) over (order by stage_order) as previous_n_datasets
    from {{ ref('mart_funnel') }}
)

select stage, n_datasets, n_dropped, previous_n_datasets
from stages
where (stage_order > 1 and n_datasets <> previous_n_datasets - n_dropped)
   or (stage = 'eligible' and n_datasets <> n_criterion_a + n_criterion_b)
