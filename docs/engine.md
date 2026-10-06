# Motor de detecció de canvis (v2)

Paquet `notebooks/diffengine/`. Rep dues revisions d'un repositori de
Hugging Face (o dos fitxers) i retorna, per a cada taula, un **estat** i una
llista de **canvis** de la taxonomia (`docs/taxonomy.md`), cadascun amb
subtipus, columna, files afectades, confiança i evidència.

Substitueix `change_diff.py` (retirat). Per què calia: `docs/engine_audit.md`.
Decisions provisionals (P*, U*): `docs/open_decisions.md`.

---

## 1. Ús

```python
from diffengine.engine import diff_bytes          # dos fitxers
result = diff_bytes(old_bytes, ".csv", new_bytes, ".parquet")
result.status        # "ok", "identical_content", "parse_failed"
result.changes       # [Change(code="C223", column="is_male", old_column="sex", ...), ...]

from diffengine import pairs                      # dues revisions d'un repositori
compared = pairs.compare_revisions(repo_id, old_sha, new_sha, token, call=retry)
changes, statuses = pairs.revision_rows(repo_id, old_sha, new_sha, compared)
```

A la Fase 2 del pipeline, `eligibility_scan.classify_commit_tabular_changes`
fa la segona crida per a cada unitat de canvi.

**El paquet no depèn del pipeline.** Les crides al Hub passen per
`call(fn, *args, **kwargs)`; el pipeline hi passa la seva política de
reintents (`functools.partial(errors.with_retry, **retry_config)`), i per
defecte la crida és directa. Les dependències internes només van cap avall:

```
pairs ─→ engine ─→ detectors ─→ columns ─→ transforms ─→ load ─→ config
  │                    │            └────→ rows ────────↗
  └─→ units            └─→ output
```

## 2. Capes i mòduls

| Capa | Mòdul | Què fa |
|---|---|---|
| L0 | `units.py`, `pairs.py` | Resol les taules de cada revisió i les aparella entre revisions |
| L1 | `load.py` | Llegeix un fitxer i en dedueix el tipus lògic de cada columna |
| L3 | `columns.py`, `transforms.py` | Aparella columnes: per nom i per contingut |
| L4 | `rows.py` | Aparella files |
| L5 | `detectors.py` | Un detector per família de codis |
| L6 | `output.py` | Taules de sortida |
| — | `engine.py` | Orquestra L1 → L3 ↔ L4 → L5 per a un parell de taules |
| — | `config.py` | Tots els llindars i decisions provisionals |

No hi ha capa L2 (perfil en caché per fitxer): vegeu §8.

### L0 — Què és una taula i amb què s'aparella

**Unitat = taula (subset, split)**, com la mostra el Hub (decisió U1).
`units.resolve_units` aplica les mateixes regles que la llibreria
`datasets` (5.0.1, versió fixada): reconstrueix l'arbre de fitxers com a
fitxers buits en un directori temporal, hi posa només la clau `configs` del
README, i crida `LocalDatasetModuleFactory`. Així:

- els shards `train-00000-of-00003`… són una sola taula;
- els fitxers d'un split amb noms numerats (episodis LeRobot) també;
- si un split té fitxers amb noms no relacionats (`distinct`), cada fitxer
  és una taula;
- queden fora, amb motiu: fitxers fora de cap split, d'un altre format que
  el majoritari, `metadata.csv` de repositoris de media, i fitxers JSON de
  metadades (`dataset_infos.json`, `meta/info.json` de LeRobot...).

Dos casos on les regles de `datasets` no n'hi ha prou:

- **Repositori de media amb taules** (LeRobot té més vídeos que parquet, i
  `datasets` el veu com a `videofolder`): els fitxers tabulars que la media
  no fa servir es resolen sols, amb les mateixes regles.
- **Repositori que `datasets` no pot resoldre**: cada fitxer tabular és
  una taula (`RepoLayout.error` en guarda el motiu). Abans no es comparava.

