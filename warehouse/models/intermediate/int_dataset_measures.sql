-- Una fila per dataset de la mostra (eligibility_report.csv), amb les mesures
-- de fact_dataset. `eligibility`: `Si` (elegible), `Restringit` (403) o
-- `NoElegible` (la resta, també els que van fallar). Les mesures que surten de
-- les versions (versions, mida, fitxers, files i columnes, inicials i finals)
-- només es tenen per als elegibles; la mida i els fitxers són els de les dades
-- (els fitxers del dataset).

with report as (
    select
        dataset_id,
        split_part(dataset_id, '/', 1) as owner,
        case
            when is_eligible then 'Si'
            when status = 'access_restricted' then 'Restringit'
            else 'NoElegible'
        end as eligibility,
        case when is_eligible then eligibility_outcome end as eligibility_criterion,
        created_at,
        license,
        downloads,
        num_tags,
        num_branches,
        num_tabular_commits,
        num_data_files,
        tabular_file_share
    from {{ ref('stg_eligibility_report') }}
),

versions as (
    select
        dataset_id,
        count(*) as n_versions,
        arg_min_null(data_size_bytes, version_order) as initial_size_bytes,
        arg_max_null(data_size_bytes, version_order) as final_size_bytes,
        arg_min_null(n_data_files, version_order) as initial_n_files,
        arg_max_null(n_data_files, version_order) as final_n_files,
        arg_min_null(n_rows, version_order) as initial_n_rows,
        arg_min_null(n_columns, version_order) as initial_n_columns
    from {{ ref('int_version_measures') }}
    group by dataset_id
)

select
    report.*,
    versions.n_versions,
    versions.initial_size_bytes,
    versions.final_size_bytes,
    versions.initial_n_files,
    versions.final_n_files,
    versions.initial_n_rows,
    versions.initial_n_columns
from report
left join versions
    on versions.dataset_id = report.dataset_id
