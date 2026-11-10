-- Cada parell de versions comparat a la Fase 2 és una unitat de canvi, amb els
-- mateixos codis que change_classification.csv. Retorna les unitats que no quadren.

with compared as (
    select dataset_id, version_from, version_to, sum(n_codes) as n_codes
    from {{ ref('stg_comparison_status') }}
    group by dataset_id, version_from, version_to
),

classified as (
    select dataset_id, version_from, version_to, count(*) as n_rows
    from {{ ref('stg_change_classification') }}
    group by dataset_id, version_from, version_to
),

units as (
    select dataset_id, version_from, version_to, n_codes
    from {{ ref('mart_change_units') }}
)

select
    coalesce(compared.dataset_id, classified.dataset_id) as dataset_id,
    coalesce(compared.version_from, classified.version_from) as version_from,
    coalesce(compared.version_to, classified.version_to) as version_to,
    units.n_codes as unit_codes,
    compared.n_codes as status_codes,
    classified.n_rows as classification_rows
from compared
full outer join classified
    on classified.dataset_id = compared.dataset_id
    and classified.version_from = compared.version_from
    and classified.version_to = compared.version_to
left join units
    on units.dataset_id = coalesce(compared.dataset_id, classified.dataset_id)
    and units.version_from = coalesce(compared.version_from, classified.version_from)
    and units.version_to = coalesce(compared.version_to, classified.version_to)
where units.dataset_id is null
   or units.n_codes <> coalesce(compared.n_codes, 0)
   or units.n_codes <> coalesce(classified.n_rows, 0)