`pairs.pair_units` aparella per clau `subset/split`. Una taula d'un sol
fitxer que no troba parella cau a l'aparellament per fitxer: ruta igual →
mateix hash de contingut (fitxer reanomenat) → mateix nom amb una altra
extensió (canvi de format; C100 és fora d'abast, queda a `info`).

**Estat de cada parell** (sempre n'hi ha un; una fallada mai es converteix
en codis):

| Estat | Quan |
|---|---|
| `ok` | Comparat |
| `identical_content` | Mateix hash LFS / blob de git: no es descarrega |
| `absent_old`, `absent_new` | La taula no existeix en una revisió (sense codi, U2) |
| `download_failed` | Error de xarxa o del Hub després dels reintents |
| `parse_failed` | No es pot llegir, o els shards no comparteixen esquema |
| `too_large_profile_only` | Mida conjunta > `max_unit_bytes`; no es compara |
| `excluded` | Fitxer tabular que ha canviat però no forma part de cap taula (fora de cap split, un altre format, metadades); el motiu és a `detail` |

### L1 — Càrrega

`load.load_table(bytes, ext, config)` retorna una `Table`: valors, una
`Column` per columna (tipus lògic, si és entera, dtype original, tokens
d'absent, estil numèric) i el dialecte CSV.

- **CSV/TSV**: es llegeix tot com a text; `csv.Sniffer` dona el delimitador
  i si hi ha espai després del separador (el `", "` d'UCI Adult és
  dialecte, no dades). Els tokens de `missing_tokens` (`?`, `NA`, buit…)
  passen a nul i es guarden per detectar canvis de token.
- **Parquet/JSON**: tipus natius; les columnes de text també passen pels
  tokens d'absent. Una columna d'arrays d'un sol element (LeRobot desa així
  els escalars, p.e. `gripper_width`) es llegeix com a escalar. Una columna
  sense cap valor no té tipus: pren el de la columna aparellada, així que
  una columna buida que s'omple és C510, no un canvi de tipus.
- **Tipus lògic** (dels valors, no del dtype): `numeric` si tots els
  valors no nuls es poden llegir com a nombre; `text` si és text lliure
  (P6); `opaque` per a cel·les dict/list/bytes (imatges, àudio), que es
  serialitzen de forma determinista; si no, `categorical`. "Enter" ve de la
  integralitat dels valors, així una columna d'enters que guanya nuls no és
  un canvi de tipus.

### L4 — Aparellar files

`rows.align_rows` decideix quina fila nova correspon a quina d'antiga:

1. **Clau inferida**: columna única, sense nuls i amb valors compartits
   (`key_min_overlap`); es prefereixen noms tipus `id`. Un **número de
   fila** (0..n-1 o 1..n en ordre a les dues versions, p.e. `index` de
   LeRobot) no és clau: només diu la posició i es renumera quan s'afegeixen
   o s'eliminen files. Tampoc es compara com a valor (C322).
   Més en general, les **seqüències** (enters no decreixents al llarg de
   les files a totes dues versions: `index`, `episode_index`,
   `episode_data_index_from`) queden fora del hash del pas 2, perquè una
   inserció al mig les renumera a totes les files següents. Si canvien,
   surten com a C322 `renumbered`, i no entren a C520/C530.
2. Si no n'hi ha: **hash de fila** sobre les columnes "estables" (les que
   comparteixen ≥50% dels valors), amb un índex d'ocurrència per a les
   files repetides. Aparella les files idèntiques.
3. Per a les que queden: **totes les columnes menys una** (i després menys
   dues, entre les 6 que més canvien). Un aparellament parcial s'accepta
   només si la clau reduïda té el mateix nombre de files a les dues taules
   i hi ha prou coincidències per descartar l'atzar (≥ 5× les esperades per
   la taxa de col·lisió de la clau). Les files aparellades per ordre
   d'aparició dins d'un grup repetit es marquen com a **ambigües** i no
   s'usen per comparar contingut.
4. Una parella ambigua es **descarta** si no coincideix en una columna
   opaca que ha quedat fora del hash (vector, imatge): cap transformació
   no ho pot explicar, així que el hash no identificava la fila (p.e. una
   taula regravada on només `timestamp` i `frame_index` coincideixen).

