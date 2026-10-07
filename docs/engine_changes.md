# Motor de classificació de canvis: què ha canviat i què n'ha resultat

Resum de la reescriptura del motor que detecta canvis entre versions de
datasets tabulars (Fase 2 del pipeline), del canvi d'estratègia que hi ha
al darrere, i d'una execució real comparada amb l'última feta amb el motor
anterior. El detall tècnic de cada capa és a `docs/engine.md`; les
decisions encara provisionals, a `docs/open_decisions.md`.

---

## 1. En una frase

El motor anterior (`change_diff.py`) comparava **fitxers** pel **nom de
les columnes** i el **recompte de files**. El nou (`src/diffengine/`)
compara **taules** aparellant **columnes i files pel contingut**, i explica
cada canvi amb un subtipus, una evidència i una confiança. En casos
generats, el pitjor F1 per codi passa de 0.34 a 0.98.

## 2. Per què calia canviar d'estratègia

L'auditoria del motor anterior (`docs/historic/engine_audit.md`) va mostrar que els
errors no eren de llindars mal triats, sinó de com estava plantejat:

| Problema del motor anterior | Conseqüència |
|---|---|
| Columnes comparades només pel nom | Un renom amagava qualsevol canvi de valors; C223 no es detectava mai (recall 0) |
| Files sense aparellar: C421/C422 era el signe de `n_nou − n_antic` | Afegir 10 files i eliminar-ne 10 no era cap canvi |
| Tipus segons el `dtype` de pandas | Una columna entera que guanyava un nul "canviava de tipus" (C321) |
| Identificadors tractats com a variables | C322/C520/C530 falsos a columnes `id` |
| Unitat = fitxer, màxim 5 per commit | Un dataset partit en shards o episodis sortia com fitxers sencers afegits i eliminats |
| Una descàrrega fallida = fitxer inexistent | Errors de xarxa convertits en C421/C422 |

## 3. L'estratègia nova

| | Abans | Ara |
|---|---|---|
| **Què es compara** | Fitxer a fitxer (màx. 5 per commit) | Taula (subset, split) com la mostra el Hub, amb les regles de la llibreria `datasets`; els shards es concatenen |
| **Tipus d'una columna** | `dtype` de pandas | Deduït dels valors (numèric, categòric, text, opac) |
| **Columnes** | Per nom | Per nom, nom normalitzat i **contingut** (valors idèntics, bijecció, transformació numèrica, one-hot), amb assignació global (algorisme hongarès) |
| **Files** | Recompte | **Aparellament**: clau inferida o hash de fila, amb tolerància a 1–2 cel·les editades |
| **Valors** | Estadístics agregats amb un 5% de tolerància | Comparació cel·la a cel·la sobre files aparellades i ajust de transformacions (factor, log, min-max, estandardització...) |
| **Sortida** | Codi per fitxer | Codi + subtipus + columna + files afectades + confiança + evidència, i un **estat** per a cada parell de taules |
| **Llindars** | Dispersos pel codi | Tots a `config.py`; el hash de la configuració es desa a cada fila |
| **Com es valida** | Census Income (7 versions) | Arnès de mutacions amb conjunt de calibratge i conjunt reservat, més Census Income com a referència externa |

Un canvi de criteri important: **una taula que apareix o desapareix
sencera no és C421/C422** (afegir o eliminar files d'una taula que
existeix), sinó un estat `absent_old`/`absent_new` (decisió U2).

## 4. El motor com a paquet únic

Tot el motor és `src/diffengine/` (11 mòduls, uns 2.100 línies). En
aquesta última iteració s'ha unificat:

