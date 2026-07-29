# TODO — sincronitzat amb Taiga

> Els IDs (US-XXX) són els mateixos que `docs/taiga/taiga_user_stories.md`
> i `.csv`. Si Claude Code marca alguna cosa com feta aquí, actualitza
> també l'estat corresponent al CSV/MD de Taiga (i viceversa) — aquest
> fitxer i Taiga han de dir sempre el mateix.

## Seguiment del projecte

El backlog, sprints i estat de les tasques es gestionen a Taiga:
https://tree.taiga.io/project/joanferrer-estudi-canvis-datasets-hf-1/timeline

## Ara mateix (Sprint actual)

- [x] **US-108** — `notebooks/validate_eligible.py` genera automàticament
      `docs/us108_validation_report.md` a cada execució (criteri
      d'acceptació 4: automatització), amb un veredicte TP/REVIEW/ERROR
      per dataset. La comprovació de "sessions de treball"
      (`cluster_commit_times`, buit >`MIN_SUBSTANTIVE_GAP_HOURS` entre
      commits CONSECUTIUS) **només s'aplica al Criteri B**: el Criteri A
      (tags explícits) mai ha exigit dispersió temporal a
      `classify_dataset` -- la presència de >=2 tags ja és un senyal
      deliberat de versionat pel mantenidor, i la validació manual
      original ja el va trobar 100% fiable sense cap comprovació temporal.
      (Primer s'havia aplicat la comprovació de sessions per igual a A i
      B -- un criteri més estricte que el que realment decideix
      l'elegibilitat -- i es va corregir.)
      
## Següent (Fase 2 — desbloqueig urgent)

- [ ] **US-303** (nova) — Decidir amb el director l'abast de detecció
      automàtica: 15 codis complets (requereix contingut real de dades)
      vs 7 codis schema-level (sense descarregar dades). Vegeu taula a
      `docs/architecture.md`.
- [ ] **US-304** (nova) — Validar l'enfocament de classificació contra el
      ground truth del Census Income (Taula 1 del paper del director, 9
      versions reals de HF). Fer-ho amb un cost baix (9 datasets coneguts)
      abans d'escalar a tota la població elegible.

## Pendent (no bloquejat, però darrere de l'anterior)

- [ ] **US-305** (abans US-303) — Mapar cada canvi detectat als 15 codis
      oficials (C100–C530).
- [ ] **US-201** — Extreure llista completa de tags per dataset elegible.
- [ ] **US-202** — Extreure metadades de cada versió (data, autor, mida).
- [ ] **US-401** — Decidir motor de BD (DuckDB vs PostgreSQL).
- [ ] **US-402** — Implementar esquema en estrella.
- [ ] **US-403** — Anàlisi descriptiva i visualitzacions per la memòria.

## Fet ✅

- [x] US-001 — Títol i descripció del TFG
- [x] US-002 — Competències tècniques (CES) seleccionades i justificades
- [x] US-003 — Taxonomia formal rebuda i codificada (C100–C530, 15 codis)
- [x] US-004 — Metodologia de mostreig no esbiaixada
- [x] US-101 — Iteració eficient de tota la població
- [x] US-102 — Reservoir sampling no esbiaixat
- [x] US-103 — Criteri d'elegibilitat (A/B) definit i implementat
- [x] US-104 — Rate limiting gestionat amb retry + backoff + jitter
- [x] US-105 — Errors permanents (403/404) distingits dels transitoris
- [x] US-106 — Estadístiques de l'embut amb denominadors correctes
- [x] US-107 — Metodologia documentada al README amb dades reals
- [x] **US-301** — Confirmat: `commit.files`/`commit.changed_files` NO és
      accessible a `huggingface_hub==1.18.0` (`GitCommitInfo` només té
      `commit_id`/`authors`/`created_at`/`title`/`message`). Alternativa
      validada empíricament: clonatge "bare" + filtratge de blobs (`git
      clone --bare --filter=blob:none` + `git show --name-status`),
      implementada a `eligibility_scan.bare_clone`/`get_changed_files`.
- [x] **US-302** — Detecció real de fitxers implementada
      (`determine_commit_substantive`, amb fallback a l'heurística de
      títol si el clonatge falla). **Bug de desplegament detectat i
      corregit durant el procés**: la imatge Docker no tenia `git`
      instal·lat, així que `bare_clone` fallava silenciosament per a TOTS
      els datasets durant la primera execució via Docker amb les
      millores (`data/eligibility_report_2000_2.csv`) — aquell run només
      es va beneficiar de la dispersió temporal, no de la detecció real
      de fitxers. Corregit a `Dockerfile` (`apt-get install git`) i
      `bare_clone` ara registra un avís (`log.error`, un sol cop per
      procés) si `git` no és al `PATH`. **Confirmat amb una segona
      execució neta** (`eligibility_report_2000_3.csv`): US-302
      realment actiu, precisió automàtica 38.5% → 100% sobre l'execució
      de referència vigent.
