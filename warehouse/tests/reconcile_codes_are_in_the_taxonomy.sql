-- Conciliació 4: cap codi fora dels 14 de la taxonomia, ni a change_classification.csv
-- ni a fact_change. Retorna els codis desconeguts i on surten.

with taxonomy as (
    select code from {{ ref('taxonomy') }}
),

used as (
    select 'change_classification.csv' as source, code
    from {{ ref('stg_change_classification') }}
    union
    select 'fact_change', kinds.code
    from {{ ref('fact_change') }} as facts
    left join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.kind_key = facts.kind_key
)

select used.source, used.code
from used
anti join taxonomy
    on taxonomy.code = used.code
