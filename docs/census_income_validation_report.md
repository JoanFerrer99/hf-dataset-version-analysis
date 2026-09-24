# US-304 — Validació d'extractibilitat del motor de diffing (Census Income D1–D7)

> **Instantània històrica** (setembre 2026), consolidada manualment a partir de `docs/decisions_tfg.txt` (Decisions T-07, T-08, T-09, T-11) i `docs/architecture.md`. L'exercici ORIGINAL (D1–D7 vs D0, sense C410) és tancat i el seu codi d'adquisició es va eliminar deliberadament de `notebooks/change_diff.py` (Decisió T-11) -- `data/census_income_diff_report.csv`/`data/census_income_classification.csv` en són el registre permanent, mai regenerat. Des de la Decisió T-15, aquest exercici SÍ és re-validable quan calgui, via `notebooks/validate_census_income.py` -- un script permanent i aïllat del pipeline principal (vegeu "Re-validació posterior amb C410" més avall).

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

## Re-validació posterior amb C410 (Decisió T-15)

Els resultats de dalt (D1–D7 vs D0) es van obtenir ABANS d'implementar
C410 (ordre de files, Decisió T-14) -- no reflectien si el motor detecta
reordenacions de files sobre aquest ground truth. `notebooks/
validate_census_income.py` (nou script, AÏLLAT del pipeline principal --
no l'importa cap script de `eligibility_scan.py`/`version_extractor.py`/
`run_pipeline.py`, ni ell els importa a ells) reexecuta la MATEIXA
comparació D_i vs D0 amb el motor actual de `change_diff.py` (reutilitzat
sense canvis), per tancar aquest buit sense revifar codi d'adquisició
dins del mòdul principal.

**Resultat real** (`data/census_income_diff_report_2.csv` / `data/
census_income_classification_2.csv` -- re-executat un cop més a la
Decisió T-16, veure secció següent; els `codes_detected` no van canviar
entre la primera execució i aquesta, 32 etiquetes en total):

| Versió | Codis detectats (abans) | Codis detectats (amb C410) | C410 |
|---|---|---|---|
| D1 | 1 | 2 | **True** |
| D2 | 1 | 2 | **True** |
| D3 | 7 | 7 | False |
| D4 | 7 | 7 | False |
| D5 | 2 | 3 | **True** |
| D6 | 6 | 6 | False |
| D7 | 6 | 6 | False |

**C410 detecta reordenació de files en D1, D2 i D5** -- un senyal real i
plausible: a diferència de la població real (on C410 va aparèixer 0 cops
sobre 11 datasets, vegeu `docs/architecture.md`), aquí D1/D2/D5 són
repujades independents d'un dataset públic ben conegut a comptes/orgs
diferents -- exactament el tipus de context on un reordenament (p.e. un
`shuffle` en preparar l'export, o un ordre d'escriptura diferent del
`DataFrame`) és habitual, i confirma que la tècnica de hash de contingut
(vegeu `docs/taiga/taxonomy.md`, "Limitacions conegudes") funciona
correctament fora del cas sintètic amb què es va verificar originalment.

## Bug real trobat i corregit: heurística de renom (C223, Decisió T-16)

Inspeccionant directament la sortida de `diff_columns` sobre D3/D4/D6/D7
(possible gràcies a `validate_census_income.py`, T-15) es va confirmar un
bug real a l'heurística de renom ANTERIOR (posició ordinal + dtype): amb
columnes reordenades (D3/D4) o simplement amb UNA columna eliminada abans
d'una altra de renombrada (D6/D7, sense reordenar res més), l'aparellament
per posició deixa de ser fiable -- confirmat empíricament, no suposat:

```
D3, ABANS de la correcció:
  renamed = [(fnlwgt, capital_loss), (education-num, final_weight), (capital-loss, is_male)]
```

Cap d'aquests 3 parells té relació semàntica real -- són aparellaments
purament accidentals de posició+dtype (una columna eliminada anteriorment
havia desplaçat totes les posicions següents). **Corregit**: l'heurística
ara aparella per NOM NORMALITZAT (minúscules, sense separador) en lloc de
posició:

```
D3, DESPRÉS de la correcció:
  renamed = [(marital-status, marital_status), (capital-gain, capital_gain),
             (capital-loss, capital_loss), (native-country, native_country)]
```

4 renoms genuïns detectats correctament (abans es perdien, mal classificats
com a add/remove separats), zero aparellaments incorrectes. **Els
`codes_detected` no canvien** (D3/D4 segueixen a 7/7) -- el bug afectava
QUINES columnes s'atribuïen a renom vs. add/remove, no el booleà agregat
per codi. Detall complet a `docs/decisions_tfg.txt`, T-16.

**Sobre C530** (distribució, també qüestionat en la mateixa revisió):
verificat manualment que els canvis detectats a D6/D7 són REALS (p.e.
quartils d'edat 28/37/48 -> 31/40/49 a D6) -- no un bug de la tècnica. No
es pot confirmar si coincideix amb la cel·la exacta del paper (mateixa
limitació d'integritat del ground truth que la resta de codis).

## Estat i reproduïbilitat

**Exercici original tancat, d'un sol ús** (D1–D7 vs D0, sense C410) --
el codi d'adquisició es va eliminar deliberadament de `notebooks/
change_diff.py` (Decisió T-11), no viu com a codi actiu al pipeline
principal. **Re-validable, sí** (Decisió T-15): `notebooks/
validate_census_income.py` és un script permanent i aïllat -- es pot
tornar a executar quan calgui (p.e. després d'un altre canvi important al
motor de diffing) sense tocar `eligibility_scan.py`/`version_extractor.
py`/`run_pipeline.py`, numerant els seus outputs (`census_income_diff_
report_<run_id>.csv`/`census_income_classification_<run_id>.csv`) sense
sobreescriure mai els originals congelats.

Registres permanents d'aquest exercici:
1. Aquest document.
2. `data/census_income_diff_report.csv` / `data/census_income_classification.csv` (registre original, pre-C410, 30 etiquetes).
3. `data/census_income_diff_report_2.csv` / `data/census_income_classification_2.csv` (re-validació amb C410 (T-15) i l'heurística de renom corregida (T-16), 32 etiquetes -- `_1` es va generar i descartar al mig d'aquesta mateixa sessió, previ a T-16, sense diferència als `codes_detected`).
4. `notebooks/validate_census_income.py` (codi viu, reutilitzable -- l'adquisició D0-D7 ja no cal recuperar-la de l'historial de git).
