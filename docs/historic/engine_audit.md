# Auditoria del motor de detecció de canvis actual

Punt de partida per reconstruir el motor (`claude_code_prompt_diff_engine.md`,
pas 1). Descriu el detector **tal com és ara**, sense cap canvi de codi.
Referències de línia sobre el commit `301891e`.

**Com s'ha fet:** lectura de `notebooks/change_diff.py`,
`notebooks/eligibility_scan.py` (part de classificació),
`notebooks/validate_census_income.py`, els tests, `docs/decisions_tfg.txt`
i `docs/multi_file_repos_investigation.md`; i una prova empírica: s'han
passat 14 dels 20 casos FP/FN coneguts per `compute_all_diffs` amb taules
sintètiques (secció 4).

---

## 1. Com es detecta cada codi

Tot passa per `change_diff.compute_all_diffs(before, after)`
(`change_diff.py:353`), que rep dos `DataFrame` ja carregats, crida 9
funcions `diff_*` i tradueix el resultat a un booleà per codi. Després
`classify_diffs` (`:422`) crea un `ChangeLabel` per cada codi `True`.

| Codi | Funció | Com ho decideix | Línies |
|---|---|---|---|
| C100 | — | **Mai s'emet.** Fora d'abast per decisió del director (A-02, test `test_never_produces_c100`). | — |
| C210 | `diff_columns` | Llista de columnes comunes (mateix nom, sense les renombrades) en l'ordre d'abans vs. d'ara; diferent → `True`. Afegir/treure columnes no el dispara. | `:154-156` |
| C221 | `diff_columns` | Noms presents ara i no abans, menys els aparellats com a renom. | `:115-160` |
| C222 | `diff_columns` | Noms presents abans i no ara, menys els aparellats com a renom. | `:115-160` |
| C223 | `diff_columns` | Eliminada + afegida amb el **mateix nom normalitzat** (minúscules, sense `-_. `) i dtype de la mateixa família numèric/no numèric. Primer candidat que encaixa. | `:136-146` |
| C311 | `diff_column_types` | `str(dtype)` diferent en una columna comuna, si el dtype d'abans no era numèric. | `:161-175` |
| C321 | `diff_column_types` | Igual, si el dtype d'abans era numèric. | `:161-175` |
| C312 | `diff_categorical_values` | Columnes comunes no numèriques: el **conjunt** de valors únics ha canviat (categories noves o desaparegudes). No mira freqüències ni files. | `:194-215` |
| C322 | `diff_numeric_values` | Columnes comunes numèriques: `mean/std/min/max` fora de `rtol=atol=0.05` (decisió T-16). No mira files. | `:218-240` |
| C410 | `diff_row_order` | Mateix nombre de files; hash per fila sobre les columnes comunes hashables; mateix multiset en un altre ordre. | `:254-278` |
| C421 | `diff_row_count` | `len(after) > len(before)`. També s'emet si el fitxer no existia abans (`classify_file_change`, `:454`). | `:243-251`, `:384` |
| C422 | `diff_row_count` | `len(after) < len(before)`. També si el fitxer ja no existeix (`:456`). | `:243-251`, `:385` |
| C510 | `diff_missingness` | Proporció de nuls d'una columna comuna diferent per més de `1e-9` (qualsevol canvi). | `:281-294` |
| C520 | `diff_correlation` | Matriu de Pearson de les columnes numèriques comunes; diferència absoluta màxima > 0.05. Sense prova de significació. | `:297-319` |
| C530 | `diff_distribution` | Per a **totes** les columnes comunes: quartils (numèriques, tolerància 5%) o desplaçament de freqüència per categoria > 0.05. | `:322-350` |

`is_breaking` = codi dins `BREAKING_CODES` (`:27`: C210, C222, C223,
C311, C321, C410).

### Què es compara (capa per sobre del motor, `eligibility_scan.py`)

