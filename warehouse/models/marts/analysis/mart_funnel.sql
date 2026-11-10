-- Quants datasets passen cada filtre de la Fase 0, i quina proporció dels
-- classificats arriba a cada pas (amb l'interval de Wilson al 95%). Una fila
-- per pas. El denominador són els classificats: els inaccessibles i els que
-- van donar error no se sap si serien elegibles (com `eligible_proportion`).

with report as (
    select status, eligibility_outcome
    from {{ ref('stg_eligibility_report') }}
),

counts as (
    select
        count(*) as sampled,
        count(*) filter (where status = 'classified') as classified,
        count(*) filter (where status = 'access_restricted') as access_restricted,
        count(*) filter (where status = 'error') as errors,
        count(*) filter (where eligibility_outcome = 'no_version_marks') as no_version_marks,
        count(*) filter (where eligibility_outcome = 'no_tabular_files') as no_tabular_files,
        count(*) filter (where eligibility_outcome = 'no_tabular_commits') as no_tabular_commits,
        count(*) filter (where eligibility_outcome = 'A') as criterion_a,
        count(*) filter (where eligibility_outcome = 'B') as criterion_b
    from report
),

stages as (
    select 1 as stage_order, 'sample' as stage, 'Mostra' as stage_label,
        sampled as n_datasets, cast(null as bigint) as n_dropped,
        cast(null as bigint) as n_criterion_a, cast(null as bigint) as n_criterion_b
    from counts
    union all
    select 2, 'classified', 'Classificats (sense accés restringit ni errors)',
        classified, access_restricted + errors, null, null
    from counts
    union all
    select 3, 'version_marks', 'Filtre 1: 2 tags o 2 branques com a mínim',
        classified - no_version_marks, no_version_marks, null, null
    from counts
    union all
    select 4, 'tabular_files', 'Filtre 2: fitxers tabulars a la versió actual',
        classified - no_version_marks - no_tabular_files, no_tabular_files, null, null
    from counts
    union all
    select 5, 'eligible', 'Filtre 3: commits tabulars (elegibles)',
        criterion_a + criterion_b, no_tabular_commits, criterion_a, criterion_b
    from counts
)

select
    stages.stage_order,
    stages.stage,
    stages.stage_label,
    stages.n_datasets,
    stages.n_dropped,
    stages.n_criterion_a,
    stages.n_criterion_b,
    case when stages.stage_order >= 2 then stages.n_datasets / counts.classified end as share_of_classified,
    case when stages.stage_order >= 2 then {{ wilson_low('stages.n_datasets', 'counts.classified') }} end as share_low,
    case when stages.stage_order >= 2 then {{ wilson_high('stages.n_datasets', 'counts.classified') }} end as share_high
from stages
cross join counts
order by stages.stage_order
