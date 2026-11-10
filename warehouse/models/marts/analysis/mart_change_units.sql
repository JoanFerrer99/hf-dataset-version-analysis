-- Quantes comparacions (unitats de canvi: una versió contra la següent) s'han
-- fet per dataset, i quantes no s'han pogut fer. Una fila per unitat de canvi.
-- Les unitats surten de versions.csv igual que a la Fase 2 (`version_pairs`):
-- per `version_order`, sense commits buits ni dues versions seguides amb el
-- mateix commit. Cada unitat compara el dataset sencer (T-37): té un sol estat
-- (`comparison_status`) a comparison_status.csv. `unit_status` l'agrupa:
--   compared      comparat (ok o identical_content)
--   not_compared  massa gran, o no s'ha pogut baixar o llegir
--   no_data       una de les versions (o les dues) no té cap fitxer de dades
--   failed        la Fase 2 va fallar en aquest dataset (failures.csv)
--   not_run       no hi ha l'estat (p.e. l'execució es va aturar abans)
-- Les proporcions es calculen només sobre les unitats `compared`.

with versions as (
    select
        dataset_id,
        commit_sha,
        version_order,
        version_label,
        commit_date,
        lag(commit_sha) over (partition by dataset_id order by version_order) as previous_sha,
        lag(version_label) over (partition by dataset_id order by version_order) as previous_label
    from {{ ref('stg_versions') }}
    where commit_sha is not null and commit_sha <> ''
),

units as (
    select
        dataset_id,
        previous_sha as version_from,
        commit_sha as version_to,
        previous_label as label_from,
        version_label as label_to,
        commit_date as date_to
    from versions
    where previous_sha is not null and previous_sha <> commit_sha
),

comparisons as (
    select
        dataset_id,
        version_from,
        version_to,
        status,
        n_codes,
        format_from,
        format_to,
        n_files_from,
        n_files_to,
        size_bytes
    from {{ ref('stg_comparison_status') }}
),

codes as (
    select
        dataset_id,
        version_from,
        version_to,
        count(*) filter (where is_breaking) as n_breaking_codes
    from {{ ref('stg_change_classification') }}
    group by dataset_id, version_from, version_to
),

failed_datasets as (
    select distinct dataset_id
    from {{ ref('stg_failures') }}
    where phase = 'classification'
),

joined as (
    select
        units.dataset_id,
        units.version_from,
        units.version_to,
        units.label_from,
        units.label_to,
        units.date_to,
        comparisons.status as comparison_status,
        comparisons.format_from,
        comparisons.format_to,
        coalesce(comparisons.n_files_from, 0) as n_files_from,
        coalesce(comparisons.n_files_to, 0) as n_files_to,
        coalesce(comparisons.size_bytes, 0) as size_bytes,
        coalesce(comparisons.n_codes, 0) as n_codes,
        coalesce(codes.n_breaking_codes, 0) as n_breaking_codes,
        failed_datasets.dataset_id is not null as dataset_failed
    from units
    left join comparisons
        on comparisons.dataset_id = units.dataset_id
        and comparisons.version_from = units.version_from
        and comparisons.version_to = units.version_to
    left join codes
        on codes.dataset_id = units.dataset_id
        and codes.version_from = units.version_from
        and codes.version_to = units.version_to
    left join failed_datasets
        on failed_datasets.dataset_id = units.dataset_id
),

grouped as (
    select
        *,
        case
            when comparison_status in ('ok', 'identical_content') then 'compared'
            when comparison_status in ('too_large', 'download_failed', 'parse_failed') then 'not_compared'
            when comparison_status in ('absent_old', 'absent_new', 'no_data') then 'no_data'
            when dataset_failed then 'failed'
            else 'not_run'
        end as unit_status
    from joined
)

select
    dataset_id,
    version_from,
    version_to,
    label_from,
    label_to,
    date_to,
    comparison_status,
    unit_status,
    format_from,
    format_to,
    n_files_from,
    n_files_to,
    size_bytes,
    n_codes,
    n_breaking_codes,
    unit_status = 'compared' as is_compared,
    n_codes > 0 as has_change,
    n_breaking_codes > 0 as has_breaking_change
from grouped
