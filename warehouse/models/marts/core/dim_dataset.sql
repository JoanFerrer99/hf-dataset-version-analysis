-- Dimensió dels datasets: tota la mostra. A fact_version (que només té els
-- elegibles) porta l'autor, la creació, l'elegibilitat, la llicència i els
-- intervals (k-means, `int_dataset_bands`). `snapshot_date` és el dia de
-- l'execució: el de `downloads`.

with run as (
    select cast(run_timestamp as date) as snapshot_date
    from {{ ref('stg_funnel_summary') }}
)

select
    {{ surrogate_key(['measures.dataset_id']) }} as dataset_key,
    measures.dataset_id,
    measures.owner,
    measures.eligibility,
    measures.eligibility = 'Si' as is_eligible,
    measures.eligibility_criterion,
    measures.created_at,
    measures.license,
    measures.downloads,
    measures.num_tags,
    measures.num_branches,
    measures.num_tabular_commits,
    measures.num_data_files,
    measures.tabular_file_share,
    bands.downloads_band,
    bands.initial_size_band,
    bands.initial_rows_band,
    bands.initial_columns_band,
    bands.n_versions_band,
    bands.n_tabular_commits_band,
    run.snapshot_date
from {{ ref('int_dataset_measures') }} as measures
inner join {{ ref('int_dataset_bands') }} as bands
    on bands.dataset_id = measures.dataset_id
cross join run
