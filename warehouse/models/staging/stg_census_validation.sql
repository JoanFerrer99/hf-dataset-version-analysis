-- Validació de Census Income: per a cada codi, encerts (tp), falsos negatius
-- (fn) i falsos positius (fp) del motor contra la Taula 1 del paper.

with by_code as (
    select * from {{ source('census', 'paper_comparison_by_code') }}
),

typed as (
    select
        code,
        cast(tp as integer) as true_positives,
        cast(fn as integer) as false_negatives,
        cast(fp as integer) as false_positives
    from by_code
)

select * from typed
