-- Totes les fases: una fila per fallada. Si l'execució no en va tenir cap, no hi
-- ha failures.csv i el model és buit, amb les mateixes columnes.

{% if bronze_file_exists('failures.csv') %}
with failures as (
    select * from {{ source('bronze', 'failures') }}
),

typed as (
    select
        {{ to_utc('"timestamp"') }} as failed_at,
        source as phase,
        dataset_id,
        error_category,
        error_message,
        cast(retries_attempted as integer) as retries_attempted
    from failures
)

select * from typed
{% else %}
select
    cast(null as timestamp) as failed_at,
    cast(null as varchar) as phase,
    cast(null as varchar) as dataset_id,
    cast(null as varchar) as error_category,
    cast(null as varchar) as error_message,
    cast(null as integer) as retries_attempted
where false
{% endif %}
