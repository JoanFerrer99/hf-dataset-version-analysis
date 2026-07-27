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

**Estat: pràcticament tancat.** US-108 (validació manual dels elegibles
trobats) té un primer esborrany fet: `docs/us108_validation_report.md`
reporta una precisió estimada de 5/13 ≈ 38.5% sobre l'execució de
referència (Criteri A 3/3 = 100%, Criteri B 2/10 = 20%), amb 8/13 falsos
positius atribuïbles a un únic patró (eines com LeRobot que generen
desenes de commits automàtics en una sola sessió de pujada, sense
representar versions reals). **Pendent**: confirmació final de Joan (i,
si escau, el director) sobre la classificació TP/FP de cada dataset, i
decisió sobre la recomanació derivada (exigir dispersió temporal mínima
entre commits substantius del Criteri B) — no implementada encara.

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
     (heurística per títol, `is_substantive_commit`; **limitació
     coneguda**: no inspecciona fitxers reals, vegeu Fase 2 / US-301).
   - Mode `--tags-only`: només Criteri A original (1 crida per dataset),
     per a escanejos ràpids amb menys pressió sobre l'API.
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

### Resultat de referència (execució real, sample n=1000)

| Mètrica | Valor |
|---|---|
| Població escanejada | 949.991 |
| Elegibles | 13 |
| No elegibles | 938 |
| Accés restringit (403) | 49 |
| Proporció elegible | 1.37% |

## Fase 1 — Extracció de versions (pendent d'implementar)

**Estat: no iniciat.** Depèn de US-108 (llista d'elegibles validada).

Objectiu: per cada dataset elegible, obtenir la seqüència completa i
ordenada de tags/versions amb metadades (data, autor, mida aproximada).

Mòdul previst: `version_extractor.py`. Ha de reutilitzar `errors.py`
(mateix sistema de retry/classificació d'errors que Fase 0).

## Fase 2 — Classificació de canvis / taxonomia (pendent, parcialment bloquejat)

**Estat: bloquejat.** US-301 (investigar si `commit.files` és accessible
via `huggingface_hub`) condiciona tot el disseny d'aquesta fase.

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
