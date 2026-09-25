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

- **"% d'acord codi per codi" -- RESOLT** (vegeu "Comparativa codi per codi" més avall): Joan ha transcrit a mà la Taula 1 del paper mirant la imatge original, permetent una comparació cel·la a cel·la real (Precisió 60.6%, Recall 76.9%, F1 67.8%). La limitació d'integritat de l'extracció automàtica del PDF (que no conservava l'alineació de columnes) segueix sent certa -- només es va resoldre transcrivint-la a mà, tal com recomanava `docs/census_income_alignment_study.md`.
- **D6 (`ETdanR/adult_income`)**: l'ambigüitat de quin dels 3 fitxers correspon a la versió D6 del paper queda sense resoldre -- la sobre-detecció observada (4 FP a D6) és coherent amb haver triat un fitxer incorrecte, però no s'ha confirmat.
- **C100 fora d'abast**: cap dels totals d'aquest exercici inclou C100 (metadada/dataset card) -- el motor de diffing tabular mai el tracta (vegeu `docs/taiga/taxonomy.md`, "Limitacions conegudes").
- **C312 i C221/C322**: patrons sistemàtics reals trobats a la comparativa codi per codi (C312 mai es detecta correctament; C221/C322 es sobre-detecten) -- pendents d'investigar, vegeu la secció corresponent.

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

**Resultat real** (`data/census_income_diff_report_3.csv` / `data/
census_income_classification_3.csv`, 32 etiquetes en total). **Reproduïbilitat
verificada explícitament dues vegades**: un cop després de restaurar el
codi de T-16 (vegeu `docs/decisions_tfg.txt`, nota a T-16) i un altre cop
després d'afegir la comparativa amb el paper (T-18, secció següent) --
totes dues re-execucions de `validate_census_income.py` han produït un
`census_income_diff_report_*.csv` idèntic byte a byte al d'abans (les
còpies intermèdies, `_1.csv`/`_2.csv`, es van esborrar per no duplicar
dades sense informació nova, mantenint només `_3.csv` -- ara amb els
CSV de comparativa nous, `census_income_paper_comparison_3.csv`/`_by_
code_3.csv`, generats a la MATEIXA execució):

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

## Comparativa codi per codi (Taula 1 del paper transcrita a mà)

La limitació d'integritat del ground truth (extracció del PDF sense
alineació de columnes) es resol AQUÍ per primer cop: Joan ha transcrit a
mà, mirant la imatge original del paper, quins codis concrets marca la
Taula 1 per a cada D_i (D1-D7) -- codificat com a `notebooks/
validate_census_income.PAPER_GROUND_TRUTH` (dict de `frozenset`, un per
D_i, INCLOENT C100). Els totals per fila coincideixen EXACTAMENT amb els
ja documentats a T-08 -- confirma que la transcripció és consistent amb
el que ja se sabia dels totals agregats (verificat també a `tests/
test_validate_census_income.py::TestPaperGroundTruthConsistency`).

