# Investigació — repositoris amb múltiples fitxers tabulars

> Feedback del director (reunió): fins ara el pipeline tracta un
> repositori HF com UN dataset. Un repositori pot contenir més d'un
> fitxer tabular (csv/parquet). Calia investigar per què, abans de
> decidir si cal estudiar els canvis de cada fitxer per separat.
> **Aquest document és una investigació amb recomanació, NO una decisió
> tancada** -- pendent de parlar-ho amb el director (vegeu
> `docs/decisions_tfg.txt`).

## Per què això importa: evidència empírica ja existent

`classify_commit_tabular_changes` (`notebooks/eligibility_scan.py`)
classifica cada fitxer tabular d'un commit per separat, però aplana
TOTES les etiquetes resultants en una sola llista -- `ChangeLabel`
(`notebooks/change_diff.py`) no té cap camp que indiqui de quin fitxer
prové cada etiqueta. Confirmat amb dades reals: `edinburghcstr/ami` (un
dels elegibles canònics d'una execució anterior) mostra 5 files `C421`
idèntiques per al mateix parell de versions -- exactament el cap
`MAX_TABULAR_FILES_PER_COMMIT = 5`, és a dir, 5 fitxers diferents
indistingibles a la sortida.

## Dades reals: recompte de fitxers tabulars per dataset elegible

Font: `data/extension_report_1.csv`/`_summary_1.json` (14 datasets
elegibles, `data/eligibility_report_2000_6.csv`). 9 dels 14 tenen 1-3
fitxers tabulars (normal, sense ambigüitat). **5 en tenen més de 2**:

| Dataset | Fitxers tabulars |
|---|---|
| `xhaka3456/Pick_Place` | 140 |
| `lipsop/so101-block-in-bin-100ep` | 100 |
| `aaron-ser/so101-cardboard-box-pickup-dataset` | 35 |
| `davidgoss/so100_test` | 7 |
| `HanyueShen/YunXiaoHe-RISA-Avalon-Eval` | 4 |

## Inspecció dels noms de fitxer (la pregunta real: sharding o datasets genuïns?)

Recuperat amb `version_extractor.fetch_tree_paths` sobre cadascun
d'aquests 5 repositoris:

**4 de 5 -- patró de "chunking" clar i idèntic** (`xhaka3456/Pick_Place`,
`lipsop/so101-block-in-bin-100ep`, `aaron-ser/so101-cardboard-box-pickup-
dataset`, `davidgoss/so100_test`):

```
data/chunk-000/episode_000000.parquet
data/chunk-000/episode_000001.parquet
data/chunk-000/episode_000002.parquet
...
```

Aquest és el format estàndard **LeRobot** (gravacions d'episodis de
robòtica): CADA episodi és el seu propi fitxer Parquet, agrupats en
carpetes `chunk-XXX` d'uns ~1000 episodis. **Conclusió inequívoca: és
UN sol dataset (una col·lecció de demostracions d'un mateix robot/tasca)
partit en molts fitxers petits per raons d'emmagatzematge/streaming, NO
diversos datasets diferents al mateix repositori.** La intuïció del
director ("potser 1 és massa gran i està separat") es confirma
exactament per a aquests 4 casos.

**1 de 5 -- patró clarament DIFERENT** (`HanyueShen/YunXiaoHe-RISA-
Avalon-Eval`):

```
MANIFEST_SHA256.csv
data/avalon_leaderboard.csv
data/risa_five_task_token_ablation.csv
data/risa_full30_scores.csv
```

Aquests SÍ semblen taules genuïnament diferents (un rànquing, un estudi
d'ablació, una taula de puntuacions) -- un repositori de benchmark que
n'agrupa diversos resultats relacionats però conceptualment separats.
**Candidat real per a "diversos datasets al mateix repositori".**

## Troballa addicional (no buscada, trobada per casualitat)

`MANIFEST_SHA256.csv` a `HanyueShen/YunXiaoHe-RISA-Avalon-Eval` és un
**manifest de sumes de verificació** (llista hashos de fitxers per
integritat), NO contingut de dataset -- però `is_tabular_path` el compta
com a tabular NOMÉS per l'extensió `.csv`, sense cap altra comprovació.
És un fals positiu real, diferent del problema de sharding, que val la
pena documentar aquí encara que no sigui l'objecte principal d'aquesta
investigació.

## Implicació addicional del cap `MAX_TABULAR_FILES_PER_COMMIT = 5`

Per als 4 casos de sharding, un commit que toqui molts episodis alhora
(p.e. la pujada inicial d'un dataset amb 140 fitxers) NOMÉS en classifica
els primers 5 -- no és només un problema d'atribució (quin fitxer va
generar quina etiqueta), sinó que la GRAN MAJORIA dels fitxers d'aquests
datasets mai s'arriben ni a inspeccionar. Ja documentat com a limitació
coneguda (`docs/taiga/taxonomy.md`, "mostra representativa, no
exhaustiva"), però aquesta investigació en quantifica l'abast real per
primer cop: fins a un 96% dels fitxers d'un dataset (135 de 140 a
`xhaka3456/Pick_Place`) queden fora del cap en un únic commit.

## Recomanació (no una decisió tancada)

- **Pel patró de sharding (LeRobot chunk/episode, 4 de 5 casos reals)**:
  NO cal tractar cada fitxer com un dataset separat -- són fragments
  d'UN dataset. Mantenir-los agrupats sota el mateix `dataset_id` és
  conceptualment correcte. El que SÍ val la pena reconsiderar (fora
  d'abast d'aquesta investigació, treball futur) és si el mostreig
  d'aquest cap de 5 fitxers hauria de ser aleatori/representatiu en lloc
  del primer 5 per ordre alfabètic (`chunk-000/episode_000000` ...
  `episode_000004` sempre els mateixos), per no esbiaixar sistemàticament
  cap als primers episodis de cada dataset.
- **Pel patró de taules genuïnament diferents (1 de 5 casos, benchmarks
  amb diverses taules de resultats)**: aquest SÍ és un candidat real per
  afegir un camp `path`/`file` a `ChangeLabel` en un treball futur, per
  poder distingir "canvis al leaderboard" de "canvis a l'ablació" dins
  del mateix repositori -- però amb NOMÉS 1 cas real sobre 14 datasets
  elegibles (7%), l'impacte pràctic actual és baix. Val la pena revisar
  aquesta xifra quan la mostra elegible creixi (mostres de `--sample-
  size` més grans) abans de prioritzar aquest treball.
- **Filtre de manifests de checksum** (`MANIFEST_SHA256.csv` i similars,
  p.e. `checksums.csv`/`SHA256SUMS`): candidat petit i de baix risc per a
  `is_tabular_path`/`SUBSTANTIVE_DATA_EXTENSIONS` -- exclusió per nom de
  fitxer, no per extensió, similar al patró ja existent de
  `NON_SUBSTANTIVE_FILES`.

**Cap d'aquestes tres recomanacions s'implementa en aquesta sessió** --
són candidates per a treball futur, pendents de confirmar amb el
director quin és el pes real d'aquests casos a mesura que la mostra
elegible creixi.
