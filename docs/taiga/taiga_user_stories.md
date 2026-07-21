# TFG — How do HuggingFace Datasets Change?
## User Stories per a Taiga — Pla teòric + recorregut real

Format: cada user story segueix l'esquema INVEST (As a / I want / So that)
amb criteris d'acceptació. L'estat reflecteix el que ja està implementat al
codi (`eligibility_scan.py`, `errors.py`) i el que resta pendent segons el
pla teòric acordat amb el director.

Llegenda d'estat: `✅ Done` · `🔄 In progress` · `⛔ Blocked` · `📋 To do`

**v2 (aquesta versió):** taxonomia actualitzada amb els 15 codis oficials
del paper del director (C100–C530). Vegeu `docs/taiga/taxonomy.md` per al
detall complet. Canvis principals respecte a v1: US-003 tancada, Epic 3
reestructurat (noves US-303/US-304, antiga US-303 renumerada a US-305),
US-402 actualitzada.

---

## EPIC 0 — Definició i planificació del TFG

*Objectiu: tancar l'abast, el títol, les competències i la metodologia
abans de començar la implementació.*

### US-001 — Definir títol i descripció del TFG
**Com a** estudiant de TFG, **vull** tenir un títol i descripció formals
aprovats pel director, **per tal de** poder inscriure el treball a la FIB
dins del termini.

**Criteris d'acceptació:**
- [x] Títol definit: *"How do HuggingFace Datasets Change? An Automated
  Pipeline for Version Analysis"*
- [x] Descripció de màxim 500 caràcters redactada i validada
- [x] Alineat amb el correu original del director (2 juny 2026)

**Estat:** ✅ Done
**Story points:** 2
**Tags:** planning, admin

---

### US-002 — Seleccionar i justificar competències tècniques (CES)
**Com a** estudiant, **vull** triar les competències tècniques de la
menció d'Enginyeria del Software que treballaré, amb el nivell de
profunditat de cadascuna, **per tal de** complir els requisits de la
normativa de TFE de la FIB.

**Criteris d'acceptació:**
- [x] CES1.2 (integració) — En profunditat
- [x] CES3.2 (data warehouse) — En profunditat
- [x] CES1.5 (bases de dades) — Bastant
- [x] CES2.1 (definició de requisits) — Bastant
- [x] CES1.7 (qualitat i proves) — Una mica
- [x] Cada competència justificada amb el component tècnic corresponent

**Estat:** ✅ Done
**Story points:** 3
**Tags:** planning, admin

---

### US-003 — Definir la taxonomia de canvis de dataset
**Com a** equip TFG (director + estudiant), **vull** disposar d'una
taxonomia formal dels tipus de canvis que pot patir un dataset, **per tal
de** poder classificar automàticament els canvis detectats entre versions.

**Criteris d'acceptació:**
- [x] Taxonomia rebuda del director (paper amb secció formal de
  taxonomia + exemple validat amb dataset real)
- [x] 15 codis oficials identificats (C100–C530), agrupats en 5
  perspectives: Metadata, Columns Set, Column Kind, Rows Set, Data
  Characteristics
- [x] Documentada a `docs/taiga/taxonomy.md`, amb taula comparativa
  respecte a la versió informal anterior
- [x] Inclou ground truth de validació: 9 versions reals del dataset
  Census Income, etiquetades manualment pel director (Taula 1 del paper)

**Estat:** ✅ Done (v2 — versió formal i codificada, substitueix la v1
informal)
**Story points:** 3
**Tags:** planning, taxonomy

---

### US-004 — Establir metodologia de mostreig no esbiaixada
**Com a** estudiant, **vull** definir i justificar una metodologia de
mostreig estadísticament vàlida sobre la població de datasets de HF,
**per tal de** poder generalitzar les conclusions a tota la població sense
biaix de popularitat.

