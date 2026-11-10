-- Validació del motor amb Census Income: precisió, recall i F1 de cada codi
-- contra la Taula 1 del paper. Buit quan el denominador és 0 (p.e. el recall
-- d'un codi que el paper no marca mai).

with by_code as (
    select code, true_positives, false_negatives, false_positives
    from {{ ref('stg_census_validation') }}
),

kinds as (
    select code, name, perspective
    from {{ ref('dim_kind_of_change') }}
),

measured as (
    select
        by_code.code,
        kinds.name,
        kinds.perspective,
        by_code.true_positives,
        by_code.false_negatives,
        by_code.false_positives,
        case when by_code.true_positives + by_code.false_positives > 0
            then by_code.true_positives / (by_code.true_positives + by_code.false_positives) end as precision,
        case when by_code.true_positives + by_code.false_negatives > 0
            then by_code.true_positives / (by_code.true_positives + by_code.false_negatives) end as recall
    from by_code
    inner join kinds
        on kinds.code = by_code.code
)

select
    code,
    name,
    perspective,
    true_positives,
    false_negatives,
    false_positives,
    precision,
    recall,
    case when precision + recall > 0 then 2 * precision * recall / (precision + recall) end as f1
from measured
order by code
