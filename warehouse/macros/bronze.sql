{#
  Ajuts per llegir la capa bronze (una carpeta data/run_<id>/).
#}

{% macro bronze_columns(relation) %}
  {#- Les columnes que té de debò un fitxer de bronze. Fa falta perquè les
      execucions d'abans de T-25 no tenen totes les columnes del report. En
      compilar sense executar, les dona totes per presents. -#}
  {%- if not execute -%}
    {{ return(none) }}
  {%- endif -%}
  {%- set described = run_query("describe select * from " ~ relation) -%}
  {{ return(described.columns[0].values() | list) }}
{% endmacro %}


{% macro optional_column(present, name, expression, sql_type) %}
  {#- `expression` si la columna `name` és al fitxer, o un nul del tipus `sql_type`. -#}
  {%- if present is none or name in present -%}
    {{ expression }}
  {%- else -%}
    cast(null as {{ sql_type }})
  {%- endif -%}
{% endmacro %}


{% macro bronze_file_exists(filename) %}
  {#- Si el fitxer és a la carpeta de l'execució. failures.csv només hi és si hi ha hagut fallades. -#}
  {%- if not execute -%}
    {{ return(true) }}
  {%- endif -%}
  {%- set found = run_query("select count(*) from glob('" ~ var('run_dir') ~ "/" ~ filename ~ "')") -%}
  {{ return(found.columns[0].values()[0] > 0) }}
{% endmacro %}


{% macro to_utc(column) %}
  {#- Data ISO 8601 amb zona (p.e. +00:00) a timestamp en UTC, sense dependre de la zona de la sessió. -#}
  timezone('UTC', cast({{ column }} as timestamptz))
{% endmacro %}
