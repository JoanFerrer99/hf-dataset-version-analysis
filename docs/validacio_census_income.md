# El motor de detecció de canvis i la seva validació amb Census Income

Aquest document explica tres coses, en aquest ordre: **per què he hagut de
fer una segona versió (v2) del motor** de detecció de canvis, **com està
muntada**, i **com es valida** amb la Taula 1 del paper (PROFES 2026), que
etiqueta a mà els canvis de 7 versions del dataset Census Income publicades
a Hugging Face. Al final hi ha, un per un, els codis en què el motor i la
taula no coincideixen, i les preguntes obertes.

---

## Resum

- **La v1 no n'hi havia prou.** Comparava les columnes pel nom i comptava
  files. Amb Census Income troba 20 dels 26 codis de la Taula 1, i la
  majoria dels seus codis de més són errors: columnes reanomenades que veu
  com una d'eliminada i una d'afegida.
- **La v2 primer aparella i després compara.** Decideix quina columna i
  quina fila de la versió nova corresponen a quines de l'antiga, també pel
  contingut, i després les compara. Troba **els 26 codis** de la taula.
- **Els 11 codis que la v2 marca de més no són errors**: són canvis que hi
  ha a les dades i que sembla que la taula no recull (secció 5).

| | Codis de la taula trobats | Codis de més | Precisió | Recall | F1 |
|---|---|---|---|---|---|
| Motor v1 | 20 de 26 | 11 (la majoria, errors) | 64,5% | 76,9% | 70,2% |
| **Motor v2** | **26 de 26** | 11 (tots, canvis reals) | **70,3%** | **100%** | **82,5%** |

Totes dues versions es comparen amb les **mateixes dades**: cada versió
contra `adult.data`, el fitxer original de la UCI (secció 3).

---

## 1. Per què una v2 del motor

### 1.1 Com treballava la v1

La v1 (`change_diff.py`, ja retirat) era un **diff**: carregava els dos
fitxers amb pandas i en comparava característiques generals.

| Com treballava | Què en sortia |
|---|---|
| **Columnes, pel nom.** Només reconeixia un renom si el nom era el mateix canviant els separadors (`capital-gain` = `capital_gain`). | Un renom de veritat (`sex` → `is_male`) sortia com una columna eliminada (C222) i una d'afegida (C221). I com que no sabia que eren la mateixa columna, no en podia comparar els valors: el canvi `Male` → `True` no es veia mai. |
| **Files, pel recompte.** Més files era C421; menys, C422. | Si una versió afegia 4.000 files i n'eliminava 24.000, només veia que en tenia menys. No sabia quines files eren. |
| **Valors, pels estadístics** (mitjana, desviació, mínim, màxim), amb un 5% de tolerància. | Una altra mostra de les mateixes dades té estadístics una mica diferents: sortien canvis de valors (C322) que no ho eren. |
| **Ordre de files, només si les dues taules tenien exactament les mateixes files.** | Si a més de reordenar hi havia una sola fila diferent, l'ordre ja no es mirava. |
| **Tipus, segons el `dtype` de pandas.** | Una columna d'enters que guanyava un sol buit passava a decimals, i "canviava de tipus" (C321). |
| **Un fitxer = un dataset**, i com a màxim 5 fitxers per commit. | Un dataset partit en molts fitxers sortia com a fitxers sencers afegits i eliminats. |

Els errors no venien de llindars mal triats, sinó del plantejament: sense
saber quina columna i quina fila corresponen a quina, no es pot comparar bé.

### 1.2 Tots els errors de motor v1 amb Census Income

Abans, em trobava que la taula v1 donava el següents errors:

