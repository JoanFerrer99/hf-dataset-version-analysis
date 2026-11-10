-- Dimensió de les taules comparades: una fila per (dataset, taula). `format` és
-- l'extensió de la taula si és un fitxer sol, o la del seu primer fitxer si és
-- un `subset/split`.

with tables as (
    select dataset_id, table_name, file_path from {{ ref('stg_comparison_status') }}
    union all
    select dataset_id, table_name, file_path from {{ ref('stg_change_classification') }}
),

first_files as (
    select
        dataset_id,
        table_name,
        min(split_part(file_path, ',', 1)) as first_file
    from tables
    group by dataset_id, table_name
)

select
    {{ surrogate_key(['dataset_id', 'table_name']) }} as table_key,
    dataset_id,
    table_name as table_path,
    lower(coalesce(
        nullif(regexp_extract(table_name, '\.([A-Za-z0-9]+)$', 1), ''),
        nullif(regexp_extract(first_file, '\.([A-Za-z0-9]+)$', 1), '')
    )) as format
from first_files
