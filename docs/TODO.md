# TODO — sincronitzat amb Taiga

> Els IDs (US-XXX) són els mateixos que `docs/taiga/taiga_user_stories.md`
> i `.csv`. Si Claude Code marca alguna cosa com feta aquí, actualitza
> també l'estat corresponent al CSV/MD de Taiga (i viceversa) — aquest
> fitxer i Taiga han de dir sempre el mateix.

## Ara mateix (Sprint actual)

- [ ] **US-108** — Validar manualment els 13 datasets elegibles trobats a
      l'execució de referència (N=949.991, n=1000). Confirmar/desmentir
      el criteri assignat a cadascun. _Prioritat alta: bloqueja la
      confiança en tots els resultats de la Fase 0._

## Següent (Fase 2 — desbloqueig urgent)

- [ ] **US-301** — Investigar si `commit.files`/`commit.changed_files` és
      accessible a la versió instal·lada de `huggingface_hub`. Provar
      sobre 5-10 datasets reals. Si no ho és: documentar alternativa
      (bare clone + `git show --name-only`). _Bloqueja US-302 i US-305._
- [ ] **US-303** (nova) — Decidir amb el director l'abast de detecció
      automàtica: 15 codis complets (requereix contingut real de dades)
      vs 7 codis schema-level (sense descarregar dades). Vegeu taula a
      `docs/architecture.md`.
- [ ] **US-304** (nova) — Validar l'enfocament de classificació contra el
      ground truth del Census Income (Taula 1 del paper del director, 9
      versions reals de HF). Fer-ho amb un cost baix (9 datasets coneguts)
      abans d'escalar a tota la població elegible.

## Pendent (no bloquejat, però darrere de l'anterior)

- [ ] **US-302** — Implementar detecció real de fitxers de dades
      modificats per commit (substituir l'heurística de títol actual).
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