| Versió | No troba (la taula sí) | Marca de més | Per què |
|---|---|---|---|
| D3 | C312, C410 | C221, C222 | `sex` → `is_male` i `income` → `over_threshold` són renoms que no reconeix: veu columnes eliminades i afegides, i no en compara els valors (C312). L'ordre (C410) no el mira perquè D3 té menys files. |
| D4 | C312 | C221 | Com D3. |
| D6 | C223 | C221, C222, C312, C322 | No reconeix `sex` → `gender` ni `education-num` → `educational-num`. D6 és una altra mostra de files: els estadístics i les categories presents canvien, i en surten canvis de valors (C312, C322) que en realitat vénen de tenir unes altres files. |
| D7 | C223, C312 | C221, C311, C322, C530 | No reconeix `income` → `Y`, i per tant no veu que els valors de l'etiqueta s'han recodificat (C312). C322 i C530 surten dels estadístics d'unes altres files. El C311 sí que és real (la v2 també el marca, secció 5.2). |
| D1, D2, D5 | — | — | Coincideix amb la taula: renoms de separadors (`education-num` → `education.num`), ordre, i a D5 les dues columnes noves que documenta l'autor. |  

### 1.3 Com està muntada la v2

La v2 (`src/diffengine/`) respon primer una pregunta més bàsica: **què
correspon a què** entre les dues versions. Un cop aparellat tot, detectar
els canvis és directe: el que no té parella s'ha afegit o eliminat, i el que
en té es compara cel·la a cel·la. Ho fa en 5 passos, sempre en aquest ordre
(`engine.py` n'és l'índex):

1. **Trobar les taules que es comparen.** Un dataset de Hugging Face pot
   estar partit en molts fitxers (shards: trossos d'un mateix split amb les
   mateixes columnes). El motor els uneix en una sola taula, i compara taules, no fitxers.
2. **Llegir cada taula i deduir el tipus de cada columna pels valors**, no
   pel que diu pandas. Una columna d'enters amb un buit continua sent
   d'enters, i `?` vol dir "valor absent", com a Census Income.
3. **Aparellar columnes i files.**
   - *Columnes*: primer pel nom (també amb separadors diferents), i les que
     queden, pel contingut. A D3, `sex` i `is_male` són la mateixa columna
     perquè `Male` correspon sempre a `True` i `Female` a `False` (una
     correspondència u a u). `fnlwgt` i `final_weight`, perquè comparteixen
     els valors i la distribució, encara que les files siguin una altra
     mostra.
   - *Files*: per una columna que identifiqui cada fila, si n'hi ha; si no,
     pels valors de la fila sencera, tolerant una o dues cel·les editades.
     Les parelles dubtoses no es fan servir per jutjar l'ordre.
   - Columnes i files s'ajuden: amb més columnes aparellades es reconeixen
     millor les files, i al revés.
4. **Detectar els canvis**, un tipus de canvi per perspectiva de la
   taxonomia:
   - el que no té parella: columna afegida o eliminada (C221/C222), fila
     afegida o eliminada (C421/C422);
   - el que té parella: tipus (C311/C321) i valors (C312/C322), cel·la a
     cel·la; ordre de columnes (C210) i de files (C410);
   - característiques de les dades: valors absents (C510), correlacions
     (C520) i distribució (C530), amb proves estadístiques.

   Cada canvi diu també **per què**: p.e. C422 `had_nulls` (s'han eliminat
   les files amb algun buit) o C312 `recoded` (les categories s'han
   codificat com a nombres).
5. **Escriure el resultat**: una fila per taula, parell de versions i codi
   (`change_classification.csv`).

Tots els llindars són a `src/diffengine/config.py`, cadascun explicat. Cada
cas real que ha fallat alguna vegada té un test
(`tests/test_diffengine_regressions.py`).

---

## 2. Com es valida la Taula 1 del paper

