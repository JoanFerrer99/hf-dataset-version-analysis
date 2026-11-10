-- La freqüència de cada codi és el seu nombre de files a fact_change. Retorna els codis que no quadren.

with facts as (
    select kinds.code, count(*) as n_rows
    from {{ ref('fact_change') }} as facts
    inner join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.kind_key = facts.kind_key
    group by kinds.code
)

select frequency.code, frequency.n_changes, facts.n_rows
from {{ ref('mart_code_frequency') }} as frequency
left join facts
    on facts.code = frequency.code
where frequency.n_changes <> coalesce(facts.n_rows, 0)
