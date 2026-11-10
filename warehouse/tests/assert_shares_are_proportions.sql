-- Totes les proporcions dels marts són entre 0 i 1, i dins del seu interval de
-- Wilson quan en tenen. Retorna les que no ho són.

with shares as (
    select 'mart_funnel' as mart, stage as row_key, share_of_classified as share, share_low as low, share_high as high
    from {{ ref('mart_funnel') }}
    union all
    select 'mart_breaking_share', criterion, share_with_breaking_change,
        share_with_breaking_change_low, share_with_breaking_change_high
    from {{ ref('mart_breaking_share') }}
    union all
    select 'mart_breaking_share', criterion, share_with_change, null, null
    from {{ ref('mart_breaking_share') }}
    union all
    select 'mart_code_frequency', code, share_of_compared_units, null, null
    from {{ ref('mart_code_frequency') }}
    union all
    select 'mart_criterion_comparison', criterion || ' ' || perspective, share_of_compared_units, null, null
    from {{ ref('mart_criterion_comparison') }}
    union all
    select 'mart_criterion_comparison', criterion || ' ' || perspective, share_of_criterion_changes, null, null
    from {{ ref('mart_criterion_comparison') }}
    union all
    select 'mart_census_validation', code, precision, null, null
    from {{ ref('mart_census_validation') }}
    union all
    select 'mart_census_validation', code, recall, null, null
    from {{ ref('mart_census_validation') }}
    union all
    select 'mart_census_validation', code, f1, null, null
    from {{ ref('mart_census_validation') }}
)

select mart, row_key, share, low, high
from shares
where share is not null
  and (share < 0 or share > 1
       or (low is not null and (low > share + 1e-9 or low < 0))
       or (high is not null and (high < share - 1e-9 or high > 1 + 1e-9)))