- **Unitat de canvi** (`classify_dataset`, `:180`): Criteri A, cada
  commit substantiu contra `commits[i + 1]` (`:276-277`, suposa historial
  lineal); Criteri B, el commit més recent de cada sessió contra el de
  l'anterior (`classify_session_boundary_tabular_changes`, `:511`).
  Màxim 50 commits (`:266`).
- **Quins fitxers** (`classify_commit_tabular_changes`, `:460`): els
  modificats que passen `is_tabular_path` (`.parquet/.csv/.tsv`,
  `change_diff.py:51`), **els 5 primers** (`:477`), en l'ordre de
  `git show` (alfabètic).
- **Càrrega** (`download_tabular_file_at_revision`, `change_diff.py:62`):
  `hf_hub_download` + `read_parquet`, o `read_csv` amb `sep=","` (o tab
  per a `.tsv`) i els valors per defecte de pandas (`:88`). Fitxer sencer
  a memòria.

---

## 2. D'on ve cada limitació coneguda

| Limitació | Origen al codi | Confirmada a la prova? |
|---|---|---|
| **Columnes comunes = mateix nom** | Cada funció recalcula `common = [c for c in before.columns if c in after.columns]`: `:168`, `:201`, `:226`, `:268`, `:287`, `:306`, `:331`. Cap rep el mapa de renoms de `diff_columns`. | Indirectament (cas 1) |
| **Renoms semàntics perduts** | L'aparellament només compara noms normalitzats (`:136`, `:141`) i família de dtype (`:144`); mai el contingut. | Sí: casos 1 i 2 donen C221 + C222 (fins i tot amb contingut idèntic) |
| **C410 només reordenació pura** | Exigeix mateix nombre de files (`:265`) i mateix multiset de hashes (`:278`): qualsevol fila afegida, eliminada o editada ho trenca. | Sí: cas 3 no dona C410 |
| **C421/C422 aproximats** | Només el signe de `delta` (`:251`, `:384-385`). No hi ha alineació de files. | Sí: cas 4 (10 fora, 10 dins) no dona ni C421 ni C422 |
| **Fallada de descàrrega = fitxer absent** | `download_tabular_file_at_revision` retorna `None` davant **qualsevol** excepció (`:84`, `:91`): 404, 429 esgotat, error de lectura. `classify_file_change` converteix `None` en C421/C422 (`:454-457`). | No provat (requereix xarxa); és directe al codi |
| **Columnes no hashables excloses** | `_is_hashable_series` (`:178`) les treu de C312, C530 i C410 (`:269`). | Parcial: el cas 12 (reordenació amb una columna `dict`) **sí** dona C410, perquè la resta de columnes són hashables. Només falla si la reordenació afecta únicament columnes no hashables, o totes ho són. |
| **El CSV no diu de quin fitxer ve l'etiqueta** | `ChangeLabel` (`:404`) no té camp de ruta; `classify_commit_tabular_changes` aplana les etiquetes de tots els fitxers (`:481`); `run_classification` escriu `dataset_id, version_from, version_to, code, description, is_breaking` (`:814-815`). Cas real: 5 C421 idèntiques per a `edinburghcstr/ami`. | Documentat a `multi_file_repos_investigation.md` |

### Limitacions addicionals trobades

1. **Les columnes identificador es tracten com a variables.** Una columna
   `id` és numèrica: afegir o treure files en mou el mínim, màxim i
   mitjana. Al cas 3 (barrejar + afegir) surt C322 i C520; al cas 4 surt
   C322, C520 i C530, i cap codi de files. Probablement una font
   important de FP de C322/C520/C530 a dades reals.
2. **Artefactes de tipus.** C311/C321 compara `str(dtype)` (`:172`): una
   columna entera que guanya un NaN passa a `float64` i dona C321 (cas
   6). Estandarditzar una columna entera també dona C321 (cas 15).
