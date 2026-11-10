-- Dimensió de dates: només els dies en què hi ha alguna versió (no un calendari
-- fix). `date_key` és la data com a enter AAAAMMDD.

with days as (
    select distinct cast(commit_date as date) as day
    from {{ ref('stg_versions') }}
    where commit_date is not null
)

select
    cast(strftime(day, '%Y%m%d') as integer) as date_key,
    day as date,
    year(day) as year,
    quarter(day) as quarter,
    year(day) || '-T' || quarter(day) as year_quarter,
    month(day) as month,
    isodow(day) as weekday
from days
