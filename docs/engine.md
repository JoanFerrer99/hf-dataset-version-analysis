# El motor de detecció de canvis

Aquest document explica el motor que, donades dues versions d'un dataset
tabular de Hugging Face, diu **què ha canviat** segons la taxonomia del
paper (`docs/taxonomy.md`). Està pensat per llegir-lo de dalt a baix: primer
d'on venim, després la idea del motor actual, i després el recorregut
d'una comparació pas a pas, amb les funcions que cal llegir a cada pas.

El codi és a `src/diffengine/`. Les decisions encara pendents de confirmar
(P*, U*) són a `docs/open_decisions.md`. Com es valida el motor contra la
Taula 1 del paper és a `docs/validacio_census_income.md`.

---

## 1. D'on venim: el motor de diffs

La primera versió (`change_diff.py`, ja retirada) era un **diff**: rebia
dos fitxers carregats amb pandas i en comparava característiques
generals. Les columnes, pel nom: un nom que desapareix és C222, un nom
nou és C221. Les files, pel recompte: més files és C421, menys és C422.
Els valors, pels estadístics (mitjana, desviació, quartils), amb un 5% de
tolerància. Era simple i ràpid, però quan el vam auditar vam veure que els
errors no eren de llindars mal triats, sinó del plantejament mateix:

| Com treballava el diff | Què en sortia |
|---|---|
| Columnes comparades només pel nom | Un renom (`sex` → `is_male`) sortia com una columna eliminada i una d'afegida, i el canvi de valors de la columna reanomenada no es veia mai. C223 no es detectava mai. |
| C421/C422 segons el recompte de files | Afegir 10 files i eliminar-ne 10 no era cap canvi. |
| Tipus segons el `dtype` de pandas | Una columna d'enters que guanyava un sol nul passava a `float` i "canviava de tipus" (C321). |
| Totes les columnes com a variables | Una columna `id` que creix generava C322, C520 i C530 falsos. |
| Un fitxer = un dataset, màxim 5 fitxers per commit | Un dataset partit en 50 fitxers (shards, episodis) sortia com fitxers sencers afegits i eliminats. |
| Una descàrrega fallida = un fitxer que no existeix | Un error de xarxa es convertia en C421/C422. |

Amb les mateixes dades de Census Income, el diff troba 18 dels 26 codis que
marca el paper; el motor actual, 26 de 26 (`docs/validacio_census_income.md`).

## 2. La idea del motor actual

El motor actual no compara característiques generals, sinó que respon
primer una pregunta més bàsica: **què correspon a què** entre les dues
versions.

1. **Quines taules hi ha** a cada versió i quina va amb quina. Un dataset
   pot estar repartit en molts fitxers.
2. **Quina columna nova és quina columna antiga**, encara que s'hagi
   reanomenat, mirant-ne el contingut.
3. **Quina fila nova és quina fila antiga**, encara que hagi canviat de
   lloc o se n'hagi editat una cel·la.

Un cop aparellat tot, detectar els canvis és directe: el que no té
parella s'ha afegit o eliminat, i el que té parella es pot comparar cel·la
a cel·la. Cada canvi surt amb una **explicació** (subtipus: `factor`,
`relabel`, `had_nulls`...), una **evidència** (el mapatge, la fórmula, els
estadístics) i una **confiança**. Cada parell de taules acaba amb un
**estat**, de manera que res es perd en silenci.

## 3. Recorregut d'una comparació, pas a pas

Els passos s'anomenen capes (L0–L6). A la Fase 2 del pipeline, la crida és
`pairs.compare_revisions(repo, revisió_antiga, revisió_nova, ...)`, que
encadena tots els passos. Per comparar dos fitxers sols hi ha
`engine.diff_bytes(bytes_antics, ".csv", bytes_nous, ".parquet")`, que comença
directament a L1.

### L0 — Quines taules hi ha i quina va amb quina (`units.py`, `pairs.py`)

**Problema.** A Hugging Face, un dataset no és un fitxer. Pot estar partit
en shards (`train-00000-of-00003.parquet`…), en episodis (LeRobot,
centenars de parquets), en subconjunts i particions (train/test), o barrejar
dades amb metadades.

