-- Resum per dataset elegible: versions, comparacions (fetes i no), canvis i
-- codis.

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
    where is_eligible
),

versions as (
    select
        dataset_id,
        count(*) as n_versions,
        min(commit_date) as first_version_at,
        max(commit_date) as last_version_at
    from {{ ref('fact_version') }}
    group by dataset_id
),

units as (
    select
        dataset_id,
        count(*) as n_units,
        count(*) filter (where is_compared) as n_compared_units,
        count(*) filter (where has_change) as n_units_with_change,
        count(*) filter (where unit_status = 'not_compared') as n_units_not_compared
    from {{ ref('mart_change_units') }}
    group by dataset_id
),

version_codes as (
    select versions.dataset_key, unnest(string_split(differences.differences, '+')) as code
    from {{ ref('fact_version') }} as versions
    inner join {{ ref('dim_differences') }} as differences
        on differences.differences_key = versions.differences_key
    where differences.differences_status = 'changed'
),

changes as (
    select
        dataset_key,
        count(*) as n_changes,
        count(distinct code) as n_distinct_codes,
        array_to_string(list_sort(list_distinct(list(code))), ', ') as codes
    from version_codes
    group by dataset_key
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
    coalesce(units.n_units_not_compared, 0) as n_units_not_compared,
    coalesce(changes.n_changes, 0) as n_changes,
    coalesce(changes.n_distinct_codes, 0) as n_distinct_codes,
    changes.codes
from datasets
left join versions
    on versions.dataset_id = datasets.dataset_id
left join units
    on units.dataset_id = datasets.dataset_id
left join changes
    on changes.dataset_key = datasets.dataset_key
order by datasets.dataset_id
