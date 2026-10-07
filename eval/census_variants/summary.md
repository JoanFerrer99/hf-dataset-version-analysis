# Quines dades va comparar el paper (Census Income)

Generat per `eval/census_variants.py`. Errors = FP + FN contra la Taula 1 (sense C100).

## Millor variant per D0 (la millor revisió/fitxer de cada D_i)

| d0 | tp | fp | fn | precision | recall |
|---|---|---|---|---|---|
| data | 25 | 12 | 1 | 0.676 | 0.962 |
| data+test | 24 | 11 | 2 | 0.686 | 0.923 |
| data+test (amb punt) | 23 | 22 | 3 | 0.511 | 0.885 |
| test | 25 | 21 | 1 | 0.543 | 0.962 |

## Les 3 millors combinacions per versió

| version | d0 | revision | date | file | rows | tp | fp | fn | fp_codes | fn_codes |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | data | 2a7ff8e | 2022-06-20 | adult.csv | 32561 | 2 | 0 | 0 |  |  |
| D1 | data+test | 2a7ff8e | 2022-06-20 | adult.csv | 32561 | 2 | 1 | 0 | C422 |  |
| D1 | test | 2a7ff8e | 2022-06-20 | adult.csv | 32561 | 2 | 3 | 0 | C322,C421,C422 |  |
| D2 | data | c791a79 | 2023-09-21 | data/train-00000-of-00001-7e70ed54d8cbb057.parquet | 32561 | 2 | 0 | 0 |  |  |
| D2 | data+test | c791a79 | 2023-09-21 | data/train-00000-of-00001-7e70ed54d8cbb057.parquet | 32561 | 2 | 1 | 0 | C422 |  |
| D2 | test | c791a79 | 2023-09-21 | data/train-00000-of-00001-7e70ed54d8cbb057.parquet | 32561 | 2 | 3 | 0 | C322,C421,C422 |  |
| D3 | data+test | 76f8216 | 2025-10-08 | income/train.csv | 12211 | 6 | 1 | 0 | C222 |  |
| D3 | data+test | b707e93 | 2023-02-28 | adult_tr.csv | 36631 | 4 | 0 | 2 |  | C210,C312 |
| D3 | data+test | b707e93 | 2023-02-28 | adult_ts.csv | 12211 | 4 | 0 | 2 |  | C210,C312 |
| D4 | data+test | 76f8216 | 2025-10-08 | income-no race/train.csv | 12211 | 6 | 1 | 0 | C410 |  |
| D4 | data | 76f8216 | 2025-10-08 | income-no race/train.csv | 12211 | 6 | 2 | 0 | C410,C421 |  |
| D4 | test | 76f8216 | 2025-10-08 | income-no race/train.csv | 12211 | 6 | 2 | 0 | C410,C421 |  |
| D5 | data | afc71c8 | 2024-12-03 | optimized_adult_census.csv | 32561 | 3 | 0 | 0 |  |  |
| D5 | data+test | afc71c8 | 2024-12-03 | optimized_adult_census.csv | 32561 | 3 | 1 | 0 | C422 |  |
| D5 | test | afc71c8 | 2024-12-03 | optimized_adult_census.csv | 32561 | 3 | 3 | 0 | C322,C421,C422 |  |
| D6 | data+test | 780110a | 2025-05-31 | experiment_data.csv | 8968 | 3 | 3 | 0 | C222,C410,C510 |  |
| D6 | data+test | 780110a | 2025-05-31 | train_data.csv | 11208 | 3 | 3 | 0 | C222,C410,C510 |  |
| D6 | data+test | 780110a | 2025-05-31 | experiment_data.csv+train_data.csv+validation_data.csv | 22416 | 3 | 3 | 0 | C222,C410,C510 |  |
| D7 | data+test | 58b2501 | 2026-01-01 | adult_processed.csv | 45222 | 2 | 3 | 2 | C311,C422,C510 | C312,C421 |
| D7 | data | 58b2501 | 2026-01-01 | adult_processed.csv | 45222 | 3 | 4 | 1 | C311,C410,C422,C510 | C312 |
| D7 | test | 58b2501 | 2026-01-01 | adult_processed.csv | 45222 | 3 | 4 | 1 | C311,C410,C422,C510 | C312 |

