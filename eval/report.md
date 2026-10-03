# Avaluació del motor de detecció de canvis

Conjunt: **heldout** (380 casos, generats per `eval/mutations.py`). Mètriques per codi a nivell de cas; un codi permès com a efecte secundari no compta com a FP.

## Precisió / recall / F1 per codi

| Codi | Suport | old P | old R | old F1 |
|---|---|---|---|---|
| C210 | 11 | 1.00 | 1.00 | 1.00 |
| C221 | 26 | 0.46 | 1.00 | 0.63 |
| C222 | 24 | 0.46 | 1.00 | 0.63 |
| C223 | 20 | — | 0.00 | — |
| C311 | 25 | 1.00 | 0.44 | 0.61 |
| C312 | 103 | 0.94 | 0.73 | 0.82 |
| C321 | 19 | 0.21 | 1.00 | 0.35 |
| C322 | 85 | 0.92 | 0.76 | 0.83 |
| C410 | 25 | 1.00 | 0.48 | 0.65 |
| C421 | 54 | 0.86 | 0.59 | 0.70 |
| C422 | 90 | 0.94 | 0.80 | 0.86 |
| C510 | 56 | 0.53 | 1.00 | 0.69 |
| C520 | 10 | 0.45 | 1.00 | 0.62 |
| C530 | 35 | 0.42 | 0.91 | 0.58 |

## Casos d'una sola mutació resolts del tot

Un cas és correcte si surten tots els codis requerits i cap de no permès.

| Mutació | old |
|---|---|
| add_column_derived | 6/6 |
| add_column_unexplained | 6/6 |
| add_rows_duplicate | 3/6 |
| add_rows_new | 1/6 |
| cat_anonymize | 6/6 |
| cat_cell_edits | 0/6 |
| cat_merge | 6/6 |
| cat_new_categories | 6/6 |
| cat_relabel | 6/6 |
| cat_split | 6/6 |
| cat_whitespace | 6/6 |
| categorical_to_codes | 6/6 |
| csv_to_parquet | 1/6 |
| flip_labels_subgroup | 0/6 |
| identical | 6/6 |
| impute_constant | 6/6 |
| inject_nulls | 2/6 |
| int_gains_nan | 0/6 |
| int_to_float_same_values | 0/6 |
| missing_token_change | 0/5 |
| num_cell_edits | 1/6 |
| num_factor | 0/6 |
| num_log | 0/6 |
| num_minmax | 0/6 |
| num_perturb | 2/6 |
| num_scientific_notation | 0/2 |
| num_standardize | 0/6 |
| numeric_to_bins | 6/6 |
| one_hot | 0/6 |
| oversample_minority | 3/6 |
| permute_column | 0/6 |
| real_to_integer | 3/3 |
| remove_by_predicate | 3/6 |
| remove_column | 6/6 |
| remove_column_mostly_null | 6/6 |
| remove_one_duplicate | 3/6 |
| remove_outliers | 2/5 |
| remove_rows_random | 3/6 |
| remove_rows_with_nulls | 6/6 |
| rename_identical | 0/6 |
| rename_recode | 0/6 |
| replace_rows | 0/6 |
| resave_quoting_crlf | 4/4 |
| shuffle_rows | 6/6 |
| sort_rows | 6/6 |
| swap_columns | 6/6 |
| undersample_majority | 3/6 |

## Confusions més freqüents (old)

Codi requerit no detectat → codi no permès detectat al mateix cas.

| Requerit | Detectat en lloc seu | Casos |
|---|---|---|
| C223 | C221 | 18 |
| C223 | C222 | 16 |
| C311 | C222 | 12 |
| C311 | C221 | 12 |
| C312 | C221 | 10 |
| C421 | C510 | 10 |
| C422 | C510 | 7 |
| C312 | C222 | 6 |
| C421 | C520 | 6 |
| C422 | C520 | 5 |
| C223 | C530 | 4 |
| C421 | C321 | 4 |
