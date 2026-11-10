# El magatzem de dades (Fase 3)

Un fitxer DuckDB construït amb dbt a partir d'una carpeta `data/run_<id>/`.
Les eines i les versions són a `docs/decisions_tfg.txt` (T-29).

```
bronze  data/run_<id>/*.csv, funnel_summary.json        el que escriu el pipeline (no es toca mai)
  │     warehouse/models/staging/_sources.yml           es llegeix com a text
  ▼
silver  warehouse/models/staging/stg_*.sql              vistes: tipus, noms en snake_case, cap filtre
  ▼
gold    warehouse/models/marts/core/                    esquema en estrella (taules)
        warehouse/models/marts/analysis/                marts de consulta (taules)
```

La interfície i les figures només llegeixen la capa gold.

## Com es regenera

Des de l'arrel del repositori:

```bash
# Execució real (p.e. la de referència, run_9; T-30)
WAREHOUSE_PATH=data/warehouse/run_9.duckdb \
  dbt build --project-dir warehouse --profiles-dir warehouse --vars '{run_dir: data/run_9}'

# Fixture sintètica de la CI (per defecte; el fitxer va a warehouse/hf_changes.duckdb)
dbt build --project-dir warehouse --profiles-dir warehouse
```

- `run_dir` (variable dbt): la carpeta de l'execució. Per defecte,
  `tests/fixtures/run_sample/`.
- `census_dir` (variable dbt): la validació de Census Income. Per defecte,
  `data/census_income/run_2/`.
- `WAREHOUSE_PATH` (variable d'entorn): on es desa el fitxer `.duckdb`. Els
  `.duckdb` no van a git.
- `dbt build` fa els models i els tests alhora. `dbt docs generate` en fa
  la documentació i el graf de llinatge.

Les vistes de staging llegeixen els CSV amb rutes relatives a l'arrel del
repositori: només funcionen consultades des d'allà. Les taules de la capa
gold porten les dades a dins i es poden obrir des de qualsevol lloc.

## Capa silver (staging)

Una vista per fitxer de bronze. Tots els CSV es llegeixen com a text i el
tipus de cada columna es posa aquí; les dates amb zona passen a UTC.

| Model | Origen | Gra |
|---|---|---|
| `stg_eligibility_report` | `eligibility_report.csv` | Un dataset de la mostra. Afegeix `eligibility_outcome`: el motiu com a codi (`A`, `B`, `no_version_marks`, `no_tabular_files`, `no_tabular_commits`). |
| `stg_funnel_summary` | `funnel_summary.json` | Una sola fila. |
| `stg_versions` | `versions.csv` | Una versió d'un dataset. |
| `stg_change_classification` | `change_classification.csv` | Un codi en una taula entre dues versions. `table` passa a `table_name`. |
| `stg_comparison_status` | `comparison_status.csv` | Un parell de taules entre dues versions, també sense codis. |
| `stg_failures` | `failures.csv` | Una fallada. Buit si l'execució no en va tenir (el fitxer no existeix). |
| `stg_census_validation` | `data/census_income/run_<id>/paper_comparison_by_code.csv` | Un codi: encerts, falsos negatius i falsos positius contra el paper. |

Les execucions d'abans de T-25 (com run_9) no tenen `num_data_files`,
`tabular_file_share`, `created_at`, `license` ni `downloads`: surten buides
(macro `optional_column`).

## Esquema en estrella (gold)

**Gra de `fact_change`:** un codi de la taxonomia detectat en una taula,
entre dues versions consecutives d'un dataset. És una fila de
`change_classification.csv`.

Les claus subrogades són l'md5 de la clau natural (macro `surrogate_key`).
El fet les calcula de les mateixes columnes que les dimensions, de manera
que s'uneixen sense cap taula intermèdia.

| Model | Clau natural | Columnes |
|---|---|---|
| `fact_change` | dataset, versió antiga, versió nova, taula, codi | `change_key`; claus `dataset_key`, `kind_key`, `table_key`, `version_from_key`, `version_to_key`, `date_key` (dia de la versió nova); degenerades `run_id`, `description`; mesures `change_count` (= 1), `age_days` (dies des de la creació del dataset; buit si no se sap) |
| `dim_dataset` | `dataset_id` | `dataset_key`, `owner`, `eligibility_criterion` (A/B), `num_tags`, `num_branches`, `num_tabular_commits`, `num_data_files`, `tabular_file_share`, `created_at`, `license`, `downloads`, `snapshot_date` (dia de l'execució). Només els elegibles. |
| `dim_version` | `dataset_id`, `commit_sha` | `version_key`, `version_label`, `version_order`, `version_source` (`tag`, `commit_session`, o `commit` si només surt a les comparacions), `commit_date`. Fa dos rols al fet: *from* i *to*. Dos tags al mateix commit són una sola versió. |
| `dim_table` | `dataset_id`, `table_path` | `table_key`, `format` (extensió de la taula o del seu primer fitxer) |
| `dim_date` | `date` | `date_key` (AAAAMMDD), `year`, `quarter`, `year_quarter` (p.e. 2025-T1), `month`, `weekday` (1 = dilluns). Només els dies amb alguna versió. |
| `dim_kind_of_change` | `code` | `kind_key`, `name`, `perspective` (categoria del paper), `level_1` a `level_3` (les xifres del codi), `is_breaking` |

`is_breaking` és a la dimensió perquè només depèn del codi.

## Tests

- Staging: `not_null` i unicitat de les claus naturals, `accepted_values`
  dels codis (els 14) i dels estats.
- Estrella: `unique` i `not_null` a cada clau primària, `relationships` de
  cada clau forana de `fact_change` (també els dos rols de `dim_version`), i
  `accepted_values` a `is_breaking`.
- Conciliació amb el que va escriure el pipeline (`warehouse/tests/reconcile_*.sql`)
  i coherència dels marts (`assert_*.sql`): resultat a `docs/validacio_magatzem.md`.
- `tests/test_warehouse_seed.py` comprova que la seed diu el mateix que el
  motor, i `tests/test_run_sample_fixture.py`, que la fixture és el que
  escriu el pipeline.

## Limitacions

- `file_path` uneix els fitxers d'una taula amb comes, i alguns noms de
  fitxer en tenen (p.e. `pulsia/fr-bench-pdf2md`). Per això el format de
  `dim_table` surt primer del nom de la taula.
- run_9 no té la data de creació dels datasets: `age_days` és buit (T-30).