3. **No hi ha tokens de valor absent.** `read_csv` amb valors per defecte:
   `?` (el que fa servir Census Income) és una categoria més. Passar de
   `?` a nul dona C312 + C510 (cas 9).
4. **Delimitador fix.** `sep=","` per a tot excepte `.tsv` (`:88`): un
   CSV amb `;` es llegeix com una sola columna.
5. **Sense `.json`/`.jsonl`.** `TABULAR_EXTENSIONS` (`:51`) no els inclou.
6. **Edicions de cel·les invisibles.** C312 mira el conjunt de valors i
   C322 estadístics agregats: editar 5 valors dins del rang existent no
   dona res (cas 5).
7. **Sense mida d'efecte ni significació.** C510 salta per qualsevol
   diferència (`:292`); C520 per |Δ| > 0.05 sense prova; C530 sobre totes
   les columnes, no només el target.
8. **Cap de 5 fitxers esbiaixat**: sempre els 5 primers per ordre
   alfabètic (`:477`); en repositoris LeRobot, fins al 96% dels fitxers
   d'un commit no s'inspeccionen mai.
9. **Manifests comptats com a tabulars**: `MANIFEST_SHA256.csv` passa
   `is_tabular_path` només per l'extensió.
10. **Criteri A suposa historial lineal**: l'"anterior" és `commits[i+1]`
    de la llista, no el pare real de git (`:276-277`).
11. **La Fase 2 recalcula l'elegibilitat** en lloc de llegir-la del CSV de
    la Fase 0.
12. **Sense evidència ni confiança**: només booleans. Les dades de suport
    (`_details`, `:389`) es calculen i es llencen; ningú les llegeix.

---

## 3. Qui consumeix la sortida

**El CSV `change_classification_<k>.csv`** (columnes `dataset_id,
version_from, version_to, code, description, is_breaking`):
- **Cap codi el llegeix.** `run_pipeline.py` (`:125-127`) només en
  guarda la ruta per al resum per consola; els tests només en comproven
  la ruta i les columnes (`test_run_pipeline.py`,
  `test_eligibility_scan.py::TestRunClassification`).
- **El magatzem (Fase 3) no existeix.** El disseny és a la decisió T-04:
  taula de fets `Change(dataset_id, date_id, kind_of_change_id,
  age_days)` i dimensió `KindOfChange(kind_id, category, subcategory,
  is_breaking, taxonomy_level_1..3)`. Per tant, el que cal mantenir
  estable és: **els codis** (`C210`…`C530`, més `C100` si entra),
  **`is_breaking`** per codi, i les claus `dataset_id`/`version_from`/
  `version_to`. L'esquema nou de la L6 no porta `is_breaking` ni
  `description`: l'export compatible les ha de conservar.

**L'API del motor** (consumidors dins del codi, a tenir en compte en la
migració):

| Consumidor | Què fa servir |
|---|---|
| `eligibility_scan.classify_commit_tabular_changes` | `is_tabular_path`, `download_tabular_file_at_revision`, `classify_file_change` |
| `eligibility_scan.run_classification` | `CODE_DESCRIPTIONS` |
| `validate_census_income.py` | `compute_all_diffs` (claus booleanes per codi), `classify_diffs`, `TABULAR_CODES` |
| `extension_report.py` | `is_tabular_path`, `TABULAR_EXTENSIONS` |
| `tests/test_change_diff.py` | Totes les funcions `diff_*` per separat |

