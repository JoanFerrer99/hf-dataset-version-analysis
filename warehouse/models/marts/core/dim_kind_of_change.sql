-- Dimensió dels tipus de canvi: els 14 codis de la taxonomia (seed), un per fila.

with taxonomy as (
    select
        code,
        name,
        perspective,
        level_1,
        level_2,
        level_3,
        is_breaking
    from {{ ref('taxonomy') }}
)

select
    {{ surrogate_key(['code']) }} as kind_key,
    code,
    name,
    perspective,
    level_1,
    level_2,
    level_3,
    is_breaking
from taxonomy
