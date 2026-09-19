# Taxonomia de canvis de dataset — v2 (formal, codificada)

> Font: paper del director de TFG (secció 4 "Taxonomy of dataset changes"
> + secció 5 "Example of a dataset changes", amb Census Income com a
> ground truth). Aquesta versió **substitueix** el mapa mental informal
> que teníem inicialment (Metadata / Columns Set / Column Type / Rows Set
> / Data Characteristics sense codis).

## Els 15 codis oficials

| Codi | Categoria | Descripció |
|---|---|---|
| C100 | Metadata | Informació sobre el dataset com a tot (source, license, file format, field delimiter, split train/test, temporal characteristics) |
| C210 | Columns Set | Ordre de columnes |
| C221 | Columns Set | Afegir columna |
| C222 | Columns Set | Eliminar columna |
| C223 | Columns Set | Renombrar columna |
| C311 | Column Kind | Tipus de columna categòrica |
| C312 | Column Kind | Valors d'una columna categòrica |
| C321 | Column Kind | Tipus de columna numèrica |
| C322 | Column Kind | Valors d'una columna numèrica |
| C410 | Rows Set | Ordre de files |
| C421 | Rows Set | Afegir fila |
| C422 | Rows Set | Eliminar fila |
| C510 | Data Characteristics | Missings |
| C520 | Data Characteristics | Correlacions |
| C530 | Data Characteristics | Distribució de les dades |

## Canvis respecte a la versió anterior (informal)

| Abans | Ara |
|---|---|
| Columns Set → Arity (categoria pròpia) | ❌ Eliminada com a categoria classificable — ara es tracta com "impacte" (secció 4.1), no com a tipus de canvi |
| Column Type → Categorical → **Order** | ❌ Eliminada explícitament: "aquesta informació no està disponible al propi dataset, sinó externament" |
| Rows Set → Row → **Change ID** | ❌ Eliminada com a categoria pròpia |
| Rows Set → Cardinality (categoria pròpia) | ❌ Eliminada com a categoria classificable — mateix tractament que Arity |
| Data Characteristics → Target → Concept drift / Balance | ❌ **No són codis nous.** Són interpretacions de C520/C530 quan la columna afectada és el target del pipeline. La taxonomia classifica el *dataset*, no l'ús que se'n fa |

## Regla de disseny important

> "Notice that all these perspectives are related to the dataset, and not
> to the use we make of it (e.g., considering a column either the target
> to be predicted or a feature relevant to do that does not depend on the
> dataset)."

Conseqüència pràctica: el classificador **no ha de saber** quina columna
és el target. Etiqueta C520/C530 igual per a qualsevol columna; la
interpretació com a "concept drift" es fa a posteriori, fora del
classificador.

## Detectabilitat: 3 nivells (revisat, US-303 AC1)

**La taula binària original (schema-level vs content-level) simplificava
massa.** Només C100 és realment "metadada pura" (crida a l'API REST,
`DatasetInfo`/dataset card, zero accés al fitxer). C210, C221, C222,
C223, C311, C321 necessiten com a mínim una **lectura parcial** del
fitxer (capçalera CSV, o el footer d'un Parquet via lectura per rangs
HTTP/`pyarrow`, sense baixar-lo sencer) — barat, però NO és "zero
descàrrega".

| Nivell | Codis | Cost | Mecanisme |
|---|---|---|---|
| 1 — Metadada pura | C100 | ~0 | API REST (`DatasetInfo`, dataset card) |
| 2 — Lectura parcial (schema) | C210, C221, C222, C223, C311, C321 | Baix, constant per fitxer | Capçalera CSV / footer Parquet (`pyarrow`, lectura per rangs) |
| 3 — Contingut complet | C312, C322, C410, C421, C422, C510, C520, C530 | Proporcional a la mida real | Lectura del fitxer (idealment només les columnes rellevants, no tot el fitxer sencer) |

### Viabilitat real del Nivell 3 (US-303 AC2, calculat amb dades pròpies)

Amb `data/versions_1.csv` (Fase 1, 11 datasets elegibles, 40 versions,
29 parells de versions consecutius): baixar el contingut complet de cada
versió (un cop, reutilitzat entre parells) suma **151.4 GB**, amb
`edinburghcstr/ami` sol pesant 78GB. "Població elegible petita" en NOMBRE
(11 datasets) **no vol dir petita en BYTES** — corregeix l'afirmació
anterior d'aquesta secció ("ja no és inviable").