**Generat automàticament, no calculat a mà**: `validate_census_income.py`
ara calcula aquesta comparativa a CADA execució (funcions pures
`compare_detectability_with_paper`/`summarize_agreement_by_code`/
`compute_agreement_metrics`, sense cap crida de xarxa), i l'escriu a
`data/census_income_paper_comparison_<run_id>.csv` (per dataset) i
`data/census_income_paper_comparison_by_code_<run_id>.csv` (per codi) --
no cal tornar a transcriure-ho ni recalcular-ho a mà cada cop que el
motor de diffing canviï. Comparat contra `data/census_income_diff_
report_3.csv` (motor actual, amb C410 i l'heurística de renom corregits
-- T-14/T-16), **exclosos els codis on el paper marca `C100`** (fora
d'abast del nostre motor, mai comptat):

| Versió | Paper (15 codis) | Paper - C100 | El nostre motor | TP | FN | FP |
|---|---|---|---|---|---|---|
| D1 | 3 | 2 | 2 | 2 | 0 | 0 |
| D2 | 3 | 2 | 2 | 2 | 0 | 0 |
| D3 | 7 | 6 | 7 | 4 | 2 | 3 |
| D4 | 7 | 6 | 7 | 5 | 1 | 2 |
| D5 | 4 | 3 | 3 | 3 | 0 | 0 |
| D6 | 4 | 3 | 6 | 2 | 1 | 4 |
| D7 | 5 | 4 | 6 | 2 | 2 | 4 |
| **Total** | | **26** | | **20** | **6** | **13** |

**Precisió = 60.6% (20/33), Cobertura (recall) = 76.9% (20/26), F1 = 67.8%.**
D1/D2/D5 són coincidències EXACTES (0 FN, 0 FP).

Detall per dataset (codis exactes):
- **D1**: TP={C223,C410}
- **D2**: TP={C223,C410}
- **D3**: TP={C210,C223,C311,C422}; FN={C312,C410}; FP={C221,C222,C322}
- **D4**: TP={C210,C222,C223,C311,C422}; FN={C312}; FP={C221,C322}
- **D5**: TP={C221,C223,C410}
- **D6**: TP={C422,C530}; FN={C223}; FP={C221,C222,C312,C322}
- **D7**: TP={C222,C421}; FN={C223,C312}; FP={C221,C311,C322,C530}

Per codi (només els codis que apareixen almenys un cop en algun costat):

| Codi | TP | FN | FP | Lectura |
|---|---|---|---|---|
| C210 | 2 | 0 | 0 | Perfecte |
| C221 | 1 | 0 | 4 | Sobre-detectat (precisió 20%) |
| C222 | 2 | 0 | 2 | Precisió 50% |
| C223 | 5 | 2 | 0 | Mai un fals positiu; perd D6/D7 -- exactament els renoms SEMÀNTICS (`income`->`over_threshold` a D6/D7-estil) que l'heurística per nom normalitzat (T-16) no pot atrapar per disseny |
| C311 | 2 | 0 | 1 | Precisió 67% |
| C312 | 0 | 3 | 1 | **Mai un vertader positiu** -- els 3 cops que el paper el marca, el motor no el detecta |
| C322 | 0 | 0 | 4 | El paper mai el marca; el motor el detecta 4 cops -- 0% precisió |
| C410 | 3 | 1 | 0 | Mai un fals positiu; recall 75% |
| C421 | 1 | 0 | 0 | Perfecte |
| C422 | 3 | 0 | 0 | Perfecte |
| C530 | 1 | 0 | 1 | Precisió 50% |

**Dos patrons sistemàtics reals que val la pena investigar** (no
corregits en aquesta sessió -- registrat com a pas pendent):
1. **C312 (valors d'una columna categòrica) mai es detecta correctament**
   (0 TP, 3 FN) -- el paper el marca 3 cops (D3, D4, D7) i el motor no
   n'hi troba cap senyal. Candidat a revisar: potser el llindar actual
   de `diff_categorical_values` (canvi de CONJUNT de categories, no de
   freqüència) és massa estricte, o el paper compta canvis de categoria
   que el nostre disseny classifica com a C530 (distribució) en lloc de
   C312.
2. **C221/C322 es sobre-detecten sistemàticament** (precisió 20% i 0%
   respectivament) -- el motor hi troba senyal que el paper no confirma.
   Podria ser detecció genuïna que el paper no va anotar (revisió manual
   incompleta del propi paper), o llindars massa sensibles al nostre
   motor (`diff_numeric_values` no té llindar de sensibilitat -- qualsevol
   diferència de mitjana/std/min/max compta, per petita que sigui).

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
3. `data/census_income_diff_report_3.csv` / `data/census_income_classification_3.csv` (re-validació amb C410 (T-15) i l'heurística de renom corregida (T-16), 32 etiquetes -- `_1`/`_2` es van generar i descartar al llarg d'aquesta mateixa sessió, sense diferència als `codes_detected`).
4. `data/census_income_paper_comparison_3.csv` / `data/census_income_paper_comparison_by_code_3.csv` (comparativa codi per codi contra `PAPER_GROUND_TRUTH`, T-18 -- generats automàticament per `validate_census_income.py`, no calculats a mà).
5. `notebooks/validate_census_income.py` (codi viu, reutilitzable -- l'adquisició D0-D7 ja no cal recuperar-la de l'historial de git; cada execució regenera TOTS els CSV d'aquesta llista, punts 3-4).
