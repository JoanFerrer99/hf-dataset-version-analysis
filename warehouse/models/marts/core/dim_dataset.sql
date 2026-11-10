-- Dimensió dels datasets elegibles, els únics que tenen versions i canvis.
-- `snapshot_date` és el dia de l'execució: el de `downloads`. Les execucions
-- d'abans de T-25 no tenen les metadades del dataset (queden buides).

with eligible as (
    select
        dataset_id,
        eligibility_outcome as eligibility_criterion,
        num_tags,
        num_branches,
        num_tabular_commits,
        num_data_files,
        tabular_file_share,
        created_at,
        license,
        downloads
    from {{ ref('stg_eligibility_report') }}
    where is_eligible
),

run as (
    select cast(run_timestamp as date) as snapshot_date
    from {{ ref('stg_funnel_summary') }}
)

select
    {{ surrogate_key(['eligible.dataset_id']) }} as dataset_key,
    eligible.dataset_id,
    split_part(eligible.dataset_id, '/', 1) as owner,
    eligible.eligibility_criterion,
    eligible.num_tags,
    eligible.num_branches,
    eligible.num_tabular_commits,
    eligible.num_data_files,
    eligible.tabular_file_share,
    eligible.created_at,
    eligible.license,
    eligible.downloads,
    run.snapshot_date
from eligible
cross join run
