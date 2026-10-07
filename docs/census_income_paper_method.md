# Com va identificar i etiquetar els canvis el paper (Census Income)

Anàlisi de la Taula 1 del paper (`paper.pdf`, PROFES 2026, §5) per saber
amb quines dades es va fer i amb quin criteri, i per què el motor no hi
coincideix del tot. Experiment: `experiments/census_variants.py` (resultats a
`experiments/census_variants/`). Validació: `src/validate_census_income.py`.

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

1. **D0 és `adult.data`, i el paper decideix les files comptant-les.** D1,
   D2 i D5 són còpies d'`adult.data`; D3, D4, D6 i D7 barregen files
   d'`adult.data` i d'`adult.test`. La Taula 1 marca C422 a les versions
   amb menys files que `adult.data` (D3, D4, D6) i C421 a la que en té més
   (D7), sense mirar quines files són. La validació compara totes les
   versions amb `adult.data`.
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

Una alternativa provada va ser comparar cada versió amb la publicació de la
qual surten les seves files (`adult.data` + `adult.test` per a D3, D4, D6 i
D7). Dona més precisió (75,8%), però perd el C421 de D7 (recall 96,2%) i no
és el que fa el paper.

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

`data/census_income/census_income_paper_comparison_by_code_9.csv`:
**precisió 68,4%, recall 100%, F1 81,3%** (26 TP, 12 FP, 0 FN). El motor
troba tots els codis del paper. Els 12 FP, un per un, amb què hi ha a les
dades, són a `docs/falsos_positius.md`: 11 són canvis reals que la targeta
no documenta o que comptar files no deixa veure, i 1 és un error del motor
(C410 a D7).

Amb les mateixes dades, el motor anterior (diferències simples de noms de
columna, recompte de files i estadístics) treu 72,0% / 69,2% / 70,6%: perd
8 dels 26 codis del paper.

## 5. Canvis fets al motor i a la validació

- **D0 = `adult.data`** per a totes les versions, revisions fixades i D6
  com a concatenació (`src/validate_census_income.py`).
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
