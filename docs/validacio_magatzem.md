# Conciliació del magatzem amb l'execució de referència

Comprovació que el magatzem (`docs/warehouse.md`) diu el mateix que els
fitxers que va escriure el pipeline, amb l'execució de referència, run_9
(decisió T-30).

- Execució: `data/run_9/`
- Magatzem: `python src/build_warehouse.py --run-dir data/run_9`
  (`data/warehouse/run_9.duckdb`), amb dbt-core 1.12.6, dbt-duckdb 1.11.1 i
  DuckDB 1.5.6.

## Resultat

`dbt build`: **109 de 109 correctes**, 0 avisos i 0 errors. Són 21 models, 1
seed i 87 tests: 78 genèrics (claus, relacions i valors admesos) i 9
singulars (5 de coherència dels marts i les 4 conciliacions de sota).

| # | Conciliació | Test | Resultat a run_9 |
|---|---|---|---|
| 1 | `fact_change` té tantes files com `change_classification.csv`, i són les mateixes | `reconcile_fact_change_with_classification` | 1.868 = 1.868; 0 files només a un costat, comparant la clau natural (dataset, versions, taula i codi) en els dos sentits |
| 2 | Elegibles + no elegibles + inaccessibles + errors = mida de la mostra | `reconcile_funnel_totals_with_sample` | 8 + 1.895 + 89 + 8 = 2.000. El report té 2.000 files i els mateixos recomptes per estat i per criteri (A: 4, B: 4); `mart_funnel` diu el mateix |
| 3 | Cada dataset de `fact_change` és elegible a `eligibility_report.csv` | `reconcile_changed_datasets_are_eligible` | Els 3 datasets amb canvis són elegibles |
| 4 | Cap codi fora dels 14 de la taxonomia | `reconcile_codes_are_in_the_taxonomy` | 10 codis diferents, tots de la taxonomia |
| 5 | Els hash de `data/reference_run.json` coincideixen | — | No s'aplica: l'execució de referència no es congela (T-30) |

Altres comprovacions de coherència que també passen:

- Cada parell de versions comparat (52 comparacions, 15.435 parells de
  taules) és una unitat de `mart_change_units`, amb els mateixos codis que
  `change_classification.csv` (`assert_change_units_cover_every_comparison`).
- La freqüència de cada codi a `mart_code_frequency` és el seu nombre de
  files a `fact_change` (`assert_code_frequency_matches_fact`).
- Els passos de `mart_funnel` sumen (`assert_funnel_stages_add_up`) i la fila
  total de `mart_breaking_share` és la suma dels criteris
  (`assert_breaking_share_total_is_the_sum`).
- Totes les proporcions són entre 0 i 1, i dins del seu interval de Wilson
  (`assert_shares_are_proportions`).

## Que els tests fallen quan toca

Cada conciliació s'ha provat amb una còpia de la fixture sintètica
(`tests/fixtures/run_sample/`) amb un error introduït a propòsit:

| Error introduït | Tests que fallen |
|---|---|
| Un canvi d'un dataset no elegible | 1 i 3 (i la relació de `fact_change` amb `dim_dataset`) |
| Un codi que no existeix (C999) | 1 i 4 (i `accepted_values` de staging) |
| Un recompte d'errors canviat a `funnel_summary.json` | 2, amb les dues comprovacions que no quadren |
| Un codi de més que `comparison_status.csv` no compta | `assert_change_units_cover_every_comparison` |

## Com es torna a fer

```bash
python src/build_warehouse.py --run-dir data/run_9   # models i tests; surt amb error si en falla algun
```

La CI fa el mateix amb la fixture sintètica a cada push.