**Criteris d'acceptació:**
- [x] Descartat el mostreig per popularitat (biaix a l'alça documentat)
- [x] Adoptat reservoir sampling (algorisme R de Vitter)
- [x] Justificat amb referència al paper "Lessons Learned from Mining the
  Hugging Face Repository" (Castaño et al., WSESE 2024)
- [x] Confirmat que full-scan de ~950K datasets NO és viable sense pla de
  pagament (rate limiting); mostreig és l'única via viable

**Estat:** ✅ Done
**Story points:** 5
**Tags:** planning, methodology

---

## EPIC 1 — Fase 0: Mostreig i elegibilitat

*Objectiu: determinar, amb validesa estadística, quina proporció de la
població de datasets de HF té múltiples versions reals.*

### US-101 — Iterar tota la població de datasets de HF eficientment
**Com a** pipeline d'extracció, **vull** iterar tots els datasets de HF
sense carregar-los tots a memòria i minimitzant el payload per petició,
**per tal de** fer viable un escaneig de ~950.000 datasets.

**Criteris d'acceptació:**
- [x] `iter_all_dataset_ids()` implementat com a generador (no llista)
- [x] Ús de `expand=["disabled"]` per reduir payload per petició
- [x] Datasets marcats `disabled` descartats abans de cap crida addicional
- [x] Gestió d'excepcions sense propagar-les (l'escaneig no es talla per
  un error puntual de xarxa durant la paginació)

**Estat:** ✅ Done
**Story points:** 3
**Tags:** extraction, performance

---

### US-102 — Mostrejar aleatòriament sense biaix de popularitat
**Com a** investigador, **vull** una mostra aleatòria uniforme de la
població total de datasets, **per tal de** poder estimar la proporció
real d'elegibles sense esbiaixar-la cap als datasets més populars.

**Criteris d'acceptació:**
- [x] Reservoir sampling implementat (`reservoir_sample_dataset_ids`)
- [x] Cada dataset té probabilitat `sample_size / N` de ser seleccionat,
  independentment de l'ordre d'arribada
- [x] Suport per `--max-scanned` (proves ràpides, esbiaixat, documentat
  com a tal) i escaneig complet (`None`, no esbiaixat)
- [x] Suport per `--seed` (reproduïbilitat)
- [x] Barra de progrés (`tqdm`) sense conèixer el total per endavant

**Estat:** ✅ Done
**Story points:** 5
**Tags:** extraction, statistics

---

### US-103 — Definir criteri d'elegibilitat d'un dataset (versions reals)
**Com a** investigador, **vull** un criteri objectiu i reproduïble per
decidir si un dataset té "múltiples versions reals", **per tal de**
classificar la població de forma consistent.

**Criteris d'acceptació:**
- [x] Criteri A: ≥2 tags de Git AMB ≥2 commits substantius associats (no
  només tags "buits" sense canvis reals)
- [x] Criteri B (fallback): ≥2 branches I ≥2 commits substantius (per
  títol, heurística documentada com a limitació coneguda)
- [x] Mode `--tags-only` per avaluar només el Criteri A original (1 sola
  crida per dataset, útil per minimitzar rate limiting)
- [x] Cada resultat inclou `eligibility_reason` explícit (auditable)

**Estat:** ✅ Done
**Story points:** 5
**Tags:** extraction, methodology

---

### US-104 — Gestionar rate limiting (HTTP 429) sense perdre dades
**Com a** pipeline d'extracció, **vull** reintentar automàticament les
crides que xoquen amb el rate limit de l'API, **per tal de** no perdre
classificacions vàlides per un error transitori.

**Criteris d'acceptació:**
- [x] `with_retry()` amb backoff exponencial + jitter implementat
- [x] 4 alternatives avaluades i documentades (cap retry / espera fixa /
  backoff sense jitter / backoff amb jitter) amb justificació de la tria
- [x] Configurable en temps d'execució (`--retry-max-attempts`,
  `--retry-base-wait`, `--retry-max-wait`)
