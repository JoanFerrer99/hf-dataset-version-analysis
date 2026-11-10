-- Fase 0: una fila per dataset de la mostra, amb tipus. `eligibility_outcome`
-- és el motiu del report com a codi estable: el criteri (A, B) o el filtre on
-- s'atura el dataset. Les execucions d'abans de T-25 no tenen les cinc últimes
-- columnes: surten buides.
{%- set present = bronze_columns(source('bronze', 'eligibility_report')) %}

with report as (
    select * from {{ source('bronze', 'eligibility_report') }}
),

typed as (
    select
        dataset_id,
        cast(num_tags as integer) as num_tags,
        cast(num_branches as integer) as num_branches,
        cast(num_tabular_commits as integer) as num_tabular_commits,
        cast(eligible as boolean) as is_eligible,
        eligibility_reason,
        case
            when eligibility_reason like 'Criteri A%' then 'A'
            when eligibility_reason like 'Criteri B%' then 'B'
            when eligibility_reason like 'no elegible: menys de 2 tags%' then 'no_version_marks'
            when eligibility_reason like 'no elegible: cap fitxer de dades tabular%' then 'no_tabular_files'
            when eligibility_reason like 'no elegible: no hi ha prou commits%' then 'no_tabular_commits'
        end as eligibility_outcome,
        status,
        error_category,
        error as error_message,
        {{ optional_column(present, 'num_data_files', 'cast(cast(num_data_files as double) as integer)', 'integer') }} as num_data_files,
        {{ optional_column(present, 'tabular_file_share', 'cast(tabular_file_share as double)', 'double') }} as tabular_file_share,
        {{ optional_column(present, 'created_at', to_utc('created_at'), 'timestamp') }} as created_at,
        {{ optional_column(present, 'license', 'license', 'varchar') }} as license,
        {{ optional_column(present, 'downloads', 'cast(cast(downloads as double) as bigint)', 'bigint') }} as downloads
    from report
)

select * from typed
