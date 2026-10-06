# Decisions obertes del motor de detecció v2

Decisions que el motor pren amb un valor per defecte però que cal
confirmar amb el director. Cada una té una opció a `notebooks/diffengine/
config.py`; canviar-la no requereix tocar codi. Les decisions ja tancades
són a `docs/decisions_tfg.txt`.

---

## U1. Unitat de "dataset": la taula (subset, split)

**Per defecte:** un dataset és una taula (subset, split) tal com la
mostra el Hub. Si una taula està partida en fitxers del mateix tipus
(shards `train-00000-of-00003`, o episodis numerats tipus LeRobot), es
concatenen en ordre i es comparen com una sola taula, **només si tots
tenen el mateix esquema**. Si els fitxers d'un split tenen noms no
relacionats, cada fitxer és un dataset. Els fitxers tabulars que no
formen part de cap taula (fora de cap split, metadades de repositoris
d'imatge/àudio, un altre format) no es classifiquen, però queden
registrats.

**Per què no "un fitxer = un dataset":** enquesta sobre els 69
repositoris elegibles de totes les execucions (151 revisions; detall a
`eval/survey/summary.md`, script `eval/survey_units.py`):

- **24 dels 50** repositoris amb dades tabulars tenen almenys una taula
  repartida en diversos fitxers: 13 taules d'episodis numerats (LeRobot),
  15 de shards del Hub, 6 amb noms no relacionats.
- Quan els fitxers d'una taula canvien entre dues versions, **en 10 de 14
  casos no es conserva cap ruta**: p.e. repositoris LeRobot que passen de
  104 episodis a 1 sol fitxer, o `aicrowd/arc-whestbench-public-2026`, que
  passa de 8 a 28 i a 63 shards. Comparant fitxer a fitxer, cada cas
  d'aquests surt com fitxers sencers eliminats i afegits (C421/C422 falsos).
- Els 6 grups amb noms no relacionats sí que són taules diferents
  (fitxers `meta/*.jsonl` de LeRobot, puntuacions amb esquemes diferents,
  lots de tres tipus de fitxer): per a aquests es manté un fitxer = un
  dataset.

**Efecte conegut:** una fila que passa de `train` a `test` surt com a
C422 a una taula i C421 a l'altra. Un canvi de partició és C100, que és
fora d'abast.

**Pregunta per a Alberto:** és correcte considerar els shards d'un mateix
(subset, split) com un sol dataset?

## U2. Fitxer absent en una de les dues revisions

**Per defecte:** estat `absent_old`/`absent_new`, sense codi. Abans
s'emetia C421/C422. Una taula nova sencera no és "afegir files" a una
taula existent.

## U3. Fitxers tabulars que no són dades

**Per defecte:** fora. Inclou manifests de checksums
(`MANIFEST_SHA256.csv`) i `metadata.csv` de repositoris de media. Les
regles de `datasets` ja excloen la major part (vegeu U1).

## U4. Cost de concatenar shards

Una taula LeRobot pot tenir centenars d'episodis. **Per defecte:** límit
de bytes per taula (`max_unit_bytes`, la suma de les dues versions); per
sobre, estat `too_large_profile_only` i **cap codi**. Les taules amb el
mateix contingut a les dues revisions (hash LFS o blob de git) no es
descarreguen. Encara no hi ha perfil en caché per fitxer ni codis de perfil
per a les taules massa grans.

---

## Decisions d'etiquetatge provisionals

| Id | Per defecte | Alternativa |
|---|---|---|
| **P1** | Un valor que passa a nul (o al revés) en una fila aparellada és **C510**, no C312/C322. | C312/C322 |
| **P2** | Dues files són "la mateixa fila editada" si coincideixen en **≥ 50%** de les columnes aparellades, o en totes les columnes clau inferides. Si no, són C422 + C421. | Un altre llindar |
| **P3** | Una conversió entre tipus (numèric ↔ categòric, one-hot) es codifica pel tipus de la columna **antiga**: C311 si era categòrica, C321 si era numèrica. | Segons el tipus nou |
| **P5** | Els canvis només de representació es reporten, mai s'amaguen: espais o majúscules en categories → C312 `representation`; separador decimal o notació científica → C322 `representation`; token d'absent (`?` → buit) → C510 `representation`. | No reportar-los |
| **P6** | Les columnes de text lliure (moltes categories, textos llargs) es tracten com a categòriques, però només amb comparacions de resum (diferència de domini, taxa de nuls). | Comparar-ne la distribució |
| **P8** | Si el canvi d'una columna queda explicat per una transformació ajustada (C322: factor, log, min-max, estandardització...), **no** s'emet C530 per a la mateixa columna: el canvi de distribució n'és conseqüència. | Emetre també C530 |
| **P9** | C312 només surt de canvis en files **aparellades** (o de representació). Si una categoria apareix o desapareix només perquè s'han afegit o eliminat files, el canvi és C421/C422, no C312. | Comptar també la diferència de domini de tota la columna |
| **P10** | Els comptadors de posició (enters no decreixents al llarg de les files a totes dues versions: `index`, `episode_index` de LeRobot) no són atributs: no són clau, no entren al hash de fila ni a C520/C530, i si es renumeren surten com a C322 `renumbered`. Trobat a l'execució real (`stlee601/cube_pick1`). | Tractar-los com qualsevol columna numèrica |
| **P11** | En un repositori de media (més vídeos que parquet, p.e. LeRobot), els fitxers tabulars que la media no fa servir es resolen com a taules pròpies i es comparen. La regla estricta de `datasets` (un sol format per repositori) els deixaria fora. | Seguir `datasets` al peu de la lletra |
| **P12** | Si la proporció de nuls d'una columna només canvia perquè s'afegeixen o s'eliminen files (cap cel·la aparellada passa de nul a valor o al revés), no és C510: és conseqüència de C421/C422. Criteri del paper a Census D6/D7. | C510 sempre que canviï la proporció |

Decisions del prompt original que **no s'apliquen**, per decisió de Joan:
- **D2 / P4** (C530 només per a la variable objectiu): C530 és un canvi
  de distribució de qualsevol atribut i el motor no identifica el target.
  C520 cobreix tots els parells de columnes.
- **P7 i C100**: C100 és fora d'abast; un canvi de format o de
  delimitador queda registrat a l'estat del parell, sense codi.

## Preguntes amb evidència de Census Income (Taula 1 del paper)

Resultat actual: precisió 71,4%, recall 96,2% (25 TP, 10 FP, 1 FN;
`data/census_income/census_income_paper_comparison_by_code_7.csv`). Cada
fals positiu s'ha comprovat obrint les dades:

| Versió | Codi del motor que el paper no marca | Què hi ha a les dades | Tipus |
|---|---|---|---|
| D3, D4 | C421 | 3.534 files (29%) amb una combinació (edat, `fnlwgt`, guanys, pèrdues) que no existeix a D0: vénen d'`adult.test` | Canvi real |
| D6 | C421 | Una altra mostra de files, part noves | Canvi real |
| D3 | C222 `education-num` | La columna `education` passa a ser numèrica (C311, que el paper sí marca) i `education-num` desapareix | Canvi real; el paper hi és incoherent |
| D6 | C222 `fnlwgt` | `fnlwgt` no hi és | Canvi real |
| D4, D6 | C410 | Ordre de files aleatori respecte a D0 (tau de Kendall ≈ 0). D3 ve del mateix repositori i el paper sí que hi marca C410 | Canvi real |
| D7 | C422 `had_nulls` | S'eliminen les 2.385 files amb `?` | Canvi real |
| D7 | C311 (i C312 no detectat) | Totes les categòriques passen a codis enters. Amb P3 és C311; el paper hi marca C312, però a D3/D4 marca C311 per al mateix tipus de canvi | Criteri (P3); el paper no és coherent |
| D7 | C410 | 14 files de D0 amb un nul s'aparellen amb files d'`adult.test` idèntiques en totes les altres columnes; D7 conserva l'ordre de D0 | Error del motor, indecidible amb les dades |

Ja resolts: el renom `fnlwgt` → `final_weight` sobre una altra mostra de
files (D3/D4, abans C221 + C222), i el C510 de D6/D7, que ara segueix el
criteri del paper (P12).

**Preguntes per a Alberto:** amb quin criteri el paper no marca C421 quan
la versió nova té files que no eren a l'original (D3, D4, D6), ni C422 a
D7? I la codificació de categòriques com a enters, és C311 o C312?

## Preguntes d'etiquetatge trobades en construir l'avaluació

- **Codificar una categòrica com a enters** (`Male/Female` → `0/1`): amb
  P3 és C311. S'hi ha d'afegir també C312 (els valors canvien)? Per
  defecte: només C311; C312 es permet però no s'exigeix.
- **Real → enter arrodonint** (`3.7` → `4`): és C321 (canvi de tipus). Els
  valors també canvien lleugerament: per defecte només C321; C322 es
  permet.
- **Files eliminades per un predicat que també tenien nuls**: si les
  files eliminades són exactament les d'una categoria i, alhora, totes
  tenen algun nul, el motor diu `had_nulls` (es comprova abans que
  `predicate`). Totes dues descripcions són certes; quina s'ha de
  preferir?
- **Benchmark d'Explain-Da-V**: pendent de revisar-ne la llicència i el
  format; el mapatge dels seus tipus de canvi als nostres codis s'afegirà
  aquí abans de fer-lo servir.
