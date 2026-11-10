-- Quantes comparacions (unitats de canvi: una versió contra la següent) s'han
-- fet per dataset, i quantes no s'han pogut fer. Una fila per unitat de canvi.
-- Les unitats surten de versions.csv igual que a la Fase 2 (`version_pairs`):
-- per `version_order`, sense commits buits ni dues versions seguides amb el
-- mateix commit. `unit_status`:
--   compared         alguna taula s'ha comparat (ok o identical_content)
--   not_compared     cap taula comparada, i alguna massa gran o que no s'ha pogut baixar o llegir
--   no_common_table  només taules afegides o eliminades senceres, o excloses
--   no_tables        cap parell de taules
--   failed           la Fase 2 va fallar en aquest dataset (failures.csv)
-- Les proporcions es calculen només sobre les unitats `compared`. A més dels grups,
-- hi ha el recompte de taules de cada estat (`n_tables_<estat>`), per saber per què
-- no s'ha pogut fer una comparació.

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

tables as (
    select
        dataset_id,
        version_from,
        version_to,
        count(*) as n_tables,
        count(*) filter (where status in ('ok', 'identical_content')) as n_tables_compared,
        count(*) filter (where status in ('too_large', 'download_failed', 'parse_failed')) as n_tables_not_compared,
        count(*) filter (where status in ('absent_old', 'absent_new')) as n_tables_added_or_removed,
        count(*) filter (where status = 'excluded') as n_tables_excluded,
        count(*) filter (where status = 'ok') as n_tables_ok,
        count(*) filter (where status = 'identical_content') as n_tables_identical_content,
        count(*) filter (where status = 'absent_old') as n_tables_absent_old,
        count(*) filter (where status = 'absent_new') as n_tables_absent_new,
        count(*) filter (where status = 'download_failed') as n_tables_download_failed,
        count(*) filter (where status = 'parse_failed') as n_tables_parse_failed,
        count(*) filter (where status = 'too_large') as n_tables_too_large,
        sum(n_codes) as n_codes
    from {{ ref('stg_comparison_status') }}
    group by dataset_id, version_from, version_to
),

codes as (
    select
        dataset_id,
        version_from,
        version_to,
        count(distinct code) as n_distinct_codes,
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
        coalesce(tables.n_tables, 0) as n_tables,
        coalesce(tables.n_tables_compared, 0) as n_tables_compared,
        coalesce(tables.n_tables_not_compared, 0) as n_tables_not_compared,
        coalesce(tables.n_tables_added_or_removed, 0) as n_tables_added_or_removed,
        coalesce(tables.n_tables_excluded, 0) as n_tables_excluded,
        coalesce(tables.n_tables_ok, 0) as n_tables_ok,
        coalesce(tables.n_tables_identical_content, 0) as n_tables_identical_content,
        coalesce(tables.n_tables_absent_old, 0) as n_tables_absent_old,
        coalesce(tables.n_tables_absent_new, 0) as n_tables_absent_new,
        coalesce(tables.n_tables_download_failed, 0) as n_tables_download_failed,
        coalesce(tables.n_tables_parse_failed, 0) as n_tables_parse_failed,
        coalesce(tables.n_tables_too_large, 0) as n_tables_too_large,
        coalesce(tables.n_codes, 0) as n_codes,
        coalesce(codes.n_distinct_codes, 0) as n_distinct_codes,
        coalesce(codes.n_breaking_codes, 0) as n_breaking_codes,
        failed_datasets.dataset_id is not null as dataset_failed
    from units
    left join tables
        on tables.dataset_id = units.dataset_id
        and tables.version_from = units.version_from
        and tables.version_to = units.version_to
    left join codes
        on codes.dataset_id = units.dataset_id
        and codes.version_from = units.version_from
        and codes.version_to = units.version_to
    left join failed_datasets
        on failed_datasets.dataset_id = units.dataset_id
)

select
    dataset_id,
    version_from,
    version_to,
    label_from,
    label_to,
    date_to,
    n_tables,
    n_tables_compared,
    n_tables_not_compared,
    n_tables_added_or_removed,
    n_tables_excluded,
    n_tables_ok,
    n_tables_identical_content,
    n_tables_absent_old,
    n_tables_absent_new,
    n_tables_download_failed,
    n_tables_parse_failed,
    n_tables_too_large,
    n_codes,
    n_distinct_codes,
    n_breaking_codes,
    case
        when n_tables_compared > 0 then 'compared'
        when n_tables_not_compared > 0 then 'not_compared'
        when n_tables > 0 then 'no_common_table'
        when dataset_failed then 'failed'
        else 'no_tables'
    end as unit_status,
    n_tables_compared > 0 as is_compared,
    n_codes > 0 as has_change,
    n_breaking_codes > 0 as has_breaking_change
from joined
