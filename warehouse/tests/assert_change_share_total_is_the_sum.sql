-- La fila `all` de mart_change_share és la suma dels criteris. Retorna-la si no quadra.

with criteria as (
    select
        sum(n_compared_units) as n_compared_units,
        sum(n_units_with_change) as n_units_with_change
    from {{ ref('mart_change_share') }}
    where criterion <> 'all'
)

select total.criterion
from {{ ref('mart_change_share') }} as total
cross join criteria
where total.criterion = 'all'
  and (total.n_compared_units <> criteria.n_compared_units
       or total.n_units_with_change <> criteria.n_units_with_change)