- [x] Validat empíricament: errors 429 reduïts de ~59% a ~0% en execucions
  reals

**Estat:** ✅ Done
**Story points:** 8
**Tags:** extraction, reliability

---

### US-105 — Distingir errors permanents (403/404) d'errors transitoris
**Com a** investigador, **vull** que els datasets amb accés restringit
(gated/privat) es comptabilitzin per separat dels errors reals, **per tal
de** no esbiaixar la proporció d'elegibles ni malgastar temps reintentant
una condició que mai es resoldrà.

**Criteris d'acceptació:**
- [x] `ErrorCategory` enum: RATE_LIMITED, ACCESS_RESTRICTED, NOT_FOUND,
  TRANSIENT, UNKNOWN
- [x] 403 exclòs del reintent (condició permanent, no transitòria)
- [x] 403 exclòs tant del numerador com del denominador de "no elegible"
- [x] Registre estructurat a `data/failures.csv` (auditable a posteriori)
- [x] Hipòtesi descartada amb evidència pròpia: el 403 no es deu al rol
  del token (read vs write), sinó a datasets gated per llicència

**Estat:** ✅ Done
**Story points:** 5
**Tags:** extraction, reliability, data-quality

---

### US-106 — Calcular estadístiques de l'embut amb denominadors correctes
**Com a** investigador, **vull** que la proporció d'elegibles es calculi
sobre el denominador correcte (només classificacions vàlides), **per tal
de** no esbiaixar l'estimació estadística.

**Criteris d'acceptació:**
- [x] Bug identificat i corregit: els errors es comptaven abans dins del
  `total` de la proporció, esbiaixant-la a la baixa
- [x] `eligible_proportion` (denominador: eligible + ineligible, exclou
  errors i accessos restringits)
- [x] `eligible_proportion_of_attempts` (mètrica secundària, inclou tots
  els intents, útil per taxa d'èxit de l'scan)
