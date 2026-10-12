# Validació del motor amb Census Income

Document per a la reunió amb el director (octubre de 2026). Explica com es
comprova el motor de detecció de canvis amb la **Taula 1 del paper**
(PROFES 2026, §5), el resultat, i un per un els codis en què el motor i la
taula no coincideixen. Al final hi ha les preguntes per a la reunió i els
altres temes pendents.

---

## Resum

- **El motor troba els 26 codis que marca la Taula 1** (recall del 100%).
- **Marca 11 codis més que la taula no té** (precisió del 70,3%). Cap és un
  error del motor: tots són canvis que hi ha a les dades, comprovats un per
  un. Vénen de quatre motius:

| Motiu | Codis | Secció |
|---|---|---|
| La taula decideix les files comptant-les: no veu que una versió n'afegeix i n'elimina alhora | 4 | 5.1 |
| El mateix canvi està etiquetat diferent en versions diferents | 3 | 5.2 |
| Canvis reals que la targeta del repositori no esmenta | 2 | 5.3 |
| Valors absents que desapareixen en eliminar files | 2 | 5.4 |

- **Des de l'última reunió:**
  - L'únic error del motor que quedava (un canvi d'ordre de files a D7)
    està corregit (secció 6).
  - Totes les versions es comparen amb `adult.data`, cadascuna a una
    revisió fixada del repositori (secció 2).
  - Els tres fitxers de D6 es comparen junts (secció 2.4).
- **Preguntes per a la reunió:** secció 8.

---

## 1. Com es mesura

