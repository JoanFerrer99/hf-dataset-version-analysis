# Arquitectura — HF Dataset Version Analysis

> Aquest document és la font de veritat sobre "com està fet" el pipeline.
> Es manté sincronitzat manualment entre el xat de planificació (Claude,
> web) i el desenvolupament de codi (Claude Code). Quan un mòdul canvia
> de disseny de forma significativa, actualitza aquest fitxer al mateix
> commit.

## Visió general

Pipeline de recerca (TFG) que respon: *com canvien els datasets de
Hugging Face entre versions successives?* Es divideix en 4 fases
seqüencials, cadascuna amb el seu propi mòdul de codi i el seu epic a
Taiga (`docs/taiga/taiga_user_stories.md`).

```
Fase 0            Fase 1              Fase 2                 Fase 3
Mostreig i    →   Extracció de   →    Classificació de   →   Data warehouse
elegibilitat      versions            canvis (taxonomia)     i anàlisi

eligibility_      version_          change_                 warehouse/
scan.py           extractor.py      classifier.py            (a decidir:
errors.py         (a crear)         (a crear)                DuckDB/Postgres)
```

## Fase 0 — Mostreig i elegibilitat (`eligibility_scan.py`, `errors.py`)

**Estat: pràcticament tancat.** Sobre la mostra original de 13 elegibles
(n=1000), la validació manual (`docs/us108_validation_report.md`, versió
històrica) va trobar una precisió de 5/13 ≈ 38.5%, amb 8/13 falsos
positius atribuïbles a un únic patró (eines com LeRobot que generen
desenes de commits automàtics en una sola sessió de pujada). Això va
motivar dues millores, totes dues implementades:

1. **Dispersió temporal mínima al Criteri B** (`MIN_SUBSTANTIVE_GAP_HOURS`,
   actualment 6h, entre el commit substantiu més antic i el més recent).
2. **Detecció real de fitxers per commit (US-302)**, en lloc de
   l'heurística de títol: clonatge "bare" + filtratge de blobs
   (`bare_clone`/`get_changed_files`/`determine_commit_substantive`),
   amb fallback a l'heurística de títol si el clonatge falla.

