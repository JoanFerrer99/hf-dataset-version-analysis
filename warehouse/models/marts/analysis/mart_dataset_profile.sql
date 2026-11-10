-- Resum per dataset elegible: versions, comparacions (fetes i no), taules,
-- canvis, codis i canvis trencadors.

with datasets as (
    select
        dataset_key,
        dataset_id,
        owner,
        eligibility_criterion,
        num_tags,
        num_branches,
        license,
        downloads
    from {{ ref('dim_dataset') }}
),

versions as (
    select
        dataset_id,
        count(*) filter (where version_source <> 'commit') as n_versions,
        min(commit_date) as first_version_at,
        max(commit_date) as last_version_at
    from {{ ref('dim_version') }}
    group by dataset_id
),

units as (
    select
        dataset_id,
        count(*) as n_units,
        count(*) filter (where is_compared) as n_compared_units,
        count(*) filter (where has_change) as n_units_with_change,
        count(*) filter (where has_breaking_change) as n_units_with_breaking_change,
        sum(n_tables_not_compared) as n_tables_not_compared
    from {{ ref('mart_change_units') }}
    group by dataset_id
),

tables as (
    select dataset_id, count(*) as n_tables
    from {{ ref('dim_table') }}
    group by dataset_id
),

changes as (
    select
        facts.dataset_key,
        sum(facts.change_count) as n_changes,
        count(*) filter (where kinds.is_breaking) as n_breaking_changes,
        count(distinct kinds.code) as n_distinct_codes,
        array_to_string(list_sort(list_distinct(list(kinds.code))), ', ') as codes
    from {{ ref('fact_change') }} as facts
    inner join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.kind_key = facts.kind_key
    group by facts.dataset_key
)

select
    datasets.dataset_id,
    datasets.owner,
    datasets.eligibility_criterion,
    datasets.num_tags,
    datasets.num_branches,
    datasets.license,
    datasets.downloads,
    coalesce(versions.n_versions, 0) as n_versions,
    versions.first_version_at,
    versions.last_version_at,
    coalesce(units.n_units, 0) as n_units,
    coalesce(units.n_compared_units, 0) as n_compared_units,
    coalesce(units.n_units_with_change, 0) as n_units_with_change,
    coalesce(units.n_units_with_breaking_change, 0) as n_units_with_breaking_change,
    coalesce(units.n_tables_not_compared, 0) as n_tables_not_compared,
    coalesce(tables.n_tables, 0) as n_tables,
    coalesce(changes.n_changes, 0) as n_changes,
    coalesce(changes.n_breaking_changes, 0) as n_breaking_changes,
    coalesce(changes.n_distinct_codes, 0) as n_distinct_codes,
    changes.codes
from datasets
left join versions
    on versions.dataset_id = datasets.dataset_id
left join units
    on units.dataset_id = datasets.dataset_id
left join tables
    on tables.dataset_id = datasets.dataset_id
left join changes
    on changes.dataset_key = datasets.dataset_key
order by datasets.dataset_id