Per a cada versió D1–D7, es compara la llista de codis que dona el motor
amb la que marca la Taula 1, sense C100 (metadades, fora d'abast). D8 i D9
no són a Hugging Face i no es validen.

- **Encert (TP):** el motor i la taula marquen el codi.
- **Fals positiu (FP):** el motor marca un codi que la taula no té.
- **Fals negatiu (FN):** la taula marca un codi que el motor no troba.

La **precisió** és la part del que diu el motor que coincideix amb la taula,
TP / (TP + FP). El **recall** és la part del que marca la taula que troba el
motor, TP / (TP + FN).

## 2. Amb quines dades es compara

### 2.1 D0 i les revisions

El paper només dona la URL de cada repositori i de la pàgina de la UCI. No
diu quin fitxer, quina revisió ni quina part de la UCI va fer servir. La UCI
publica `adult.data` (32.561 files) i `adult.test` (16.281). Es van provar
totes les combinacions (cada fitxer, cada revisió del repositori fins a la
data del paper i les tres D0 possibles; script `census_variants.py`, a
l'historial de git, commit `d084ff7`). Conclusions:

- **D0 = `adult.data`.** És l'única D0 amb què la taula quadra en les
  files (secció 3).
- **Cada versió es llegeix a una revisió fixada**: la més recent abans del
  paper. Així el resultat no canvia si l'autor actualitza el repositori.

### 2.2 D'on surten les files de cada versió

| Versió | Repositori | Fitxer | Files | Només a `adult.data` | Només a `adult.test` | A tots dos |
|---|---|---|---|---|---|---|
| D1 | `scikit-learn/adult-census-income` | `adult.csv` | 32.561 | totes | 0 | — |
| D2 | `AiresPucrs/adult-census-income` | `data/train-…parquet` | 32.561 | totes | 0 | — |
| D3 | `mstz/adult` | `income/train.csv` | 12.211 | 8.048 (66%) | 4.065 (33%) | 98 (1%) |
| D4 | `mstz/adult` | `income-no race/train.csv` | 12.211 | com D3 | com D3 | com D3 |
| D5 | `Databoost/optimized_adult_census` | `optimized_adult_census.csv` | 32.561 | totes | 0 | — |
| D6 | `ETdanR/adult_income` | els 3 fitxers junts | 22.416 | 13.416 (60%) | 6.308 (28%) | 2.692 (12%) |
| D7 | `kuldeepbishnoi29/adult-fairness` | `adult_processed.csv` | 45.222 | 30.162 (67%) | 15.060 (33%) | — |

Una fila "és" d'un fitxer de la UCI si aquest fitxer té una fila amb els
mateixos valors. "A tots dos" vol dir que hi ha files idèntiques a tots dos
fitxers i no es pot saber de quin surt. **Cap fila de cap versió és
inventada**: totes surten de la UCI.

### 2.3 D3 i D4 (`mstz/adult`)

- L'autor tenia un script que construïa el dataset: esborrava `education`
  (text) i deixava els valors d'`education-num` en una columna anomenada
  `education`. Respecte a la UCI, també canvien noms: `sex` → `is_male`,
  `fnlwgt` → `final_weight`, `income` → `over_threshold`, i els guions
  passen a guions baixos.
- Les 12.211 files són una mostra aleatòria d'`adult.data` i
  `adult.test`.
- **D4 és D3 sense la columna `race`**: les mateixes 12.211 files, en el
  mateix ordre (comprovat fila a fila).

### 2.4 D6 (`ETdanR/adult_income`)

**El repositori.** Tres commits, tots del 31 de maig de 2025: el commit
inicial, la pujada de les dades (`780110a`, el que fem servir) i un canvi
al README. La targeta diu: "A balanced version of the UCI Adult dataset,
split into training, validation, and test sets". La van preparar per a un
projecte d'atacs adversaris sobre models tabulars.

**Els tres fitxers**, cadascun equilibrat al 50% entre les dues classes
d'ingressos:

| Fitxer | Files | `>50K` | `<=50K` |
|---|---|---|---|
| `train_data.csv` | 11.208 | 5.604 | 5.604 |
| `validation_data.csv` | 2.240 | 1.120 | 1.120 |
| `experiment_data.csv` | 8.968 | 4.484 | 4.484 |
| **Total** | **22.416** | **11.208** | **11.208** |

Com que la targeta diu que són un sol dataset partit, **es comparen els
tres junts**. Comparats per separat donen exactament els mateixos codis,
així que la tria no canvia el resultat.

**Com es va construir** (deduït de les dades):

- Parteix de la **UCI completa** (`adult.data` + `adult.test`) sense les
  files amb valors absents: 45.222 files, de les quals 11.208 són `>50K`.
  D6 té tantes files `>50K` com aquestes 11.208, molt probablement totes, i
  el mateix nombre de files `<=50K`. Després les reparteix en tres fitxers.
- **No té `fnlwgt`** i fa servir altres noms: `educational-num` en lloc
  d'`education-num` i `gender` en lloc de `sex`. Coincideixen amb els noms
  de la versió de l'Adult que circula a Kaggle.
- No té cap valor absent (`?`).

**La branca `refs/convert/parquet`.** Té un commit de l'agost de 2025
("Update parquet files"). No és una versió nova del dataset: la fa un bot
de Hugging Face per al visor web, en una branca a part i amb un sol commit.
Conté les mateixes files, en el mateix ordre, que `train_data.csv` i
`validation_data.csv`, i no inclou `experiment_data.csv`. És la mateixa
dada en un altre format (C100, fora d'abast). Per això el pipeline només
mira les branques de l'autor.

### 2.5 D7 (`kuldeepbishnoi29/adult-fairness`)

- La targeta diu que és el dataset "preprocessed for fairness".
- Les 45.222 files són, en aquest ordre, **les 30.162 files d'`adult.data`
  sense cap `?`** (en el mateix ordre que a `adult.data`) i **les 15.060
  files d'`adult.test` sense cap `?`** (comprovat fila a fila).
- Totes les columnes de text passen a ser nombres (p.e. `Private` → 2),
  s'elimina `education` (es conserva `education-num`) i `income` passa a
  dir-se `Y`.
- El repositori també té una branca `refs/convert/parquet`, però el bot hi
  va convertir el fitxer de metadades en lloc de les dades.

## 3. Com va etiquetar el paper

El paper ho explica així (§5): "The changes were identified by combining
information provided in the corresponding repositories (e.g., dataset cards
when available) with a manual inspection of the datasets. Repository
documentation was used to identify explicitly documented modifications,
while manual analysis enabled the detection of additional changes that were
not explicitly reported."

Comparant la taula amb la targeta de cada repositori, s'hi veuen les dues
fonts.

**Les columnes i els tipus coincideixen amb la targeta:**

| Versió | Què diu la targeta | Taula 1 |
|---|---|---|
| D1 | Còpia de la UCI | C223, C410 |
| D2 | Només com carregar-lo | C223, C410 |
| D3 | Llista de columnes: `final_weight`, `is_male` (sí/no), `over_threshold` (0/1), `education` com a nombre; "target… always in last position" | C210, C223, C311, C312, C410, C422 |
| D4 | Com D3 i "the `race` feature is removed" | C210, C222, C223, C311, C312, C422 |
| D5 | "adding two new columns: capital_gain_loss_ratio and age_group" | C221, C223, C410 |
| D6 | "a **balanced** version… split into training, validation, and test" | C223, C422, C530 |
| D7 | "preprocessed for fairness" | C222, C223, C312, C421 |

**Les files coincideixen amb comptar-les** respecte a `adult.data` (32.561
files):

| Versió | Files | Respecte a `adult.data` | Taula 1 |
|---|---|---|---|
| D1, D2, D5 | 32.561 | igual | ni C421 ni C422 |
| D3, D4 | 12.211 | menys | C422 |
| D6 | 22.416 | menys | C422 |
| D7 | 45.222 | més | C421 |

El motor, en canvi, mira **quines** files són, no quantes n'hi ha. Per això
troba canvis que la targeta no esmenta i que el recompte no deixa veure.

## 4. Resultat

| | Precisió | Recall | F1 | Codis de la taula trobats |
|---|---|---|---|---|
| Motor anterior (diferències simples) | 72,0% | 69,2% | 70,6% | 18 de 26 |
| **Motor actual** | **70,3%** | **100%** | **82,5%** | **26 de 26** |

**Per versió:**

| Versió | Taula 1 (sense C100) | El motor els troba tots? | El motor en marca de més |
|---|---|---|---|
| D1 | C223, C410 | sí | — |
| D2 | C223, C410 | sí | — |
| D3 | C210, C223, C311, C312, C410, C422 | sí | C222, C421 |
| D4 | C210, C222, C223, C311, C312, C422 | sí | C410, C421 |
| D5 | C221, C223, C410 | sí | — |
| D6 | C223, C422, C530 | sí | C222, C410, C421, C510 |
| D7 | C222, C223, C312, C421 | sí | C311, C422, C510 |

**Per codi:**

| Codi | Encerts | Falten | De més |
|---|---|---|---|
| C210, C221, C223, C312, C530 | 2, 1, 7, 3, 1 | 0 | 0 |
| C222 | 2 | 0 | 2 |
| C311 | 2 | 0 | 1 |
| C410 | 4 | 0 | 2 |
| C421 | 1 | 0 | 3 |
| C422 | 3 | 0 | 1 |
| C510 | 0 | 0 | 2 |

**Per què calia un motor més complet que les diferències simples.** El motor
anterior comparava noms de columna i comptava files, i perdia 8 dels 26
codis: canvis de tipus, de valors i d'ordre en columnes reanomenades (`sex`
→ `is_male`, `income` → `over_threshold`). Per trobar-los cal aparellar les
columnes pel contingut, no pel nom. En canvi, el motor anterior coincidia
amb la taula en les files perquè feia el mateix que la taula: comptar-les.

## 5. Els 11 codis de més, un per un

| # | Versió | Codi | Què hi ha a les dades | Motiu |
|---|---|---|---|---|
| 1 | D3 | C421 afegir files | 4.065 files només existeixen a `adult.test` | 5.1 |
| 2 | D4 | C421 afegir files | Les mateixes files que D3 | 5.1 |
| 3 | D6 | C421 afegir files | Almenys 6.308 files només existeixen a `adult.test` | 5.1 |
| 4 | D7 | C422 eliminar files | S'eliminen les 2.399 files d'`adult.data` amb algun `?` | 5.1 |
| 5 | D3 | C222 eliminar columna | Desapareix `education-num` | 5.2 |
| 6 | D4 | C410 ordre de files | Mateixes files i mateix ordre que D3, on la taula sí marca C410 | 5.2 |
| 7 | D7 | C311 tipus de categòrica | Totes les categòriques passen a nombres; a D3/D4 la taula ho marca | 5.2 |
| 8 | D6 | C222 eliminar columna | Desapareix `fnlwgt` | 5.3 |
| 9 | D6 | C410 ordre de files | Les files estan en ordre aleatori | 5.3 |
| 10 | D6 | C510 valors absents | Els `?` de tres columnes desapareixen | 5.4 |
| 11 | D7 | C510 valors absents | Igual que D6 | 5.4 |

### 5.1 La taula compta les files (4 codis)

La taula marca C421 si la versió té més files que `adult.data` i C422 si en
té menys (secció 3). Però una versió pot afegir files i eliminar-ne alhora,
i el paper considera totes dues coses: "as with columns, we should consider
the addition/removal of rows (C421/C422)" (§4). També diu que una versió
pot canviar en diverses perspectives a la vegada: "versions of the same
dataset can differ from many of these perspectives at the same time" (§4).

- **D3 i D4, C421.** Tenen 12.211 files: conserven unes 8.100 files
  d'`adult.data` (n'eliminen la resta: C422, que la taula sí marca) i
  **afegeixen 4.065 files que només existeixen a `adult.test`**. Comptant,
  només es veu que en tenen menys.
- **D6, C421.** Té 22.416 files, menys que `adult.data`, però **almenys
  6.308 només existeixen a `adult.test`** (secció 2.4: parteix de la UCI
  completa).
- **D7, C422.** Té 45.222 files, més que `adult.data`, però **no conté cap
  de les 2.399 files d'`adult.data` que tenen algun `?`**: les ha eliminat.
  Les 15.060 files noves vénen d'`adult.test` (C421, que la taula sí marca).

### 5.2 El mateix canvi, etiquetat diferent en versions diferents (3 codis)

En aquests tres casos, la taula marca un canvi en una versió i no el marca
en una altra on passa el mateix. El motor aplica el mateix criteri a totes.

- **D3, C222 (`education-num` desapareix).** A `adult.data`, `education`
  (text) i `education-num` (1–16) són la mateixa informació: cada nivell
  d'estudis té un número propi (`HS-grad` = 9, `Bachelors` = 13). D3 té una
  columna `education` amb els números 1–16: a les files aparellades, val el
  mateix que l'antiga `education-num` en el 99,9% dels casos.
  `education-num` ja no hi és.
  - El motor ho llegeix pel nom, com la taula: `education` canvia de tipus i
    de valors (C311 + C312, que la taula marca) i `education-num`
    s'elimina (C222, que la taula no marca).
  - A **D7 passa el contrari**: s'elimina `education` (text) i es conserva
    `education-num`, i aquí la taula **sí** marca C222.
  - El paper (§4.1) considera que eliminar una columna que es pot derivar
    d'altres té "middle ground importance": és un canvi, encara que menys
    crític.
  - A D4 passa el mateix, però no compta com a codi de més perquè la taula
    ja hi marca C222 per `race`.
- **D4, C410 (ordre de files).** D4 té les mateixes files que D3 i en el
  mateix ordre (comprovat fila a fila). Respecte a `adult.data`, l'ordre és
  aleatori. La taula marca C410 a D3 i no a D4. El paper (§4.1): "Even some
  innocent change in the order of rows (C410) can affect the resulting model
  if the learner being used in the pipeline is incremental".
- **D7, C311 (tipus de categòrica).** A D7 totes les columnes de text
  (`workclass`, `marital-status`, `occupation`, `relationship`, `race`,
  `sex`, `native-country`) i l'etiqueta (`income` → `Y`) passen a ser
  nombres. A D3/D4, la taula marca C311 + C312 per la mateixa operació
  (`education` i `income` passen a nombres); a D7, només C312. El paper
  (§4) inclou aquest cas a C311: "Both categorial (C311) and numerical
  (C321) can change the data type (e.g., … or simply between them,
  numerical to categorical or vice-versa)". El motor marca C311 + C312
  `recoded` a totes tres versions.

### 5.3 Canvis reals que la targeta no esmenta (2 codis)

- **D6, C222 (`fnlwgt` desapareix).** La columna no hi és, i la targeta no
  ho diu.
- **D6, C410 (ordre de files).** Les files estan en ordre aleatori respecte
  a `adult.data`: no hi ha cap relació entre la posició antiga i la nova.
  Probablement es van barrejar en equilibrar les classes i repartir-les en
  tres fitxers. La targeta no ho esmenta.

Tots dos canvis es veuen inspeccionant les dades, però no surten a la
targeta ni a la taula.

### 5.4 Valors absents que desapareixen en eliminar files (2 codis)

A `adult.data` hi ha valors absents (`?`) a tres columnes: `workclass`
(1.836 files, el 5,6%), `occupation` (1.843, el 5,7%) i `native-country`
(583, l'1,8%). **A D6 i D7 no n'hi ha cap.** Cap valor s'ha omplert: les
files que en tenien s'han eliminat senceres.

- El paper defineix C510 com "the presence/absence of missing values in
  the columns" (§4). Aquí les columnes passen de tenir valors absents a no
  tenir-ne.
- El paper també diu que aquests canvis poden venir d'afegir o eliminar
  files, i que es consideren igualment: "Notice that these can be a
  consequence of the addition/removal of rows. However, we consider them
  separately, because the nature of the impact in the corresponding
  pipeline is different" (§4).
- Per a un pipeline, el canvi importa: el pas d'imputar valors absents
  deixa de fer falta.

Per això el motor el marca, i la taula no. A D7, la taula tampoc no marca
que s'eliminen aquestes files (5.1).

## 6. L'error del motor que hem corregit: C410 a D7

**Què passava.** El motor deia que D7 canvia l'ordre de les files (C410),
però D7 conserva l'ordre d'`adult.data` (secció 2.5).

**Per què.** Per saber quina fila nova és quina fila antiga, el motor fa
servir les columnes que conserven els valors. A D7 les categòriques passen
a nombres, i només queden les 6 numèriques (`age`, `fnlwgt`,
`education-num`, `capital-gain`, `capital-loss`, `hours-per-week`). Hi ha
14 files d'`adult.data` amb un `?`, que D7 elimina, que tenen exactament els
mateixos 6 valors que 14 files d'`adult.test`, que D7 afegeix al final. El
motor les aparellava com si fossin la mateixa fila, i com que les noves són
al final, semblava que 14 files havien canviat de lloc.

**La correcció.** En aquestes 14 parelles, una cel·la passa de buida (`?`)
a tenir valor. Una cel·la buida no pot confirmar que dues files siguin la
mateixa. Ara, **una parella amb alguna cel·la que passa de buida a tenir
valor (o al revés) no es fa servir per jutjar l'ordre**. Sí que es fa
servir per comparar valors.

- Comprovat a les 7 versions: només afecta aquestes 14 parelles de D7. El
  C410 de D1–D6 no canvia.
- Test nou amb un cas sintètic igual (`test_28` a
  `tests/test_diffengine_regressions.py`).
- Resultat: 11 codis de més en lloc de 12. La precisió passa del 68,4% al
  70,3% i el recall continua al 100%.

## 7. Canvis al motor arran de la validació

Cadascun té el seu test. Tots es justifiquen pel text del paper (§4), no
per la taula, excepte llegir les columnes pel nom primer, que segueix la
lectura de la taula:

- **Renom sobre una altra mostra de files** (`fnlwgt` → `final_weight` a
  D3/D4). Si la majoria de valors coincideixen i la distribució no canvia,
  és la mateixa columna.
- **Columnes pel nom abans que pel contingut** (`education` a D3/D4,
  secció 5.2). És la lectura de la taula i la d'un pipeline que llegeix les
  columnes pel nom.
- **L'ordre de les files (C410) es jutja només amb parelles segures:** ni
  dubtoses, ni editades, ni amb cel·les que passen de buides a tenir valor
  (secció 6).
- **Codificar categories com a nombres** és C311 i també C312 `recoded`.
- **C510 es reporta encara que vingui de files eliminades.** Una versió
  anterior del motor l'amagava per coincidir amb la taula, i es va retirar.

## 8. Preguntes per a la reunió

1. **Files (4 codis, secció 5.1).** La taula marca C421 o C422 segons si la
   versió té més o menys files que `adult.data`. D3, D4 i D6 també afegeixen
   files (d'`adult.test`) i D7 també n'elimina. Es van etiquetar comptant
   les files? Quan una versió n'afegeix i n'elimina, s'han de marcar tots
   dos codis?
2. **El mateix canvi en versions diferents (3 codis, secció 5.2).** El motor
   aplica el mateix criteri a totes les versions. És el que esperaries?
   - D3 i D4 tenen les mateixes files en el mateix ordre: C410 a les dues?
   - Eliminar una de dues columnes redundants: C222 a D3 (`education-num`)
     com a D7 (`education`)?
   - Codificar categories com a nombres: C311 + C312 (com a D3/D4) o només
     C312 (com a D7)?
3. **Canvis que la targeta no documenta (2 codis, secció 5.3).** S'havien
   d'etiquetar l'eliminació de `fnlwgt` i l'ordre aleatori de D6?
4. **C510 quan s'eliminen les files amb valors absents (2 codis, secció
   5.4).** Hem seguit el text del paper, que diu que es consideren per
   separat. Ho confirmes?
5. **Mida de la mostra.** Quants datasets comparats voldries tenir? Amb
   `attempts_per_eligible` (secció 9.1) es calcula la mostra necessària.

## 9. Altres temes de la reunió

### 9.1 L'escaneig d'elegibilitat (resposta als correus)

- **Només compten els datasets tabulars.** Un commit només compta per a
  l'elegibilitat si toca un fitxer de dades tabular (`.parquet`, `.csv`,
  `.tsv`, `.json`, `.jsonl`), amb la mateixa definició que fa servir el
  motor. A `run_8`, 7 dels 11 elegibles no tenien res a comparar: 4 no
  tocaven cap fitxer tabular (àudio, imatge...), 2 només tenien taules que
  apareixien o desapareixien senceres i 1 tenia el mateix contingut a les
  dues versions. Ara un dataset de vídeo o d'àudio ja no és elegible.
- **Les fórmules** de l'embut són a `docs/architecture.md`, secció 7.4.
- **L'estimació, sobre tots els intents.** `attempts_per_eligible` = tots
  els intents / elegibles: per tenir N datasets elegibles cal una mostra
  d'unes N × `attempts_per_eligible`. Els inaccessibles, els errors i els no
  elegibles hi queden inclosos. A `run_8` (criteri antic): 2.000 / 11 =
  181,8 intents per elegible.
- **`eligible_total` s'ha eliminat**: valia sempre el mateix que
  `eligible`.

### 9.2 Joc de proves del nou company

El format més útil és el mateix que Census Income, perquè es pugui puntuar
amb els mateixos scripts:

- parells de fitxers (versió antiga i nova);
- la llista de codis esperats per a cada parell, com a
  `tests/fixtures/census_income_labels.csv`.

Els casos que més ajudarien són els que la Taula 1 no cobreix: C322 (canvis
numèrics), C520 (correlacions) i C510 quan s'omplen valors absents.

### 9.3 Què queda per fer

1. Una nova execució de la Fase 0 amb el criteri tabular, per tenir la
   proporció d'elegibles i `attempts_per_eligible` reals. La proporció ja
   variava entre el 0,35% i el 0,85% segons l'execució (sis execucions de
   2.000), així que caldrà un marge.
2. Integrar el joc de proves del nou company quan arribi.

## 10. Com reproduir-ho

```bash
python src/validate_census_income.py   # escriu a data/census_income/run_<id>/
```

L'execució de referència d'aquest document és `data/census_income/run_2/`
(`paper_comparison.csv` per versió i `paper_comparison_by_code.csv` per
codi). La de l'última reunió, abans de corregir el C410 de D7, és
`data/census_income/census_income_paper_comparison_9.csv`; la del motor
anterior, `…_5.csv`.
