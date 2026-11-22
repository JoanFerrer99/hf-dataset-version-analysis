-- Dimensió de temps, a l'hora: només les hores en què hi ha alguna versió
-- (commit) o es va crear algun dataset de la mostra. `time_key` és
-- AAAAMMDDHH. Fa dos rols: el commit de fact_version i la creació a fact_dataset.

with hours as (
    select distinct date_trunc('hour', commit_date) as hour_start
    from {{ ref('int_version_measures') }}
    where commit_date is not null
    union
    select distinct date_trunc('hour', created_at)
    from {{ ref('int_dataset_measures') }}
    where created_at is not null
)

select
    cast(strftime(hour_start, '%Y%m%d%H') as integer) as time_key,
    hour_start,
    cast(hour_start as date) as date,
    year(hour_start) as year,
    quarter(hour_start) as quarter,
    year(hour_start) || '-T' || quarter(hour_start) as year_quarter,
    month(hour_start) as month,
    day(hour_start) as day,
    hour(hour_start) as hour,
    isodow(hour_start) as weekday
from hours
