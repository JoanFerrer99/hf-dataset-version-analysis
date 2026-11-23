-- Dimensió brossa (junk) de les diferències d'una versió respecte a l'anterior:
-- una fila per combinació de codis que surt a l'execució, més tres estats que
-- hi són sempre (`first_version`, `no_changes`, `not_compared`). Té un
-- indicador per a cada nivell de la taxonomia: perspectiva (nivell 1, p.e.
-- `has_c2`), grup de dues xifres (nivell 2, `has_c22`) i codi (nivell 3,
-- `has_c221`).
{%- set codes = ['C210', 'C221', 'C222', 'C223', 'C311', 'C312', 'C321', 'C322', 'C323',
                 'C410', 'C421', 'C422', 'C510', 'C520', 'C530'] %}
{%- set groups = [] %}{%- set perspectives = [] %}
{%- for c in codes %}
  {%- if c[:3] not in groups %}{%- do groups.append(c[:3]) %}{%- endif %}
  {%- if c[:2] not in perspectives %}{%- do perspectives.append(c[:2]) %}{%- endif %}
{%- endfor %}

with observed as (
    select distinct differences
    from {{ ref('int_version_measures') }}
    union
    select unnest(['first_version', 'no_changes', 'not_compared'])
),

split as (
    select
        differences,
        case
            when differences in ('first_version', 'no_changes', 'not_compared') then differences
            else 'changed'
        end as differences_status,
        case
            when differences in ('first_version', 'no_changes', 'not_compared') then []::varchar[]
            else string_split(differences, '+')
        end as code_list
    from observed
),

named as (
    select
        split.differences,
        string_agg(distinct kinds.level_1, ', ' order by kinds.level_1) as perspectives
    from split
    cross join unnest(split.code_list) as listed(code)
    inner join {{ ref('dim_kind_of_change') }} as kinds
        on kinds.code = listed.code
    group by split.differences
)

select
    {{ surrogate_key(['split.differences']) }} as differences_key,
    split.differences,
    split.differences_status,
    len(split.code_list) as n_codes,
    named.perspectives,
    {%- for p in perspectives %}
    len(list_filter(split.code_list, c -> c like '{{ p }}%')) > 0 as has_{{ p | lower }},
    {%- endfor %}
    {%- for g in groups %}
    len(list_filter(split.code_list, c -> c like '{{ g }}%')) > 0 as has_{{ g | lower }},
    {%- endfor %}
    {%- for c in codes %}
    list_contains(split.code_list, '{{ c }}') as has_{{ c | lower }}{{ "," if not loop.last }}
    {%- endfor %}
from split
left join named
    on named.differences = split.differences