- [x] `estimated_eligible_in_population` (extrapolació documentada amb
  l'amenaça a la validesa corresponent)

**Estat:** ✅ Done
**Story points:** 3
**Tags:** extraction, statistics, data-quality

---

### US-107 — Documentar la metodologia i mida de mostra al README
**Com a** lector extern (tribunal, director), **vull** trobar documentada
la metodologia estadística amb dades reals, **per tal de** poder avaluar
la validesa de l'estudi sense haver de llegir el codi.

**Criteris d'acceptació:**
- [x] Execució real documentada: N=949.991, p=1.37% elegibles
- [x] Taula de marge d'error segons mida de mostra (fórmula justificada)
- [x] Explicació de per què `--max-scanned` esbiaixa la mostra
- [x] Sample size per defecte justificat (2000, ±0.51pp)

**Estat:** ✅ Done
**Story points:** 2
**Tags:** documentation

---

### US-108 — Validar manualment una mostra dels datasets elegibles
**Com a** investigador, **vull** revisar manualment els datasets marcats
com elegibles, **per tal de** confirmar que el criteri automàtic
(especialment el Criteri B, basat en heurística de títol) no genera falsos
positius sistemàtics.

**Criteris d'acceptació:**
- [ ] Revisar manualment els 13 datasets elegibles de l'execució de
  referència (N=949.991, sample n=1000)
- [ ] Per cada un, confirmar/desmentir si el criteri assignat és correcte
- [ ] Documentar el % d'acord (precisió de la heurística) per a la secció
  de validesa de la memòria
- [ ] Si la precisió és baixa, replantejar el llindar o el mètode del
  Criteri B abans de continuar a l'Epic 3

**Estat:** 📋 To do
**Story points:** 5
**Tags:** validation, data-quality
**Prioritat:** Alta — bloqueja la confiança en els resultats de l'Epic 1

---

## EPIC 2 — Fase 1: Extracció de versions

*Objectiu: per cada dataset elegible, obtenir la llista completa i
ordenada de versions amb les seves metadades.*

### US-201 — Extreure la llista completa de tags per dataset elegible
**Com a** pipeline d'extracció, **vull** obtenir tots els tags (no només
comprovar que n'hi ha ≥2) de cada dataset elegible, **per tal de** tenir
la seqüència completa de versions a analitzar.

**Criteris d'acceptació:**
- [ ] Per cada dataset de la llista d'elegibles (Epic 1), cridar
  `list_repo_refs` i extreure tots els tags
- [ ] Ordenar els tags cronològicament (per data de commit associat, no
  per ordre alfabètic del nom del tag)
- [ ] Gestionar el mateix sistema de retry/error de l'Epic 1
  (reutilitzar `errors.py`)
- [ ] Output: taula `dataset_id, tag_name, commit_sha, tag_order`

**Estat:** 📋 To do
**Story points:** 5
**Tags:** extraction
**Depèn de:** US-108 (llista d'elegibles validada)

---

### US-202 — Extreure metadades de cada versió
**Com a** pipeline d'extracció, **vull** capturar data, autor i mida
aproximada de cada versió, **per tal de** alimentar les dimensions del
data warehouse (Epic 4).

**Criteris d'acceptació:**
- [ ] Per cada tag, extreure data del commit associat
- [ ] Extreure autor/committer del commit
- [ ] Extreure mida aproximada del dataset en aquella versió (via API,
  sense descarregar els fitxers complets — Git-LFS fa inviable la
  descàrrega completa a escala)
- [ ] Output persistit a `data/raw/versions_<run_id>.csv`

**Estat:** 📋 To do
**Story points:** 5
**Tags:** extraction
**Depèn de:** US-201

---

## EPIC 3 — Fase 2: Classificació de canvis (taxonomia)

*Objectiu: per cada parell de versions consecutives, determinar quins
fitxers han canviat i classificar el canvi segons els 15 codis oficials
de la taxonomia del director (`docs/taiga/taxonomy.md`).*

### US-301 — Investigar si `commit.files` és accessible via huggingface_hub
**Com a** desenvolupador, **vull** confirmar si la versió instal·lada de
`huggingface_hub` exposa la llista real de fitxers modificats per commit,
**per tal de** decidir si cal una estratègia alternativa (clonació bare +
`git show`) abans de dissenyar la resta de l'Epic 3.

**Criteris d'acceptació:**
- [ ] Provar `commit.files` / `commit.changed_files` sobre 5-10 datasets
  reals i documentar el resultat
- [ ] Si NO és accessible: documentar l'alternativa (bare clone +
  `git show --name-only`, com fa el paper dels LLM, secció 4.2.1)
- [ ] Decisió registrada a `docs/decisions_tfg.txt` com a Risc R-01
  (tancat)

**Estat:** ⛔ Blocked — bloqueja tota la resta de l'Epic 3
**Story points:** 3
**Tags:** research, spike
**Prioritat:** Urgent

---

### US-302 — Detectar fitxers de dades modificats per commit (real, no heurística)
**Com a** investigador, **vull** substituir la detecció per títol de
commit per una inspecció real dels fitxers modificats, **per tal de**
eliminar la limitació metodològica de falsos positius/negatius de la
heurística actual.

**Criteris d'acceptació:**
- [ ] Substituir `is_substantive_commit()` (heurística per títol) per
  inspecció real de fitxers
- [ ] Filtrar per extensió: fitxers de dades (`.parquet`, `.csv`, `.json`,
  `.arrow`...) vs fitxers purament documentals
- [ ] Reprocessar el Criteri B de l'Epic 1 amb el nou mètode i comparar
  resultats amb la validació manual de US-108

**Estat:** 📋 To do (bloquejat per US-301)
**Story points:** 8
**Tags:** classification
**Depèn de:** US-301

---

### US-303 — Decidir l'abast de detecció automàtica per codi de taxonomia (NOVA)
**Com a** equip TFG, **vull** decidir explícitament quins dels 15 codis
de la taxonomia entren dins l'abast de detecció automàtica, **per tal de**
no comprometre's a implementar categories que requereixen contingut real
de les dades sense haver-ho parlat amb el director.

**Criteris d'acceptació:**
- [ ] Taula de detectabilitat completada: 7 codis schema-level (C100,
  C210, C221, C222, C223, C311, C321) vs 8 codis content-level (C312,
  C322, C410, C421, C422, C510, C520, C530) — vegeu `taxonomy.md`
- [ ] Avaluar viabilitat de descarregar contingut real NOMÉS per als
  datasets elegibles (població petita, ~1.37%), a diferència de la
  decisió original que ho descartava per a tota la població
- [ ] Decisió consultada i tancada amb el director
- [ ] Decisió registrada a `docs/decisions_tfg.txt` (actualitza la
  Decisió A-02 original)

**Estat:** 📋 To do
**Story points:** 3
**Tags:** planning, taxonomy, scope
**Prioritat:** Alta — condiciona tot el disseny de US-305

---

### US-304 — Validar la classificació amb el ground truth Census Income (NOVA)
**Com a** investigador, **vull** comparar el resultat del meu pipeline de
classificació amb les etiquetes manuals del director sobre 9 versions
reals del dataset Census Income (Taula 1 del paper), **per tal de**
obtenir una mesura de precisió abans d'escalar a tota la població
elegible.

**Criteris d'acceptació:**
- [ ] Executar el pipeline propi (extracció + classificació) sobre els 9
  repositoris D1–D9 llistats a `taxonomy.md`
- [ ] Comparar el resultat, codi per codi, amb la Taula 1 del paper
- [ ] Calcular % d'acord global i per codi
- [ ] Documentar discrepàncies i, si escau, ajustar les regles de
  detecció abans d'aplicar-les a la població elegible completa
- [ ] Resultat documentat a la memòria com a validesa del mètode
  (equivalent al Cohen's Kappa del paper dels LLM per a la classificació
  de commits)

**Estat:** 📋 To do
**Story points:** 5
**Tags:** validation, taxonomy
**Depèn de:** US-303, US-302 (parcialment — es pot fer amb detecció
manual/semi-automàtica si US-302 encara no està llesta)

---

### US-305 — Mapar canvis detectats als 15 codis oficials de la taxonomia
*(Anteriorment US-303 a la v1 d'aquest document)*

**Com a** investigador, **vull** classificar cada canvi de fitxer
detectat segons els 15 codis oficials (C100–C530), **per tal de**
respondre la pregunta central del TFG amb una classificació formal,
reproduïble i validada.

**Criteris d'acceptació:**
- [ ] Regles de classificació definides per a cada codi dins l'abast
  acordat a US-303 (mínim: els 7 codis schema-level)
- [ ] Cada canvi detectat s'etiqueta amb el codi corresponent (C1XX–C5XX)
- [ ] El classificador NO usa informació de quina columna és el target
  (regla de disseny explícita de la taxonomia — vegeu `taxonomy.md`)
- [ ] Documentar limitacions per als codis fora de l'abast decidit
- [ ] Output: taula `dataset_id, version_from, version_to, code,
  is_breaking`

**Estat:** 📋 To do (bloquejat per US-301, US-302, US-303, US-304)
**Story points:** 13
**Tags:** classification, taxonomy
**Depèn de:** US-003, US-302, US-303, US-304

---

## EPIC 4 — Fase 3: Data warehouse i anàlisi

*Objectiu: emmagatzemar els canvis classificats en un esquema en estrella
i produir una anàlisi descriptiva per a la memòria.*

### US-401 — Decidir motor de base de dades
**Com a** equip TFG, **vull** triar entre PostgreSQL i DuckDB de forma
justificada, **per tal de** no haver de migrar a mitja implementació.

**Criteris d'acceptació:**
- [ ] Avaluar DuckDB (analítica local, sense servidor, ideal per TFG)
  vs PostgreSQL (desplegable, més pesat)
- [ ] Decisió registrada a `docs/decisions_tfg.txt`
- [ ] Consultat amb el director si té preferència

**Estat:** 📋 To do
**Story points:** 2
**Tags:** data-warehouse, decision

---

### US-402 — Implementar l'esquema en estrella
**Com a** investigador, **vull** un data warehouse amb taula de fets
`Change` i dimensions `Dataset`, `DateOfChange`, `KindOfChange`, **per tal
de** poder consultar analíticament els canvis trobats (competència
CES3.2).

**Criteris d'acceptació:**
- [ ] Taula de fets `Change`: `dataset_id` (FK), `date_id` (FK),
  `kind_of_change_id` (FK), `age_days` (calculat)
- [ ] Dimensió `Dataset`: id, name, domain, license, num_downloads,
  creation_date, num_versions
- [ ] Dimensió `DateOfChange`: date_id, date, year, quarter, month
- [ ] Dimensió `KindOfChange`: **conjunt tancat dels 15 codis oficials**
  (C100–C530), no una taxonomia oberta — actualitzat respecte a la v1
- [ ] Script de càrrega (ETL) des dels CSV de l'Epic 2/3 cap al DW

**Estat:** 📋 To do
**Story points:** 8
**Tags:** data-warehouse
**Depèn de:** US-305, US-401

---

### US-403 — Produir anàlisi descriptiva i visualitzacions per a la memòria
**Com a** autor de la memòria, **vull** un conjunt de gràfics i taules
descriptives sobre els canvis trobats, **per tal de** respondre
visualment els objectius específics (OE1-OE4) del TFG.

**Criteris d'acceptació:**
- [ ] Distribució de canvis per codi de la taxonomia
- [ ] Evolució temporal dels tipus de canvi
- [ ] Relació entre codi de canvi i popularitat/domini del dataset
- [ ] Comparació de cobertura respecte a l'exemple del director (100%
  de les categories cobertes al Census Income amb 9 versions)
- [ ] Explícitament FORA d'abast: anàlisi estadístic inferencial
  (Bayesian Networks), segons la descripció original del TFG

**Estat:** 📋 To do
**Story points:** 8
**Tags:** analysis, thesis-writing
**Depèn de:** US-402

---

## Resum per Sprint (proposta de seqüenciació, actualitzada)

| Sprint | Epic | User Stories | Punts totals |
|---|---|---|---|
| Sprint 0 (fet) | Epic 0 | US-001 a US-004 | 13 |
| Sprint 1 (fet) | Epic 1 | US-101 a US-107 | 31 |
| Sprint 2 (actual) | Epic 1 | US-108 | 5 |
| Sprint 3 | Epic 3 (spike) | US-301, US-303 | 6 |
| Sprint 4 | Epic 2 + Epic 3 | US-201, US-202, US-304 | 15 |
| Sprint 5 | Epic 3 | US-302, US-305 | 21 |
| Sprint 6 | Epic 4 | US-401, US-402 | 10 |
| Sprint 7 | Epic 4 | US-403 | 8 |
| Sprint 8+ | — | Redacció de la memòria | — |

**Canvi respecte a la v1**: s'ha avançat el spike US-301 i la decisió
d'abast US-303 al Sprint 3 (abans que l'extracció de versions), perquè
condicionen si val la pena invertir temps en descàrrega de contingut
real. US-304 (validació amb Census Income) s'ha situat al Sprint 4 perquè
es pot fer amb un cost baix (9 datasets) fins i tot abans que US-302
estigui acabada.

**Velocitat estimada:** ~20-25 punts/sprint (basat en Sprint 0+1 fets en
~2 setmanes reals).
