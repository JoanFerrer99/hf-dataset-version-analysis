-- Conciliació 3: cada dataset amb canvis (change_classification.csv, i per tant
-- fact_change, conciliació 1) és elegible a eligibility_report.csv. Retorna els
-- que no ho són o no hi surten.

with changed as (
    select distinct dataset_id
    from {{ ref('stg_change_classification') }}
),

eligible as (
    select dataset_id
    from {{ ref('stg_eligibility_report') }}
    where is_eligible
)

select changed.dataset_id
from changed
anti join eligible
    on eligible.dataset_id = changed.dataset_id
