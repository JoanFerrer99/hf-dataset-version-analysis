-- La freqüència de cada codi és el nombre de versions de fact_version que el
-- tenen a dim_differences. Retorna els codis que no quadren.

with facts as (
    select code, count(*) as n_rows
    from (
        select unnest(string_split(differences.differences, '+')) as code
        from {{ ref('fact_version') }} as versions
        inner join {{ ref('dim_differences') }} as differences
            on differences.differences_key = versions.differences_key
        where differences.differences_status = 'changed'
    )
    group by code
)

select frequency.code, frequency.n_changes, facts.n_rows
from {{ ref('mart_code_frequency') }} as frequency
left join facts
    on facts.code = frequency.code
where frequency.n_changes <> coalesce(facts.n_rows, 0)
