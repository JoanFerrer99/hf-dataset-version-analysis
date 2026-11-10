{#
  Cap combinació de `columns` es repeteix al model (la clau natural d'un model
  de més d'una columna). Sense paquets externs.
#}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
