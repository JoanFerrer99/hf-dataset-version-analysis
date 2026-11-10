-- Conciliació 2: l'embut quadra amb la mida de la mostra. A funnel_summary.json,
-- elegibles + no elegibles + inaccessibles + errors = mida de la mostra; el report
-- (eligibility_report.csv) té una fila per dataset de la mostra i els mateixos
-- recomptes per estat i per criteri; i mart_funnel diu el mateix. Retorna cada
-- comprovació que no quadra, amb el valor esperat i el trobat.

with summary as (
    select
        sample_size,
        eligible,
        ineligible,
        access_restricted,
        errors,
        eligible_criterion_a,
        eligible_criterion_b
    from {{ ref('stg_funnel_summary') }}
),

report as (
    select
        count(*) as n_rows,
        count(*) filter (where status = 'classified' and is_eligible) as eligible,
        count(*) filter (where status = 'classified' and not is_eligible) as ineligible,
        count(*) filter (where status = 'access_restricted') as access_restricted,
        count(*) filter (where status = 'error') as errors,
        count(*) filter (where eligibility_outcome = 'A') as criterion_a,
        count(*) filter (where eligibility_outcome = 'B') as criterion_b
    from {{ ref('stg_eligibility_report') }}
),

funnel as (
    select
        max(n_datasets) filter (where stage = 'sample') as sampled,
        max(n_datasets) filter (where stage = 'classified') as classified,
        max(n_datasets) filter (where stage = 'eligible') as eligible
    from {{ ref('mart_funnel') }}
),

checks as (
    select 'resum: elegibles + no elegibles + inaccessibles + errors = mostra' as check_name,
        s.sample_size as expected, s.eligible + s.ineligible + s.access_restricted + s.errors as actual
    from summary as s
    union all
    select 'report: una fila per dataset de la mostra', s.sample_size, r.n_rows
    from summary as s cross join report as r
    union all
    select 'report: elegibles', s.eligible, r.eligible
    from summary as s cross join report as r
    union all
    select 'report: no elegibles', s.ineligible, r.ineligible
    from summary as s cross join report as r
    union all
    select 'report: inaccessibles', s.access_restricted, r.access_restricted
    from summary as s cross join report as r
    union all
    select 'report: errors', s.errors, r.errors
    from summary as s cross join report as r
    union all
    select 'report: elegibles pel Criteri A', s.eligible_criterion_a, r.criterion_a
    from summary as s cross join report as r
    union all
    select 'report: elegibles pel Criteri B', s.eligible_criterion_b, r.criterion_b
    from summary as s cross join report as r
    union all
    select 'mart_funnel: mostra', s.sample_size, f.sampled
    from summary as s cross join funnel as f
    union all
    select 'mart_funnel: classificats', s.eligible + s.ineligible, f.classified
    from summary as s cross join funnel as f
    union all
    select 'mart_funnel: elegibles', s.eligible, f.eligible
    from summary as s cross join funnel as f
)

select check_name, expected, actual
from checks
where expected is distinct from actual
