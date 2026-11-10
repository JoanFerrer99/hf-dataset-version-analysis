{% macro surrogate_key(columns) %}
  {#- Clau subrogada: md5 de les columnes de la clau natural, unides per `|`. Sense paquets externs. -#}
  md5(concat_ws('|', {% for column in columns %}coalesce(cast({{ column }} as varchar), ''){{ ", " if not loop.last }}{% endfor %}))
{%- endmacro %}