Les files sense parella són C421/C422 (`all_rows` si no en queda cap).

### L3 — Aparellar columnes

`columns.py`, alternant amb L4 (`engine.diff_tables`, 2 iteracions com a
màxim): nom exacte → nom normalitzat → **contingut** sobre les files
aparellades. Una parella eliminada/afegida és la mateixa columna si una
explicació reprodueix ≥95% de les files (`column_match_min_validity`):
valors idèntics, bijecció de categories, una transformació numèrica, o el
mateix multiconjunt de valors (si té ≥20 valors distints; no cal aparellar
files). Si la versió nova és **una altra mostra de files** (p.e. Census D3,
amb part de les files noves), una columna amb ≥20 valors distints també és
la mateixa si la majoria dels seus valors distints ja hi eren
(`same_column_min_shared_values`) i la seva distribució no canvia segons el
criteri de C530 (`transforms.distribution_distance` < `c530_min_distance`). Abans es busquen codificacions one-hot. L'assignació global es
resol amb l'algorisme hongarès (`scipy.optimize.linear_sum_assignment`);
la semblança del nom només desempata.

Les columnes que queden sense parella són C221 o C222. C221 és `derived`
si depèn d'una columna existent: dependència funcional (cada valor de la
font dona un sol valor nou) o, si la font és numèrica contínua,
discretització (cada valor nou ocupa un sol interval de la font); si no,
`unexplained`. C222 és `mostly_null`, `duplicate_of:<col>` o
`unexplained`.

`transforms.py` conté els ajustos:
- **numèrics** (`fit_numeric`): identitat, min-max, estandardització,
  normalització per la suma, arrodoniment, log/sqrt/recíproc/exp, factor i
  lineal; prova de **pertorbació** (molts valors canviats poc i sense
  tendència);
- **categòrics** (`analyze_mapping`): identitat, representació (espais,
  majúscules), reetiquetatge, anonimització, fusió, divisió, edició de
  cel·les.

Per atribuir un canvi de valors a una transformació o a un mapatge de
categories (C322 `factor`, C312 `merge`...), l'explicació ha de reproduir
≥95% de les files **i** ≥95% de les files que han canviat: si no, una
columna amb molts zeros multiplicada per 1000 "s'explicaria" per la
identitat, i unes quantes cel·les editades, per un mapatge. Cal un mínim
de files canviades (`min_explained_rows`); per sota, és `cell_edits`.

### L5 — Detectors

Cada detector rep un `Context` (taules, aparellaments, config) i retorna
`Change`s. Comparen només columnes aparellades i, per a valors, només
files aparellades no ambigües.

| Detector | Codis | Criteri |
|---|---|---|
| `detect_column_set` | C210, C221, C222, C223, C311 `one_hot` | Ordre relatiu de les columnes aparellades; columnes sobrants; renoms |
| `detect_kinds` | C311, C321 | Canvi de família numèric ↔ categòric, codificat pel tipus antic (P3). C321 `real_to_integer` només si l'ajust és un arrodoniment |
| `detect_values` | C312, C322, C510 | Cel·les de files aparellades. Valor ↔ nul és C510 (P1: `imputed_constant:<mean\|median\|mode\|value>`, `masking`). Numèriques: subtipus de l'ajust, `perturbation`, `representation` (notació científica, coma decimal) o `cell_edits`. Categòriques: el tipus de mapatge (P9) |
| `detect_order` | C410 | Les files aparellades **segures** (no ambigües i fetes amb totes les columnes, no editades) canvien d'ordre: subsqüència creixent més llarga i tau de Kendall; `sorted_by:<col>` si la nova està ordenada per una columna |
| `detect_rows` | C421, C422 | Files sense parella. C421 `duplicate_of_existing`/`new`. C422 `duplicate_removed`, `had_nulls`, `outlier`, `predicate` (arbre de decisió de profunditat 2) o `unexplained` |
| `detect_missing` | C510 | Proporció de nuls de la columna: prova de dues proporcions + efecte ≥ `c510_min_rate_delta`, excepte si el canvi només ve de files afegides o eliminades (P12); canvi de token d'absent → `representation` |
| `detect_correlation` | C520 | Spearman (num-num), V de Cramér corregida (cat-cat, categories rares agrupades; no es calcula si no compleix la regla de Cochran), raó de correlació (num-cat); \|Δ\| ≥ `c520_min_delta` i prova de Fisher z p < `alpha` per a totes les mesures |
| `detect_distribution` | C530 | KS (numèriques) o variació total (categòriques) ≥ `c530_min_distance` i p < `alpha`. Salta identificadors, columnes amb canvi de tipus, text i columnes explicades per una transformació (P8); compara després d'aplicar el reetiquetatge |

