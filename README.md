# HF Dataset Version Analysis

Mostreig aleatori de datasets de Hugging Face per estimar quants tenen 2 o mes versions.

## Configuració

1. Crea i activa l'entorn virtual, i instal·la les dependències:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

   **Requereix `git` instal·lat i al `PATH`** (US-302): `classify_dataset()`
   clona temporalment cada repositori en mode "bare" i amb filtratge de
   blobs (`git clone --bare --filter=blob:none`, sense contingut real de
   fitxers, només l'historial) per determinar amb precisió quins fitxers
   toca cada commit. Si `git` no és disponible (o el clonatge falla per
   qualsevol motiu), el pipeline recorre automàticament a l'heurística de
   títol anterior (`is_substantive_commit`) sense aturar-se — vegeu
   `docs/paper_techniques_ml_models_change.md`.

2. **Genera un token de Hugging Face** (necessari per fer les crides a l'API):
   1. Inicia sessió a [huggingface.co](https://huggingface.co) i ves a
      [Settings → Access Tokens](https://huggingface.co/settings/tokens).
   2. Fes clic a **"New token"**.
   3. Dona-li un nom (p.e. `tfg-dataset-analysis`) i tria el rol **"Read"**
      (n'hi ha prou: aquest pipeline només llegeix metadades públiques/gated
      de repositoris, mai n'escriu res).
   4. Copia el token generat (comença per `hf_...`). Només es mostra un cop.

3. **Desa el token en un fitxer `.env`** a l'arrel del repositori (al mateix
   nivell que `requirements.txt`):
   ```bash
   echo "HF_TOKEN=hf_el_teu_token_aqui" > .env
   ```
   El fitxer `.env` ja està exclòs a `.gitignore`: **no el pugis mai al
   repositori**. Si el token es filtra per error, revoca'l immediatament des
   de la mateixa pàgina de tokens i genera'n un de nou.

   El script falla ràpid amb un missatge clar (`Cap token HF detectat...`) si
   no troba `HF_TOKEN` a l'entorn, així que aquest pas és obligatori abans
   d'executar res.

## Quickstart

```bash
source venv/bin/activate
python notebooks/run_pipeline.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova rapida
python notebooks/run_pipeline.py --sample-size 2000 --threads 4 --seed 42                    # execucio principal
```

`run_pipeline.py` és l'orquestrador: encadena mostreig+elegibilitat
(`eligibility_scan.py`, Fase 0-1), extracció de versions
(`version_extractor.py`, Fase 1b) i classificació de canvis dels elegibles
(Fase 2) en un sol comandament, reutilitzant el mateix CSV entre fases --
sense pas manual d'un run a l'altre. `--skip-version-extraction`/
`--skip-classification` ometen una fase concreta; `--input-csv <csv>` salta
el mostreig i reutilitza un CSV d'un run previ.

### Scripts individuals

Per a proves o depuració d'una sola fase, cada script també s'invoca per
separat:

```bash
python notebooks/eligibility_scan.py --sample-size 50 --threads 4 --seed 42  # només Fase 0-1
python notebooks/version_extractor.py --input data/eligibility_report_50_1.csv  # només Fase 1b
python notebooks/eligibility_scan.py --classify-eligible data/eligibility_report_50_1.csv  # només Fase 2
```

## Ús amb Docker

Alternativa a l'entorn virtual local: no cal instal·lar Python ni les
dependències, només Docker. Cal el mateix fitxer `.env` amb `HF_TOKEN`
descrit més amunt. Si el teu usuari no és al grup `docker` del sistema,
anteposa `sudo` a totes les comandes següents (`sudo docker compose ...`).

```bash
docker compose build

# Pipeline complet en un sol comandament (Fase 0-1 + 1b + 2, mateix CSV
# encadenat entre fases -- vegeu Quickstart més amunt):
docker compose run --rm --remove-orphans run-pipeline --sample-size 50 --threads 4 --seed 42 --max-scanned 5000
ls data/eligibility_report_50_*.csv         # CSV d'elegibilitat (nom exacte inclou el run_id)
ls data/versions_*.csv                      # CSV de versions
ls data/change_classification_*.csv         # CSV de canvis classificats (nomes si hi ha elegibles)
```

Scripts individuals (ús manual/depuració d'una sola fase):

```bash
# eligibility-scan -- NOMÉS Fase 0-1
docker compose run --rm --remove-orphans eligibility-scan --sample-size 50 --threads 4 --seed 42 --max-scanned 5000

# version-extractor -- NOMÉS Fase 1b, usa el CSV que ha generat eligibility-scan
docker compose run --rm --remove-orphans version-extractor --input data/eligibility_report_<sample_size>_<run_id>.csv

# eligibility-scan --classify-eligible -- reclassificar un CSV d'un run previ
# sense tornar a mostrejar (mateix servei eligibility-scan, flag diferent)
docker compose run --rm --remove-orphans eligibility-scan --classify-eligible data/eligibility_report_<sample_size>_<run_id>.csv
```

`--remove-orphans` neteja contenidors aturats d'execucions anteriors amb
`docker compose run` (cadascuna en crea un de nou, amb un nom únic tipus
`..._run_<hash>`, que no s'esborra sol) -- evita l'avís "Found orphan
containers" a cada crida, no és obligatori per al funcionament.

**Important -- torna a fer `docker compose build` sempre que canviï el
codi a `notebooks/`** (per exemple, en afegir `version_extractor.py`):
`docker compose run` NO reconstrueix la imatge automàticament, així que
reutilitza la que ja tenia en caché. Si veus un error tipus `python: can't
open file '/app/notebooks/<script>.py': No such file or directory`, és
exactament això -- la imatge és anterior a aquell fitxer; `docker compose
build` (o `docker compose run --build ...`) ho arregla.

`data/` es munta com a volum (`./data:/app/data`), així que els CSV/JSON de
sortida apareixen directament al repositori de l'host, igual que executant
els scripts en local. Els scripts individuals **necessiten que la Fase 0-1
s'hagi executat abans**: llegeixen el CSV que aquesta genera, no en creen
cap de nou. Sense `docker compose`, l'equivalent amb `docker run` (l'imatge
usa `run_pipeline.py` com a entrypoint per defecte; sobreescriu-lo per a un
script individual):

```bash
docker build -t hf-dataset-version-analysis .
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" \
  hf-dataset-version-analysis --sample-size 50 --threads 4 --seed 42 --max-scanned 5000

# eligibility_scan.py sol, amb docker run (cal sobreescriure l'entrypoint per defecte):
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" \
  --entrypoint python hf-dataset-version-analysis notebooks/eligibility_scan.py \
  --sample-size 50 --threads 4 --seed 42 --max-scanned 5000

# version_extractor.py sol, amb docker run:
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" \
  --entrypoint python hf-dataset-version-analysis notebooks/version_extractor.py \
  --input data/eligibility_report_<sample_size>_<run_id>.csv
```

A cada tag `vX.Y.Z` a `main` (vegeu `docs/GIT_FLOW.md`), la imatge es publica
automàticament a `ghcr.io/joanferrer99/hf-dataset-version-analysis:X.Y.Z`.

Per l'estimació principal, **no passis `--max-scanned`**: la mostra ha
d'escanejar tota la població per no esbiaixar-se (vegeu "Mida de la mostra"
més avall). `--max-scanned` només és per a proves ràpides de desenvolupament.

Classificar exhaustivament tots els datasets (en lloc d'una mostra) **no és
viable sense un pla de pagament de Hugging Face**: als límits de peticions
per segon d'un compte gratuït, classificar els ~950.000 datasets de la
població trigaria hores i xocaria constantment amb rate limiting. Per això
aquest pipeline només implementa el mode de mostreig (`--sample-size`).

## Mida de la mostra i interval de confiança

L'objectiu és estimar, amb un 95% de confiança, la proporció de datasets de
HF que són elegibles (≥2 versions reals). Una execució real i no esbiaixada
(`--sample-size 1000`, sense `--max-scanned`) va donar:

| Mètrica                | Valor          |
|-------------------------|----------------|
| Població escanejada (N) | 949.991        |
| Elegibles                | 13             |
| No elegibles             | 938            |
| Accés restringit (403)   | 49             |
| Errors                   | 0              |
| Proporció elegible (p)   | 0.0137 (1.37%) |

Aquesta p observada és molt més baixa que les proves ràpides amb
`--max-scanned` (~10-17%), perquè `list_datasets()` no retorna els datasets
en ordre aleatori: capar l'escaneig als primers N esbiaixa la mostra. Només
un escaneig complet (sense `--max-scanned`) dona una p fiable.

Amb aquesta p (en lloc de l'assumpció conservadora p=0.5, que sobredimensiona
molt la mostra necessària quan la proporció real és petita), la mida de
mostra necessària per a un marge d'error E amb 95% de confiança és
n = z²·p·(1-p)/E² (z=1.96):

| Marge d'error (E) | n necessària |
|---|---|
| ±1.0 punts percentuals | ~520 |
| ±0.5 punts percentuals | ~2.070 |
| ±0.3 punts percentuals | ~5.730 |

Per això el valor per defecte de `--sample-size` és **2000**: marge d'error
±0.51pp (interval aprox. [0.86%, 1.88%]), doblant la precisió respecte a
n=1000 (±0.72pp) per només el doble de cost de classificació (~2 minuts amb
4 threads). La correcció per població finita és negligible en aquest rang
(fracció de mostreig < 0.6%).

## Criteri d'elegibilitat

Un dataset és **elegible** si té **2 o més versions genuïnes**, detectades per:
- **Tags/refs versionades** (explícites): p.e., `v1.0`, `v2.0`, etc.
- **Commits substantius** (implícits): commits que toquen fitxers de dades
  reals (no purament README/metadada), determinat inspeccionant els
  fitxers reals afegits/modificats/eliminats per cada commit (`git show`
  sobre un clonatge local, US-302; recorre a l'heurística de títol si el
  clonatge falla), I separats en el temps (mínim 6h entre commits
  substantius CONSECUTIUS, `MIN_SUBSTANTIVE_GAP_HOURS`) per descartar
  sessions úniques de pujada automàtica (p.e. eines com LeRobot) que
  generen desenes de commits en pocs minuts sense representar versions
  reals — vegeu `docs/us108_validation_report.md` i `docs/architecture.md`.

## Sortida

- `data/eligibility_report_N_version.csv` / `data/funnel_summary_N_version.json`
  (`eligibility_scan.py`, Fase 0-1: mostreig + elegibilitat)
- `data/versions_run_id.csv` / `data/versions_summary_run_id.json`
  (`version_extractor.py`, Fase 1b: seqüència de versions per dataset
  elegible, vegeu més avall)
- `data/change_classification_run_id.csv` (Fase 2: canvis classificats
  segons la taxonomia, vegeu més avall)

Amb `run_pipeline.py` (recomanat, vegeu Quickstart) les tres fases
s'encadenen soles, reutilitzant el mateix CSV d'elegibilitat; amb els
scripts individuals cal passar-se'l a mà d'un pas a l'altre (vegeu
"Scripts individuals" més amunt).

## Variables utils

- `--sample-size`: mida de la mostra
- `--threads`: processament en paral·lel
- `--max-scanned`: limit opcional nomes per proves rapides
- `--seed`: mostra reproduible
- `--skip-version-extraction` / `--skip-classification` (`run_pipeline.py`): ometen una fase concreta
- `--input-csv` (`run_pipeline.py`): salta el mostreig, reutilitza un CSV d'un run previ

## Extracció de versions (Fase 1b)

`version_extractor.py` extreu la seqüència ordenada de versions dels
datasets elegibles d'un CSV d'`eligibility_scan.py` (tags per als datasets
amb Criteri A, sessions de commits per als datasets amb Criteri B -- vegeu
`docs/architecture.md`, secció "Fase 1"). `run_pipeline.py` ja l'invoca
automàticament; per invocar-lo sol:

```bash
python notebooks/version_extractor.py --input data/eligibility_report_2000_5.csv
python notebooks/version_extractor.py --input data/eligibility_report_2000_5.csv --skip-size  # més ràpid, sense mida
```

## Classificació de canvis (Fase 2, US-305)

Integrada dins de `classify_dataset()` (`eligibility_scan.py`), NO com a
script separat -- reutilitza el mateix clonatge/inspecció de commits que
ja fa l'elegibilitat. Classifica cada commit substantiu amb un pare
conegut segons els 14 codis estructurals de la taxonomia implementats
(C210-C530, `docs/taiga/taxonomy.md`) -- **deliberadament sense C100**
(metadada, vegeu "Limitacions conegudes" a `docs/taiga/taxonomy.md`).
Només diferencia contingut real dels fitxers tabulars (`.parquet`/
`.csv`/`.tsv`) que van canviar; els binaris (àudio/vídeo/tensors) només
compten per a l'elegibilitat.

`run_pipeline.py` ja l'invoca automàticament en acabar la Fase 0-1,
reutilitzant el mateix CSV (vegeu Quickstart). També es pot invocar sola,
per reclassificar un CSV d'un run previ sense tornar a mostrejar:

```bash
python notebooks/eligibility_scan.py --classify-eligible data/eligibility_report_2000_5.csv
```

**Mai s'aplica a tota la mostra escanejada** (fins a 2000 datasets a la
Fase 0/1), només al subconjunt ja filtrat com a elegible (`eligible ==
True`, desenes com a molt sobre 2000): classificar contingut real a tots
els datasets mostrejats, elegibles o no, reintroduiria el cost de ~150GB
identificat a `docs/decisions_tfg.txt` (Decisió A-02), multiplicat per
~180x. Aquest filtre (no un flag manual) és el que manté barat encadenar-ho
sempre per defecte a `run_pipeline.py` -- per obtenir només el mostreig/
elegibilitat, sense classificar canvis, usa `run_pipeline.py
--skip-classification`. Output: `data/change_classification_<run_id>.csv`
(`dataset_id, version_from, version_to, code, is_breaking`).
