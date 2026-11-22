-- Conciliació 4: cap codi fora dels 15 de la taxonomia, ni a change_classification.csv
-- ni a dim_differences. Retorna els codis desconeguts i on surten.

with taxonomy as (
    select code from {{ ref('taxonomy') }}
),

used as (
    select 'change_classification.csv' as source, code
    from {{ ref('stg_change_classification') }}
    union
    select 'dim_differences', unnest(string_split(differences, '+'))
    from {{ ref('dim_differences') }}
    where differences_status = 'changed'
)

select used.source, used.code
from used
anti join taxonomy
    on taxonomy.code = used.code
