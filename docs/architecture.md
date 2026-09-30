# Arquitectura — HF Dataset Version Analysis

## Visió general

Pipeline de recerca (TFG) que respon: *com canvien els datasets de
Hugging Face entre versions successives?* Es divideix en 4 fases
seqüencials, cadascuna amb el seu propi mòdul de codi i el seu epic a
Taiga (`docs/taiga/taiga_user_stories.md`).


```
Fase 0            Fase 1              Fase 2                 Fase 3
Mostreig i    →   Extracció de   →    Classificació de   →   Data warehouse
elegibilitat      versions            canvis (taxonomia)     i anàlisi

eligibility_      version_          change_diff.py           warehouse/
scan.py           extractor.py      (motor + classificador)  (a decidir:
errors.py                                                    DuckDB/Postgres)
```

## Fase 0 — Mostreig i elegibilitat (`eligibility_scan.py`, `errors.py`)

La fase inicial del pipeline, on es realitza un estudi amb repositoris aleatoris de HF (no per popularitat) de una
mida sampling indicada (normalment 2000 s'ha trobat que és una mida significativa) per trobar repositoris elegibles.
Aquesta elegibilitat 

### Flux

1. `iter_all_dataset_ids()` — genera ids de tota la població de HF
   (~950K), amb `expand=["disabled"]` per minimitzar payload i descartar
   datasets `disabled` sense cap crida addicional.
2. `reservoir_sample_dataset_ids()` — algorisme R de Vitter sobre el
   generador anterior. Mai materialitza la població a memòria. Mode
   `--max-scanned` disponible només per a proves (esbiaixa la mostra,
   documentat com a tal).
3. `classify_dataset()` — per cada id de la mostra, avalua elegibilitat:
   - **Criteri A**: ≥2 tags de Git **amb** ≥2 commits substantius
     associats (evita comptar tags "buits" sense canvi real).
   - **Criteri B** (fallback): ≥2 branches i ≥2 commits substantius
     **separats en el temps ≥6h** (`MIN_SUBSTANTIVE_GAP_HOURS`).
   - Un commit es considera substantiu si toca fitxers de dades reals
     (`determine_commit_substantive`, US-302: clonatge "bare" local +
     `git show --name-status`, amb fallback a l'heurística de títol
     `is_substantive_commit` si el clonatge falla -- **cal `git`
     instal·lat al sistema/imatge**, vegeu nota de bug de Docker més
     amunt). Un fitxer concret es considera substantiu segons
     `is_substantive_path` (prefix de ruta + extensió, vegeu secció
     "Detecció de fitxers substantius" més avall).
   - Mode `--tags-only`: només permet elegibilitat via Criteri A (el
     Criteri B mai s'avalua), però segueix verificant els commits
     substantius (`list_repo_commits` + clonatge) -- només estalvia
     crides quan `tags < 2` (cas en què cap criteri pot aplicar-se).
4. `write_results()` — CSV + JSON amb `FunnelCounts`/`compute_funnel_stats`
   (dues mètriques diferenciades: `eligible_proportion` i
   `eligible_proportion_of_attempts`, vegeu decisió D-de-disseny més avall).


Sobre la mostra original de 13 elegibles (n=1000), la validació manual (`docs/us108_validation_report.md`, versió històrica) va trobar una precisió de 5/13 ≈ 38.5%, amb 8/13 falsos positius. Això va motivar a dues millores:

1. **Dispersió temporal mínima al Criteri B** (`MIN_SUBSTANTIVE_GAP_HOURS`,
   actualment 6h, entre el commit substantiu més antic i el més recent).
2. **Detecció real de fitxers per commit (US-302)**, en lloc de
   l'heurística de títol: clonatge "bare" + filtratge de blobs
   (`bare_clone`/`get_changed_files`/`determine_commit_substantive`),
   amb fallback a l'heurística de títol si el clonatge falla.


### Detecció de fitxers substantius: de denylist pura a allowlist+prefix (agost 2026)

**Problema detectat**: `is_substantive_path()` (US-302) determinava si un
fitxer era substantiu amb una única llista negra de noms exactes
(`NON_SUBSTANTIVE_FILES`): tot el que NO hi era explícitament es
considerava substantiu per defecte ("fail-open total"). Aquest disseny és
estructuralment incapaç de ser complet -- un denylist enumera exclusions
d'un espai obert (qualsevol nom de fitxer possible), així que sempre hi
ha convencions noves que se n'escapen (`CARD.md`, `pyproject.toml`,
`changelog.json`, etc.).

**Calibratge empíric** (4 datasets reals clonats i inspeccionats:
`AG42/lerobot_dataset_try1`, `villekuosmanen/close_shoebox`,
`unitreerobotics/G1_Dex3_ObjectPlacement_Dataset`,
`AndreaBozzo/ceres-open-data-index`): es va explorar fer servir la MIDA
del fitxer com a desempat per a extensions ambigües (`.json`/`.txt`),
llegint la mida real via el punter LFS (el "blob" que git guarda per a un
fitxer LFS és només ~130 bytes de text amb un camp `size:`, així que
llegir-lo no trenca la garantia de "mai descarregar dades reals" de
`bare_clone`). **Resultat descartat**: la mida NO separa bé metadada de
dades reals -- fitxers de metadades poden ser MÉS GRANS que fitxers de
dades genuïns del mateix dataset (`meta/episodes_stats.jsonl` de
villekuosmanen pesa 393KB, més que la majoria dels
`data/chunk-*/episode_*.parquet` del mateix dataset; `meta/episodes/
chunk-000/file-000.parquet` d'unitreerobotics pesa 482KB, també metadada
tot i l'extensió `.parquet`). El senyal que SÍ va separar-ho de forma
consistent en els 4 datasets: el **prefix de la ruta** (`meta/` conté
sempre metadada, `data/`/`videos/` sempre contingut real).

**Disseny final** (`NON_SUBSTANTIVE_PATH_PREFIXES`,
`NON_SUBSTANTIVE_EXTENSIONS`, `SUBSTANTIVE_DATA_EXTENSIONS`,
`NON_SUBSTANTIVE_FILES`), en ordre de decisió dins `is_substantive_path`:
1. Prefix de ruta a `meta/`/`meta_data/`/`.github/` → NO substantiu,
   **independentment de l'extensió** (comprovat abans que l'extensió a
   propòsit: un `.parquet` sota `meta/` és metadada, no dades).
2. Nom exacte a `NON_SUBSTANTIVE_FILES` (inclou `changelog.json`, trobat
   al calibratge), o extensió a `NON_SUBSTANTIVE_EXTENSIONS` (`.md`,
   `.yml`, `.yaml`, `.toml`, `.cfg`, `.ini`, `.lock` -- generalitzat per
   extensió, no només `README.md`/`setup.cfg` un per un) → NO substantiu.
3. Extensió a `SUBSTANTIVE_DATA_EXTENSIONS` (parquet, csv, arrow, tensors,
   multimèdia, arxius) → substantiu.
4. Qualsevol altre cas (p.e. `.json`/`.txt` fora de `meta/`, o una
   extensió no prevista) → substantiu per defecte (fail-open), però
   registrat (`log.debug`) perquè es pugui revisar i ampliar les llistes
   amb dades reals més endavant, en lloc d'endevinar-les.


### Gestió d'errors (`errors.py`)

- `with_retry()`: backoff exponencial + jitter. 4 estratègies avaluades
  empíricament (cap / fixa / exp. sense jitter / exp. amb jitter); la
  quarta és la implementada (429 reduïts de ~59% a ~0%).
- `ErrorCategory`: `RATE_LIMITED`, `ACCESS_RESTRICTED` (403, sense
  reintent — condició permanent), `NOT_FOUND`, `TRANSIENT`, `UNKNOWN`.
- `data/failures.csv`: registre estructurat separat del report principal,
  auditable a posteriori.

### Decisions de disseny clau (detall complet a `docs/taiga/decisions_tfg.txt`)

- Reservoir sampling en lloc d'ordenar per popularitat (biaix documentat).
- Error 403 exclòs tant del reintent com del denominador de `eligible_proportion`.
- Full-scan de tota la població NO és viable sense pla de pagament de HF
  (rate limiting); només s'implementa el mode mostreig.
- Mida de mostra per defecte: 2000 (±0.51pp, 95% confiança, p=0.0137
  observat a N=949.991).

### Resultats d'execucions reals

| Execució | Mostra | Població | Elegibles | Accés restringit | Proporció | Millores actives |
|---|---|---|---|---|---|---|
| `eligibility_report_1000_3` (baseline històric, esborrat de `data/`, vegeu historial de git) | 1000 | 949.991 | 13 | 49 | 1.37% | Cap (pipeline original, pre-US-302) |
| `eligibility_report_2000_2` | 2000 | 979.377 | 11 | 74 | 0.58% | Només dispersió temporal (bug de Docker) |
| `eligibility_report_2000_3` | 2000 | 979.480 | 12 | 87 | 0.63% | Totes dues, però amb el llindar antic de 24h |
| **`eligibility_report_2000_5` (execució de referència vigent)** | 2000 | 1.019.447 | 11 | 79 | 0.58% | Totes dues, llindar de 6h ja actiu (elegibilitat i informe) |

La proporció d'elegibles (~0.6%) es manté estable entre totes les
execucions amb dispersió temporal activa, molt per sota del baseline
històric (1.37%): la major part de la reducció ve de la dispersió
temporal, i la detecció real de fitxers (US-302) afina encara més la
qualitat de la classificació. Precisió automàtica (`docs/
us108_validation_report.md`, comprovació de sessions només per al Criteri
B, llindar unificat a 6h): **11/11 = 100%** sobre `eligibility_report_
2000_5` (referència vigent, única execució amb el llindar de 6h actiu
també per a l'elegibilitat -- no només per a l'informe), molt per sobre
del 38.5% del baseline històric. Cada dataset elegible d'aquesta execució
té una fitxa a `data/versions_1.csv` (Fase 1, vegeu més avall): 3 via
Criteri A (tags), 8 via Criteri B (sessions de commits). (Els percentatges
de 81.8%/83.3% citats en versions anteriors d'aquest document es van
calcular amb metodologies intermèdies de l'informe (llindar de sessió
d'1h, o comprovació de sessions aplicada també al Criteri A) ja
corregides -- no comparables directament.)


## Mida de la mostra i interval de confiança

L'objectiu és estimar, amb un 95% de confiança, la proporció de datasets de
HF que són elegibles (≥2 versions reals). Una execució real i no esbiaixada
(`--sample-size 1000`, sense `--max-scanned`) va donar:

| Mètrica                | Valor          |
|-------------------------|----------------|
| Població escanejada (N) | 949.991        |
| Elegibles                | 13             |
| No elegibles             | 938            |
| Accés restringit (403)   | 49             |
| Errors                   | 0              |
| Proporció elegible (p)   | 0.0137 (1.37%) |

Aquesta p observada és molt més baixa que les proves ràpides amb
`--max-scanned` (~10-17%), perquè `list_datasets()` no retorna els datasets
en ordre aleatori: capar l'escaneig als primers N esbiaixa la mostra. Només
un escaneig complet (sense `--max-scanned`) dona una p fiable.

Amb aquesta p (en lloc de l'assumpció conservadora p=0.5, que sobredimensiona
molt la mostra necessària quan la proporció real és petita), la mida de
mostra necessària per a un marge d'error E amb 95% de confiança és
n = z²·p·(1-p)/E² (z=1.96):

| Marge d'error (E) | n necessària |
|---|---|
| ±1.0 punts percentuals | ~520 |
| ±0.5 punts percentuals | ~2.070 |
| ±0.3 punts percentuals | ~5.730 |

Per això el valor per defecte de `--sample-size` és **2000**: marge d'error
±0.51pp (interval aprox. [0.86%, 1.88%]), doblant la precisió respecte a
n=1000 (±0.72pp) per només el doble de cost de classificació (~2 minuts amb
4 threads). La correcció per població finita és negligible en aquest rang
(fracció de mostreig < 0.6%).

## Fase 1 — Extracció de versions (`version_extractor.py`)

**Estat: implementat (US-201 + US-202).** Objectiu: per cada dataset
elegible de `eligibility_report_2000_5.csv` (execució de referència),
obtenir la seqüència completa i ordenada de versions amb metadades (data,
autors, mida aproximada), reutilitzant `errors.py` (mateix sistema de
retry/classificació d'errors que Fase 0).

**Ampliació d'abast respecte al text original de US-201/US-202**: la
majoria de la població elegible (8/11 a `eligibility_report_2000_5.csv`,
~70%) ho és via Criteri B i NO té cap tag de Git -- una implementació
literal de "llistar tags" hauria deixat buida la majoria de la població.
En lloc de restringir l'abast a només els datasets amb tags (Criteri A) i
deixar la resta per a una user story futura, es va decidir ampliar l'abast
immediatament: el concepte de "versió" es defineix segons quin criteri va
fer elegible el dataset (reutilitzant `eligibility_reason`, sense
recalcular el criteri):

- **Criteri A** (tags explícits): cada TAG és una versió (US-201 literal).
  `GitRefInfo.target_commit` dona el SHA directament, sense cap crida
  extra per resoldre tag -> commit.
- **Criteri B** (sense tags): cada SESSIÓ de treball és una versió
  inferida, reutilitzant `eligibility_scan.cluster_commit_times` -- LA
  MATEIXA lògica ja validada a US-108 (buit > `MIN_SUBSTANTIVE_GAP_HOURS`
  entre commits substantius consecutius), no una reimplementació.

Cada fila de sortida porta un camp `version_source` (`"tag"` o
`"commit_session"`) explícit: el nivell de confiança NO és el mateix (un
tag és un senyal deliberat del mantenidor; una sessió és una heurística
inferida, amb les mateixes cauteles que el Criteri B a
`docs/us108_validation_report.md`).

**Limitació coneguda**: `huggingface_hub` no distingeix autor de
committer com el git natiu -- `GitCommitInfo.authors` (`list[str]` de
noms d'usuari) és l'únic camp disponible. El camp `authors` de la sortida
reflecteix aquesta limitació de l'API, no una decisió de disseny propia.

**Detall tècnic rellevant**: `list_repo_tree` (usat per a `approx_size_
bytes`, via `RepoFile.size` -- ja la mida real, resolta per a LFS, sense
cap tècnica de lectura de punter) és un GENERADOR lazy: la crida HTTP no
es fa en cridar-lo, només en iterar-lo. Es passa embolicat en un tancament
de mida zero que el consumeix SENCER (`list(...)`) dins de la crida
reintentada (`errors.with_retry`), perquè un error no es perdi fora del
`try/except` de `with_retry` sense cap reintent (vegeu el comentari
"DISSENY" a `version_extractor.fetch_tree_size_bytes`).

**Sortida**: `data/versions_<run_id>.csv` (una fila per versió; columnes
`dataset_id`, `version_label`, `version_order`, `version_source`,
`commit_sha`, `commit_date`, `authors`, `approx_size_bytes`,
`session_commit_count`, `status`) i `data/versions_summary_<run_id>.json`
(resum de l'execució). Execució real sobre `eligibility_report_2000_5.csv`
(11 datasets elegibles): 40 versions extretes, 0 fallades de dataset
sencer, cap sessió buida (coherent amb l'elegibilitat original via
Criteri B, que ja exigia >=2 commits substantius dispersos).

### Inventari d'extensions i repositoris multifitxer (`extension_report.py`, VE3)

Ens interessa aber quin percentatge dels fitxers dels
repositoris JA elegibles és tabular (i per tant classificable amb la
taxonomia) i sobre quants d'aquests elegibles s'aplicarà realment la
classificació de canvis -- una pregunta prèvia a la Fase 2, que respon
"quant pesa" l'exclusió dels binaris abans d'arribar-hi.

**Funcions implementades**:
- `version_extractor.fetch_tree_paths(dataset_id, hf_token, retry_config)`
  -- llista TOTS els fitxers de la revisió més recent d'un repositori
  (`list_repo_tree`, generador lazy consumit sencer dins `errors.
  with_retry`, mateix patró que `fetch_tree_size_bytes`).
- `extension_report.build_extension_report(input_csv, hf_token, retry_config)`
  -- llegeix els elegibles del CSV d'entrada i agrega, PER EXTENSIÓ (no
  per dataset), quants fitxers hi ha sobre TOTS els elegibles junts.
- `extension_report._file_extension(path)` -- extensió en minúscules, amb
  cas especial per a `.tar.gz` (`os.path.splitext` per si sol donaria
  `.gz`).

**Resultats** (execució real sobre els 7 elegibles vigents,
`data/eligibility_report_2000_7.csv`): 480 fitxers en total, 135
tabulars (28.12%), **7/7 elegibles amb almenys un fitxer tabular**
(`n_eligible_with_tabular_files` -- el nombre de datasets sobre els quals
s'aplicarà realment la Fase 2).

**Problemes i solucions**:
- **Disseny inicial massa granular**: la primera versió produïa una fila
  per `(dataset_id, extensió, is_tabular, is_substantive)` -- una taula
  amb tots els elegibles, no el que calia. Redissenyat a una fila per
  extensió (`file_count`, `pct_of_total`, `is_tabular`), eliminant el
  desglossament `is_substantive` (depèn del prefix de la ruta, no de
  l'extensió, i no aportava res a aquesta pregunta concreta).
- `version_extractor.py` ja no escriu `versions_summary_<run_id>.json` --
  el CSV sol és suficient i el JSON no s'utilitzava enlloc.

## Fase 2 — Classificació de canvis / taxonomia (US-301/US-302/US-304/US-305 fetes; US-303 en curs)


### Taxonomia (font: paper del director, `docs/taiga/taxonomy.md`)

15 codis finals, agrupats en 5 perspectives. **Important**: la taxonomia
anterior (mapa mental informal) queda **substituïda** per aquesta versió
codificada i validada amb un cas real (Census Income, 9 versions de HF).

| Codi | Descripció |
|---|---|
| C100 | Dataset metadata (source, license, file format, delimiter...) |
| C210 | Columns order |
| C221 | Add column |
| C222 | Remove column |
| C223 | Rename column |
| C311 | Categorical column type |
| C312 | Categorical column values |
| C321 | Numerical column type |
| C322 | Numerical column values |
| C410 | Rows order |
| C421 | Add row |
| C422 | Remove row |
| C510 | Missings |
| C520 | Correlation |
| C530 | Data distribution |

### Decisió d'abast (US-303)

La taula binària original (7 codis "schema-level, sense descarregar
dades" vs 8 "content-level") simplificava massa. Només C100 és
realment metadada pura (API REST, zero accés al fitxer). Substituïda per
**3 nivells**:

| Nivell | Codis | Cost | Mecanisme |
|---|---|---|---|
| 1 — Metadada pura | C100 | ~0 | API REST (`DatasetInfo`, dataset card) |
| 2 — Lectura parcial (schema) | C210, C221, C222, C223, C311, C321 | Baix, constant | Capçalera CSV / footer Parquet (`pyarrow`, lectura per rangs) |
| 3 — Contingut complet | C312, C322, C410, C421, C422, C510, C520, C530 | Proporcional a la mida | Lectura del fitxer, idealment només les columnes rellevants |

**Viabilitat del Nivell 3, calculada amb dades pròpies** (`data/
versions_1.csv`, no una suposició): 11 datasets elegibles, 29 parells de
versions consecutius, **151.4 GB** si es baixa el contingut complet de
cada versió un cop (`edinburghcstr/ami` sol, 78GB). "Població petita" en
NOMBRE (11) no vol dir petita en BYTES.

**Hipòtesi provada i descartada**: exclusió de datasets amb >500 commits
(Castaño et al. 2025, `docs/paper_techniques_ml_models_change.md` §3) com
a manera de descartar-ne els més pesats. Comptat el nombre REAL de
commits dels 11 elegibles (no el comptador capat a 50 de
`classify_dataset`): màxim 25 (`QFIN/FCMBench-Data`) — cap s'acosta a
500, i no hi ha correlació amb el pes (`edinburghcstr/ami`, el més pesat,
només en té 20). Val la pena implementar aquesta guarda com a millora
general (encara no feta), però no resol aquest problema.

**Estratègia recomanada**: Nivell 1+2 sempre; Nivell 3 amb lectura
selectiva **per columna** (projecció Parquet) en lloc del fitxer sencer
— la major part dels 151GB són columnes binàries (àudio/vídeo/tensors)
que no fan falta per a recompte de files/missings/distribució d'UNA
columna. Mesura empírica del cost real amb projecció: pendent (US-305).


### Ground truth de validació — Census Income (D1–D7, no D1–D9)

El paper del director inclou una taula (Taula 1) amb 9 versions del
dataset Census Income/Adult, etiquetades manualment contra les 15
categories, cadascuna comparada contra l'**original de la UCI** (D0), no
D_i contra D_{i-1} — són repositoris/fonts **independents entre si**, no
commits/tags d'un mateix repo.

**Només D1–D7 són a Hugging Face**. D8 és un registre de Zenodo
(12533514); D9 és `AdultDataset` d'AIF360 (llibreria Python, baixa de
l'UCI, no un repo). Descarregar-los requeriria 2 connectors únics sense
reutilitat per a la resta del projecte (la població real només prové de
HF). **US-304 cobreix només D1–D7**; D8/D9 documentats com a fora d'abast.

**US-304 (redefinida)**: NO calcula cap "% d'acord" (pressuposaria un
classificador que encara no existeix — dependència circular corregida,
vegeu `docs/decisions_tfg.txt` T-07). Valida que el motor de diffing
(`notebooks/change_diff.py`, funcions pures `df_before`/`df_after`,
reutilitzables sense canvis a US-305) detecta mecànicament un senyal allà
on el paper marca un canvi. El "% d'acord codi per codi" es calcula més
endavant, a US-305, un cop hi hagi un classificador real amb qui
comparar.


**Per què dins de `classify_dataset` i no com un pas separat**:
`classify_dataset()` ja itera commits i n'inspecciona els fitxers
canviats (`bare_clone`/`get_changed_files`/`is_substantive_path`) per
decidir l'elegibilitat -- és el punt natural on afegir "i quin tipus de
canvi és" sense tornar a clonar/relistar commits en un script separat
més endavant.

**Disseny concret**:

- `classify_commit_tabular_changes`: NOMÉS diferencia contingut per als
  fitxers TABULARS (`change_diff.is_tabular_path`: `.parquet`/`.csv`/
  `.tsv`) que van canviar -- els binaris (àudio/vídeo/tensors) ja compten
  per a l'elegibilitat via `is_substantive_path`, però no tenen
  "columnes"/"files" a classificar. Per cada fitxer tabular, baixa
  ambdues revisions (`change_diff.download_tabular_file_at_revision`,
  generalització de l'adquisició de Census Income a QUALSEVOL
  repositori/revisió, ara amb `errors.with_retry`) i crida `change_
  classifier.classify_file_change`. **Cap de `MAX_TABULAR_FILES_PER_
  COMMIT = 5`** fitxers tabulars per commit (mateix esperit que
  `MAX_COMMITS = 50`) -- confirmat en una execució real que alguns
  datasets "chunked" (p.e. `edinburghcstr/ami`, >40 fragments Parquet per
  commit) haurien trigat més d'una hora sense aquest cap; mostra
  representativa, no exhaustiva, per a commits amb més fitxers.

**Cost, per què és opt-in**: `classify_dataset()` s'invoca fins a 2000
cops per execució de Fase 0/1 (Fase 2 i 3 de `run_sampling`: mostreig +
classificació d'elegibilitat), on només ~11-13 acaben elegibles. Fer
classificació de contingut real a TOTS aquests 2000 descarregaria
contingut a escala poblacional -- exactament el problema dels 151GB
identificat a US-303 (Decisió A-02/T-07), multiplicat per ~180x. La
Fase 2/3 de `run_sampling` (el bucle de `classify_dataset_safe`) MAI
passa `classify_changes=True`; `write_results` descarta la columna
`change_labels` del CSV principal (sempre buida allà). L'opt-in és,
doncs, per COLUMNA de dades (contingut real només per als elegibles), no
un flag manual que calgui recordar activar cada cop -- vegeu la Fase 2 de
l'orquestrador tot seguit.

**Encadenat per `notebooks/run_pipeline.py` (Decisió T-13)**: aquest
orquestrador (no `eligibility_scan.py` mateix -- separació de
responsabilitats, vegeu T-13) crida, amb el MATEIX CSV: Fase 0-1
(`eligibility_scan.run_sampling`) -> Fase 1b (`version_extractor.
run_extraction`) -> Fase 2 (`eligibility_scan.run_classification`, llevat
de `--skip-classification`). `run_classification` itera NOMÉS els
elegibles d'aquest CSV (`df["eligible"] == True`, mai la resta de la
mostra) amb `classify_dataset(..., classify_changes=True)` i escriu
`data/change_classification_<run_id>.csv` (`dataset_id, version_from,
version_to, code, is_breaking`). Com que està filtrat a `eligible ==
True` abans de baixar cap contingut, encadenar-ho sempre no reintrodueix
el cost poblacional -- creix amb el nombre d'elegibles (~0.6% de la
mostra), no amb `sample_size`. `eligibility_scan.py --classify-eligible
<csv>` segueix disponible per reclassificar un CSV d'un run previ sense
tornar a mostrejar (mode standalone, ignora `--sample-size` i la resta de
flags de mostreig).

`is_breaking` és una heurística **pròpia d'aquest estudi** (el paper no
en defineix cap de formal): `C210`, `C222`, `C223`, `C311`, `C321`, `C410`
("trenca" un pipeline que llegeix per nom/posició/tipus/ordre sense
adaptar-se) són `True`; la resta `False`.

### Resultats reals — classificació sobre la població elegible

Execució real (`python eligibility_scan.py --classify-eligible
data/eligibility_report_2000_6.csv`, `data/change_classification_3.csv`
-- amb la correcció de renom per nom normalitzat i la
unitat de canvi per sessió per als datasets Criteri B  ja
actives): **14/14 datasets classificats, 0 fallats, 110 etiquetes de
canvi.**

Els 14 codis tabulars (tot excepte C100, fora d'abast per disseny --
vegeu "Limitacions conegudes" a `docs/taiga/taxonomy.md`), agrupats per
si van aparèixer en aquesta mostra real:

**Han aparegut:**

| Codi | Descripció | Recompte |
|---|---|---|
| C421 | Afegir fila | 65 |
| C422 | Eliminar fila | 23 |
| C322 | Valors d'una columna numèrica | 9 |
| C530 | Distribució de les dades | 8 |
| C312 | Valors d'una columna categòrica | 4 |
| C221 | Afegir columna | 1 |

**Implementats però 0 ocurrències en aquesta mostra:** C210 (ordre de
columnes), C222 (eliminar columna), C223 (renom de columna), C311 (tipus
de columna categòrica), C321 (tipus numèric), C410 (ordre de files --
implementat a la Decisió T-14, 0 ocurrències reals és un resultat
legítim, no un indici que la tècnica no funcioni; vegeu els 7 casos
sintètics verificats a `tests/test_change_diff.py::TestDiffRowOrder`, i
la re-validació amb C410=True a 3 de 7 versions de Census Income,
`docs/census_income_validation_report.md`), C510 (missingness), C520
(correlació).

**Fora d'abast:** C100 (metadada -- inspecció de dataset card/README, no
una comparació tabular).


## Fase 3 — Data warehouse i anàlisi (pendent)

**Estat: no iniciat.** Depèn de la Fase 2.

Esquema en estrella proposat pel director:
- Taula de fets `Change`: `dataset_id` (FK), `date_id` (FK),
  `kind_of_change_id` (FK), `age_days` (calculat).
- Dimensió `Dataset`, `DateOfChange`, `KindOfChange` (aquesta última
  poblada amb els 15 codis oficials com a conjunt tancat).

Motor de BD: pendent de decidir (DuckDB vs PostgreSQL, US-401).

## Convencions transversals del projecte

- **Git Flow** complet (`GIT_FLOW.md`): `main`/`develop` permanents,
  `feature/*`/`release/*`/`hotfix/*` temporals, Semantic Versioning,
  Conventional Commits (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`).
- **Persistència incremental**: cada fase escriu resultats a mesura que
  processa (no espera al final), amb `run_id` incremental per no
  sobreescriure execucions anteriors.
- **Separació resultats/errors**: cada fase té el seu CSV de resultats
  principal + `failures.csv` per a fallades, mai barrejats.
