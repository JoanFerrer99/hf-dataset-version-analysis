# Decisions obertes del motor de detecció

Decisions que el motor pren amb un valor per defecte però que cal
confirmar amb el director. Les que depenen d'un llindar o d'un interruptor
es canvien a `src/diffengine/config.py`, sense tocar codi.

- Les decisions ja tancades (U1, U2, P12 i les del prompt original que no
  s'apliquen) són a `docs/decisions_tfg.txt` (T-17 i T-20).
- Les preguntes sobre els desacords amb la Taula 1 del paper, comprovades
  amb les dades, són a `docs/validacio_census_income.md`.

---

## Unitat de comparació

### U3. Fitxers tabulars que no són dades

**Per defecte:** fora. Inclou manifests de checksums
(`MANIFEST_SHA256.csv`) i `metadata.csv` de repositoris de media. Les
regles de `datasets` ja excloen la major part.

### U4. Cost de concatenar shards

Una taula LeRobot pot tenir centenars d'episodis. **Per defecte:** límit
de bytes per taula (`max_unit_bytes`, la suma de les dues versions); per
sobre, estat `too_large` i **cap codi**. Les taules amb el
mateix contingut a les dues revisions (hash LFS o blob de git) no es
descarreguen. Encara no hi ha perfil en caché per fitxer ni codis de perfil
per a les taules massa grans. Aquest límit només s'aplica al pipeline: la
validació de Census Income descarrega i compara sempre els fitxers sencers
(el més gran fa 4,1 MB).

---

## Decisions d'etiquetatge provisionals

| Id | Per defecte | Alternativa |
|---|---|---|
| **P1** | Un valor que passa a nul (o al revés) en una fila aparellada és **C510**, no C312/C322. | C312/C322 |
| **P2** | Dues files són "la mateixa fila editada" si coincideixen en **≥ 50%** de les columnes aparellades, o en totes les columnes clau inferides. Si no, són C422 + C421. | Un altre llindar |
| **P3** | Una conversió entre tipus (numèric ↔ categòric, one-hot) es codifica pel tipus de la columna **antiga**: C311 si era categòrica, C321 si era numèrica. | Segons el tipus nou |
| **P5** | Els canvis només de representació es reporten, mai s'amaguen: espais o majúscules en categories → C312 `representation`; separador decimal o notació científica → C322 `representation`; token d'absent (`?` → buit) → C510 `representation`. | No reportar-los |
| **P6** | Les columnes de text lliure (moltes categories, textos llargs) es tracten com a categòriques, però només amb comparacions de resum (diferència de domini, taxa de nuls). | Comparar-ne la distribució |
| **P8** | Si el canvi d'una columna queda explicat per una transformació ajustada (C322: factor, log, min-max, estandardització...), **no** s'emet C530 per a la mateixa columna: el canvi de distribució n'és conseqüència. El text del paper (§4, canvis elementals que poden aparèixer junts) suggereix l'alternativa; cap cas de la Taula 1 ho resol. | Emetre també C530 |
| **P9** | C312 només surt de canvis en files **aparellades** (o de representació). Si una categoria apareix o desapareix només perquè s'han afegit o eliminat files, el canvi és C421/C422, no C312. | Comptar també la diferència de domini de tota la columna |
| **P10** | Els comptadors de posició (enters no decreixents al llarg de les files a totes dues versions: `index`, `episode_index` de LeRobot) no són atributs: no són clau, no entren al hash de fila ni a C520/C530, i si es renumeren surten com a C322 `renumbered`. Trobat a l'execució real (`stlee601/cube_pick1`). | Tractar-los com qualsevol columna numèrica |
| **P11** | En un repositori de media (més vídeos que parquet, p.e. LeRobot), els fitxers tabulars que la media no fa servir es resolen com a taules pròpies i es comparen. La regla estricta de `datasets` (un sol format per repositori) els deixaria fora. | Seguir `datasets` al peu de la lletra |
| **P13** | Un canvi de tipus que és una bijecció entre valors (codificar categories com a enters, o al revés) és C311/C321 **i** C312 `recoded`: canvien el tipus i els valors del domini (paper §4; Taula 1 a D3/D4). Un canvi només de format ("1" → 1) no és C312. La Taula 1 no és coherent: a D7 només marca C312 (`docs/validacio_census_income.md`, secció 5.2). | Només C312, com a D7 |

## Altres preguntes d'etiquetatge

- **Real → enter arrodonint** (`3.7` → `4`): és C321 `real_to_integer`
  (canvi de tipus). Els valors també canvien lleugerament; per defecte no
  s'hi afegeix C322.
- **Files eliminades per un predicat que també tenien nuls**: si les
  files eliminades són exactament les d'una categoria i, alhora, totes
  tenen algun nul, el motor diu `had_nulls` (es comprova abans que
  `predicate`). Totes dues descripcions són certes; quina s'ha de
  preferir?

## Pendent

- **Benchmark d'Explain-Da-V**: pendent de revisar-ne la llicència i el
  format; el mapatge dels seus tipus de canvi als nostres codis s'afegirà
  aquí abans de fer-lo servir.
