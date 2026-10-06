# Avaluació del motor de detecció de canvis

Conjunt: **heldout** (379 casos, generats per `eval/mutations.py`). Mètriques per codi a nivell de cas; un codi permès com a efecte secundari no compta com a FP.

## Precisió / recall / F1 per codi

| Codi | Suport | old P | old R | old F1 | new P | new R | new F1 |
|---|---|---|---|---|---|---|---|
| C210 | 11 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| C221 | 26 | 0.46 | 1.00 | 0.63 | 1.00 | 1.00 | 1.00 |
| C222 | 24 | 0.46 | 1.00 | 0.63 | 1.00 | 1.00 | 1.00 |
| C223 | 20 | — | 0.00 | — | 1.00 | 1.00 | 1.00 |
| C311 | 25 | 1.00 | 0.52 | 0.68 | 1.00 | 1.00 | 1.00 |
| C312 | 103 | 0.94 | 0.74 | 0.83 | 1.00 | 0.99 | 1.00 |
| C321 | 19 | 0.20 | 1.00 | 0.34 | 1.00 | 1.00 | 1.00 |
| C322 | 85 | 0.91 | 0.79 | 0.84 | 1.00 | 1.00 | 1.00 |
| C410 | 25 | 1.00 | 0.48 | 0.65 | 1.00 | 1.00 | 1.00 |
| C421 | 54 | 0.87 | 0.63 | 0.73 | 1.00 | 1.00 | 1.00 |
| C422 | 89 | 0.93 | 0.80 | 0.86 | 0.97 | 1.00 | 0.98 |
| C510 | 45 | 0.47 | 1.00 | 0.64 | 1.00 | 1.00 | 1.00 |
| C520 | 10 | 0.50 | 1.00 | 0.67 | 1.00 | 1.00 | 1.00 |
| C530 | 24 | 0.34 | 1.00 | 0.51 | 1.00 | 0.96 | 0.98 |

## Casos d'una sola mutació resolts del tot

Un cas és correcte si surten tots els codis requerits i cap de no permès.

| Mutació | old | new |
|---|---|---|
| add_column_derived | 6/6 | 6/6 |
| add_column_unexplained | 6/6 | 6/6 |
| add_rows_duplicate | 3/6 | 6/6 |
| add_rows_new | 1/6 | 6/6 |
| cat_anonymize | 6/6 | 6/6 |
| cat_cell_edits | 0/6 | 6/6 |
| cat_merge | 6/6 | 6/6 |
| cat_new_categories | 6/6 | 6/6 |
| cat_relabel | 6/6 | 6/6 |
| cat_split | 6/6 | 6/6 |
| cat_whitespace | 6/6 | 6/6 |
| categorical_to_codes | 6/6 | 6/6 |
| csv_to_parquet | 1/6 | 6/6 |
| flip_labels_subgroup | 0/6 | 6/6 |
| identical | 6/6 | 6/6 |
| impute_constant | 6/6 | 6/6 |
| inject_nulls | 2/6 | 6/6 |
| int_gains_nan | 0/6 | 6/6 |
| int_to_float_same_values | 0/6 | 6/6 |
| missing_token_change | 0/5 | 5/5 |
| num_cell_edits | 2/6 | 6/6 |
| num_factor | 0/6 | 6/6 |
| num_log | 0/6 | 6/6 |
| num_minmax | 0/6 | 6/6 |
| num_perturb | 2/6 | 6/6 |
| num_scientific_notation | 0/2 | 2/2 |
| num_standardize | 0/6 | 6/6 |
| numeric_to_bins | 6/6 | 6/6 |
| one_hot | 0/6 | 6/6 |
| oversample_minority | 3/6 | 6/6 |
| permute_column | 0/6 | 6/6 |
| real_to_integer | 3/3 | 3/3 |
| remove_by_predicate | 3/6 | 6/6 |
| remove_column | 6/6 | 6/6 |
| remove_column_mostly_null | 6/6 | 6/6 |
| remove_one_duplicate | 3/6 | 6/6 |
| remove_outliers | 2/5 | 5/5 |
| remove_rows_random | 3/6 | 6/6 |
| remove_rows_with_nulls | 6/6 | 6/6 |
| rename_identical | 0/6 | 6/6 |
| rename_recode | 0/6 | 6/6 |
| replace_rows | 0/6 | 6/6 |
| resave_quoting_crlf | 4/4 | 4/4 |
| shuffle_rows | 6/6 | 6/6 |
| sort_rows | 6/6 | 6/6 |
| swap_columns | 6/6 | 6/6 |
| undersample_majority | 3/6 | 6/6 |

## Confusions més freqüents (old)

Codi requerit no detectat → codi no permès detectat al mateix cas.

| Requerit | Detectat en lloc seu | Casos |
|---|---|---|
| C223 | C221 | 18 |
| C223 | C222 | 16 |
| C311 | C221 | 12 |
| C311 | C222 | 12 |
| C312 | C221 | 10 |
| C421 | C510 | 9 |
| C422 | C510 | 8 |
| C312 | C222 | 6 |
| C421 | C520 | 6 |
| C422 | C520 | 5 |
| C223 | C530 | 4 |
| C422 | C321 | 4 |

## Confusions més freqüents (new)

Codi requerit no detectat → codi no permès detectat al mateix cas.

| Requerit | Detectat en lloc seu | Casos |
|---|---|---|
| — | — | — |

## Subtipus (new, casos d'una sola mutació)

| Codi | Subtipus | Encerts |
|---|---|---|
| C221 | derived | 6/6 |
| C221 | unexplained | 6/6 |
| C222 | mostly_null | 6/6 |
| C222 | unexplained | 6/6 |
| C311 | one_hot | 6/6 |
| C311 | to_numeric | 6/6 |
| C312 | anonymization | 6/6 |
| C312 | cell_edits | 18/18 |
| C312 | merge | 6/6 |
| C312 | relabel | 12/12 |
| C312 | representation | 6/6 |
| C312 | split | 6/6 |
| C321 | real_to_integer | 3/3 |
| C321 | to_categorical | 6/6 |
| C322 | cell_edits | 12/12 |
| C322 | factor | 6/6 |
| C322 | log | 6/6 |
| C322 | minmax | 6/6 |
| C322 | perturbation | 6/6 |
| C322 | representation | 2/2 |
| C322 | standardization | 6/6 |
| C410 | sorted_by | 6/6 |
| C421 | duplicate_of_existing | 12/12 |
| C421 | new | 12/12 |
| C422 | duplicate_removed | 6/6 |
| C422 | had_nulls | 6/6 |
| C422 | outlier | 5/5 |
| C422 | predicate | 3/6 |
| C510 | imputed_constant | 6/6 |
| C510 | masking | 12/12 |
| C510 | representation | 5/5 |