Per a cada versió D1–D7, es compara la llista de codis que dona el motor
amb la que marca la Taula 1, sense C100 (metadades, fora d'abast). D8 i D9
no són a Hugging Face i no es validen.

- **Encert:** el motor i la taula marquen el codi.
- **Codi de més (fals positiu):** el motor marca un codi que la taula no té.
- **Codi que falta (fals negatiu):** la taula marca un codi que el motor no
  troba.

La **precisió** és la part del que diu el motor que coincideix amb la
taula; el **recall**, la part del que marca la taula que troba el motor.

**Com va etiquetar el paper.** "The changes were identified by combining
information provided in the corresponding repositories (e.g., dataset cards
when available) with a manual inspection of the datasets." Comparant la
taula amb la targeta de cada repositori, s'hi veuen les dues fonts:

| Versió | Què diu la targeta | Taula 1 |
|---|---|---|
| D1 | Còpia de la UCI | C223, C410 |
| D2 | Només com carregar-lo | C223, C410 |
| D3 | Llista de columnes: `final_weight`, `is_male` (sí/no), `over_threshold` (0/1), `education` com a nombre; "target… always in last position" | C210, C223, C311, C312, C410, C422 |
| D4 | Com D3 i "the `race` feature is removed" | C210, C222, C223, C311, C312, C422 |
| D5 | "adding two new columns: capital_gain_loss_ratio and age_group" | C221, C223, C410 |
| D6 | "a **balanced** version… split into training, validation, and test" | C223, C422, C530 |
| D7 | "preprocessed for fairness" | C222, C223, C312, C421 |

Les columnes i els tipus surten de la targeta. Les files, de comptar-les
respecte a `adult.data` (32.561 files): D1, D2 i D5 en tenen les mateixes
(ni C421 ni C422); D3, D4 i D6, menys (C422); D7, més (C421).

**Què no valida Census Income.** La taula només fa servir 10 dels 14 codis
tabulars. C321 (tipus d'una numèrica), C322 (valors d'una numèrica), C510
(valors absents) i C520 (correlacions) no hi surten mai, i per a aquests
codis el motor només està provat amb els tests.

---

## 3. Amb quines dades es compara

### 3.1 D0 = `adult.data`, i per què no `adult.test`

La UCI publica dos fitxers: `adult.data` (32.561 files) i `adult.test`
(16.281). El paper no diu amb quin compara, ni quin fitxer ni quina revisió
de cada repositori va fer servir. Per això es van provar totes les
combinacions: cada fitxer i cada revisió de cada repositori fins a la data
del paper, i tres D0 possibles (`adult.data`, `adult.test` o tots dos
junts; script `census_variants.py`, a l'historial de git, commit
`d084ff7`).

**Durant l'estudi es va fer servir `adult.test`.** Quatre versions (D3, D4,
D6 i D7) tenen files de tots dos fitxers (secció 3.2). Per això, durant un
temps, aquestes quatre es comparaven amb `adult.data` i `adult.test` junts,
i D1, D2 i D5 amb `adult.data` sol. Amb aquesta base, a D7 faltava el C421
que marca la taula: D7 té 45.222 files i la base en tenia 48.842, així que
semblava que D7 només n'eliminava.

**Ara totes es comparen amb `adult.data`, com fa el paper.** És l'única base
amb què quadren els codis de files de la taula:

| Base (D0) | Què passa |
|---|---|
| **`adult.data`** | D1, D2 i D5 són exactament `adult.data`: cap canvi de files, com la taula. D7 en té més: C421, com la taula. |
| `adult.data` + `adult.test` | D1, D2 i D5 semblarien haver eliminat 16.281 files (C422), que la taula no marca. D7 perd el C421. |
| `adult.test` | Encara pitjor: D1, D2 i D5 semblarien tenir files i valors nous. |

**Quin paper té ara `adult.test`.** Cap com a base: només serveix per
**explicar d'on surten** les files que la v2 veu com a afegides a D3, D4 i
D6 (secció 5.1). Comparant amb `adult.data`, aquestes files són noves,
perquè vénen d'`adult.test`. La taula no les veu, perquè compta files.

**Cada versió es llegeix a una revisió fixada**, la més recent abans del
paper, perquè el resultat no canviï si l'autor actualitza el repositori.

### 3.2 D'on surten les files de cada versió

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
mateixos valors; "a tots dos" vol dir que hi ha files idèntiques als dos
fitxers. **Cap fila de cap versió és inventada**: totes surten de la UCI.

### 3.3 Detalls de D3/D4, D6 i D7