**Bug de desplegament detectat i corregit**: la primera execució via
Docker amb les millores (`eligibility_report_2000_2.csv`) es va
beneficiar només de la millora (1) -- la imatge Docker no tenia `git`
instal·lat, així que `bare_clone` fallava silenciosament per a TOTS els
datasets i el pipeline recorria sempre al fallback de títol. Corregit al
`Dockerfile` (s'hi instal·la `git`) i `bare_clone` ara registra un
`log.error` (un sol cop per procés) si `git` no és al `PATH`. Una segona
execució neta (`eligibility_report_2000_3.csv`, amb `git` disponible i
totes dues millores realment actives) confirma la correcció.

`notebooks/validate_eligible.py` genera automàticament
`docs/us108_validation_report.md` a cada execució (US-108, criteri
d'acceptació 4), amb un veredicte TP/REVIEW per dataset. La comprovació
de sessions de treball (`cluster_commit_times`, buit >
`MIN_SUBSTANTIVE_GAP_HOURS` entre commits CONSECUTIUS -- el MATEIX
llindar que decideix l'elegibilitat via Criteri B) **només s'aplica al
Criteri B**: el Criteri A (tags explícits) mai ha exigit dispersió
temporal a `classify_dataset` -- la presència de >=2 tags ja és un
senyal deliberat de versionat pel mantenidor, independent de quan es van
crear, i la validació manual original de US-108 ja el va trobar 100%
fiable sense cap comprovació temporal.

**Iteracions de disseny durant el desenvolupament**:
1. Primer es va aplicar la comprovació de sessions per igual al Criteri
   A i B, amb el llindar unificat a 24h (abans encara hi havia un segon
   llindar propi d'1h només per a l'informe, més permissiu i confús amb
   el del Criteri B -- també corregit). Això marcava com a REVIEW casos
   de Criteri A legítims (p.e. `qualia-robotics/qualia-dataset-real`, 3
   tags del mateix dia natural; o `aytsaiusc/play_robot_new_1`, creat i
   acabat de pujar amb ~6h de diferència), inventant un criteri més
   estricte a la capa de l'informe que el que realment decideix
   l'elegibilitat. Corregit: la comprovació de sessions ara només
   s'aplica al Criteri B.
2. `MIN_SUBSTANTIVE_GAP_HOURS` reduït de 24h a 6h: com que el mateix
   llindar serveix per a dues coses (l'interval mínim/màxim del Criteri
   B, i el buit entre commits CONSECUTIUS del recompte de sessions), amb
   24h una sèrie de commits separats per <24h cadascun però repartits en
   diversos dies (p.e. un cada ~20h durant una setmana) es podia comptar
   com UNA sola sessió -- el recompte de sessions només mira parells
   consecutius, no l'interval total. Amb 6h aquest fals negatiu és molt
   menys probable. L'anàlisi de sensibilitat original (mostra de 13
   elegibles) dona la mateixa precisió a 6h que a 24h (83.3%, 1/8 falsos
   positius conservats): no reintrodueix cap dels falsos positius ja
   identificats (patrons LeRobot densos, tots per sota de 6h).

Sobre `eligibility_report_2000_3.csv` (execució neta, totes dues
millores de US-302 realment actives, però classificada amb el llindar
antic de 24h -- vegeu nota més avall): **12/12 (100%) TP automàtic, 0
REVIEW** -- Criteri A (3 datasets) sempre TP; Criteri B (9 datasets) amb
totes les sessions >=2, també a resolució de 6h (reduir el llindar només
pot augmentar el recompte de sessions, mai disminuir-lo). Revisió manual
puntual (Claude Code) confirma que el resultat és coherent, no un
artefacte: p.e. `AG42/lerobot_dataset_try1` usa el mateix patró d'eines
LeRobot que els falsos positius originals, però aquest cas concret
(Criteri B) té commits substantius genuïnament repartits en 3 dies
diferents (11, 13 i 16 de gener).

**Pendent**: `eligibility_report_2000_3.csv` es va generar amb el
llindar antic de 24h per a l'ELEGIBILITAT del Criteri B (no només per a
l'informe); com que 6h és més PERMISSIU per a l'elegibilitat (tot i ser
més ESTRICTE per al recompte de sessions -- efectes en sentits oposats
del mateix llindar unificat), caldria una execució neta amb 6h per
confirmar si sorgeixen nous elegibles que abans no complien el llindar
de 24h. I, com sempre, confirmació final de Joan/director.

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
     amunt).
   - Mode `--tags-only`: només permet elegibilitat via Criteri A (el
     Criteri B mai s'avalua), però segueix verificant els commits
     substantius (`list_repo_commits` + clonatge) -- només estalvia
     crides quan `tags < 2` (cas en què cap criteri pot aplicar-se).
4. `write_results()` — CSV + JSON amb `FunnelCounts`/`compute_funnel_stats`
   (dues mètriques diferenciades: `eligible_proportion` i
   `eligible_proportion_of_attempts`, vegeu decisió D-de-disseny més avall).

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
- 403 exclòs tant del reintent com del denominador de `eligible_proportion`.
- Full-scan de tota la població NO és viable sense pla de pagament de HF
  (rate limiting); només s'implementa el mode mostreig.
- Mida de mostra per defecte: 2000 (±0.51pp, 95% confiança, p=0.0137
  observat a N=949.991).

### Resultats d'execucions reals

| Execució | Mostra | Població | Elegibles | Accés restringit | Proporció | Millores actives |
|---|---|---|---|---|---|---|
| `eligibility_report_1000_3` (baseline històric, esborrat de `data/`, vegeu historial de git) | 1000 | 949.991 | 13 | 49 | 1.37% | Cap (pipeline original, pre-US-302) |
| `eligibility_report_2000_2` | 2000 | 979.377 | 11 | 74 | 0.58% | Només dispersió temporal (bug de Docker) |
| **`eligibility_report_2000_3` (execució de referència vigent)** | 2000 | 979.480 | 12 | 87 | 0.63% | Totes dues (dispersió temporal + US-302) |

La proporció d'elegibles (~0.6%) es manté estable entre les dues
execucions amb dispersió temporal activa, molt per sota del baseline
històric (1.37%): la major part de la reducció ve de la dispersió
temporal, i la detecció real de fitxers (US-302) afina encara més la
qualitat de la classificació. Precisió automàtica (`docs/
us108_validation_report.md`, comprovació de sessions només per al Criteri
B, llindar unificat i actualment a 6h): **12/12 = 100%** sobre
`eligibility_report_2000_3` (totes dues millores actives; execució
classificada amb el llindar antic de 24h, vegeu nota més amunt), molt per
sobre del 38.5% del
baseline històric. (Els percentatges de 81.8%/83.3% citats en versions
anteriors d'aquest document es van calcular amb metodologies intermèdies
de l'informe (llindar de sessió d'1h, o comprovació de sessions aplicada
també al Criteri A) ja corregides -- no comparables directament.)

## Fase 1 — Extracció de versions (pendent d'implementar)

Objectiu: per cada dataset elegible, obtenir la seqüència completa i
ordenada de tags/versions amb metadades (data, autor, mida aproximada).

Mòdul previst: `version_extractor.py`. Ha de reutilitzar `errors.py`
(mateix sistema de retry/classificació d'errors que Fase 0).

## Fase 2 — Classificació de canvis / taxonomia (pendent)

**Estat: desbloquejat.** US-301 ja no condiciona el disseny d'aquesta
fase: confirmat que `commit.files` no és accessible via `huggingface_hub`,
i implementada l'alternativa (clonatge "bare" + `git show --name-status`,
US-302, ja integrada a `eligibility_scan.py`).

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

**Nota crítica**: "concept drift" i "class balance" **no són codis nous**
— són com s'anomenaria C520/C530 si la columna afectada resulta ser el
target del pipeline. La taxonomia classifica el dataset, no l'ús que se'n
fa.

### Decisió d'abast pendent (US-303, nova)

No totes les categories són detectables sense descarregar el contingut
real dels fitxers de dades:

- **Detectables per esquema/metadades** (sense descarregar dades): C100,
  C210, C221, C222, C223, C311, C321.
- **Requereixen contingut real de les dades**: C312, C322, C410, C421,
  C422, C510, C520, C530.

Amb la població elegible petita (~1.37%), descarregar contingut real
només per als elegibles deixa de ser inviable (a diferència de fer-ho
sobre tota la població). **Cal decidir amb el director** si l'abast
inclou les 15 categories o només les 7 de schema-level.

### Ground truth de validació

El paper del director inclou una taula (Taula 1) amb 9 versions reals de
HF del dataset Census Income/Adult, etiquetades manualment contra les 15
categories. Abans d'escalar el classificador a tota la població elegible,
cal validar-lo contra aquest ground truth (US-304, nova).

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
