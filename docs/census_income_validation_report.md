# US-304 — Validació d'extractibilitat del motor de diffing (Census Income D1–D7)

> **Instantània històrica congelada**, consolidada manualment (setembre 2026) a partir de `docs/decisions_tfg.txt` (Decisions T-07, T-08, T-09, T-11) i `docs/architecture.md`. El codi que va generar aquests resultats (`CENSUS_INCOME_SOURCES`, `download_uci_adult_baseline`, `download_census_income_version`, `build_detectability_report`, `run_validation`, `run_census_income_classification`, `summarize_agreement`) es va **eliminar deliberadament** de `notebooks/change_diff.py` (Decisió T-11) un cop la pregunta que responia va quedar contestada. Aquest document, junt amb `data/census_income_diff_report.csv` i `data/census_income_classification.csv` (totes dues fitxers tracked a git), és el **registre permanent** d'aquest exercici -- no es regenera a cap execució, i **no cal tornar-lo a córrer**.

## Abast: D1–D7, no D1–D9

El ground truth del paper del director defineix 9 versions (D1–D9) del dataset UCI Adult / Census Income, cadascuna comparada contra l'original D0. D'aquestes, **només D1–D7 són repositoris de Hugging Face**:

| Versió | Font | Dins l'abast? |
|---|---|---|
| D0 (baseline) | UCI Machine Learning Repository (`archive.ics.uci.edu/dataset/2/adult`) | Sí (baseline, no compta com a codi) |
| D1–D7 | Repositoris independents a Hugging Face | **Sí** |
| D8 | Registre de Zenodo (12533514) | No |
| D9 | `AdultDataset` d'AIF360 (llibreria Python, baixa de l'UCI archive, no és un repositori) | No |

D8/D9 requeririen 2 connectors únics (Zenodo API + AIF360/UCI) per a només 2/9 files del ground truth, sense cap reutilitat per a la resta del projecte (la població real mostrejada prové exclusivament d'HF) -- es documenten com a fora d'abast, no com una limitació temporal (vegeu Decisió T-07).

**D1–D7 són repositoris INDEPENDENTS entre si** (comptes/orgs diferents), no commits/tags successius d'un mateix repo -- a diferència del que `eligibility_scan.py`/`version_extractor.py` detecten sobre la població real (versions dins d'UN mateix repositori). El paper compara cada D_i contra l'original D0, no D_i contra D_{i-1}.

## Metodologia

El motor de diffing (8 funcions pures en aquell moment: `diff_columns`, `diff_column_types`, `diff_categorical_values`, `diff_numeric_values`, `diff_row_count`, `diff_missingness`, `diff_correlation`, `diff_distribution`, cadascuna prenent dos `DataFrame` sense saber res d'HF/HTTP/codis) va comparar cada D_i (i=1..7) contra D0, comptant quants dels 14 codis tabulars (tot excepte C100) mostraven algun senyal -- sense encara assignar-hi el codi exacte (aquesta part, disseny agnòstic d'adquisició, és la que permet reutilitzar el mateix motor sense canvis sobre la població real).

**Integritat del ground truth**: la Taula 1 del paper es va extreure d'un PDF que NO conserva l'alineació de columnes d'una taula amb marques "✔" -- només els totals per fila es poden llegir amb fiabilitat. La comparació d'aquest exercici és per TOTAL agregat per dataset, mai codi per codi.

## Resultats de detectabilitat (D_i vs D0)

Sortida completa: `data/census_income_diff_report.csv`.

| Versió | Codis amb senyal (el nostre motor) | Total de fila del paper |
|---|---|---|
| D1 | 1 | 3 |
| D2 | 1 | 3 |
| D3 | **7** | **7** |
| D4 | **7** | **7** |
| D5 | 2 | 4 |
| D6 | 6 | 4 |
| D7 | 6 | 5 |

**Lectura honesta** (no és una mètrica de precisió -- els totals del paper inclouen C100, fora de l'abast tabular d'aquest motor):
- **D3/D4 encaixen exactament** amb el total del paper (7/7 els dos) -- bon senyal que el motor funciona correctament quan el fitxer font és net i comparable directament amb la UCI.
- **D1/D2/D5 per sota** del total del paper -- esperat en part (el motor no intenta C100), però probablement també hi ha canvis subtils que els llindars actuals (5% de canvi relatiu/absolut a `diff_distribution`/`diff_correlation`) no capten.
- **D6 clarament per sobre** (6 detectats vs 4 del paper) -- confirma una ambigüitat detectada en aquell moment: el repo `ETdanR/adult_income` té 3 fitxers (`experiment_data.csv`, `train_data.csv`, `validation_data.csv`) i el paper no especifica quin -- es va triar `train_data.csv` sense confirmació. Aquest resultat suggereix que probablement NO és el fitxer correcte.
- **D7 una mica per sobre** (6 vs 5) -- podria ser el mateix efecte de llindars massa sensibles, o que el paper tampoc compta C100 al seu total.

## Resultats de classificació

Un cop construït el classificador (US-305, reutilitzant el mateix motor sense reimplementar-lo), es va executar de nou sobre D1–D7: **`data/census_income_classification.csv`, 30 etiquetes de canvi** -- mateixos totals que la taula de detectabilitat anterior (esperat, mateix motor, ara amb etiquetes `(dataset_id, version_from, version_to, code, is_breaking)` reals).

## Limitacions

- **"% d'acord codi per codi" mai resolt**: l'extracció del PDF del paper no conserva l'alineació de columnes de la Taula 1 amb marques "✔" -- només els totals per fila/columna són fiables. La comparació d'aquest exercici és per total agregat per dataset, no codi per codi. No és una limitació resoluble sense accedir a una font del paper amb estructura de taula preservada (p.e. el dataset original de l'autor, si existeix).
- **D6 (`ETdanR/adult_income`)**: l'ambigüitat de quin dels 3 fitxers correspon a la versió D6 del paper queda sense resoldre -- la sobre-detecció observada (6 vs 4) és coherent amb haver triat un fitxer incorrecte, però no s'ha confirmat.
- **C100 fora d'abast**: cap dels totals d'aquest exercici inclou C100 (metadada/dataset card) -- el motor de diffing tabular mai el tracta (vegeu `docs/taiga/taxonomy.md`, "Limitacions conegudes").

## Estat i reproduïbilitat

**Exercici tancat, d'un sol ús.** El codi d'adquisició/informe (D0–D7) es va eliminar deliberadament de `notebooks/change_diff.py` (Decisió T-11) -- no viu com a codi actiu al projecte. Els registres permanents d'aquest exercici són:
1. Aquest document.
2. `data/census_income_diff_report.csv` (detall per codi, `C210`...`C530`).
3. `data/census_income_classification.csv` (30 etiquetes de canvi).

Si mai calgués tornar a córrer aquest exercici (p.e. per validar un canvi important al motor de diffing), el codi d'adquisició es pot recuperar de l'historial de git: `git show ab62d07 -- notebooks/change_diff.py` (commit on es va introduir originalment). El motor de diffing en si (`diff_*`/`compute_all_diffs`, incloent `diff_row_order`/C410 afegit a la Decisió T-14, posterior a aquest exercici) es manté viu i es reutilitza sense canvis sobre la població real -- vegeu `docs/architecture.md`, "Resultats reals — classificació sobre la població elegible".