**D3 i D4 (`mstz/adult`).** L'autor tenia un script que construïa el
dataset: esborrava `education` (text) i deixava els valors
d'`education-num` en una columna anomenada `education`. També canvien noms
(`sex` → `is_male`, `fnlwgt` → `final_weight`, `income` → `over_threshold`,
i els guions passen a guions baixos). Les 12.211 files són una mostra
aleatòria d'`adult.data` i `adult.test`. **D4 és D3 sense `race`**: les
mateixes files, en el mateix ordre (comprovat fila a fila).

**D6 (`ETdanR/adult_income`).** La targeta diu: "A balanced version of the
UCI Adult dataset, split into training, validation, and test sets". Té tres
fitxers, cadascun equilibrat al 50% entre les dues classes d'ingressos
(`train_data.csv`, 11.208 files; `validation_data.csv`, 2.240;
`experiment_data.csv`, 8.968). Com que és un sol dataset partit, **es
comparen els tres junts**; per separat donen els mateixos codis.
- Parteix de la UCI completa sense les files amb valors absents (45.222
  files, de les quals 11.208 són `>50K`). D6 té tantes files `>50K` com
  aquestes, molt probablement totes, i el mateix nombre de `<=50K`.
- No té `fnlwgt`, fa servir `educational-num` i `gender`, i no té cap `?`.
- La branca `refs/convert/parquet` (un commit de l'agost de 2025) no és una
  versió nova: la fa un bot de Hugging Face per al visor web, i conté les
  mateixes files en un altre format. Per això el pipeline només mira les
  branques de l'autor.

**D7 (`kuldeepbishnoi29/adult-fairness`).** Les 45.222 files són, en
aquest ordre, les 30.162 files d'`adult.data` sense cap `?` i les 15.060
d'`adult.test` sense cap `?` (comprovat fila a fila). Totes les columnes de
text passen a ser nombres (p.e. `Private` → 2), s'elimina `education` i
`income` passa a dir-se `Y`.

---

## 4. Resultat: què troba la v2

| Versió | Taula 1 (sense C100) | La v2 els troba tots? | La v1 no trobava | La v2 en marca de més |
|---|---|---|---|---|
| D1 | C223, C410 | sí | — | — |
| D2 | C223, C410 | sí | — | — |
| D3 | C210, C223, C311, C312, C410, C422 | sí | C312, C410 | C222, C421 |
| D4 | C210, C222, C223, C311, C312, C422 | sí | C312 | C410, C421 |
| D5 | C221, C223, C410 | sí | — | — |
| D6 | C223, C422, C530 | sí | C223 | C222, C410, C421, C510 |
| D7 | C222, C223, C312, C421 | sí | C223, C312 | C311, C422, C510 |

Comparant només amb `adult.data`, la v2 troba tot el que diuen les targetes
i la taula: els renoms (C223), els canvis de tipus i de valors de les
columnes reanomenades (C311, C312), les columnes eliminades i afegides que
documenta l'autor (C222 a D4 per `race`, C221 a D5), l'equilibri de classes
de D6 (C530) i els canvis de files que la taula compta. A més, troba 11
canvis que la taula no té.

---

## 5. Els 11 codis FALSOS POSITIUS

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
té menys. Però una versió pot afegir files i eliminar-ne alhora, i el paper
considera totes dues coses: "as with columns, we should consider the
addition/removal of rows (C421/C422)" (§4), i "versions of the same dataset
can differ from many of these perspectives at the same time" (§4).

- **D3 i D4, C421.** Conserven unes 8.100 files d'`adult.data` (eliminen la
  resta: C422, que la taula sí marca) i **afegeixen 4.065 files que només
  existeixen a `adult.test`**. Comptant, només es veu que en tenen menys.
- **D6, C421.** Té menys files que `adult.data`, però **almenys 6.308 només
  existeixen a `adult.test`**.
- **D7, C422.** Té més files que `adult.data`, però **no conté cap de les
  2.399 files d'`adult.data` que tenen algun `?`**: les ha eliminat. Les
  15.060 noves vénen d'`adult.test` (C421, que la taula sí marca).

### 5.2 El mateix canvi, etiquetat diferent en versions diferents (3 codis)

