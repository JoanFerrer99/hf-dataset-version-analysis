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

## Detectabilitat: schema-level vs content-level

**Decisió d'abast pendent — vegeu US-303.**

| Grup | Codis | Detectable sense descarregar contingut real |
|---|---|---|
| Schema-level | C210, C221, C222, C223, C311, C321 | ✅ Sí — comparant esquema entre versions (`dataset_infos.json`, `config.json`, llista de noms de columnes, `dtype` declarat) |
| Content-level | C312, C322, C410, C421, C422, C510, C520, C530 | ❌ No — cal llegir els valors reals de les dades |

Amb la població elegible observada (~1.37% de ~950K, previsiblement
desenes-centenars de datasets finals), descarregar contingut real només
per als elegibles ja no és inviable com ho seria per a tota la població.
**Aquesta és la decisió a portar al director**: 15 codis complets o
subconjunt schema-level.

## Ground truth de validació — Census Income (D1–D9)

El paper del director documenta 9 versions reals de HF del dataset
Census Income/Adult, etiquetades manualment contra els 15 codis
(combinant dataset cards + inspecció manual):

| Versió | Font (HF) |
|---|---|
| D1 | `scikit-learn/adult-census-income` |
| D2 | `AiresPucrs/adult-census-income` |
| D3 | `mstz/adult` (income) |
| D4 | `mstz/adult` (income-no race) |
| D5 | `Databoost/optimized_adult_census` |
| D6 | `ETdanR/adult_income` |
| D7 | `kuldeepbishnoi29/adult-fairness` |
| D8 | Zenodo record 12533514 |
| D9 | AIF360 `AdultDataset` |

Resultat reportat: cobertura del 100% (les 15 categories apareixen en
algun dels 9 datasets); D9 és el més divers (9/15 categories); C100 i
C223 (metadata i rename) són gairebé universals; canvis numèrics (C321/
C322) són els menys freqüents (el dataset base és majoritàriament
categòric).

**Ús previst (US-304)**: executar el pipeline propi sobre aquests 9
repositoris i comparar el resultat amb la Taula 1 del paper. Mètrica:
% d'acord per codi. Aquest és un conjunt de validació de cost molt baix
(9 datasets coneguts) abans d'escalar a tota la població elegible.
