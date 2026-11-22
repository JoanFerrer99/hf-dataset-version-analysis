-- Els intervals k-means són ordenats: tots els valors d'un interval són més
-- petits o iguals que els de l'interval següent. Retorna les mesures on dos
-- intervals es trepitgen.

with banded as (
    select 'downloads' as measure, measures.downloads as value, bands.downloads_band as band
    from {{ ref('int_dataset_measures') }} as measures
    inner join {{ ref('int_dataset_bands') }} as bands on bands.dataset_id = measures.dataset_id
    union all
    select 'initial_size', measures.initial_size_bytes, bands.initial_size_band
    from {{ ref('int_dataset_measures') }} as measures
    inner join {{ ref('int_dataset_bands') }} as bands on bands.dataset_id = measures.dataset_id
    union all
    select 'n_versions', measures.n_versions, bands.n_versions_band
    from {{ ref('int_dataset_measures') }} as measures
    inner join {{ ref('int_dataset_bands') }} as bands on bands.dataset_id = measures.dataset_id
),

ranges as (
    select
        measure,
        case band when 'Few' then 1 when 'Low' then 1 when 'Medium' then 2 else 3 end as band_rank,
        min(value) as low,
        max(value) as high
    from banded
    where band is not null
    group by measure, band
)

select a.measure, a.band_rank, a.high, b.band_rank as next_rank, b.low as next_low
from ranges as a
inner join ranges as b
    on b.measure = a.measure and b.band_rank > a.band_rank
where a.high > b.low