La taula marca un canvi en una versió i no en una altra on passa el mateix.
El motor aplica el mateix criteri a totes.

- **D3, C222 (`education-num` desapareix).** A `adult.data`, `education`
  (text) i `education-num` (1–16) són la mateixa informació (`HS-grad` = 9,
  `Bachelors` = 13). D3 té una columna `education` amb els números 1–16, i
  `education-num` ja no hi és. El motor ho llegeix pel nom, com la taula:
  `education` canvia de tipus i de valors (C311 + C312, que la taula marca)
  i `education-num` s'elimina (C222, que la taula no marca). A **D7 passa
  el contrari** (s'elimina `education` i es conserva `education-num`), i
  aquí la taula **sí** marca C222. El paper (§4.1) considera que eliminar
  una columna que es pot derivar d'altres té "middle ground importance".
- **D4, C410 (ordre de files).** D4 té les mateixes files que D3, en el
  mateix ordre, aleatori respecte a `adult.data`. La taula marca C410 a D3 i
  no a D4. El paper (§4.1): "Even some innocent change in the order of rows
  (C410) can affect the resulting model if the learner being used in the
  pipeline is incremental".
- **D7, C311 (tipus de categòrica).** A D7 totes les columnes de text i
  l'etiqueta passen a ser nombres. A D3/D4 la taula marca C311 + C312 per la
  mateixa operació (`education` i `income` passen a nombres); a D7, només
  C312. El paper (§4) inclou aquest cas a C311 ("…or simply between them,
  numerical to categorical or vice-versa").

### 5.3 Canvis reals que la targeta no esmenta (2 codis)

- **D6, C222.** `fnlwgt` no hi és, i la targeta no ho diu.
- **D6, C410.** Les files estan en ordre aleatori respecte a `adult.data`.
  Probablement es van barrejar en equilibrar les classes i repartir-les en
  tres fitxers. La targeta no ho esmenta.

### 5.4 Valors absents que desapareixen en eliminar files (2 codis)

A `adult.data` hi ha valors absents (`?`) a tres columnes: `workclass`
(1.836 files, el 5,6%), `occupation` (1.843, el 5,7%) i `native-country`
(583, l'1,8%). **A D6 i D7 no n'hi ha cap**: les files que en tenien s'han
eliminat senceres. El paper defineix C510 com "the presence/absence of
missing values in the columns" i diu que aquests canvis es consideren encara
que vinguin d'eliminar files: "Notice that these can be a consequence of the
addition/removal of rows. However, we consider them separately" (§4). Per a
un pipeline importa: el pas d'imputar valors absents deixa de fer falta.

---

## 6. Canvis al motor arran de la validació

Cadascun té el seu test. Tots es justifiquen pel text del paper, no
per la taula, excepte llegir les columnes pel nom primer, que segueix la
lectura de la taula:

- **Renom sobre una altra mostra de files** (`fnlwgt` → `final_weight` a
  D3/D4). Si la majoria de valors coincideixen i la distribució no canvia,
  és la mateixa columna.
- **Columnes pel nom abans que pel contingut** (`education` a D3/D4,
  secció 5.2). És la lectura de la taula i la d'un pipeline que llegeix les
  columnes pel nom.
- **L'ordre de les files (C410) es jutja només amb parelles segures.** Una
  parella amb una cel·la que passa de buida a tenir valor no compta: a D7,
  14 files d'`adult.data` amb un `?` tenien els mateixos valors numèrics que
  14 files d'`adult.test`, i el motor les prenia per la mateixa fila. Era
  l'únic error del motor; corregir-lo va fer passar la precisió del 68,4% al
  70,3%.
- **Codificar categories com a nombres** és C311 i també C312 `recoded`.
- **C510 es reporta encara que vingui de files eliminades.** Una versió
  anterior del motor l'amagava per coincidir amb la taula, i es va retirar.

## 7. Preguntes obertes

1. **C510 quan s'eliminen les files amb valors absents? El paper sembla dir que sí
2. **Mida de la mostra.** Quants datasets comparats voldries tenir?