## Procedència de les files de cada variant

| version | revision | date | file | rows | key_columns | in_data | in_test | in_neither |
|---|---|---|---|---|---|---|---|---|
| D1 | 2a7ff8e | 2022-06-20 | adult.csv | 32561 | age,fnlwgt,gain,loss,hours | 1.0 | 0.0 | 0.0 |
| D2 | c791a79 | 2023-09-21 | data/train-00000-of-00001-7e70ed54d8cbb057.parquet | 32561 | age,fnlwgt,gain,loss,hours | 1.0 | 0.0 | 0.0 |
| D3 | b707e93 | 2023-02-28 | adult_tr.csv | 36631 |  | nan | nan | nan |
| D3 | b707e93 | 2023-02-28 | adult_ts.csv | 12211 |  | nan | nan | nan |
| D3 | b707e93 | 2023-02-28 | adult_tr.csv+adult_ts.csv | 48842 |  | nan | nan | nan |
| D3 | ba4f505 | 2023-02-28 | adult_tr.csv | 36631 | age,fnlwgt,gain,loss,hours | 0.682 | 0.318 | 0.0 |
| D3 | ba4f505 | 2023-02-28 | adult_ts.csv | 12211 | age,fnlwgt,gain,loss,hours | 0.678 | 0.322 | 0.0 |
| D3 | ba4f505 | 2023-02-28 | adult_tr.csv+adult_ts.csv | 48842 | age,fnlwgt,gain,loss,hours | 0.681 | 0.319 | 0.0 |
| D3 | 76f8216 | 2025-10-08 | income/train.csv | 12211 | age,fnlwgt,gain,loss,hours | 0.678 | 0.322 | 0.0 |
| D4 | b707e93 | 2023-02-28 | adult_tr.csv | 36631 |  | nan | nan | nan |
| D4 | b707e93 | 2023-02-28 | adult_ts.csv | 12211 |  | nan | nan | nan |
| D4 | b707e93 | 2023-02-28 | adult_tr.csv+adult_ts.csv | 48842 |  | nan | nan | nan |
| D4 | ba4f505 | 2023-02-28 | adult_tr.csv | 36631 | age,fnlwgt,gain,loss,hours | 0.682 | 0.318 | 0.0 |
| D4 | ba4f505 | 2023-02-28 | adult_ts.csv | 12211 | age,fnlwgt,gain,loss,hours | 0.678 | 0.322 | 0.0 |
| D4 | ba4f505 | 2023-02-28 | adult_tr.csv+adult_ts.csv | 48842 | age,fnlwgt,gain,loss,hours | 0.681 | 0.319 | 0.0 |
| D4 | 76f8216 | 2025-10-08 | income-no race/train.csv | 12211 | age,fnlwgt,gain,loss,hours | 0.678 | 0.322 | 0.0 |
| D5 | afc71c8 | 2024-12-03 | optimized_adult_census.csv | 32561 | age,fnlwgt,gain,loss,hours | 1.0 | 0.0 | 0.0 |
| D6 | 780110a | 2025-05-31 | experiment_data.csv | 8968 | age,gain,loss,hours | 0.954 | 0.046 | 0.0 |
| D6 | 780110a | 2025-05-31 | train_data.csv | 11208 | age,gain,loss,hours | 0.953 | 0.047 | 0.0 |
| D6 | 780110a | 2025-05-31 | validation_data.csv | 2240 | age,gain,loss,hours | 0.953 | 0.047 | 0.0 |
| D6 | 780110a | 2025-05-31 | experiment_data.csv+train_data.csv+validation_data.csv | 22416 | age,gain,loss,hours | 0.953 | 0.047 | 0.0 |
| D7 | 58b2501 | 2026-01-01 | adult_processed.csv | 45222 | age,fnlwgt,gain,loss,hours | 0.681 | 0.319 | 0.0 |
