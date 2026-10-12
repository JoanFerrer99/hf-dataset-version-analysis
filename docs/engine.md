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
a cel·la. Cada canvi surt amb el seu codi de la taxonomia, la columna
afectada i una **explicació** (subtipus: `factor`, `relabel`,
`had_nulls`...). Cada parell de taules té un **estat** intern que decideix
si es compara; una taula que no s'ha pogut llegir mai genera codis.

## 3. Recorregut d'una comparació, pas a pas

El motor fa sempre els mateixos 5 passos, en aquest ordre. `engine.py` n'és
l'índex: llegint-lo de dalt a baix es veuen tots cinc.

| Pas | Què fa | Mòduls |
|---|---|---|
| 1 | Trobar les taules que es comparen i quina va amb quina | `units.py`, `pairs.py` |
| 2 | Llegir cada taula i saber el tipus de cada columna | `load.py` |
| 3 | Aparellar columnes i files: 3a columnes pel nom, 3b files, 3c columnes pel contingut | `columns.py`, `rows.py`, `transforms.py` |
| 4 | Detectar els canvis | `detectors/` |
| 5 | Escriure el resultat | `output.py` |

Hi ha dues maneres d'entrar. El pipeline (Fase 2) crida
`pairs.compare_revisions(repo, revisió_antiga, revisió_nova, ...)`, que fa
el pas 1 i, per a cada parell de taules, els passos 2 a 4. Per comparar dos
fitxers sols (la validació de Census Income, els tests) hi ha
`engine.diff_bytes(bytes_antics, ".csv", bytes_nous, ".parquet")`, que comença
al pas 2.

### Pas 1 — Trobar les taules que es comparen (`units.py`, `pairs.py`)

**Problema.** A Hugging Face, un dataset no és un fitxer. Pot estar partit
en shards (`train-00000-of-00003.parquet`…), en episodis (LeRobot,
centenars de parquets), en subconjunts i particions (train/test), o barrejar
dades amb metadades.

**Solució.** La unitat de comparació és la **taula** tal com
la mostra el Hub (decisió U1, confirmada). Per saber quines taules hi ha, a la funció
`units.resolve_units` es fa servir les mateixes regles que la llibreria
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
| `absent_old`, `absent_new` | La taula sencera apareix o desapareix|
| `download_failed`, `parse_failed` | No s'ha pogut descarregar o llegir; mai es converteix en codis |
| `too_large` | Massa gran (`max_unit_bytes`); no es compara |
| `excluded` | Fitxer tabular que ha canviat però no és cap taula (metadades, fora de cap partició) |

### Pas 2 — Llegir cada taula (`load.py`)

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

### Pas 3 — Aparellar columnes i files (`columns.py`, `rows.py`, `transforms.py`)

**Problema.** Saber quina columna nova és quina antiga (`is_male` era
`sex`, `final_weight` era `fnlwgt`) i quina fila nova és quina antiga
(encara que hagin canviat de lloc, n'hi hagi de noves o se n'hagi editat
alguna cel·la).

Columnes i files depenen les unes de les altres: per reconèixer una columna
reanomenada pel contingut cal saber quines files són la mateixa, i una
columna reconeguda ajuda a reconèixer files. Per això el pas 3 té tres
subpassos, que s'alternen com a màxim dues vegades
(`engine.match_columns_and_rows`).

#### 3a. Columnes pel nom (`columns.align_by_name`)

Les columnes amb el mateix nom, exacte o normalitzat (`marital-status` =
`marital.status`), són la mateixa. Les altres queden pendents per al 3c.

El nom té prioritat sobre el contingut. A Census Income D3/D4, la columna
`education` passa a tenir els valors d'`education-num`, que desapareix. El
motor ho llegeix pel nom, com la Taula 1 del paper i com ho veuria un
pipeline que llegeix les columnes pel nom: `education` canvia de tipus i de
valors (C311 + C312), i `education-num` s'elimina (C222).

#### 3b. Files (`rows.align_rows`)

Es prova, en aquest ordre:

1. **Clau.** Si hi ha una columna amb valors únics a les dues versions i
   que comparteixen la majoria de valors (un identificador), s'uneix per
   aquesta columna. Un número de fila (0, 1, 2…) no compta com a clau:
   només diu la posició i es renumera quan s'insereixen files.
2. **Files idèntiques.** Sense clau, cada fila es resumeix en un número
   (hash) a partir dels valors de les columnes que conserven la majoria
   dels seus valors. Dues files amb el mateix hash són la mateixa fila.
3. **Files editades en una columna.** Les que queden sense parella es
   tornen a comparar sense una de les columnes; si ara coincideixen, és la
   mateixa fila amb una cel·la editada.
4. **Files editades en dues columnes**, només entre les 6 columnes que més
   canvien.
5. **Parelles dubtoses.** Si diverses files són idèntiques, quina va amb
   quina és ambigu; aquestes parelles es marquen i no s'usen per comparar
   valors ni l'ordre.
6. **Parelles no confirmades.** Si en una parella alguna cel·la passa de
   buida a tenir valor, o al revés, la cel·la buida no confirma que siguin
   la mateixa fila. Aquestes parelles serveixen per comparar valors, però
   no per jutjar l'ordre (C410). És el cas de Census Income D7: 14 files
   d'`adult.data` amb un `?`, que D7 elimina, coincideixen en les columnes
   numèriques amb files d'`adult.test` que D7 afegeix al final.

