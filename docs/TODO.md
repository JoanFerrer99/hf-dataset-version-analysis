# TODO — sincronitzat amb Taiga


## Seguiment del projecte

El backlog, sprints i estat de les tasques es gestionen a Taiga:
https://tree.taiga.io/project/joanferrer-estudi-canvis-datasets-hf-1/timeline

## Situació actual

**Fase 0, Fase 1 i (gairebé) Fase 2 tancades.** Referència vigent:
`data/eligibility_report_2000_5.csv` (11 elegibles) → `data/versions_1.
csv` (40 versions) → `data/change_classification_1.csv` (67 etiquetes de
canvi, 11/11 datasets classificats, 0 fallats). La classificació de
canvis ja NO és un script separat -- integrada DINS de `eligibility_
scan.classify_dataset()` (paràmetre opt-in `classify_changes`),
reutilitzant `change_diff.py` (motor de diffing + etiquetatge en un sol
fitxer, validats contra Census Income D1-D7 i sobre la població real).
C100 (metadada) exclòs, només els 14 codis estructurals/de contingut.
**L'única cosa que falta per tancar formalment Fase 2** és
que Joan parli amb el director sobre l'abast final (US-303 AC3/AC4) --
Claude Code no pot completar aquesta conversa.

## Ara mateix (Sprint actual)

- [ ] **US-303** — AC1/AC2 fets (taula de detectabilitat de 3 nivells +
      anàlisi de cost real, `docs/taiga/taxonomy.md`). Pendent: AC3/AC4,
      tancar la decisió d'abast amb el director (conversa real de Joan
      amb Alberto Abelló, Claude Code no la pot completar).

## Pendent (no bloquejat, però darrere de l'anterior)

- [ ] **US-401** — Decidir motor de BD (DuckDB vs PostgreSQL).
- [ ] **US-402** — Implementar esquema en estrella.
- [ ] **US-403** — Anàlisi descriptiva i visualitzacions per la memòria.

## Fet ✅

- [x] **US-108** — `notebooks/validate_eligible.py` (eliminat setembre
      2026, eina de validació puntual, no part del pipeline en marxa --
      vegeu `docs/decisions_tfg.txt` T-11) va generar
      `docs/us108_validation_report.md` (mantingut, document històric),
      amb un veredicte TP/REVIEW/ERROR per dataset. La comprovació de
      "sessions de treball" (`cluster_commit_times`, ara a
      `eligibility_scan.py`, buit >`MIN_SUBSTANTIVE_GAP_HOURS` entre
      commits CONSECUTIUS) **només s'aplicava al Criteri B**: el Criteri A
      (tags explícits) mai ha exigit dispersió temporal a
      `classify_dataset` -- la presència de >=2 tags ja és un senyal
      deliberat de versionat pel mantenidor, i la validació manual
      original ja el va trobar 100% fiable sense cap comprovació temporal.
      (Primer s'havia aplicat la comprovació de sessions per igual a A i
      B -- un criteri més estricte que el que realment decideix
      l'elegibilitat -- i es va corregir.)

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
      realment actiu, precisió automàtica 38.5% → 100%. Reconfirmat amb
      `eligibility_report_2000_5.csv` (execució de referència vigent,
      llindar de 6h ja actiu també per a l'elegibilitat): 11/11 = 100%.
- [x] **US-201 + US-202** — `notebooks/version_extractor.py`: per cada
      dataset elegible (`eligibility_report_2000_5.csv`), extreu la
      seqüència ordenada de versions amb data/autors/mida aproximada.
      **Ampliació d'abast decidida durant la implementació**: ~70% (8/11)
      dels elegibles ho són via Criteri B i no tenen cap tag -- en lloc de
      deixar-los sense versions o deferir-ho a una story nova, cada SESSIÓ
      de treball (`eligibility_scan.cluster_commit_times`, mateixa lògica
      que US-108) es tracta com una versió inferida (`version_source=
      "commit_session"`), diferenciada de les versions per tag
      (`version_source="tag"`) al mateix output. Detall tècnic: `list_
      repo_tree` és un generador lazy -- cal consumir-lo dins de la crida
      reintentada (`errors.with_retry`), no passar-lo cru, o els errors es
      perdrien sense reintent. Limitació coneguda: `huggingface_hub` no
      distingeix autor de committer (`GitCommitInfo.authors` és l'únic
      camp). Execució real sobre els 11 elegibles: 40 versions extretes, 0
      fallades. Vegeu `docs/architecture.md` (Fase 1) per al disseny
      complet.
- [x] **US-304** — Validació d'extractibilitat mecànica (`notebooks/
      change_diff.py`) contra Census Income D1-D7 (D8/D9 fora d'abast, no
      són a HF -- Zenodo i AIF360/UCI respectivament). Redefinida per
      trencar una dependència circular real amb US-305 (vegeu
      `docs/decisions_tfg.txt`, T-07). D3/D4 encaixen EXACTAMENT amb el
      total del paper (7/7 els dos).
- [x] **US-305** — Classificació de canvis (14 codis, SENSE C100)
      **integrada DINS de `classify_dataset()`** (`eligibility_scan.py`,
      paràmetre opt-in `classify_changes`), no com a script separat --
      "l'escalabilitat del projecte parteix d'aquell fitxer". Reutilitza
      `change_diff.py` sense reimplementar-lo.
      Mode CLI nou: `--classify-eligible`. **Execució real sobre els 11
      elegibles: 11/11 classificats, 0 fallats, 67 etiquetes** (C421=53,
      C422=10, C223=3, C311=1; 4 breaking). 7/11 datasets amb etiquetes;
      els altres 4 només toquen fitxers binaris (àudio/vídeo), confirmat
      pel log, no un error. **2 bugs reals trobats i corregits durant
      l'execució** (no hipotètics): `unhashable type: 'dict'` en columnes
      d'àudio/imatge llegides amb `pandas.read_parquet` (corregit amb
      `change_diff._is_hashable_series`, salta només la columna
      problemàtica); cost desproporcionat en datasets "chunked" com
      `edinburghcstr/ami` (>40 fragments Parquet/commit -- corregit amb
      `MAX_TABULAR_FILES_PER_COMMIT = 5`). Vegeu `docs/architecture.md`
      per al disseny complet i `docs/decisions_tfg.txt` (T-10) per al
      relat detallat de la primera execució (fallada per timeout) i la
      segona (completa). **Neteja posterior (dues passes)**: (1)
      `change_diff.py`/`change_classifier.py` es van trimar al motor viu
      (sense el codi C100, mai cridat, ni l'adquisició/informe específic
      de Census Income, exercici puntual ja fet); `validate_eligible.py`
      eliminat pel mateix motiu (T-11). (2) Amb `change_classifier.py`
      ja reduït a ~120 línies i un únic cridant real, es va fusionar
      dins de `change_diff.py` (`change_classifier.py` eliminat);
      `RETRY_CONFIG` (repetit a 3 scripts) consolidat en `errors.
      DEFAULT_RETRY_CONFIG`, corregint de pas un bug real (les
      descàrregues de contingut no rebien mai els `--retry-*` de la CLI)
      (T-12).
