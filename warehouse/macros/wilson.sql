{#
  Interval de Wilson al 95% d'una proporció k/n (z = 1,96). Buit si n = 0.
#}
{% macro wilson_low(k, n, z=1.96) %}
  case when {{ n }} > 0 then
    (({{ k }}) / ({{ n }}) + {{ z }}^2 / (2 * ({{ n }}))
      - {{ z }} * sqrt(({{ k }}) / ({{ n }}) * (1 - ({{ k }}) / ({{ n }})) / ({{ n }}) + {{ z }}^2 / (4 * ({{ n }})^2)))
    / (1 + {{ z }}^2 / ({{ n }}))
  end
{%- endmacro %}

{% macro wilson_high(k, n, z=1.96) %}
  case when {{ n }} > 0 then
    (({{ k }}) / ({{ n }}) + {{ z }}^2 / (2 * ({{ n }}))
      + {{ z }} * sqrt(({{ k }}) / ({{ n }}) * (1 - ({{ k }}) / ({{ n }})) / ({{ n }}) + {{ z }}^2 / (4 * ({{ n }})^2)))
    / (1 + {{ z }}^2 / ({{ n }}))
  end
{%- endmacro %}