**Tests que fixen comportament que el disseny nou canvia** (s'hauran de
reescriure, no d'esquivar):
- `test_never_produces_c100` (C100 torna a entrar).
- `test_classifier_never_receives_a_target_column_parameter` (D2 necessita
  el target).
- `test_remove_and_add_different_name_is_not_a_rename` (L3 aparella per
  contingut).
- `test_added_file_produces_c421` / `test_removed_file_produces_c422`
  (L0: estats `absent_old`/`absent_new`).
- `test_reorder_confined_to_non_hashable_column_not_detected`.

---

## 4. Prova empírica: casos FP/FN coneguts amb el motor actual

Taula sintètica de 200 files (`id, age, sex, wc, inc`), passada per
`compute_all_diffs`. Els casos que depenen de fitxers reals o de la xarxa
(8, 11, 13, 16-18, 20) queden per a l'arnès d'avaluació.

| Cas | Esperat | Motor actual | |
|---|---|---|---|
| 1 Renom + recodificació `sex`→`is_male` | C223 + C312 | C221, C222 | ✗ |
| 2 Renom amb contingut idèntic | C223 | C221, C222 | ✗ |
| 3 Barrejar + afegir files | C410 + C421 | C322, C421, C520 | ✗ |
| 4 10 files fora + 10 de noves | C421 + C422 | C322, C520, C530 | ✗ |
| 5 Cel·les editades | C322 `cell_edits` | (res) | ✗ |
| 6 Enter que guanya NaN | C510 | C321, C510 | ✗ |
| 7 Mateixes dades, altres cometes i CRLF | (res) | (res) | ✓ |
| 9 `?` → nul | C510 `representation` | C312, C510 | ✗ |
| 10 Espais inicials a les categories | C312 `representation` | C312 (sense subtipus) | ≈ |
| 12 Reordenar amb columna `dict` | C410 | C410 | ✓ |
| 14a Columna afegida al mig | C221 | C221 | ✓ |
| 14b Columnes aparellades intercanviades | C210 | C210 | ✓ |
| 15 Estandarditzar una variable | C322 | C321, C322, C530 | ✗ |
| 19 Treure una còpia d'una fila duplicada | C422 | C422 | ✓ |

---

## 5. Abans de planificar: conflictes i dades que falten

Coses que el prompt dona per decidides però que xoquen amb decisions o
documentació existents. No les resolc jo; cal confirmar-les.

1. **D2 (C530 només per al target) contradiu la regla de disseny
   documentada**: `docs/taxonomy.md` ("la taxonomia classifica el
   *dataset*, no l'ús que se'n fa; el classificador no ha de saber quina
   columna és el target") i la decisió M-03. El codi i un test ho
   imposen. Si D2 està confirmada pel director, cal actualitzar aquesta
   regla i la decisió.
2. **D3 (un fitxer = un dataset) va en sentit contrari a la recomanació
   de `multi_file_repos_investigation.md`**, que considerava els
   fragments LeRobot (`data/chunk-000/episode_*.parquet`) com un sol
   dataset. Amb D3, un repositori com `xhaka3456/Pick_Place` passa a
   ser 140 datasets. Afecta directament la dimensió `Dataset` del
   magatzem i el cap de 5 fitxers.
3. **C100 torna a l'abast.** La decisió A-02 i el director el van
   excloure.
4. **Etiquetes de Census Income.** El prompt diu que no es reconstrueixin
   del PDF, però ja existeixen: `PAPER_GROUND_TRUTH` a
   `validate_census_income.py`, transcrit a mà per Joan des de la Taula 1
   (decisió T-14). Es pot exportar tal qual a
   `tests/fixtures/census_income_labels.csv` si ho vols.
5. **El PDF de la taxonomia no és al repositori**: `docs/papers/` no
   existeix.
6. **Dependències**: `scipy` (algorisme hongarès, proves estadístiques) i
   `scikit-learn` (arbre de decisió per al subtipus `predicate`) no estan
   instal·lats. Entorn: `huggingface_hub` 1.18.0, pandas 3.0.3,
   numpy 2.4.6, pyarrow 25.0.1.

**Línia base que ja tenim** (abans de l'arnès de mutacions): Census
Income D1-D7 amb el motor actual, precisió 64.5% (20/31), recall 76.9%
(20/26); per codi a
`data/census_income/census_income_paper_comparison_by_code_5.csv`.
