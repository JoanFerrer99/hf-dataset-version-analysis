-- Una fila per versió d'un dataset elegible (dos tags al mateix commit són una
-- sola versió), amb les mesures de fact_version i les diferències respecte a
-- la versió anterior:
--   differences  els codis units amb `+` (p.e. C221+C421), o un estat:
--                `first_version`, `no_changes` (comparada, sense codis o amb el
--                mateix contingut) o `not_compared` (massa gran, il·legible,
--                columnes diferents, o sense estat).
-- Les files i columnes surten de la comparació que llegeix la versió (com a
-- nova o com a antiga). Si la comparació va ser `identical_content`, no es va
-- llegir: la versió hereta les de l'anterior.

with versions as (
    select
        dataset_id,
        commit_sha,
        string_agg(version_label, ', ' order by version_order) as version_label,
        min(version_order) as listed_order,
        min(version_source) as version_source,
        min(commit_date) as commit_date,
        max(session_commit_count) as session_commit_count,
        max(data_size_bytes) as data_size_bytes,
        max(metadata_size_bytes) as metadata_size_bytes,
        max(n_data_files) as n_data_files,
        max(n_metadata_files) as n_metadata_files
    from {{ ref('stg_versions') }}
    where commit_sha is not null and commit_sha <> ''
    group by dataset_id, commit_sha
),

ordered as (
    select
        *,
        row_number() over (partition by dataset_id order by listed_order) as version_order,
        count(*) over (partition by dataset_id) as n_versions,
        lag(commit_date) over (partition by dataset_id order by listed_order) as previous_date,
        lead(commit_date) over (partition by dataset_id order by listed_order) as next_date
    from versions
),

incoming as (
    select dataset_id, version_to as commit_sha, status, n_rows_to as n_rows, n_columns_to as n_columns
    from {{ ref('stg_comparison_status') }}
),

outgoing as (
    select dataset_id, version_from as commit_sha, n_rows_from as n_rows, n_columns_from as n_columns
    from {{ ref('stg_comparison_status') }}
),

codes as (
    select dataset_id, version_to as commit_sha, string_agg(code, '+' order by code) as codes
    from {{ ref('stg_change_classification') }}
    group by dataset_id, version_to
),

joined as (
    select
        ordered.*,
        incoming.status as comparison_status,
        coalesce(incoming.n_rows, outgoing.n_rows) as read_rows,
        coalesce(incoming.n_columns, outgoing.n_columns) as read_columns,
        case
            when ordered.version_order = 1 then 'first_version'
            when incoming.status in ('ok', 'identical_content') and codes.codes is null then 'no_changes'
            when incoming.status = 'ok' then codes.codes
            else 'not_compared'
        end as differences,
        -- cada versió que no és `identical_content` comença un grup; dins del grup s'hereten files i columnes
        sum(case when incoming.status = 'identical_content' then 0 else 1 end)
            over (partition by ordered.dataset_id order by ordered.version_order) as shape_group
    from ordered
    left join incoming
        on incoming.dataset_id = ordered.dataset_id
        and incoming.commit_sha = ordered.commit_sha
    left join (select distinct * from outgoing) as outgoing
        on outgoing.dataset_id = ordered.dataset_id
        and outgoing.commit_sha = ordered.commit_sha
    left join codes
        on codes.dataset_id = ordered.dataset_id
        and codes.commit_sha = ordered.commit_sha
)

select
    dataset_id,
    commit_sha,
    version_label,
    version_order,
    n_versions,
    case version_source when 'tag' then 'tag' else 'commit' end as version_kind,
    case
        when version_order = 1 then 'First'
        when version_order = n_versions then 'Last'
        else 'Intermediate'
    end as version_position,
    commit_date,
    comparison_status,
    differences,
    date_diff('day', commit_date, next_date) as lifespan_days,
    date_diff('day', previous_date, commit_date) as conception_days,
    data_size_bytes,
    metadata_size_bytes,
    n_data_files,
    n_metadata_files,
    session_commit_count,
    last_value(read_rows ignore nulls) over shape as n_rows,
    last_value(read_columns ignore nulls) over shape as n_columns
from joined
window shape as (
    partition by dataset_id, shape_group order by version_order rows between unbounded preceding and current row
)
