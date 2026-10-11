# Taxonomia de canvis de dataset

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

## `is_breaking`: heurística d'execució, no de qualitat

`is_breaking` (`diffengine.output.BREAKING_CODES`)
respon NOMÉS "trenca l'execució d'un pipeline que llegeix el dataset per
nom/posició/tipus sense adaptar-se?" -- NO "afecta la qualitat del
model?". És una heurística pròpia d'aquest estudi, el paper no en
defineix cap de formal.

`True`: C210 (ordre de columnes), C222 (eliminar columna), C223 (renom),
C311/C321 (canvi de tipus), C410 (ordre de files).

`False` per a la resta -- C221/C421/C422 (afegir/eliminar columna o
fila), C312/C322/C510/C520/C530 (canvis de valors/missings/correlacions/
distribució). Aquests **poden degradar la qualitat del model igualment**
(data drift, concept drift), però no fan fallar un pipeline que
simplement llegeix el dataset. La distinció és deliberada, no un
oblit: `is_breaking` respon una pregunta d'infraestructura (crasha
l'execució o no), separada de si el canvi afecta el resultat del
model -- coherent amb la "Regla de disseny important" de dalt (la
taxonomia classifica el *dataset*, no l'ús que se'n fa).


## Detectabilitat: 3 nivells (revisat, US-303 AC1)

Només C100 és realment "metadada pura" (crida a l'API REST,
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
(Castaño et al. 2025, §3) com
a manera de descartar els datasets més "esbiaixats"/pesats. Comptat el
nombre REAL de commits (no el comptador capat a 50 de `classify_dataset`)
dels 11 elegibles: màxim 25 commits (`QFIN/FCMBench-Data`) — cap s'acosta
a 500, i no hi ha correlació amb el pes (`edinburghcstr/ami`, el més
pesat amb 29GB/versió, només té 20 commits). La guarda de >500 commits
segueix sent una bona pràctica general (encara no implementada a
`eligibility_scan.py`), però no redueix aquest problema concret.


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

## Com es detecta cada codi

El motor és `src/diffengine/`; `docs/engine.md` n'explica els 5 passos.
Detecta els 14 codis tabulars (C100 és fora d'abast), i cada canvi porta
el subtipus, l'evidència i una confiança. Les decisions d'etiquetatge que
encara són provisionals són a `docs/open_decisions.md`.

Límits que encara té:

- **Renoms semàntics sense relació de contingut.** Un renom es detecta pel
  nom normalitzat o pel contingut (valors idèntics, bijecció,
  transformació). Si la columna canvia de nom i de valors de manera que
  no es poden relacionar, surt com a C222 + C221.
- **Files duplicades i ordre (C410).** Quan hi ha files idèntiques,
  quina còpia correspon a quina és ambigu; en combinació amb altres canvis
  pot aparèixer un C410 que no hi és.
- **Taules massa grans.** Per sobre de `max_unit_bytes` el parell queda
  amb l'estat `too_large` i sense codis.
