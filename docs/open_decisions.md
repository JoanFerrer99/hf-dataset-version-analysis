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
de bytes per taula (`max_unit_bytes`); per sobre, estat
`too_large_profile_only` i només codis de perfil. Els fitxers sense canvis
entre revisions no es tornen a llegir (perfil en caché per hash de
contingut).

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

Decisions del prompt original que **no s'apliquen**, per decisió de Joan:
- **D2 / P4** (C530 només per a la variable objectiu): C530 és un canvi
  de distribució de qualsevol atribut i el motor no identifica el target.
  C520 cobreix tots els parells de columnes.
- **P7 i C100**: C100 és fora d'abast; un canvi de format o de
  delimitador queda registrat a l'estat del parell, sense codi.

## Preguntes d'etiquetatge trobades en construir l'avaluació

- **Codificar una categòrica com a enters** (`Male/Female` → `0/1`): amb
  P3 és C311. S'hi ha d'afegir també C312 (els valors canvien)? Per
  defecte: només C311; C312 es permet però no s'exigeix.
- **Real → enter arrodonint** (`3.7` → `4`): és C321 (canvi de tipus). Els
  valors també canvien lleugerament: per defecte només C321; C322 es
  permet.
- **Benchmark d'Explain-Da-V**: pendent de revisar-ne la llicència i el
  format; el mapatge dels seus tipus de canvi als nostres codis s'afegirà
  aquí abans de fer-lo servir.