Les columnes que són comptadors de posició (`index`, `episode_index` a
LeRobot) no entren al hash, perquè una inserció al mig les renumera totes
(P10). La classe `_HashMatcher` té un mètode per cada pas.

#### 3c. Columnes pel contingut (`columns.align_by_content`)

Les columnes que han quedat sense parella al 3a es comparen pel
**contingut**, sobre les files aparellades al 3b: valors idèntics, una
correspondència u a u entre categories (`Male` → `True`), o una
transformació numèrica (×1000, logaritme, estandardització…). Si la versió
nova és una altra mostra de files, una columna també és la mateixa si
comparteix la majoria de valors i la mateixa distribució. Abans es busquen
les codificacions one-hot (una categòrica que es converteix en diverses
columnes 0/1). Totes les parelles es trien alhora amb l'algorisme hongarès
(`linear_sum_assignment`); el nom només desempata.

**Si en troba alguna, torna al 3b**: amb més columnes aparellades es
reconeixen millor les files. Al final, les columnes que encara no tenen
parella s'han afegit (C221) o eliminat (C222) (`columns.classify_leftovers`).

Les funcions que expliquen com ha canviat una columna són a
`transforms.py`: `fit_numeric` (quina transformació porta els valors vells
als nous), `analyze_mapping` (reetiquetatge, fusió o divisió de categories,
edicions soltes) i `distribution_distance` (quant ha canviat la
distribució). Les fan servir el 3c i el pas 4.

### Pas 4 — Detectar els canvis (`detectors/`)

Amb tot aparellat, cada detector busca uns codis. Hi ha un fitxer per cada
perspectiva de la taxonomia del paper:

| Fitxer | Perspectiva | Codis | Com |
|---|---|---|---|
| `columns_set.py` | Conjunt de columnes | C210, C221, C222, C223 | Ordre relatiu, columnes sense parella, renoms. Una columna nova és `derived` si es pot calcular a partir d'una que ja hi era |
| `column_kind.py` | Tipus i valors d'una columna | C311, C312, C321, C322 | Canvi de tipus (categòric ↔ numèric). Cel·la a cel·la sobre les files aparellades: quina transformació o quin mapatge ho explica |
| `rows_set.py` | Conjunt de files | C410, C421, C422 | Ordre de les files aparellades segures; files sense parella i per què s'han eliminat (`had_nulls`, `outlier`, una regla…) |
| `data.py` | Característiques de les dades | C510, C520, C530 | Valors absents, correlacions entre columnes i distribució de cada columna, amb proves estadístiques |

Els detectors comparteixen un `Context` (`detectors/common.py`) on uns
deixen anotacions per als altres. Per exemple, si una columna s'explica per
una transformació (C322), el detector de distribució no hi afegeix un C530.
Les columnes que identifiquen files (claus, comptadors) no es tracten
com a variables.

### Pas 5 — Escriure el resultat (`output.py`)

`pairs.revision_rows` converteix els canvis en files, i
`output.classification_frame` escriu `change_classification.csv`: una fila
per taula, parell de versions i codi, amb la descripció del codi i si
trenca el pipeline (`is_breaking`). Si una taula té el mateix codi en diverses
columnes, surt un sol cop. La columna i el subtipus de cada canvi queden a
l'objecte `Change`; els fan servir els tests i la validació de Census
Income (`classification.csv`).

## 4. Configuració i decisions

Tots els llindars són a `config.EngineConfig`, cadascun amb el seu perquè al
docstring. Les decisions provisionals són interruptors: P1 (un valor que
passa a nul és C510), P3 (un canvi de tipus es codifica pel tipus antic),
P5 (els canvis de format es reporten) i P8 (una transformació no genera
també C530).

## 5. Guia per programar-hi

- **Punts d'entrada:** `engine.diff_bytes` (dos fitxers), `engine.diff_tables`
  (dues taules ja carregades), `pairs.compare_revisions` +
  `pairs.revision_rows` (dues revisions d'un repositori).
- **Ordre de lectura del codi:** `engine.py` (l'índex dels 5 passos, curt), i
  després cada pas en ordre: `units.py` + `pairs.py`, `load.py`,
  `columns.py` + `rows.py` + `transforms.py`, `detectors/`, `output.py`.
- **El paquet no depèn del pipeline.** Les crides al Hub passen per un
  paràmetre `call`, on el pipeline hi posa la seva política de reintents.
  Les dependències internes només van cap avall:

```
pairs ─→ engine ─→ detectors ─→ columns ─→ transforms ─→ load ─→ config
  │                    │            └────→ rows ────────↗
  └─→ units            └─→ output
```

## 7. Límits coneguts

- **Els vectors i les imatges no es comparen**: només serveixen per aparellar
  files. Un canvi dins d'un vector no surt com a codi.
- **Files gairebé idèntiques**: si una fila desapareix i n'apareix una altra
  igual en tot excepte una cel·la, el motor les aparella com si fossin la
  mateixa fila editada. A Census Income D7 passa amb 14 files d'`adult.data`
  i d'`adult.test`. Com que la cel·la que les diferencia és buida en una de
  les dues, la parella no compta per a l'ordre i no en surt cap codi de
  més; només el recompte intern de files eliminades i afegides es desvia
  en 14.
- **Renoms sense cap relació de contingut** (canvien el nom i tots els
  valors): surten com a C221 + C222.
- **Taules massa grans** (més de 500 MB): només estat, sense codis.
- **No es detecta** el canvi de patró conjunt de valors absents entre
  columnes.
