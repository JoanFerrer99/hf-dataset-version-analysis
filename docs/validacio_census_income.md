# Validació del motor amb Census Income

Aquest document explica com es comprova que el motor detecta bé els canvis:
comparant-lo amb la **Taula 1 del paper** (PROFES 2026, §5), on els autors
van etiquetar a mà els canvis de 7 versions del dataset Census Income
publicades a Hugging Face. Explica amb quines dades es fa la comparació, com
va etiquetar el paper, el resultat, i cada cas en què el motor i el paper no
coincideixen.

Codi: `src/validate_census_income.py` (la validació) i
`experiments/census_variants.py` (l'experiment de la secció 3).

---

## 1. Com es mesura

Per a cada versió D1–D7, es compara la llista de codis que dona el motor
amb la que marca la Taula 1 (sense C100, que és fora d'abast):

- **Encert (TP):** el motor marca el codi i el paper també.
- **Fals positiu (FP):** el motor marca un codi que el paper no marca.
- **Fals negatiu (FN):** el paper marca un codi que el motor no troba.

D'aquí surten la **precisió** (de tot el que diu el motor, quina part
coincideix amb el paper: TP / (TP + FP)) i el **recall** (de tot el que
marca el paper, quina part troba el motor: TP / (TP + FN)).

## 2. Com va etiquetar el paper

El paper ho explica així: "The changes were identified by combining
information provided in the corresponding repositories (e.g., dataset
cards when available) with a manual inspection of the datasets". Comparant
la taula amb la targeta (la descripció) de cada repositori, s'hi veuen dues
fonts:

**Les columnes i els tipus surten de la targeta:**

| Versió | Repositori | Què diu la targeta | Taula 1 |
|---|---|---|---|
| D1 | `scikit-learn/adult-census-income` | Còpia de la UCI | C223, C410 |
| D2 | `AiresPucrs/adult-census-income` | Només com carregar-lo | C223, C410 |
| D3 | `mstz/adult` (`income`) | Llista de columnes: `final_weight`, `is_male` (sí/no), `over_threshold` (0/1), `education` com a nombre; "target… always in last position" | C210, C223, C311, C312, C410, C422 |
| D4 | `mstz/adult` (`income-no race`) | Com D3 i "the `race` feature is removed" | + C222 |
| D5 | `Databoost/optimized_adult_census` | "adding two new columns: capital_gain_loss_ratio and age_group" | C221, C223, C410 |
| D6 | `ETdanR/adult_income` | "a **balanced** version… split into training, validation, and test" | C223, C422, C530 |
| D7 | `kuldeepbishnoi29/adult-fairness` | "preprocessed for fairness" | C222, C223, C312, C421 |

**Les files surten de comptar-les** respecte a `adult.data` (32.561 files):

| Versió | Files | Respecte a `adult.data` | Taula 1 |
|---|---|---|---|
| D1, D2, D5 | 32.561 | igual | ni C421 ni C422 |
| D3, D4 | 12.211 | menys | C422 |
| D6 | 22.416 | menys | C422 |
| D7 | 45.222 | més | C421 |

En canvi, el motor mira **quines** files són, no quantes n'hi ha. Per això
troba canvis que la targeta no esmenta i que el recompte no deixa veure.

## 3. Amb quines dades es compara

El paper només dona la URL de cada repositori i de la pàgina de la UCI. No
diu quin fitxer, quina revisió ni quina part de la UCI va fer servir: la UCI
publica `adult.data` (32.561 files) i `adult.test` (16.281). Per saber-ho,
l'experiment `experiments/census_variants.py` va provar totes les
combinacions (cada fitxer, cada revisió del repositori fins a la data del
paper, i les tres D0 possibles) i va mirar d'on surten les files de cada
versió:

| Versió | Fitxer | Files | D'`adult.data` | D'`adult.test` |
|---|---|---|---|---|
| D1 | `adult.csv` | 32.561 | 100% | 0% |
| D2 | `data/train-…parquet` | 32.561 | 100% | 0% |
| D3 | `income/train.csv` | 12.211 | 68% | 32% |
| D4 | `income-no race/train.csv` | 12.211 | 68% | 32% |
| D5 | `optimized_adult_census.csv` | 32.561 | 100% | 0% |
| D6 | els 3 fitxers junts | 22.416 | 95% | 5% |
| D7 | `adult_processed.csv` | 45.222 | 68% | 32% |

Cap fila de cap versió és inventada: totes surten de la UCI.

**La validació compara totes les versions amb D0 = `adult.data`**, com fa
el paper (és l'única D0 amb què la taula quadra en les files). Cada versió es
llegeix a una revisió fixada.

Dos casos concrets:

- **D3 i D4** (`mstz/adult`). L'autor tenia un script que construïa el
  dataset: esborrava `education` (text), deixava `education-num` amb el nom
  `education`, i reanomenava `sex` → `is_male` i `threshold` →
  `over_threshold`. Les 12.211 files són una mostra aleatòria d'`adult.data` +
  `adult.test`.
- **D6** (`ETdanR/adult_income`). Tres fitxers (`train_data.csv`,
  `validation_data.csv` i `experiment_data.csv`), cadascun equilibrat al
  50% entre les dues classes d'ingressos. Com que la targeta diu que són un
  sol dataset partit, es comparen junts; per separat donen els mateixos
  codis. Les 22.416 files són 11.208 de cada classe: exactament totes les
  files `>50K` de la UCI completa sense valors absents, i el mateix nombre de
  `<=50K`.

## 4. Resultat

| | Precisió | Recall | Codis del paper trobats |
|---|---|---|---|
| Motor anterior (diferències simples) | 72,0% | 69,2% | 18 de 26 |
| **Motor actual** | 68,4% | **100%** | **26 de 26** |

Fitxers: `data/census_income/census_income_paper_comparison_by_code_9.csv`
(motor actual) i `_5` (motor anterior, amb les dades d'aleshores).

**El motor troba tots els canvis que marca el paper.** El motor anterior en
perd 8 de 26: canvis de tipus, de valors i d'ordre en columnes que s'han
reanomenat (`sex` → `is_male`, `income` → `over_threshold`). Per trobar-los
cal aparellar les columnes pel contingut, no pel nom. En canvi, el motor
anterior coincideix amb el paper en les files perquè fa el mateix que el
paper: comptar-les.

## 5. Els 12 falsos positius, un per un

| Versió | El motor diu | Què hi ha a les dades | Tipus |
|---|---|---|---|
| D3 | C421: s'afegeixen files | 3.534 files no són a `adult.data`: vénen d'`adult.test`. Com que D3 té menys files en total, comptant només es veu C422 | Canvi real que el recompte amaga |
| D4 | C421: s'afegeixen files | Igual que D3 | Canvi real que el recompte amaga |
| D6 | C421: s'afegeixen files | Part de les files vénen d'`adult.test` | Canvi real que el recompte amaga |
| D7 | C422: s'eliminen files | S'eliminen les 2.399 files d'`adult.data` amb algun `?`. Com que D7 té més files en total, comptant només es veu C421 | Canvi real que el recompte amaga |
| D3 | C222: s'elimina `education-num` | L'script de l'autor esborra `education` i posa `education-num` amb aquest nom | Canvi real no documentat |
| D6 | C222: s'elimina `fnlwgt` | La columna no hi és | Canvi real no documentat |
| D4 | C410: canvia l'ordre de files | Files en ordre aleatori. D3, del mateix repositori i amb el mateix procés, sí que té C410 a la taula | La taula no és coherent |
| D6 | C410: canvia l'ordre de files | Files en ordre aleatori | Canvi real no documentat |
| D6 | C510: canvien els valors absents | Abans hi havia `?` a 3 columnes; ara cap | Canvi real (secció 6) |
| D7 | C510: canvien els valors absents | Igual que D6 | Canvi real (secció 6) |
| D7 | C311: canvia el tipus de les categòriques | Totes les columnes de text passen a ser nombres. A D3/D4 la taula marca C311 + C312 pel mateix canvi; a D7, només C312 | La taula no és coherent |
| D7 | C410: canvia l'ordre de files | D7 conserva l'ordre d'`adult.data`. 14 files d'`adult.data` amb un `?` són idèntiques en tota la resta a files d'`adult.test`, i el motor les aparella com si fossin la mateixa fila | **Error del motor** (indecidible amb les dades) |

**11 dels 12 són canvis reals** de les dades que la targeta no documenta o
que comptar files no deixa veure. Només un és un error del motor.

## 6. C510 quan s'eliminen files (D6 i D7)

A `adult.data` hi ha valors absents (`?`) a tres columnes: `workclass`
(5,6% de les files), `occupation` (5,7%) i `native-country` (1,8%). A D6 i D7
no n'hi ha cap. Cap valor s'ha omplert: les files que en tenien s'han
eliminat senceres.

El paper defineix C510 com "the presence/absence of missing values in the
columns" (§4), i aquí les columnes passen de tenir valors absents a no
tenir-ne. A més, diu que aquests canvis "can be a consequence of the
addition/removal of rows. However, we consider them separately". Per a un
pipeline, el canvi importa: el pas d'imputar valors absents deixa de fer
falta. Per això el motor el marca. La taula no ho fa: a D7 tampoc no hi
marca que s'eliminen files, i la targeta de D6 no parla de valors absents.

## 7. El C421 de D7 i la branca de conversió a parquet

**C421 a D7.** D7 té les 30.162 files d'`adult.data` sense `?` i, a
continuació, les 15.060 d'`adult.test` sense `?`. Comparada amb `adult.data`,
té 15.046 files noves: C421, com el paper.

**El commit "Update parquet files" (agost de 2025)** és del repositori de D6,
no de D7. No és un canvi del dataset:

- El fa un bot de Hugging Face en una branca a part (`refs/convert/parquet`)
  per al visor web, amb un sol commit i sense cap versió anterior.
- Conté les mateixes files, en el mateix ordre, que `train_data.csv` i
  `validation_data.csv`. És la mateixa dada en un altre format (C100, fora
  d'abast).
- No inclou `experiment_data.csv`, i a D7 hi converteix el fitxer de
  metadades en lloc de les dades.

Per això el pipeline només mira les branques de l'autor.

## 8. Canvis fets al motor arran de la validació

Tots es justifiquen pel text del paper (§4), no per la taula, i tenen el seu
test:

- **Renom sobre una altra mostra de files** (`fnlwgt` → `final_weight` a
  D3/D4). Si la majoria de valors coincideixen i la distribució no canvia, és
  la mateixa columna.
- **L'ordre de les files (C410) es jutja només amb parelles segures.**
- **Codificar categories com a nombres** és C311 i també C312 `recoded`
  (P13).
- **C510 es reporta encara que vingui de files eliminades.** Una versió
  anterior l'amagava per coincidir amb la taula (P12), i es va retirar.

## 9. Preguntes per al director

1. **Les files es van etiquetar comptant-les?** D3, D4 i D6 també contenen
   files noves (d'`adult.test`), i D7 també n'elimina.
2. **S'havien d'etiquetar els canvis que la targeta no documenta?** Per
   exemple, `fnlwgt` eliminada a D6 o l'ordre aleatori de D4 i D6.
3. **Codificar categories com a nombres:** C311 + C312 (com a D3/D4) o
   només C312 (com a D7)?
4. **C510 per files eliminades:** seguim el text del paper (es reporta) o
   la taula (no es reporta)?

## 10. Com reproduir-ho

```bash
python src/validate_census_income.py      # la validació (escriu a data/)
python experiments/census_variants.py     # quines dades va fer servir el paper
```
