# Com va identificar i etiquetar els canvis el paper (Census Income)

Anàlisi de la Taula 1 del paper (`paper.pdf`, PROFES 2026, §5) per saber
amb quines dades es va fer i amb quin criteri, i per què el motor no hi
coincideix del tot. Experiment: `eval/census_variants.py` (resultats a
`eval/census_variants/`). Validació: `notebooks/validate_census_income.py`.

---

## 1. Què diu el paper del mètode

- **Dades.** Només dona la URL de cada versió (notes 1–8): la pàgina de
  la UCI per a D0 i el repositori (o carpeta) de Hugging Face per a D1–D7.
  No diu quin fitxer, quin split, quina revisió ni quina part de la UCI.
- **Etiquetatge.** "The changes were identified by combining information
  provided in the corresponding repositories (e.g., dataset cards when
  available) with a manual inspection of the datasets. Repository
  documentation was used to identify explicitly documented modifications,
  while manual analysis enabled the detection of additional changes that
  were not explicitly reported."
- **Definicions (§4).** Cada codi és un canvi *elemental*, i diversos poden
  aparèixer alhora: "if the percentage of missing values of a column
  changes, most probably also its values distribution will". Els canvis de
  dades (C510/C520/C530) "can be a consequence of the addition/removal of
  rows. However, we consider them separately".

## 2. Quines dades va comparar (experiment)

Per a cada versió s'han provat totes les definicions possibles:

- **D0:** `adult.data`, `adult.test`, totes dues juntes (amb i sense el
  punt final de les etiquetes de test).
- **D_i:** cada fitxer de dades i la concatenació dels que comparteixen
  columnes, a cada revisió del repositori amb contingut diferent fins a la
  data del paper (2026-07-04).

I per a cada variant s'ha mirat **d'on surten les files** (per edat,
`fnlwgt`, guanys, pèrdues i hores):

| Versió | Fitxer | Files | De `adult.data` | De `adult.test` | D'enlloc |
|---|---|---|---|---|---|
| D1 | `adult.csv` | 32.561 | 100% | 0% | 0% |
| D2 | `data/train-…parquet` | 32.561 | 100% | 0% | 0% |
| D3 | `income/train.csv` | 12.211 | 68% | 32% | 0% |
| D4 | `income-no race/train.csv` | 12.211 | 68% | 32% | 0% |
| D5 | `optimized_adult_census.csv` | 32.561 | 100% | 0% | 0% |
| D6 | els 3 fitxers junts | 22.416 | 95%¹ | 5%¹ | 0% |
| D7 | `adult_processed.csv` | 45.222 | 68% | 32% | 0% |

¹ D6 no té `fnlwgt`: la clau és més feble i la proporció, aproximada. Les
22.416 files són 11.208 per classe: exactament el nombre de `>50K` de la UCI
completa sense nuls.

**Conclusions:**

1. **No hi ha una sola D0.** D1, D2 i D5 són còpies d'`adult.data`; D3, D4,
   D6 i D7 són mostres de **les dues publicacions juntes** (48.842 files).
   Comparades amb una D0 fixa, unes o altres surten amb C421/C422 que el
   paper no marca. La Taula 1 és coherent si cada versió es compara amb la
   publicació de la qual surt; això és el que fa ara la validació
   (`CENSUS_INCOME_SOURCES[...]["d0"]`).
2. **D3/D4:** el `income/train.csv` actual (des del 2025-10-08) té les
   mateixes 12.211 files que l'antic `adult_ts.csv`, una partició aleatòria
   de les 48.842. Abans, un script (`adult.py`) construïa les
   configuracions: esborrava `education` (categòrica), deixava
   `education-num` amb el nom `education`, i reanomenava `threshold` →
   `over_threshold` i `sex` → `is_male`. La URL del paper (`tree/main/income`)
   apunta a la versió amb carpetes.
3. **D6:** la targeta diu que és un sol dataset equilibrat partit en tres
   fitxers; els tres donen el mateix resultat, i es fa servir la
   concatenació.