**Solució.** La unitat de comparació és la **taula (subset, split)** tal com
la mostra el Hub (decisió U1, confirmada). Per saber quines taules hi ha,
`units.resolve_units` fa servir les mateixes regles que la llibreria
`datasets`: recrea l'arbre de fitxers com a fitxers buits en un directori
temporal (sense descarregar res) i li demana a `datasets` quines particions
hi veu. Els shards d'una partició són una sola taula. Dos casos s'han hagut
d'afegir a mà:

- **Repositoris de vídeo amb taules** (LeRobot té més vídeos que parquets, i
  `datasets` el veu com un dataset de vídeo): les taules que el vídeo no fa
  servir es resolen per separat (P11).
- **Repositoris que `datasets` no sap llegir**: cada fitxer tabular és una
  taula.

`pairs.pair_units` aparella les taules de les dues revisions per nom de
partició. Si una taula d'un sol fitxer no troba parella, prova pel camí
del fitxer, després pel mateix contingut (fitxer reanomenat) i després pel
mateix nom amb una altra extensió (canvi de format). Si dues taules tenen
exactament el mateix contingut (mateix hash de git), no es descarreguen.

`pairs.compare_pair` descarrega i compara cada parell, i li posa un
**estat**:

| Estat | Quan |
|---|---|
| `ok` | Comparat |
| `identical_content` | Mateix contingut a les dues revisions: no es descarrega |
| `absent_old`, `absent_new` | La taula sencera apareix o desapareix (no és C421/C422: no s'afegeixen files a una taula existent, decisió U2) |
| `download_failed`, `parse_failed` | No s'ha pogut descarregar o llegir; mai es converteix en codis |
| `too_large_profile_only` | Massa gran (`max_unit_bytes`); no es compara |
| `excluded` | Fitxer tabular que ha canviat però no és cap taula (metadades, fora de cap partició); el motiu queda a `detail` |

### L1 — Llegir un fitxer i saber el tipus de cada columna (`load.py`)

**Problema.** El tipus que dona pandas no és el tipus de la dada: una
columna d'enters amb un nul passa a `float`, un CSV porta espais després de
les comes, `?` vol dir "absent".

**Solució.** `load.load_table` llegeix el fitxer i dedueix el **tipus lògic**
de cada columna pels valors: `numeric`, `categorical`, `text` (text lliure) o
`opaque` (imatges, àudio, vectors). Els CSV es llegeixen com a text i se'n
detecta el separador. Els tokens d'absent (`?`, `NA`, buit…) passen a nul,
però es recorden per detectar si canvien (C510 `representation`). Les
columnes de LeRobot que guarden un escalar dins d'un array d'un element
(`[0.04]`) es llegeixen com a nombres.

### L4 — Aparellar files (`rows.py`)

**Problema.** Saber quina fila nova correspon a quina antiga, encara que
les files estiguin en un altre ordre, n'hi hagi de noves o d'eliminades, o
se n'hagi editat alguna cel·la.

**Solució.** `rows.align_rows`, per passos:

1. **Clau.** Si hi ha una columna amb valors únics a les dues versions i
   que comparteixen la majoria de valors (un identificador), s'uneix per
   aquesta columna. Un número de fila (0, 1, 2…) no compta com a clau:
   només diu la posició i es renumera quan s'insereixen files.
2. **Files idèntiques.** Sense clau, cada fila es resumeix en un número
   (hash) a partir dels valors de les columnes que conserven la majoria
   dels seus valors. Dues files amb el mateix hash són la mateixa fila.
3. **Files editades en una columna.** Les que queden sense parella es
   tornen a comparar sense una de les columnes; si ara coincideixen, és la
   mateixa fila amb una cel·la editada. Només s'accepta si no pot ser
   casualitat.
4. **Files editades en dues columnes**, només entre les 6 columnes que més
   canvien.
5. **Parelles dubtoses.** Si diverses files són idèntiques, quina va amb
   quina és ambigu; aquestes parelles es marquen i no s'usen per comparar
   valors ni l'ordre.

Les columnes que són comptadors de posició (`index`, `episode_index` a
LeRobot) no entren al hash, perquè una inserció al mig les renumera totes
(P10). La classe `_HashMatcher` té un mètode per cada pas.

### L3 — Aparellar columnes (`columns.py`, `transforms.py`)

**Problema.** Saber que `is_male` és l'antiga `sex`, o que `final_weight` és
l'antiga `fnlwgt`.

**Solució.** Primer pel **nom** (exacte i normalitzat: `marital-status` =
`marital.status`). Les columnes que queden sense parella es comparen pel
**contingut** sobre les files aparellades: valors idèntics, una
correspondència u a u entre categories (`Male` → `True`), o una
transformació numèrica (×1000, logaritme, estandardització…). L'assignació
de totes les parelles alhora la fa l'algorisme hongarès
(`linear_sum_assignment`). Si la versió nova és una altra mostra de files,
una columna també és la mateixa si comparteix la majoria de valors i la
mateixa distribució. Abans de tot això es busquen les codificacions one-hot
(una categòrica que es converteix en diverses columnes 0/1).

Columnes i files depenen les unes de les altres: per comparar el contingut
de dues columnes calen les files aparellades, i un renom trobat millora
l'aparellament de files. Per això `engine.diff_tables` alterna L4 i L3 fins
a dues vegades.

`transforms.py` conté les funcions que expliquen com ha canviat una columna:
`fit_numeric` (quina transformació porta els valors vells als nous),
`analyze_mapping` (reetiquetatge, fusió o divisió de categories, edicions
soltes) i `distribution_distance` (quant ha canviat la distribució).

### L5 — Detectar els canvis (`detectors/`)

Amb tot aparellat, cada detector busca uns codis. Hi ha un fitxer per cada
perspectiva de la taxonomia del paper (§4):

| Fitxer | Perspectiva | Codis | Com |
|---|---|---|---|
| `columns_set.py` | Conjunt de columnes | C210, C221, C222, C223 | Ordre relatiu, columnes sense parella, renoms. Una columna nova és `derived` si es pot calcular a partir d'una que ja hi era |
| `column_kind.py` | Tipus i valors d'una columna | C311, C312, C321, C322 | Canvi de tipus (categòric ↔ numèric). Cel·la a cel·la sobre les files aparellades: quina transformació o quin mapatge ho explica |
| `rows_set.py` | Conjunt de files | C410, C421, C422 | Ordre de les files aparellades segures; files sense parella i per què s'han eliminat (`had_nulls`, `outlier`, una regla…) |
| `data.py` | Característiques de les dades | C510, C520, C530 | Valors absents, correlacions entre columnes i distribució de cada columna, amb proves estadístiques |

Els detectors comparteixen un `Context` (`detectors/common.py`) on uns
deixen anotacions per als altres. Per exemple, si una columna s'explica per
una transformació (C322), el detector de distribució no hi afegeix un C530
(P8). Les columnes que identifiquen files (claus, comptadors) no es tracten
com a variables.

**Confiança i evidència.** La confiança és la proporció de files que una
explicació reprodueix, o 1 − p d'una prova estadística. L'evidència guarda
el que justifica el codi. Els tests comproven que cap codi surt sense totes
dues.

### L6 — Sortida (`output.py`)

| Fitxer | Una fila per | Contingut |
|---|---|---|
| `changes_<k>.csv` / `.parquet` | canvi | Revisions, fitxer, codi, columna, subtipus, files afectades, confiança, evidència, versió del motor i hash de la configuració |
| `change_pairs_<k>.csv` | parell de taules | L'estat de cada parell i com s'han aparellat les files |
| `change_classification_<k>.csv` | codi per fitxer | El format antic, per compatibilitat |

## 4. Configuració i decisions

Tots els llindars són a `config.EngineConfig`, cadascun amb el seu perquè al
docstring. Les decisions provisionals són interruptors: P1 (un valor que
passa a nul és C510), P3 (un canvi de tipus es codifica pel tipus antic),
P5 (els canvis de format es reporten) i P8 (una transformació no genera
també C530). Cada fila de sortida guarda el hash de la configuració, per
saber amb quins llindars s'ha generat.

## 5. Com sabem que funciona

- **Casos generats** (`experiments/`). 47 mutacions conegudes (reanomenar,
  escalar, eliminar files…) aplicades a una taula sintètica i a UCI Adult,
  soles o combinades. Un conjunt serveix per ajustar i un altre, reservat,
  per mesurar. Al conjunt reservat, el pitjor F1 per codi passa de 0,34 amb
  el diff a 0,98 (`experiments/report.md`).
- **Census Income** (la Taula 1 del paper). El motor troba els 26 codis que
  marca el paper; el diff, 18 (`docs/validacio_census_income.md`).
- **Dades reals.** Una execució del pipeline amb els 11 elegibles de
  `run_8` va destapar vuit problemes que els casos generats no cobrien.
  Cadascun s'ha verificat obrint les dades, s'ha corregit i té el seu
  test:

| Què passava | Correcció |
|---|---|
| Els repositoris LeRobot (més vídeos que parquets) no es comparaven | Les seves taules es resolen per separat (P11) |
| Els repositoris amb `dataset_infos.json` no es resolien | Aquest fitxer de metadades ja no es recrea |
| Si `datasets` fallava, el repositori es perdia en silenci | Cada fitxer tabular passa a ser una taula |
| A `stlee601/cube_pick1`, inserir episodis renumerava `index` i aparellava frames diferents | Els comptadors de posició no són clau ni entren al hash; si canvien, C322 `renumbered` (P10) |
| `gripper_width` (un escalar dins d'un array) no es comparava | Els arrays d'un element es llegeixen com a escalars |
| Una taula regravada s'aparellava només per `timestamp` i `frame_index`, que es repeteixen a cada episodi | Una parella dubtosa es descarta si un vector o una imatge la desmenteix |
| Una taula que perdia 12.919 files tenia el C422 amb confiança 0 | La diferència de recompte és segura; subtipus `all_rows` si no en queda cap |
| C520 per 5 files en una taula de 600 | Prova estadística per a totes les mesures i regla de Cochran |

Amb la mateixa entrada, el diff donava 30 etiquetes en 3 datasets, i el
motor actual dona 35 canvis en 3 datasets, cadascun amb la seva explicació.
A més, el motor actual llegeix dades que el diff no llegia (els `.jsonl` de
`ckwolfe/benchmarks-viz-tiles`) i registra un estat per a cada taula: 70
taules de 5 datasets a `data/run_12`, l'execució de referència amb el codi
actual. Els altres 6 elegibles de `run_8` ja no ho són amb el criteri
tabular: 4 no tenen cap taula, i 2 tenen totes les pujades de dades en una
sola sessió.

## 6. Guia per programar-hi

- **Punts d'entrada:** `engine.diff_bytes` (dos fitxers), `engine.diff_tables`
  (dues taules ja carregades), `pairs.compare_revisions` +
  `pairs.revision_rows` (dues revisions d'un repositori).
- **Ordre de lectura del codi:** `engine.py` (l'esquelet, curt), `load.py`,
  `rows.py`, `columns.py` + `transforms.py`, `detectors/` (un fitxer per
  perspectiva), `output.py`, i finalment `units.py` + `pairs.py`.
- **El paquet no depèn del pipeline.** Les crides al Hub passen per un
  paràmetre `call`, on el pipeline hi posa la seva política de reintents.
  Les dependències internes només van cap avall:

```
pairs ─→ engine ─→ detectors ─→ columns ─→ transforms ─→ load ─→ config
  │                    │            └────→ rows ────────↗
  └─→ units            └─→ output
```

- **Canviar un llindar:** només a `config.py`.
- **Afegir un detector:** una funció `detect_x(ctx) -> list[Change]` al
  fitxer de la seva perspectiva, afegida a `DETECTORS`
  (`detectors/__init__.py`); una mutació a `experiments/mutations.py` amb el
  codi esperat; i tornar a executar `python experiments/run_eval.py --split
  calibration`.
- **Tests:** `tests/test_diffengine_regressions.py` té un test per cada cas
  real o conegut; `test_diffengine_units.py`, `test_diffengine_pairs.py` i
  `test_diffengine_load.py` cobreixen L0 i L1.
- **Cost:** per a una taula de `r` files i `c` columnes, gairebé tot és
  proporcional a `r × c`. Les taules amb el mateix contingut no es
  descarreguen, i les que passen de 500 MB no es comparen.

## 7. Límits coneguts

- **Els vectors i les imatges no es comparen**: només serveixen per aparellar
  files. Un canvi dins d'un vector no surt com a codi.
- **Files gairebé idèntiques**: si una fila desapareix i n'apareix una altra
  igual en tot excepte una cel·la, el motor les aparella com si fossin la
  mateixa fila editada. A Census Income D7 passa amb 14 files d'`adult.data`
  i d'`adult.test`, i en surt un C410 de més: és l'únic error del motor a
  Census Income.
- **Renoms sense cap relació de contingut** (canvien el nom i tots els
  valors): surten com a C221 + C222.
- **Taules massa grans** (més de 500 MB): només estat, sense codis.
- **No es detecta** el canvi de patró conjunt de valors absents entre
  columnes.