**Confiança**: validesa de l'explicació (proporció de files que reprodueix)
o 1 − p de la prova; 1.0 per a fets deterministes (una columna que no hi
és). Per a C410/C421/C422 es limita per la proporció de parells no ambigus,
excepte la part segura d'un C421/C422: si la taula perd 100 files, almenys
100 són C422.
**Evidència**: el mapatge, la fórmula ajustada, els estadístics; els
codis que depenen de files aparellades hi afegeixen com s'han aparellat
(mètode, clau, proporció aparellada). Els tests de regressió comproven que
cap codi surt sense evidència ni confiança.

### L6 — Sortida

Per a cada execució de la Fase 2 (`eligibility_scan.run_classification`):

| Fitxer | Una fila per | Columnes |
|---|---|---|
| `changes_<k>.csv` / `.parquet` | canvi | `repo_id, old_rev, new_rev, file_path, old_file_path, code, column, old_column, subtype, n_affected, share_affected, confidence, evidence_json, engine_version, config_hash` |
| `change_pairs_<k>.csv` | parell de taules comparat | `repo_id, old_rev, new_rev, file_path, old_file_path, unit, status, alignment_method, key_columns, matched_row_share, format_old, format_new, detail` (`detail`: motiu d'exclusió o error) |
| `change_classification_<k>.csv` | codi per fitxer i unitat de canvi | format antic (`dataset_id, version_from, version_to, file_path, code, description, is_breaking`), derivat de `changes` |

`engine_version` i `config_hash` permeten saber amb quin motor i quins
llindars s'ha produït cada fila.

## 3. Configuració

Tots els llindars són a `config.EngineConfig` (dataclass immutable), amb el
valor per defecte i el perquè al docstring de cada camp. Per provar uns
altres valors: `dataclasses.replace(DEFAULT_CONFIG, alpha=0.05)`; el
`config_hash` de la sortida ho registra. Les decisions provisionals són
interruptors:
`null_transition_is_c510` (P1), `kind_change_by_old_kind` (P3),
`report_representation` (P5), `transformation_suppresses_c530` (P8),
`row_change_suppresses_c510` (P12).

## 4. Avaluació

`eval/` mesura el motor amb casos generats per mutació, abans i després
de cada canvi:

- `eval/mutations.py`: 47 mutacions etiquetades (codi + subtipus requerits,
  codis permesos com a efecte secundari), aplicades soles o combinades
  (1–3) sobre una taula sintètica i sobre UCI Adult, en CSV i parquet.
  Dos conjunts amb llavors disjuntes: **calibratge** (per ajustar) i
  **reservat** (per informar).
- `eval/run_eval.py`: precisió/recall per codi a nivell de cas, encerts per
  mutació i subtipus, confusions. Escriu `eval/report.md` (conjunt
  reservat, motor antic vs nou). Els resultats del motor antic són a
  `eval/baseline_old_engine.json`, desats abans de retirar-lo.

Resultats al conjunt reservat (379 casos, `eval/report.md`):

| | C221/C222 P | C223 R | C321 P | C410 R | C421 R | C510 P | C530 P | Pitjor F1 |
|---|---|---|---|---|---|---|---|---|
| Motor antic | 0.46 | 0.00 | 0.20 | 0.48 | 0.63 | 0.52 | 0.34 | 0.34 (C321) |
| Motor nou | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.98 (C422, C530) |

Subtipus: tots correctes en els casos d'una sola mutació, menys C422
`predicate` (3/6): els 3 errors eliminen **una sola** fila (la categoria
més rara de la mostra), i un predicat sobre una fila no és identificable
(se'n demanen ≥5). És un defecte de l'etiqueta del generador; no s'ha
regenerat el conjunt reservat perquè la línia base del motor antic es va
calcular sobre aquests mateixos casos.

**Census Income** (referència externa, mai usada per ajustar):
`notebooks/validate_census_income.py` compara D1–D7 amb D0 contra la
Taula 1 del paper (`tests/fixtures/census_income_labels.csv`). Resultat a
l'apartat 13.2 de `docs/architecture.md`; les discrepàncies que són
preguntes d'etiquetatge, a `docs/open_decisions.md`.

## 5. Cost

Per parell de taules de `r` files i `c` columnes, amb les dues taules a
memòria: càrrega O(r·c); aparellament de files O(r·c) per passada (hash
additiu vectoritzat), amb fins a `c` passades "totes menys una"
(limitades a `max_pairing_columns`) i 15 de "menys dues"; aparellament de
columnes O(a·e·r) per a `a` afegides i `e` eliminades; C520 O(r·c²) amb
`c ≤ c520_max_columns`. Les taules amb el mateix hash de contingut no es
descarreguen, i les que passen de `max_unit_bytes` no es comparen.

## 6. Tests

| Fitxer | Cobreix |
|---|---|
| `tests/test_diffengine_regressions.py` | Els casos FP/FN coneguts del motor antic (un test per cas) |
| `tests/test_diffengine_units.py` | Resolució de taules (shards, splits, configs, exclusions) |
| `tests/test_diffengine_pairs.py` | Aparellament entre revisions, estats, concatenació |
| `tests/test_diffengine_load.py` | Dialecte, tokens d'absent, tipus lògic |
| `tests/test_census_income_labels.py` | La fixture coincideix amb el paper; extrem a extrem amb xarxa (`RUN_NETWORK_TESTS=1`) |

## 7. Afegir un codi o canviar un llindar

- **Llindar**: només a `config.py`. El `config_hash` de la sortida canvia.
- **Detector nou**: una funció `detect_x(ctx) -> list[Change]` a
  `detectors.py`, afegida a `DETECTORS`; una mutació a `eval/mutations.py`
  amb la seva etiqueta; tornar a executar `python eval/run_eval.py --split
  calibration` i, al final, el reservat.

## 8. Límits coneguts

- **Sense perfil en caché per fitxer (L2).** Una taula que canvia es torna
  a llegir sencera a cada unitat de canvi.
- **Taules massa grans**: només estat `too_large_profile_only`, sense codis.
- **Aparellament de files sense blocking** (MinHash/LSH): una taula amb
  moltes files editades en moltes columnes alhora surt com a C421 + C422.
- **Files repetides**: si s'afegeix una còpia d'una fila i alhora se
  n'edita l'original, la fila antiga s'aparella amb la còpia (coincidència
  exacta) i no amb l'original editat; en surten un C410 i un C422 de més.
  Passa en casos combinats del conjunt de calibratge (C410 P = 0.85); al
  reservat, P = 1.00.
- **Renoms sense relació de contingut** (nom i valors canvien sense cap
  mapatge reconeixible): C221 + C222.
- **C520** només considera les primeres `c520_max_columns` columnes.
- **Columnes opaques** (vectors, imatges, àudio) participen a
  l'aparellament de files però no es comparen: un canvi dins d'un vector
  (p.e. un component d'`observation.state` que passa de NaN a valor) no
  surt com a codi.
- **Taula regravada només amb columnes escalars**: si cap columna opaca no
  desmenteix una parella ambigua, es manté (pot ser una transformació).
- **No es detecta** el canvi de patró de co-absència entre columnes.