**Hipòtesi provada i descartada**: exclusió de datasets amb >500 commits
(Castaño et al. 2025, `docs/paper_techniques_ml_models_change.md` §3) com
a manera de descartar els datasets més "esbiaixats"/pesats. Comptat el
nombre REAL de commits (no el comptador capat a 50 de `classify_dataset`)
dels 11 elegibles: màxim 25 commits (`QFIN/FCMBench-Data`) — cap s'acosta
a 500, i no hi ha correlació amb el pes (`edinburghcstr/ami`, el més
pesat amb 29GB/versió, només té 20 commits). La guarda de >500 commits
segueix sent una bona pràctica general (encara no implementada a
`eligibility_scan.py`), però no redueix aquest problema concret.

**Estratègia recomanada** (mínim possible, aplicada per codi/columna, no
per exclusió de dataset): Nivell 1/2 sempre, per a tots els parells de
versions (cost gairebé nul). Nivell 3 només per als codis que ho
exigeixen, llegit de forma selectiva **per columna** (projecció de
columnes Parquet) en lloc del fitxer sencer — la major part dels 151GB
són columnes binàries (àudio/vídeo/tensors) que no fan falta per calcular
recompte de files, missings o distribució d'una columna concreta. Mesura
empírica del cost real amb projecció de columnes: pendent (US-305).

**Aquesta és la decisió a portar al director**: 15 codis complets (amb
lectura selectiva per columna) o subconjunt de Nivell 1+2 únicament.

## Ground truth de validació — Census Income (D1–D9, D1-D7 dins d'abast)

El paper del director documenta 9 versions del dataset Census
Income/Adult, etiquetades manualment contra els 15 codis (combinant
dataset cards + inspecció manual), cadascuna comparada contra l'**original
de la UCI** (D0: `archive.ics.uci.edu/dataset/2/adult`, footnote 1 del
paper) — **no** D_i contra D_{i-1}. D1–D9 són repositoris/fonts
**independents entre si** (comptes/organitzacions diferents), no
commits/tags successius d'un mateix repositori.

| Versió | Font | A Hugging Face? |
|---|---|---|
| D0 (baseline) | `archive.ics.uci.edu/dataset/2/adult` | ❌ No (UCI) |
| D1 | `scikit-learn/adult-census-income` | ✅ |
| D2 | `AiresPucrs/adult-census-income` | ✅ |
| D3 | `mstz/adult` (subcarpeta `income`) | ✅ |
| D4 | `mstz/adult` (subcarpeta `income-no race`) | ✅ |
| D5 | `Databoost/optimized_adult_census` | ✅ |
| D6 | `ETdanR/adult_income` | ✅ |
| D7 | `kuldeepbishnoi29/adult-fairness` | ✅ |
| D8 | Zenodo record 12533514 | ❌ No (Zenodo) |
| D9 | AIF360 `AdultDataset` (llibreria Python, baixa de la UCI) | ❌ No (AIF360) |

**Troballa (no evident al text principal del paper, només a les notes a
peu de pàgina)**: D8 i D9 NO són a Hugging Face. El nostre pipeline està
construït sencer sobre `huggingface_hub` — descarregar-los requeriria 2
connectors únics (API de Zenodo; AIF360/UCI) només per a 2/9 files, sense
cap reutilitat per a la resta del projecte (la població real mostrejada
només prové de HF). **Decidit: US-304 cobreix només D1–D7**; D8/D9 queden
documentats aquí com a fora d'abast.

Resultat reportat pel paper (sobre els 9): cobertura del 100% (les 15
categories apareixen en algun dels 9 datasets); D9 és el més divers
(9/15 categories, però fora del nostre abast); C100 i C223 (metadata i
rename) són gairebé universals; canvis numèrics (C321/C322) són els
menys freqüents (el dataset base és majoritàriament categòric).