**Sense dependències d'entrada i sortida.** Abans, `diffengine/pairs.py`
importava el mòdul `errors` del pipeline, i el pipeline importava
`diffengine`: una dependència circular entre paquets. Ara el motor rep la
política de reintents com a paràmetre (`call`), i no importa res del
pipeline. Dins del paquet, les dependències només van cap avall i no hi ha
cicles (comprovat amb una anàlisi de l'AST):

```
pairs ─→ engine ─→ detectors ─→ columns ─→ transforms ─→ load ─→ config
  │                    │            └────→ rows ────────↗
  └─→ units            └─→ output
```

**Sense codi duplicat.** S'han unificat en una sola implementació:

| Duplicat | Ara |
|---|---|
| Solapament de valors (multiconjunt) calculat a `columns` i a `rows` | `rows.value_overlap` |
| "Valors d'una columna a les files aparellades", escrit dues vegades | `rows.paired_values` |
| Mapa de valors dominants (endavant/enrere) a `analyze_mapping` i `is_bijection` | `transforms._dominant_maps` |
| Tres maneres de detectar un nul, i el token `"\x00null"` repetit | `load.is_missing`, `load.NULL_TOKEN` |
| Llista de columnes de sortida a `eligibility_scan` i a `output` | `output.CHANGE_COLUMNS` |
| Llista de codis a `experiments/run_eval.py` | `output.TABULAR_CODES` |
| Llistar una revisió del Hub a `experiments/survey_units.py` | `pairs.list_revision` |
| Funció privada (`_norm_repr`) importada des d'un altre mòdul | `transforms.normalize_value`, pública |
| Diccionari identitat `_FIT_SUBTYPE` | un conjunt |

**Sense codi mort.** S'han eliminat `change_diff.py` i els seus tests,
`EngineConfig.from_yaml` (cap crida; per provar uns altres llindars:
`dataclasses.replace(DEFAULT_CONFIG, ...)`), el paràmetre `exclude`
d'`align_rows`, i els imports dins de funcions de `pairs.py`. Les úniques
importacions diferides que queden són deliberades: `datasets` i
`scikit-learn` són pesades i només les fa servir una funció.

**Punts d'entrada.** Dos fitxers: `engine.diff_bytes`. Dues revisions d'un
repositori: `pairs.compare_revisions` + `pairs.revision_rows`.

## 5. Errors trobats en executar-lo amb dades reals

La primera execució real del motor nou (mateixa entrada que `run_8`) va
destapar vuit problemes que els casos generats no cobrien. Cadascun s'ha
verificat obrint les dades, s'ha corregit i té el seu test:

| # | Què passava | Causa | Correcció |
|---|---|---|---|
| 1 | Repositoris LeRobot (500 episodis parquet) **no es comparaven** | `datasets` tria un sol format per repositori; amb més vídeos que parquet, el veu com a `videofolder` i deixa fora totes les taules | Les taules que la media no fa servir es resolen soles, amb les mateixes regles (P11) |
| 2 | Repositoris amb `dataset_infos.json` no es resolien | El fitxer buit que el motor crea per simular l'arbre fa fallar `datasets` en llegir-lo | Les metadades JSON no es recreen i no es consideren taules |
| 3 | Si `datasets` fallava, el repositori es descartava en silenci | — | Cada fitxer tabular passa a ser una taula; el motiu queda a `RepoLayout.error` |
| 4 | `stlee601/cube_pick1`: C322 "pertorbació" a `episode_index` | La columna `index` (0..n-1) es va prendre com a clau; en inserir episodis es renumera i aparella frames diferents | Un número de fila no és clau. Les seqüències (`index`, `episode_index`...) no entren al hash de fila; si canvien, C322 `renumbered`; no entren a C520/C530 (P10) |
| 5 | `gripper_width` (LeRobot) no es comparava | LeRobot desa els escalars com a arrays d'un element, i es llegien com a cel·les opaques | Els arrays d'un element es llegeixen com a escalars |
| 6 | `nuoyihan/...`: 1.011 files "aparellades" en una taula regravada | Només `timestamp`/`frame_index` coincidien, i es repeteixen a cada episodi | Una parella ambigua es descarta si no coincideix en una columna opaca (vector, imatge), cosa que cap transformació no pot explicar |
| 7 | C422 amb confiança 0 quan la taula perdia 12.919 files | La confiança es limitava per les parelles ambigües, encara que el recompte sigui segur | La diferència de recompte és segura; només la resta depèn de l'aparellament. Subtipus `all_rows` si no queda cap fila |
| 8 | C520 amb V de Cramér de 0.0 → 0.77 per 5 files | Només hi havia prova de significació per a parells numèrics; amb categories molt petites la V no és fiable | Prova de Fisher z per a totes les mesures, i regla de Cochran (comptes esperats ≥ 5) per a la V de Cramér |

També s'ha afegit l'estat `excluded`: els fitxers tabulars que han canviat
però no formen part de cap taula (p.e. `meta/episodes.jsonl` de LeRobot)
queden registrats amb el motiu, com deia la decisió U1 i el codi encara no
feia.

Cap d'aquestes correccions canvia els resultats de l'avaluació (§6.1), i
Census Income tampoc no varia: els casos que corregeixen només apareixen
en dades reals.

## 6. Resultats

**Com es llegeixen les mètriques.** Per a cada codi es compta: vertader
positiu (TP) si el motor el detecta i hi és; fals positiu (FP) si el
detecta i no hi és; fals negatiu (FN) si hi és i no el detecta.

- **Precisió** = TP / (TP + FP): de tot el que el motor diu, quina part és
  correcta.
- **Recall** = TP / (TP + FN): de tot el que hi ha, quina part troba.
- **F1** = mitjana harmònica de totes dues: només és alta si les dues ho
  són. Un motor que no digués mai res tindria precisió perfecta i recall 0.

### 6.1 Casos generats (conjunt reservat, 379 casos)

Mutacions etiquetades aplicades a una taula sintètica i a UCI Adult; el
conjunt reservat no s'ha fet servir mai per ajustar. Detall a
`experiments/report.md`.

| Codi | Motor anterior F1 | Motor nou F1 |
|---|---|---|
| C210 | 1.00 | 1.00 |
| C221 / C222 | 0.63 / 0.63 | 1.00 / 1.00 |
| C223 | — (recall 0) | 1.00 |
| C311 / C312 | 0.68 / 0.83 | 1.00 / 1.00 |
| C321 / C322 | 0.34 / 0.84 | 1.00 / 1.00 |
| C410 | 0.65 | 1.00 |
| C421 / C422 | 0.73 / 0.86 | 1.00 / 0.98 |
| C510 | 0.69 | 1.00 |
| C520 / C530 | 0.67 / 0.51 | 1.00 / 0.98 |

### 6.2 Census Income (Taula 1 del paper)

| | Precisió | Recall | F1 |
|---|---|---|---|
| Motor anterior | 64,5% | 76,9% | 70,2% |
| Motor nou, primera versió | 61,0% | 96,2% | 74,6% |
| Motor nou, després de revisar els FP | 71,4% | 96,2% | 82,0% |
| **Motor nou, amb les dades del paper** | **75,8%** | **96,2%** | **84,7%** |

Detall complet: `docs/census_income_paper_method.md`. En resum:

1. **Les dades.** El paper no diu quin fitxer, revisió ni part de la UCI
   va fer servir. Un experiment (`experiments/census_variants.py`) ho ha provat
   tot i ha mirat d'on surten les files: D1, D2 i D5 són còpies
   d'`adult.data`; D3, D4, D6 i D7 són mostres d'`adult.data` +
   `adult.test`. Cada versió es compara ara amb la publicació de la qual
   surt.
2. **El mètode del paper.** Les etiquetes vénen de la targeta de cada
   repositori i d'una inspecció manual; els canvis que la targeta no
   documenta no hi són.
3. **Canvis al motor**, tots justificats pel text del paper (§4), no per la
   taula:
   - renom sobre una altra mostra de files (`fnlwgt` → `final_weight`);
   - l'ordre (C410) només es jutja amb parelles de files segures;
   - un canvi de tipus que és una bijecció entre valors (codificar
     categories com a enters) també és C312 `recoded`;
   - **no** s'oculta C510 quan els nuls canvien per files eliminades: el
     text diu que es reporta (la decisió P12, que ho ometia per coincidir
     amb la taula, s'ha retirat).

Els 9 desacords que queden (8 FP, 1 FN) són canvis reals que la targeta no
documenta o casos on la taula no aplica el mateix criteri a versions
equivalents; cap no és un error del motor.

### 6.3 Execució real: `run_11` (motor nou, 2.3.0) contra `run_8` (motor anterior)

Mateixa entrada (`data/run_8/eligibility_report_2000_8.csv`, 11 datasets
elegibles) i mateixes versions (els dos `versions_*.csv` són idèntics).
Ordre: `python src/run_pipeline.py --input-csv
data/run_8/eligibility_report_2000_8.csv`. Un minut i mig amb la caché de
Hugging Face plena (uns 2,5 minuts la primera vegada).

| | `run_8` (anterior) | `run_11` (nou) |
|---|---|---|
| Datasets amb algun resultat | 3 | 7 amb parells de taules, 3 amb canvis |
| Què es compara | Fins a 5 fitxers per unitat de canvi | 78 parells: 10 comparats (`ok`), 33 sense canvis (`identical_content`, sense descarregar), 14 taules que apareixen o desapareixen, 21 fitxers exclosos amb motiu |
| Canvis | 30 etiquetes | 35 canvis amb subtipus i evidència (23 files al CSV en format antic) |

Execucions anteriors amb la mateixa entrada: `data/run_9` (motor 2.1.0) i
`data/run_10` (2.2.0). Respecte a `run_9` desapareix un C321 fals
(`ckwolfe`, una columna buida que s'omple) i el C510 de `gripper_width` passa
de `rate` a `imputed`. `run_10` ometia dos C510 de `ckwolfe` (P12, ja
retirada).

Unitat de canvi per unitat de canvi (només les que tenen alguna diferència;
les comprovacions s'han fet obrint els fitxers):

| Dataset | Versions | Motor anterior | Motor nou | Què hi ha a les dades |
|---|---|---|---|---|
| `stlee601/cube_pick1` | cf5046c→1addd3a | C322, C421, C530 | C421 `new` (2.881 files); C510 `imputed` (`gripper_width`); C322 `renumbered` × 3 | **5 episodis inserits al mig** (2.881 frames) i el valor de la pinça, abans NaN a totes les files, ara informat. Els comptadors (`episode_index`...) es renumeren a partir de la inserció. El nou ho descriu tot; l'anterior no deia quines files ni per què |
| `nuoyihan/eval_lerobot-pick-red-pen` | c304fd4→01f8557 | C210, C221, C322×2, C422×2, C520, C530×2 | C422 `all_rows` (13.930); C421 `new` (1.011); C530 × 2 | **Taula regravada**: 70 episodis de 199 frames passen a 6 episodis de ~169 frames, amb vectors nous. La taula de dades té les mateixes columnes a totes dues versions (comprovat), així que el C210 i el C221 de l'anterior havien de venir d'un altre fitxer del commit, probablement les metadades (`meta/*.parquet`), que al nou surten com a `excluded` |
| `nuoyihan/...` | 3 unitats més | C421×8, C422×5 | `absent_old` / `absent_new` | Conversió de format LeRobot: es treuen tots els episodis en un commit i s'afegeix un fitxer únic en un altre. Són taules senceres, no files (U2) |
| `Ray0v0/cl-piper-single-stack-bowls` | a1d4e69→f81ff5e | C421×5 | `absent_old` (taula de 500 episodis) | La primera versió és un repositori buit. L'anterior en veia 5 fitxers (el límit); el nou hi veu una taula nova sencera |
| `ckwolfe/benchmarks-viz-tiles` | 7 unitats | — | C421 × 5, C422, C510 × 4, C520 × 13, C530 × 2, C221 | Taules de resultats de benchmark en `.jsonl`, que el motor anterior no llegia. Les files afegides i els canvis de nuls són directes de verificar; **els C520 no s'han revisat un per un** |
| `phospho-app/grasp_red_50_bboxes` | cda949d→8a4c6e4 | — | `ok`, cap canvi | Fitxers tornats a pujar (hash diferent) amb les mateixes files: 100% aparellades |
| `kimyg119/...`, `younghyopark/...` | 4 unitats | — | `absent_*`, `identical_content`, `excluded` | Conversió LeRobot (com `nuoyihan`) i re-pujades sense canvis |

**Lectura.** On tots dos motors diuen alguna cosa, el nou encerta el
*què* (episodis inserits, taula regravada, valors informats) i l'anterior
només en donava el signe. El nou, a més, cobreix dades que l'anterior no
veia (`ckwolfe`, els 500 episodis de `Ray0v0`) i deixa constància de tot el
que no compara.

## 7. Límits i preguntes obertes

- **Vectors i imatges no es comparen** (només serveixen per aparellar
  files): a `stlee601`, el component de la pinça dins
  d'`observation.state` també canvia i no surt com a codi.
- **Els C520 de taules petites** han passat a tenir prova estadística,
  però els de `ckwolfe` no s'han verificat a mà.
- **Fitxers de metadades de LeRobot** (`meta/episodes.jsonl`...): ara
  surten com a `excluded`. Si s'han de classificar, és una ampliació de la
  decisió U1.
- **C410 amb files duplicades i editades alhora**, i **C422 `predicate`**
  quan s'elimina una sola fila: vegeu `docs/engine.md` §8.
- Decisions noves que cal confirmar: **P10** (comptadors de posició),
  **P11** (taules dins de repositoris de media) i **P13** (C312 `recoded`
  en codificar categories), a `docs/open_decisions.md`.

## 8. Com reproduir-ho

```bash
pytest                                            # 214 tests, sense xarxa
python experiments/run_eval.py                           # experiments/report.md (reservat, antic vs nou)
python src/validate_census_income.py        # Census Income
python experiments/census_variants.py                    # quines dades va fer servir el paper
python src/run_pipeline.py --input-csv data/run_8/eligibility_report_2000_8.csv
```

Cada fila de `changes_<k>.csv` porta `engine_version` (2.3.0) i
`config_hash`, per saber amb quin motor i quins llindars s'ha generat.