Precisió contra la Taula 1 segons la D0 (amb la millor variant de cada
versió): només `adult.data` 0,676; totes dues juntes 0,686; **segons la
procedència 0,758**.

## 3. Com es va etiquetar: targeta + inspecció

| Versió | Què diu la targeta | Taula 1 |
|---|---|---|
| D1 | Còpia de la UCI, descripció de `fnlwgt` | C223 (noms amb `.`), C410 (inspecció) |
| D2 | Només com carregar-lo | C223, C410 (inspecció) |
| D3 | Taula de columnes: `final_weight`, `is_male` bool, `over_threshold` int8, `education` int8 ("the higher, the more educated"); "target… always in last position" | C210, C223, C311, C312, C410, C422 |
| D4 | Com D3 i "the `race` feature is removed" | + C222 |
| D5 | "adding two new columns: capital_gain_loss_ratio and age_group"; 32.562 files | C221, C223, C410 |
| D6 | "**balanced** version… split into training, validation, and test" | C223, C422, **C530** (equilibri de classes) |
| D7 | "preprocessed for fairness", metadades amb columnes numèriques i categòriques | C222, C223, C312, C421 |

Gairebé totes les etiquetes surten de la targeta o d'una inspecció
directa (renoms, ordre de files). Els canvis que la targeta no esmenta no
hi són, encara que siguin a les dades.

## 4. Resultat i desacords que queden

`data/census_income/census_income_paper_comparison_by_code_8.csv`:
**precisió 75,8%, recall 96,2%, F1 84,7%** (25 TP, 8 FP, 1 FN). Abans
d'aquest estudi: 71,4% / 96,2% / 82,0%; motor anterior: 64,5% / 76,9% /
70,2%.

| Versió | Desacord | Què hi ha a les dades | Per què el paper no hi coincideix |
|---|---|---|---|
| D3 | C222 (`education-num`) | L'script de l'autor esborra `education` i en deixa la versió numèrica amb el mateix nom | El paper ho llegeix com a canvi de tipus (C311), igual que el motor, però no marca la columna que desapareix |
| D4 | C410 | Files en ordre aleatori (tau de Kendall ≈ 0) | Mateix procés que D3, on sí que hi ha C410: incoherència de la taula |
| D6 | C222 (`fnlwgt`) | La columna no hi és (la targeta tampoc no la llista) | No documentat |
| D6 | C410 | Ordre aleatori | No documentat |
| D6, D7 | C510 | Les files amb `?` s'han eliminat: la proporció de nuls passa de ~7% a 0% | El text (§4) diu que es reporta; la taula no ho fa |
| D7 | C422 | S'eliminen les 3.620 files amb `?` | No documentat |
| D7 | C311 | Totes les categòriques passen a enters | La taula hi marca només C312; a D3/D4 marca C311 + C312 pel mateix canvi |
| D7 | C421 no detectat | Respecte a les dues publicacions juntes no hi ha cap fila nova | Només té sentit comparant amb `adult.data` (les files de test serien noves); a D3, amb el mateix tipus de files, no es marca |

Cap d'aquests desacords és un error del motor: són canvis reals que la
targeta no documenta, o casos on la taula no aplica el mateix criteri a
dues versions.

## 5. Canvis fets al motor i a la validació

- **D0 segons la procedència**, revisions fixades i D6 com a concatenació
  (`notebooks/validate_census_income.py`).
- **Retirada de P12.** Ometia C510 quan els nuls canviaven només per files
  eliminades, per coincidir amb la taula; el text del paper diu el
  contrari.
- **C312 `recoded`.** Un canvi de tipus que és una bijecció entre valors
  (codificar categories com a enters) també és un canvi de valors del
  domini, com marca la taula a D3/D4 i com defineix el text. Un canvi només
  de format ("1" → 1) no ho és.
- **P8** (una transformació no genera també C530) es manté com a decisió
  provisional; el text suggereix reportar tots dos canvis, però no hi ha
  cap cas a la Taula 1 que ho resolgui (`docs/open_decisions.md`).