**Ús previst (US-304, redefinida)**: NO calcular encara cap "% d'acord"
(això pressuposaria un classificador de codis, que és feina de US-305).
US-304 valida que el nostre MOTOR DE DIFFING pot observar mecànicament
un senyal allà on el paper marca un canvi, sobre D1–D7 (contra D0). El
% d'acord codi per codi es calcula més endavant, a US-305, un cop
existeixi el classificador. Registre complet i permanent d'aquesta
validació: `docs/census_income_validation_report.md`.

## Limitacions conegudes del motor de diffing

`notebooks/change_diff.py` implementa 14 dels 15 codis (tots excepte
C100). D'aquests 14, tots són detectats amb tècniques exactes o
heurístiques explícitament documentades -- cap és una "caixa negra".

**Únic codi realment fora d'abast:**
- **C100** (metadada): és inspecció de dataset card/README, no una
  comparació tabular -- fora de l'abast per disseny, mai un objectiu
  d'aquest motor (`change_diff.py:17-19`).

**Implementat, amb abast declarat (no és el mateix que "no detectable"):**
- **C410** (ordre de files, Decisió T-14): tècnica de hash de contingut
  per fila (multiset), NOMÉS sobre columnes hashables -- detecta
  reordenació PURA (mateix contingut exacte, ordre diferent) amb certesa;
  NO detecta reordenació barrejada amb altres canvis al mateix parell de
  versions, ni reordenació confinada a columnes no hashables (p.e. bytes
  d'àudio) mentre les columnes hashables es mantenen en la mateixa
  posició (`change_diff.py`, `diff_row_order`). És a `BREAKING_CODES`:
  un canvi d'ordre pot afectar pipelines d'ML que accedeixen a les dades
  per posició, potencialment requerint adaptació als components d'ingesta
  o preprocessament.
- **C223** (renom de columna): heurística explícita -- una columna
  eliminada i una afegida es tracten com a renom NOMÉS si ocupen la
  mateixa posició ordinal i tenen dtype de la mateixa família; qualsevol
  altre cas es reporta com a add/remove per separat, no com a renom.
  Cap tècnica purament estructural distingeix un renom d'un remove+add
  sense heurística (`change_diff.py:117-162`, `diff_columns`).
- **C421/C422** (afegir/eliminar fila): sense un identificador d'instància
  estable, NO es pot atribuir un canvi de recompte a "files afegides" vs
  "files eliminades" amb certesa -- només al signe del delta
  (`change_diff.py:265-275`, `diff_row_count`).
- **Cap `MAX_TABULAR_FILES_PER_COMMIT = 5`** (`eligibility_scan.py:615`):
  per a commits que toquen més de 5 fitxers tabulars, només se'n
  classifiquen 5 -- mostra representativa, no exhaustiva (confirmat en
  una execució real que alguns datasets "chunked", p.e.
  `edinburghcstr/ami`, haurien trigat més d'una hora sense aquest cap).
- **Census Income, "% d'acord codi per codi"**: mai calculable contra el
  ground truth del paper (extracció del PDF no conserva l'alineació de
  columnes de la taula amb marques "✔") -- vegeu `docs/census_income_
  validation_report.md`, secció "Limitacions".

### Tècniques alternatives considerades (i descartades conscientment)

Per a cada codi següent, es va triar una tècnica més simple per sobre
d'una alternativa més sofisticada -- decisions conscients, no llacunes
obertes:
- **C223 (renom)**: heurística posició+dtype triada per sobre d'una
  alternativa de similitud de contingut (comparar distribucions de valors
  entre la columna eliminada i l'afegida) -- menys risc de falsos
  positius, cost computacional més baix.
- **C530 (distribució)**: quartils/freqüència relativa triats per sobre
  d'un test estadístic formal (Kolmogorov-Smirnov, `scipy`) -- evita una
  dependència nova només per a aquesta heurística (`change_diff.py:327-334`).
- **C520 (correlació)**: només Pearson (relacions lineals) -- Spearman
  (monotòniques, no lineals) detectaria més casos amb més cost
  computacional; límit conegut, no un error.
- **C421/C422 (recompte de files)**: cap tècnica alternativa resol
  l'atribució exacta sense canviar QUÈ s'adquireix -- caldria que el
  dataset mateix tingués una columna d'ID estable, cosa que no es pot
  assumir per a datasets arbitraris d'HF.
