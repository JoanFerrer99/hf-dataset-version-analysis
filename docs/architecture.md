# Arquitectura — HF Dataset Version Analysis
 
 ----

## 1. Què fa aquest projecte i per què

> **Com canvien els datasets publicats a Hugging Face d'una versió a la
> següent, i amb quina freqüència apareix cada tipus de canvi?**

El motiu: molts sistemes d'aprenentatge automàtic (ML) s'entrenen amb datasets de tercers. Si el mantenidor del dataset reanomena una columna, afegeix files o reescala una variable, el pipeline de qui el consumeix pot fallar o, pitjor, seguir funcionant amb dades que ja no són les que esperava. Hugging Face no obliga a versionar ni a documentar els canvis, per tant no hi ha manera barata de saber què ha canviat.

El projecte construeix un **pipeline automàtic** que:

1. Agafa una **mostra aleatòria** de tota la població de datasets de HF(~1 milió).
2. Detecta quins tenen **més d'una versió real** (la gran majoria no en tenen: es publiquen un cop i no es toquen més).
3. Per a aquests, n'extreu la **seqüència de versions**.
4. Compara versions consecutives i **classifica cada diferència** segons una taxonomia de canvis definida pel director i grup d'investigació.
5. Carrega els resultats en un esquema de dades per analitzar-ne la freqüència.

---

## 2. Conceptes previs

### 2.1 Un "dataset" de Hugging Face és un repositori Git

[Hugging Face Hub](https://huggingface.co) és una plataforma on es
publiquen models i datasets d'ML. Cada dataset és un **repositori Git** complet, amb identificador `propietari/nom` i conté els fitxers de dades,
la documentació i metadades. Com qualsevol repositori Git, té:

- **Commits**: cada pujada de fitxers és un commit, amb data i autor.
- **Branques** (`branches`): com a mínim `main`; poques en tenen més.
- **Tags**: etiquetes que el mantenidor posa a un commit concret (p.e.
  `v1.0`). Són l'única manera explícita de marcar una "versió", i molt
  pocs datasets les fan servir.

Un mateix repositori pot contenir molts fitxers de dades (particions
`train`/`test`, un dataset gran partit en trossos, subconjunts per idioma...).
La secció següent explica com s'organitzen.

### 2.2 Subsets, splits i shards: com es reparteix un dataset en fitxers

Les dades d'un dataset del Hub s'organitzen en tres nivells:

- **Subset** (o *config*): una part del dataset amb les seves pròpies
  columnes, p.e. un subset per idioma (`ca`, `es`...). La majoria de
  datasets en tenen un de sol, que es diu `default`.
- **Split** (partició): la divisió per a l'aprenentatge automàtic, com
  `train`, `validation` o `test`. Totes les files d'un split tenen les
  mateixes columnes.
- **Shard** (tros): **un fitxer que només conté una part de les files d'un
  split**. Quan un split és massa gran per a un sol fitxer, es parteix en
  diversos fitxers amb les mateixes columnes, i cadascun guarda un bloc de
  files consecutives. Unint els shards en ordre es recupera el split sencer.

Exemple: un split `train` de 3 milions de files partit en 3 shards, i un
split `test` petit, en un sol fitxer.

```
data/train-00000-of-00003.parquet   files 1 a 1.000.000
data/train-00001-of-00003.parquet   files 1.000.001 a 2.000.000
data/train-00002-of-00003.parquet   files 2.000.001 a 3.000.000
data/test-00000-of-00001.parquet    tot el split test
```

`00001-of-00003` vol dir "shard número 1 (es compta des de 0) d'un total
de 3". És el format de la llibreria `datasets` i de la conversió automàtica
a parquet del Hub.

**Per al projecte, un repositori és un dataset**. Subsets,
splits i shards són maneres de repartir-lo en fitxers, com ho poden ser un
CSV per any o un fitxer per document. A la Fase 2, tots els fitxers de dades
del repositori, de qualsevol dels formats de la llista, s'uneixen en ordre i
es comparen com un sol dataset: si la versió nova reparteix les mateixes
files en més o menys fitxers, no surt cap canvi. Per a cada versió:

- **Documents JSON.** Un `.json` només és dades si és una llista de
  registres (`[{...}, {...}]`). Qualsevol altre (p.e. `croissant.json` o
  `dataset_metadata.json`) és un document: no es llegeix i compta com a
  fitxer ignorat (secció 9.2).
- **Columnes diferents.** Si els fitxers no tenen tots el mateix conjunt de
  columnes (taules diferents, o camps opcionals), la versió no es compara:
  la comparació queda amb l'estat `mixed_columns`.
- **Files repetides entre fitxers.** Si un fitxer repeteix files d'un altre
  més gran (p.e. un `overall` amb les files de tots els fitxers per
  categoria), s'ignora el més petit. Els fitxers es recorren de més files a
  menys i es conserva cada fitxer que no comparteix cap fila amb els ja
  conservats. Les repeticions dins d'un mateix fitxer són dades.
- **Formats diferents.** Cada format es prepara pel seu compte (el CSV
  decideix el tipus pels valors; parquet i JSON ja el porten) i després
  s'uneixen. Una columna numèrica en un format és numèrica a la taula unida
  si tots els seus valors, de tots els formats, són números; si no, text.

### 2.3 Git LFS i el "clon bare" sense contingut

Els fitxers grans es guarden amb **Git LFS** (Large File Storage): el
repositori Git només conté un **punter** de text de ~130 bytes per
fitxer, i el contingut real viu en un magatzem a part.

Això ens permet una tècnica clau del projecte:

```
git clone --bare --filter=blob:none --depth=51 https://huggingface.co/datasets/<id>
```

- `--bare`: no crea còpia de treball (no hi ha fitxers desplegats).
- `--filter=blob:none`: no baixa el contingut de cap fitxer, només els
  commits i els arbres (la llista de fitxers de cada commit).
- `--depth=51`: només els últims 50 commits, que són els que es revisen,
  més el pare del més vell, que cal per saber què va canviar.

Requereix `git` instal·lat al sistema.

### 2.4 L'API de Hugging Face (`huggingface_hub`)

Llibreria Python oficial. Les crides que fem servir:

| Crida | Per a què | On |
|---|---|---|
| `HfApi.list_datasets` | Recórrer tota la població de datasets | Fase 0 |
| `list_repo_refs` | Tags i branques d'un repositori | Fases 0, 1, 2 |
| `list_repo_commits` | Historial de commits (branca per defecte) | Fase 0, i Fase 1 per a les dates dels tags |
| `list_repo_tree` | Fitxers d'una revisió, amb la mida real (LFS resolt) | Fases 1 i 2 |
| `hf_hub_download` | Descarregar un fitxer concret a una revisió concreta | Fase 2, validació |

Totes necessiten un **token** de HF (rol "Read" és suficient), que es
llegeix de la variable d'entorn `HF_TOKEN` (fitxer `.env`).

Detall que sorprèn: `list_repo_tree` retorna un **generador**; la
petició HTTP es fa en iterar-lo, no en cridar-lo. Per això el codi el
consumeix sencer (`list(...)`) dins de la funció de reintent (vegeu 2.5).

### 2.5 Límits de l'API: errors 429 i 403

- **429 Too Many Requests**: HF limita les peticions per segon. Sense
  reintents, una execució de 1000 datasets va perdre el 59% de la mostra.
  Solució: reintentar amb espera exponencial (10s, 20s, 40s...) més un
  soroll aleatori ("jitter") perquè els threads no reintentin tots alhora.
- **403 Forbidden**: el dataset és *gated* (cal acceptar condicions a la
  web) o privat. És permanent: no es reintenta. Aquests datasets
  s'exclouen dels càlculs de proporcions però es compten a part.

Tota la lògica és a `src/errors.py`; la justificació completa, a
`docs/decisions_tfg.txt` (T-02).

### 2.6 La taxonomia de canvis

El director amb un equip d'investigació (Abelló et al.)
va definir una taxonomia de **15 tipus de canvi** elementals
que pot patir un dataset tabular, agrupats en cinc perspectives.
Cada tipus té un codi:

| Codi | Canvi | Perspectiva |
|---|---|---|
| C100 | Metadades (font, llicència, format...) | Metadades del dataset |
| C210 | Ordre de columnes | Conjunt de columnes |
| C221 | Afegir columna | Conjunt de columnes |
| C222 | Eliminar columna | Conjunt de columnes |
| C223 | Renombrar columna | Conjunt de columnes |
| C311 | Tipus d'una columna categòrica | Característiques d'una columna |
| C312 | Valors d'una columna categòrica | Característiques d'una columna |
| C321 | Tipus d'una columna numèrica | Característiques d'una columna |
| C322 | Valors d'una columna numèrica | Característiques d'una columna |
| C323 | Format d'una columna numèrica (coma decimal, notació científica) | Característiques d'una columna |
| C410 | Ordre de files | Conjunt de files |
| C421 | Afegir fila | Conjunt de files |
| C422 | Eliminar fila | Conjunt de files |
| C510 | Afegir valors absents (*Add missing*) | Valors de les dades |
| C520 | Eliminar valors absents (*Remove missing*) | Valors de les dades |
| C530 | Actualitzar valors sense absents (*Update value not involving missing*) | Valors de les dades |


Decisions d'abast: **C100 no es classifica** (el director va indicar que
no interessa), així que el projecte treballa amb els altres 15 codis. I
la taxonomia només té sentit sobre **fitxers tabulars** (files i
columnes): àudio, vídeo, imatges o tensors queden fora de la
classificació. La taxonomia classifica el *dataset*, no l'ús que se'n
fa: no sap quina columna és el "target" d'un model.


### 2.7 Census Income: el cas de referència

Per saber si el nostre detector encerta, ens cal un cas on algú ja hagi
etiquetat els canvis a mà. El paper del director ho fa amb el dataset
**Census Income**: compara l'original (**D0**) amb 9 còpies publicades per 
altres persones(**D1-D9**) i marca a mà quins codis presenta cadascuna (Taula 1 del
paper). D1-D7 són a Hugging Face; D8 i D9 no, i queden fora d'abast.
Aquesta taula és el nostre **ground truth** (veritat de referència).
Atenció: D1-D7 són repositoris independents comparats contra D0, no
versions successives d'un mateix repositori.

---

## 3. Vocabulari propi del projecte

Termes que defineix aquest codi:

| Terme | Què vol dir | On es defineix |
|---|---|---|
| **Fitxer substantiu** | Fitxer amb dades reals, no metadades ni documentació. Es decideix per la ruta i l'extensió (secció 7.3). | funció `is_substantive_path` |
| **Fitxer de dades tabular** | Fitxer substantiu i tabular (d'un dels formats de `config/formats.toml`). És el que fa elegible un dataset i el que compara el motor. | funció `is_tabular_data_path` |
| **Commit tabular** | Commit que modifica almenys un fitxer de dades tabular. Cal el clon per saber-ho: sense clon, no compta. | funció `is_tabular_commit` |
| **Candidat** | Dataset de la mostra amb ≥2 tags o ≥2 branques: l'únic al qual es mira la llista de fitxers i, si té dades tabulars, els commits (secció 7.2). | funció `classify_dataset` |
| **Sessió de treball** | Grup de commits tabulars propers en el temps: ordenats per data, en comença una de nova quan dos consecutius estan separats per **més de 6 hores**. Evita comptar com a versions diferents els 5 commits que una eina de pujada fa en 10 minuts. Hi ha una sola implementació, compartida per totes les fases. | agrupat en la funció `cluster_commit_times` |
| **Dataset elegible** | Dataset amb ≥2 versions reals, i per tant estudiable. Criteri A o B (secció 7.2). | definit a la funció `classify_dataset` |
| **Criteri A** | ≥2 tags i ≥2 commits tabulars. | funció `eligibility_criterion` |
| **Criteri B** | ≥2 branques i commits tabulars repartits en ≥2 sessions. | funció `eligibility_criterion` (sessions: `has_time_dispersed_substantive_commits`) |
| **Versió** | Criteri A: cada tag. Criteri B: cada sessió (representada pel seu commit més recent). | extracció a `version_extractor.extract_versions_for_dataset` |
| **Unitat de canvi** | Què es compara a la Fase 2: cada versió contra la següent. Criteri A: cada tag contra el tag següent. Criteri B: el final de cada sessió contra el final de la sessió següent. | funció `version_pairs` |
| **Fitxer tabular** | D'un dels formats de l'execució (els de `config/formats.toml`, per defecte `.csv`, `.tsv`, `.parquet`, `.jsonl` i `.json`, o els de `--formats`) i fora de les carpetes de metadades (`meta/`...). L'únic tipus que es descarrega i es compara. Si una versió en té de més d'un format, tots formen el dataset (decisions T-36, T-42 i T-44). | es defineix a la funció `diffengine.datafiles.is_tabular_path` |
| **Shard** | Fitxer amb només una part de les files d'un split. |  |
| **Dataset** | Un repositori del Hub. A la Fase 2, tots els seus fitxers tabulars s'uneixen en ordre i es comparen com un de sol, si tenen les mateixes columnes (secció 2.2, decisions T-37 i T-44). | funció `diffengine.datafiles.dataset_files` |


### Identificadors que es troben al codi i als documents

- **Fase 0 / 1 / 2 / 3**: les etapes del pipeline (secció 6).
  Els missatges de log "FASE 1/2/3" dins de `run_sampling` són passos
  interns de la Fase 0 (mostreig, classificació, escriptura).
- **US-xxx**: històries d'usuari de la planificació a Taiga. P.e. US-302 =
  detecció real de fitxers modificats.
- **M-xx, T-xx, A-xx**: decisions metodològiques, tècniques i d'abast,
  a `docs/decisions_tfg.txt`.

---

## 4. Posar-ho en marxa

Passos complets (token, `.env`, Docker) al `README.md`. Resum:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "HF_TOKEN=hf_..." > .env          # token de HF amb rol "Read"

python src/run_pipeline.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova ràpida
python src/run_pipeline.py --sample-size 2000 --threads 4 --seed 42                    # execució real
python src/build_warehouse.py --run-dir data/run_9                                      # només el magatzem (Fase 3)
```

- Cal `git` al sistema (la imatge Docker ja l'inclou).
- La Fase 3 fa servir el `dbt` del mateix entorn (`requirements.txt`) i
  s'executa des de l'arrel del repositori (secció 10).
- Sense arguments, els scripts mostren l'ajuda i surten, perquè una
  crida accidental no engegui una execució de diverses hores.
- Una execució real de 2000 datasets recorre tota la població de HF:
  compta amb hores, no minuts.

---

## 5. Estructura del repositori

```
src/                Codi del pipeline: un script per fase i el motor de detecció de canvis
config/             formats.toml: els formats tabulars (T-36, T-44)
  diffengine/       El motor, com a paquet de Python (s'explica a docs/validacio_census_income.md, secció 1)
warehouse/          Magatzem de la Fase 3: projecte dbt sobre DuckDB (secció 10)
ui/                 Interfície de consulta (Streamlit): un visualitzador de l'execució, de només lectura sobre el magatzem
tests/              Tests automàtics (pytest), sense xarxa; fixtures/run_sample/ és una execució sintètica
data/               Resultats de les execucions (secció 11)
docs/               Documentació (ordre de lectura: docs/README.md)
```

### 5.1 Fitxers del pipeline (`src/`)

| Fitxer | Què fa |
|---|---|---|
| `run_pipeline.py` | **Orquestrador.** Crea una carpeta nova per a l'execució i encadena les Fases 0, 1, 2 i 3. |
| `eligibility_scan.py` | Fase 0 (mostra aleatòria i elegibilitat) i Fase 2 (classificació de canvis dels elegibles). Conté també el clon de git i el criteri de quins fitxers compten. |
| `version_extractor.py` | Fase 1: la llista ordenada de versions de cada elegible, amb data, autors i mida. |
| `errors.py` | Reintents davant els límits de l'API, classificació dels errors i registre de fallades a `failures.csv`. És una llibreria que es fa servir totes les fases. |
| `timing.py` | La durada de cada fase (`PhaseClock`, `format_duration`). |
| `validate_census_income.py` | Valida el motor amb la Taula 1 del paper (Census Income). |
| `build_warehouse.py` | Fase 3: `dbt build` sobre una carpeta d'execució; el magatzem va a `data/warehouse/run_<id>.duckdb`. |
| `figures/` | Figures de la memòria: un mòdul per figura, que llegeix un mart; `make_all.py` les fa totes a `docs/figures/`|
| carpeta /diffengine |Compara dues versions d'un dataset en 5 passos. `engine.py` n'és l'índex. |


### 5.2 Tests (`tests/`)

Un fitxer per mòdul. L'API de Hugging Face sempre se simula: cap test necessita
xarxa ni token. `conftest.py` afegeix `src/` al camí d'importació.

| Fitxer | Comprova |
|---|---|
| `test_eligibility_scan.py` | Mostreig, criteri de fitxers, elegibilitat, embut i Fase 2 |
| `test_version_extractor.py` | Versions per tags i per sessions |
| `test_run_pipeline.py` | L'orquestrador i la carpeta de cada execució |
| `test_errors.py` | Reintents i classificació d'errors |
| `test_validate_census_income.py`, `test_census_income_labels.py` | Puntuació contra el paper i transcripció de la Taula 1 (`fixtures/`) |
| `test_diffengine_regressions.py` | El motor amb casos reals i coneguts, un test per cas |
| `test_diffengine_datafiles.py`, `test_diffengine_pairs.py`, `test_diffengine_load.py` | Passos 1 i 2 del motor |

### 5.4 Infraestructura

| Fitxer | Per a què |
|---|---|
| `requirements.txt` | Dependències amb versió fixada |
| `ruff.toml` | Regles de lint |
| `config/formats.toml` | Els formats tabulars (decisions T-36 i T-44). `docker-compose.yml` el munta a sobre del de la imatge, de manera que es pot canviar sense reconstruir-la. Per a una execució, `--formats` el substitueix (decisió T-42) |
| `Dockerfile`, `docker-compose.yml` | Imatge per executar el pipeline sense instal·lar res; `docker-compose` hi defineix un servei per script (`run-pipeline`, `eligibility-scan`, `version-extractor`, `warehouse`) |
| `.github/workflows/ci.yml` | A cada push: lint, tests i construcció de la imatge |
| `.github/workflows/docker-publish.yml` | Publica la imatge |

**Detalls a tenir en compte:**

- **La Fase 2 viu a `eligibility_scan.py`, no a `diffengine/`.** El motor
  sap comparar dues revisions; *quines* es comparen ho diuen les versions
  de la Fase 1
- **`eligibility_scan.py` surt amb error si no troba `HF_TOKEN`.** Per això 
  la CI defineix un token fictici per als tests.

---

## 6. Visió general del pipeline

```
 Població HF (~1M datasets)
        │
        ▼
 FASE 0  Mostreig i elegibilitat          eligibility_scan.run_sampling
        │  mostra aleatòria de N (2000 p.e.) → quins tenen ≥2 versions amb canvis a dades tabulars
        │  sortida: eligibility_report.csv, funnel_summary.json
        ▼
 FASE 1  Extracció de versions            version_extractor.run_extraction
        │  per a cada elegible: llista ordenada de versions amb data,
        │  autors i mida.  sortida: versions.csv
        ▼
 FASE 2  Classificació de canvis          eligibility_scan.run_classification
        │  per a cada elegible: compara cada versió de versions.csv amb
        │  la següent, el dataset sencer → codis de la taxonomia
        │  sortida: change_classification.csv, comparison_status.csv
        ▼
 FASE 3  Magatzem de dades                build_warehouse.build_warehouse
           dbt build sobre la carpeta: staging → esquema en estrella → marts
           sortida: data/warehouse/run_<id>.duckdb (fora de la carpeta)
```

Les Fases 1 i 2 només treballen amb els elegibles (aproximadament una desena de 2.000), no
amb tota la mostra. És el que fa viable descarregar contingut.

Opcions útils: `--input-csv <report>` salta la Fase 0 i fa servir un report
existent; `--skip-version-extraction` omet la Fase 1 i, per tant, la 2 (que
compara les versions de la Fase 1); `--skip-classification` omet la Fase 2;
`--skip-warehouse` omet la Fase 3; `--max-scanned` limita el recorregut (només
per a proves, perquè esbiaixa la mostra). La Fase 3 només es fa si la carpeta
té tots els fitxers de les Fases 0-2: amb `--input-csv` o amb alguna fase
saltada, no hi és. Si falla dbt, les Fases 0-2 ja són a la carpeta i
l'execució acaba igualment.

**Temps.** Cada fase es cronometra (`timing.PhaseClock`): en acabar-ne una,
el log diu quant ha durat i l'acumulat, i el resum final té una taula amb
totes les fases (les saltades hi surten com a «saltada»). Les durades, en
segons, queden també a `funnel_summary.json`: `duration_sampling_s` i
`duration_eligibility_s` (Fase 0, també quan `eligibility_scan.py`
s'executa sol), `duration_versions_s` (Fase 1b), `duration_classification_s`
(Fase 2) i `duration_total_s` (Fases 0 a 2). La Fase 3 només surt al log,
perquè llegeix aquest fitxer.

---

## 7. Fase 0 — Mostreig i elegibilitat

Codi: `eligibility_scan.py` (`run_sampling`). Objectiu: estimar quina
proporció de datasets de HF té més d'una versió real **de dades tabulars**,
i obtenir-ne la llista dins de la mostra.

### 7.1 Mostreig per reservori

No es poden processar ~1M datasets (límits de l'API, secció 2.5), i
agafar els més populars esbiaixaria el resultat. Per això es pren una
**mostra aleatòria uniforme** amb l'algorisme de reservori (algorisme R
de Vitter, `reservoir_sample_dataset_ids`):

1. Els primers N elements entren directament al reservori.
2. Per a l'element n-èsim (n > N), es tria un enter aleatori `j` entre
   0 i n-1; si `j < N`, l'element substitueix la posició `j`.

Cada dataset acaba amb la mateixa probabilitat N/total de ser escollit, i
la memòria és O(N): mai es carrega la població. Cal recórrer-la sencera
(un sol pas, paginat per l'API). `--max-scanned` talla el recorregut i
**esbiaixa** la mostra (l'API no retorna els datasets en ordre aleatori):
només per a proves. `--seed` fa el mostreig reproduïble.

**Per què N = 2000** (decisió A-01): amb la proporció observada
(p ≈ 1.37% en una primera execució de 1000), la mida necessària per a un
marge d'error E al 95% és n = 1.96²·p·(1-p)/E²:

| Marge d'error | n necessària |
|---|---|
| ±1.0 punts | ~520 |
| ±0.5 punts | ~2.070 |
| ±0.3 punts | ~5.730 |

Amb 2000, el marge és ±0.51 punts.

### 7.2 Decidir l'elegibilitat (`classify_dataset`)

Cada dataset de la mostra passa per tres filtres, del més barat al més
car. Si no en passa un, no és elegible, el motiu queda al report
(`eligibility_reason`) i no es fa cap pas més.

1. **Té marques de versió?** `list_repo_refs` (una crida a l'API) dona el
   nombre de tags i de branques. Cal tenir-ne ≥2 de les unes o de les
   altres. És el filtre que més en descarta: a `run_8`, només 29 dels
   2.000 el van passar.
2. **La versió actual té dades tabulars?** `read_current_version` (una
   crida a l'API, uns 0,2 s, sense clonar) dona la llista de fitxers.
   `tabular_file_share` compta els fitxers de dades (sense metadades ni
   documentació, secció 7.3) i quina proporció són tabulars. Si no hi ha
   cap fitxer de dades tabular, el dataset no és elegible i no es llisten
   els commits ni es clona. Aquestes dues xifres queden al report
   (`num_data_files`, `tabular_file_share`); només es tenen per als
   candidats. Les metadades del dataset (`created_at`, `license` i
   `downloads` dels últims 30 dies) surten del mateix llistat del mostreig
   (`listing_metadata`, la llicència de les etiquetes `license:*`), sense cap
   crida més: es tenen per a tota la mostra, també per als restringits.
3. **Els commits toquen dades tabulars prou vegades?**
   `list_repo_commits` dona els commits, del més nou al més vell, i se'n
   revisen els 50 més recents. `bare_clone` fa el clon sense contingut
   (secció 2.3) i, per a cada commit, `get_changed_files` mira en local
   quins fitxers toca (`git show`). Un commit compta si toca algun fitxer
   de dades tabular (`is_tabular_commit`, secció 7.3). Elegible si es
   compleix:
   - **Criteri A**: ≥2 tags i ≥2 commits tabulars; o
   - **Criteri B**: ≥2 branques i els commits tabulars formen ≥2 sessions
     (separades per més de 6 hores).

   Els commits tabulars dels elegibles no s'escriuen: `run_sampling` els
   retorna en memòria i `run_pipeline.py` els passa a la Fase 1.


### 7.3 Quins fitxers compten (`is_tabular_data_path`)

Un commit compta si toca un **fitxer de dades tabular**. Això són dues
condicions:

- **És dades, no metadades** (`is_substantive_path`, a sota).
- **És tabular** (`diffengine.datafiles.is_tabular_path`): d'un dels formats de
  `config/formats.toml` (per defecte, `.csv`, `.tsv`, `.parquet`, `.jsonl` i
  `.json`), excepte els JSON de metadades del Hub i de LeRobot. És la mateixa
  definició que fa servir el motor de la Fase 2, de manera que tot dataset
  elegible té alguna cosa que el motor pot comparar. Per deixar un format
  fora de l'estudi, es treu de la llista (decisió T-36). Per a una sola
  execució, `--formats` (p.e. `--formats json,csv`) substitueix la llista, i
  llavors el fitxer no es llegeix: els mateixos formats valen per a totes les
  fases (`use_formats`, decisió T-42).

`is_substantive_path` decideix si un fitxer és dades, en aquest ordre:

1. Ruta que comença per `meta/`, `meta_data/` o `.github/` → **no**,
   sigui quina sigui l'extensió (un `.parquet` dins `meta/` és metadada).
2. Nom a `NON_SUBSTANTIVE_FILES` (`README.md`, `LICENSE`,
   `.gitattributes`...) o extensió de configuració/documentació (`.md`,
   `.yml`, `.toml`...) → **no**.
3. Extensió de dades coneguda (`.parquet`, `.csv`, `.arrow`, `.npy`,
   `.safetensors`, `.mp4`, `.wav`, `.png`, `.zip`...) → **sí**.
4. Qualsevol altra cosa → **sí** per defecte, i queda registrat al log
   per poder ampliar les llistes.

Es va provar de distingir per mida del fitxer i es va descartar: en
repositoris reals hi ha metadades més grans que les dades. El prefix de
la ruta va ser l'únic senyal consistent (decisió M-04).

**Sense clon no es pot saber quins fitxers toca un commit**, i llavors no
compta. Abans es mirava el títol del commit ("readme", "typo"...), però un
títol no diu si el fitxer tocat és tabular.


### 7.4 Sortida i mètriques

`write_results` escriu el report per dataset i un resum de l'embut:

- `eligible`: nombre d'elegibles. Amb `ineligible`, `access_restricted`
  (403) i `errors` suma la mida de la mostra.
- `eligible_Criteri_A`, `eligible_Criteri_B`: desglossament per criteri
  (sumen `eligible`).
- `eligible_proportion` = elegibles / (elegibles + no elegibles). Els
  inaccessibles (403) i els errors **no** compten al denominador: no
  sabem si ho serien.
- `eligible_proportion_of_attempts` = elegibles / tots els intents
  (elegibles, no elegibles, inaccessibles i errors).
- `estimated_eligible_in_scanned_population` = `eligible_proportion_of_attempts`
  × `population_scanned`: quants elegibles hi hauria a tota la població
  recorreguda
- `attempts_per_eligible` = tots els intents / elegibles: quants datasets
  cal provar per obtenir-ne un d'elegible. **Serveix per fixar la mostra**:
  per tenir N datasets elegibles, i per tant amb dades tabulars per
  comparar, cal una mostra d'unes N × `attempts_per_eligible`.

Un possible exemple d'execució és el següent:

```
eligible                                     8
eligible_proportion                     0.0042   (8/1890)       elegibles / classificats sense error
eligible_proportion_of_attempts         0.0040   (8/2000)       elegibles / tots els intents
estimated_eligible_in_scanned_population  4344   (0.0040 × 1.085.939)
attempts_per_eligible                    250.0   (2000/8)       per a 50 elegibles, ~12.500 intents
```

Amb tan pocs elegibles, l'estimació té un marge ampli: l'interval de
confiança del 95% de la proporció (Wilson) va del 0,20% al 0,79%, és a dir,
entre 127 i 493 intents per elegible. Amb el criteri anterior, que no
exigia dades tabulars, `run_6` en tenia 11 (181,8 intents per elegible),
però només 3 tenien algun canvi detectat; a `run_8` en tenen 6 dels 8.

---

## 8. Fase 1 — Extracció de versions

Codi: `version_extractor.py` (`run_extraction`). Per a cada dataset
elegible, la llista ordenada de versions amb data, autors i mida.

El concepte de versió depèn del criteri d'elegibilitat (decisió T-06):

- **Criteri A**: cada tag és una versió. El commit ve del tag; la data i
  els autors, d'una crida `list_repo_commits` per tag.
- **Criteri B** (la majoria: ~70% dels elegibles no tenen cap tag):
  cada sessió és una versió, representada pel seu commit més recent
  (`build_sessions_from_commits`, mateixa funció de sessions que la
  Fase 0). Les sessions es fan amb els commits tabulars que va trobar la
  Fase 0, que `run_pipeline.py` passa en memòria: no es tornen a llistar ni
  es clona res. Si la Fase 1 s'executa sola (`version_extractor.py
  --input`), es tornen a buscar per a cada elegible (`tabular_commits_of`).

Aquestes versions són les que compara la Fase 2 (secció 9.1).

Cada fila porta `version_source` (`tag` o `commit_session`) perquè la
confiança no és la mateixa: un tag és una marca deliberada del
mantenidor; una sessió és una inferència.

Altres detalls:
- `approx_size_bytes`: suma de la mida de tots els fitxers de la
  revisió (`list_repo_tree`, una crida per versió; `--skip-size` l'omet).
  La mateixa crida la reparteix (`split_tree`): `data_size_bytes` i
  `n_data_files` són els fitxers del dataset (els que compara la Fase 2), i
  `metadata_size_bytes` i `n_metadata_files`, la resta (README, metadades,
  imatges...).
- `authors`: l'API no distingeix autor de *committer*; és l'únic camp
  disponible.
- Errors parcials (la data d'un tag, la mida d'una versió) no fan perdre
  el dataset: queden al camp `status` (`commit_error`, `size_error`).

---

## 9. Fase 2 — Classificació de canvis

Codi: `eligibility_scan.run_classification` (llegeix `versions.csv`, en
forma les parelles i les compara) i el motor
`src/diffengine/` (**`docs/validacio_census_income.md`**, secció 1). És l'única fase que **descarrega contingut real**,
i per això només s'aplica als elegibles (la classificació de tota la
mostra baixaria centenars de GB).

### 9.1 Què es compara

1. `run_classification` llegeix `versions.csv` (Fase 1) i, per a cada
   dataset, `version_pairs` forma les **unitats de canvi**: cada versió
   contra la següent, per `version_order` (decisió T-23):
   - Criteri A: cada tag contra el tag següent.
   - Criteri B: el commit més recent de cada sessió contra el de la
     sessió següent. Els commits dins d'una mateixa sessió no es
     comparen entre ells.

   Les versions sense commit no es comparen, ni dues versions seguides
   amb el mateix commit (dos tags al mateix commit).
2. `compare_change_units` crida el motor amb les dues revisions de cada
   unitat (`pairs.compare_revisions`). El motor:
   - de cada revisió en treu els **fitxers del dataset**
     (`datafiles.dataset_files`): els fitxers tabulars, amb la mateixa
     regla que l'elegibilitat de la Fase 0 (secció 7.3), de tots els
     formats de la llista (`config/formats.toml` o `--formats`);
   - si els fitxers són els mateixos i tenen el mateix contingut, no es
     descarrega res;
   - si no, es descarreguen tots i es llegeixen com un sol dataset per
     revisió (secció 9.2, "Com es llegeix el dataset"), i es comparen.
3. Cada comparació acaba amb un **estat** (`ok`, `identical_content`,
   `absent_old`/`absent_new` si una de les versions no té cap fitxer de
   dades, `no_data` si no en té cap de les dues, `download_failed`,
   `parse_failed`, `too_large` o `mixed_columns` si els fitxers d'alguna
   versió no tenen totes les mateixes columnes). Una fallada de descàrrega no es
   converteix mai en codis. L'estat, amb quants codis té, queda a
   `comparison_status.csv`, també el de les comparacions sense cap codi:
   així es distingeix "sense canvis" de "no s'ha pogut comparar".
4. Les files de cada dataset s'afegeixen a `change_classification.csv` i a
   `comparison_status.csv` en acabar-lo, i el log diu per quina parella va
   (`parella i/n`): si l'execució s'atura a mitges, es conserva el que ja
   s'havia classificat (decisió T-24).

### 9.2 El motor (`diffengine/`)

Compara dues versions d'un dataset en 5 passos. `engine.py` n'és l'índex.

| Pas | Què fa | Mòduls |
|---|---|---|
| 1 | Trobar els fitxers del dataset a cada revisió i decidir si cal comparar-los | `datafiles.py`, `pairs.py` |
| 2 | Llegir el dataset (tots els seus fitxers) i saber el tipus de cada columna | `load.py` |
| 3 | Aparellar columnes i files (3a columnes pel nom, 3b files, 3c columnes pel contingut) | `columns.py`, `rows.py`, `transforms.py` |
| 4 | Detectar els canvis, amb un fitxer per perspectiva de la taxonomia: `columns_set.py` (C2xx), `column_kind.py` (C3xx), `rows_set.py` (C4xx), `data.py` (C5xx); `common.py` és el que comparteixen | `detectors/` |
| 5 | Escriure el resultat | `output.py` |

`config.py` té tots els llindars, agrupats pels mateixos passos.

#### Com es llegeix el dataset (pas 2, `load.load_files`)

Un repositori pot tenir diversos fitxers de dades, de formats diferents, i
també fitxers que tenen un format de dades però no ho són. `load_files` en fa
una sola taula per revisió seguint aquest arbre (decisions T-44 i T-45),
cada revisió pel seu compte:

```
fitxers del dataset (pas 1)
  │
  ├─ 1. llegir cada fitxer en un DataFrame
  │      ├─ .csv/.tsv/.parquet/.jsonl que no es pot llegir → parse_failed (tota la versió)
  │      └─ .json que no és una llista de registres       → document: s'ignora
  │                                                         (si és l'únic fitxer → parse_failed)
  ├─ 2. un sol fitxer llegit → és el dataset
  ├─ 3. columnes diferents entre fitxers (el conjunt de noms) → mixed_columns, no es compara
  ├─ 4. mateixes columnes: s'ignora cada fitxer que repeteix files d'un altre més gran
  └─ 5. s'uneixen en ordre; si hi ha formats diferents, cada format es prepara
        pel seu compte i després s'uneixen (el format ja no importa)
```

**Quan un `.json` és dades (pas 1).** El JSON serveix tant per a dades com
per a metadades, i l'extensió no ho diu. Es decideix per l'estructura del
fitxer, sense mirar-ne el nom (`_read_json_records`):

| Contingut del `.json` | Exemple | Què és |
|---|---|---|
| Una llista d'objectes | `[{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]` | **Dades**: cada objecte és una fila |
| Un objecte, tingui el que tingui a dins | `{"version": "v1", "splits": {"train": 6740, "test": 843}}` | Document |
| Una llista de valors, o buida | `["train", "test"]`, `[]` | Document |
| No és JSON vàlid | | Document |

- Un document no es llegeix: es compta a `n_files_dropped_*` de
  `comparison_status.csv`, i la resta de fitxers es comparen sense ell. Si
  és l'únic fitxer de la versió, la comparació queda `parse_failed`.
- Els `.jsonl` (una línia per registre) són sempre dades.
- No n'hi ha prou que pandas el pugui llegir: `pd.read_json` converteix en
  taula un objecte amb objectes o llistes a dins. Per exemple,
  `dataset_metadata.json` de `sambodhan/misclassified_urgency_dataset`
  (run_12) té valors i un objecte `splits`, i pandas en feia 3 files (una per
  split) i 9 columnes. Com que no tenien les columnes dels parquet, les 5
  comparacions del dataset quedaven `mixed_columns`. Passava el mateix amb
  `publicdata.json` de `qld-coastal-waves-townsville` (run_11).
- Una llista de registres que no té les columnes de la resta de fitxers (p.e.
  una llista d'etiquetes al costat dels parquet) sí que és dades, i la versió
  queda `mixed_columns` (pas 3): no es pot saber pel contingut si és una taula
  auxiliar o una part del dataset.
- **Limitació:** una taula en un `.json` amb una altra forma (per columnes,
  `{"id": [1, 2], "text": ["a", "b"]}`, o dins d'una clau,
  `{"data": [...]}`) es tracta com a document. Es veu a `n_files_dropped_*`.
- **Diferència amb la Fase 1:** el repartiment de la mida entre dades i
  metadades de `versions.csv` (`split_tree`) es fa amb el llistat de fitxers,
  sense contingut. Un document JSON que no és a la llista de metadades
  (secció 7.3) hi compta com a dades.

**Columnes diferents (pas 3).** Si els fitxers llegits no tenen tots el
mateix conjunt de columnes (taules diferents al mateix repositori, o la
mateixa taula amb camps opcionals), la versió no es compara: l'estat és
`mixed_columns`.

**Files repetides entre fitxers (pas 4).** Es fa un hash de cada fila amb
els valors normalitzats, que és el mateix en qualsevol format. Els fitxers es
recorren de més files a menys i es conserva cada fitxer que no comparteix
cap fila amb els ja conservats (`files_to_keep`): així un fitxer que agrega
els altres (p.e. `overall`) no duplica les files. Les repeticions dins d'un
mateix fitxer són dades.

**Formats diferents (pas 5).** El CSV decideix el tipus de cada columna pels
valors; parquet i JSON ja el porten. Una columna numèrica en un format és
numèrica a la taula unida si tots els seus valors, de tots els formats, són
números (p.e. `"3"` en un JSON); si no, passa a text.

---

## 10. Fase 3 — Magatzem de dades

Un fitxer DuckDB construït amb dbt a partir d'una carpeta `data/run_<id>/`.
La interfície i les figures només llegeixen la capa gold.

```
bronze  data/run_<id>/*.csv, funnel_summary.json        el que escriu el pipeline (no es toca mai)
  │     warehouse/models/staging/_sources.yml           es llegeix com a text
  ▼
silver  warehouse/models/staging/stg_*.sql              vistes: tipus, noms en snake_case, cap filtre
  ▼     warehouse/models/intermediate/                  mesures per versió i per dataset, intervals k-means
gold    warehouse/models/marts/core/                    les dues estrelles: versions i datasets (taules)
        warehouse/models/marts/analysis/                marts de consulta (taules)
```

### 10.1 Com es regenera

Des de l'arrel del repositori (les vistes de staging llegeixen els CSV amb
rutes relatives a l'arrel; les taules gold porten les dades a dins):

```bash
python src/build_warehouse.py --run-dir data/<run_id>           # data/warehouse/<run_id>.duckdb
dbt build --project-dir warehouse --profiles-dir warehouse      # fixture sintètica (la de la CI)
```

- `build_warehouse.py` fa `dbt build --full-refresh` (models i tests) amb la
  carpeta com a variable `run_dir`, i desa el `.duckdb` fora de la carpeta,
  que és immutable. El crida `run_pipeline.py` després de la Fase 2.
- Variables dbt: `run_dir` (per defecte, `tests/fixtures/run_sample/`) i
  `census_dir` (la validació de Census Income, `data/census_income/run_2/`).
  Variable d'entorn `WAREHOUSE_PATH`: on es desa el `.duckdb` (fora de git).
- Les columnes que els runs antics no tenen (p.e. `n_files_dropped_*`, les
  durades, la mida de dades i de metadades o les files i columnes de cada
  versió) surten buides o a 0: el magatzem es construeix igual, però les
  mesures noves només les té una execució nova.

### 10.2 Capes

- **Silver (staging):** una vista per fitxer de bronze (`stg_eligibility_report`,
  `stg_funnel_summary`, `stg_versions`, `stg_change_classification`,
  `stg_comparison_status`, `stg_failures`, `stg_census_validation`). Hi
  posa el tipus de cada columna; les dates amb zona passen a UTC.
- **Intermediate:** `int_version_measures` (una fila per versió, amb les
  mesures i les diferències amb l'anterior), `int_dataset_measures` (una per
  dataset de la mostra) i `int_dataset_bands`, un model Python que
  discretitza les mesures dels datasets amb k-means (scikit-learn, 3
  clústers sobre `log1p` del valor, etiquetats per l'ordre del centre):
  `Few/Medium/Many` per a les descàrregues, sobre tota la mostra, i
  `Low/Medium/High` per a la resta, sobre els elegibles.
- **Gold, dues estrelles** (Star_Versions i Star_Dataset, validades pel
  director). Les claus subrogades són l'md5 de la clau natural (macro
  `surrogate_key`).

| Model | Gra | Mesures i claus |
|---|---|---|
| `fact_version` | una versió d'un dataset elegible | `lifespan_days` (fins a la següent), `conception_days` (des de l'anterior), `data_size_bytes`, `metadata_size_bytes`, `n_data_files`, `n_metadata_files`, `session_commit_count`, `n_rows`, `n_columns`; claus `dataset_key`, `differences_key`, `commit_time_key`, `version_kind_key`, `version_order_key` |
| `fact_dataset` | un dataset de la mostra | `num_tags`, `num_branches`, `num_tabular_commits`, `n_versions`, mida i fitxers inicials i finals, columnes i files inicials (les de les versions, només dels elegibles); claus `dataset_key`, `owner_key`, `creation_time_key`, `eligibility_key`, `license_key`, `downloads_band_key` |

| Dimensió | Què és |
|---|---|
| `dim_dataset` | Tota la mostra: autor, creació, elegibilitat (`Si`, `Restringit`, `NoElegible`), criteri, llicència, descàrregues i els intervals k-means (descàrregues, mida, files i columnes inicials, versions, commits tabulars). |
| `dim_differences` | *Junk dimension*: les diferències d'una versió amb l'anterior. Una fila per combinació de codis (`C221+C421`) més `first_version`, `no_changes` i `not_compared`, amb un indicador per nivell de la taxonomia: perspectiva (`has_c2`), grup (`has_c22`) i codi (`has_c221`). |
| `dim_time` | Hores amb alguna versió o creació: hora, dia, mes, trimestre i any. Rols: el commit i la creació. |
| `dim_version_kind`, `dim_version_order` | `tag`/`commit`; `First`/`Intermediate`/`Last`. |
| `dim_owner`, `dim_eligibility`, `dim_license`, `dim_downloads_band` | Les dimensions de l'estrella dels datasets. |
| `dim_kind_of_change` | Els 15 codis, amb el nom i els nivells (seed `warehouse/seeds/taxonomy.csv`). |

- **Gold, marts:** una taula per pregunta (`mart_funnel`, `mart_change_units`,
  `mart_code_frequency`, `mart_change_share`, `mart_changes_by_quarter`,
  `mart_criterion_comparison`, `mart_dataset_profile`,
  `mart_census_validation`), i `mart_version_codes` (una fila per versió i
  codi, la base de les consultes amb filtres de la interfície). Cada model té la pregunta i les columnes
  descrites al seu `_analysis.yml`. `mart_change_units` (una fila per
  comparació, amb l'estat) és la base de les proporcions: només compten les
  comparacions fetes (`is_compared`).

### 10.3 Tests i limitacions

- `dbt build` passa els tests genèrics (claus, relacions i valors admesos) i
  els de `warehouse/tests/`: conciliació amb el que va escriure el pipeline
  (`reconcile_*.sql`) i coherència dels marts (`assert_*.sql`).
- `tests/test_warehouse_seed.py` comprova que el seed diu el mateix que el
  motor; `tests/test_warehouse_bands.py`, els intervals k-means; i
  `tests/test_run_sample_fixture.py`, que la fixture és el que escriu el
  pipeline.

---

## 11. Fitxers que es generen

Cada execució de `run_pipeline.py` crea **`data/run_<id>/`** (número
incremental, mai sobreescriu) i hi desa tot:

| Fitxer | Fase | Contingut |
|---|---|---|
| `eligibility_report.csv` | 0 | Una fila per dataset de la mostra: `dataset_id, num_tags, num_branches, num_tabular_commits, eligible, eligibility_reason, status, error_category, error, num_data_files, tabular_file_share, created_at, license, downloads`. `eligibility_reason` diu el criteri que es compleix o el filtre on s'ha aturat. `status` = `classified`, `access_restricted` (403) o `error`. `num_data_files` i `tabular_file_share` només es tenen per als candidats; `created_at`, `license` i `downloads` (els dels últims 30 dies, el dia de l'execució), per a tota la mostra (secció 7.2). |
| `funnel_summary.json` | 0 | Resum de l'embut (secció 7.4): població recorreguda, quants passen cada filtre, elegibles per criteri, inaccessibles, errors, proporcions; i la durada de cada fase (`duration_*_s`, secció 6). |
| `versions.csv` | 1 | Una fila per versió: `dataset_id, version_label, version_order, version_source, commit_sha, commit_date, authors, approx_size_bytes, session_commit_count, status, data_size_bytes, metadata_size_bytes, n_data_files, n_metadata_files`. |
| `change_classification.csv` | 2 | Una fila per parell de versions i codi: `dataset_id, version_from, version_to, code, description`. `version_from`/`version_to` són SHA de commit (els `commit_sha` de `versions.csv`). |
| `comparison_status.csv` | 2 | Una fila per parell de versions, també sense cap codi: `dataset_id, version_from, version_to, status, n_codes, format_from, format_to, n_files_from, n_files_to, n_files_dropped_from, n_files_dropped_to, n_rows_from, n_rows_to, n_columns_from, n_columns_to, size_bytes`. `status` és l'estat de la comparació (secció 9.1); `n_codes`, quants codis diferents té, que són les seves files a `change_classification.csv`. `format_*` i `n_files_*`: els formats (p.e. `csv+parquet`) i quants fitxers té el dataset a cada versió; `n_files_dropped_*`, quants no s'han llegit perquè no són taules o repetien files d'un altre; `n_rows_*` i `n_columns_*`, la mida del dataset llegit a cada versió (buides si la comparació no l'ha llegit). `size_bytes`: la mida de les dues versions, sumades, que és la que es compara amb `--max-dataset-mb`. |
| `failures.csv` | totes | Només si hi ha fallades: `timestamp, source, dataset_id, error_category, error_message, retries_attempted`. `source` indica la fase. |

**Magatzem (Fase 3).** No va dins de la carpeta, que és immutable, sinó a
`data/warehouse/run_<id>.duckdb` (un fitxer DuckDB, fora de git). El
construeix `build_warehouse.py` amb dbt (secció 10).

L'únic número és el de la carpeta: a dins, els noms són fixos. Els scripts
executats sols (`eligibility_scan.py`, `version_extractor.py`) també creen
la seva carpeta. Amb `--input-csv` no hi ha Fase 0 i el CSV d'entrada no es
copia a la carpeta.

La validació de Census Income escriu a `data/census_income/run_<id>/`.

---

## 12. Gestió d'errors de l'API Hugging Face (`errors.py`)

- `with_retry(fn, ...)` embolcalla **totes** les crides a HF. Reintenta
  només els 429 i els errors de xarxa, fins a 5 intents, amb espera. Qualsevol altre error es propaga a la primera. Configurable amb `--retry-*`.
- `classify_error` tradueix l'excepció final a una categoria:
  `rate_limited`, `access_restricted`, `not_found`, `transient`,
  `unknown`.
- `append_failure_row` l'anota a `failures.csv` amb el missatge complet.
- Dos nivells de fallada:
  - **De dataset sencer** (no es poden llistar refs/commits): el dataset
    queda marcat i se'n continua amb el següent.
  - **Parcial** (una descàrrega, la mida d'una versió): es conserva la
    resta i es marca la fila afectada.
- Si el clon falla, no s'atura res, però sense clon no es pot saber quins
  fitxers toca cada commit i el dataset no pot ser elegible. Si `git` no
  està instal·lat, s'avisa un sol cop per execució.

---

## 13. Cost (Ordre - O(cost)) i complexitat

El cost no el posa el càlcul local, sinó **les crides a l'API i els
bytes descarregats**. Per això les decisions limiten *quantes* crides i
descàrregues es fan.

**Fase 0** (tota la població i la mostra):
- Recórrer la població: una passada paginada (~1M ids), temps O(total),
  memòria O(N).
- `classify_dataset` per dataset: 1 crida `list_repo_refs`; en la
  majoria s'acaba aquí. Per als candidats: 1 `dataset_info` (llista de fitxers).
  Si tenen dades tabulars: 1 `list_repo_commits` + 1 clon (51 commits, sense contingut,
  ~1 s) + fins a 50 `git show` locals, sense xarxa.

**Fase 1** (només elegibles):
- Criteri A: 1 `list_repo_refs` + per tag, 1 `list_repo_commits` i 1
  `list_repo_tree`.
- Criteri B: cap crida per trobar les sessions (fa servir els commits
  de la Fase 0, en memòria; executada sola, 1 `list_repo_commits` + 1 clon
  per elegible) + per sessió, 1 `list_repo_tree`.

**Fase 2** (només elegibles, l'única que baixa dades):
- Per unitat de canvi: 2 `list_repo_tree` i, si algun fitxer del dataset
  ha canviat, la descàrrega de tots els fitxers de les dues versions
  (queden a la caché local de HF, i els que no han canviat no es tornen a
  baixar). Baixar el contingut complet de totes les versions de 11
  elegibles es va estimar en 151 GB (un sol dataset en pesava 78): per
  això el salt per hash, la mida màxima del dataset (`max_dataset_bytes`,
  un paràmetre de l'execució: `--max-dataset-mb`, 500 MB per defecte) i
  el filtre d'elegibles.
- Comparar un dataset de `r` files i `c` columnes: majoritàriament O(r·c)
  per passada, vectoritzat. Aparellar files sense identificador no és
  quadràtic: cada fila es resumeix en un hash i les dues versions s'uneixen
  per aquest hash. Buscar si una fila afegida o eliminada és còpia d'una
  altra també fa servir un hash sense identificador, 1.000.000 de
  files es comparen en uns 70 s amb 1,9 GB.

Límits fixos: 50 commits per dataset (`MAX_COMMITS` a la Fase 0), 30 s per clonar,
10 s per `git show`. La mida màxima del dataset és un paràmetre de l'execució
(`--max-dataset-mb` a `run_pipeline.py` i a `eligibility_scan.py --classify-versions`;
500 MB per defecte, decisió T-35). El llindar de distribució (C530) també:
`--min-distribution-distance`, als mateixos dos scripts (0,1 per defecte, decisió T-40).
I els formats tabulars: `--formats`, a `run_pipeline.py`, `eligibility_scan.py` i
`version_extractor.py`, en lloc dels de `config/formats.toml` (decisió T-42).

---

## 14. Validació i resultats

### 14.1 Tests

210 tests (secció 5.4). Cap necessita xarxa ni token: l'API de Hugging Face
se simula amb `monkeypatch`.

### 14.2 Validació del motor amb Census Income

`validate_census_income.py` compara D1-D7 amb D0 (secció 2.7) amb el
mateix motor de la Fase 2 i contrasta el resultat amb la Taula 1 del
paper, codi per codi, sense C100 (decisió T-14). Per a cada versió i
codi: vertader positiu (TP) si el paper i el motor el marquen, fals
negatiu (FN) si només el paper, fals positiu (FP) si només el motor.

Cada versió es compara amb `adult.data` de la UCI (D0), a una revisió
fixada; com es va determinar, a `docs/validacio_census_income.md`.

Resultat actual (`data/census_income/run_2/paper_comparison_by_code.csv`):
**precisió 70,3%, recall 100%, F1 82,5%**. El motor anterior, amb les
mateixes dades: 64,5% / 76,9% / 70,2% (20 dels 26 codis; `docs/validacio_census_income.md`, secció 1.2).

| Codi | TP | FN | FP | Lectura |
|---|---|---|---|---|
| C210, C221, C223, C312, C530 | 2, 1, 7, 3, 1 | 0 | 0 | Encert total |
| C421 | 1 | 0 | 3 | D3, D4 i D6 tenen files d'`adult.test`; el paper compta files i no les veu |
| C410 | 4 | 0 | 2 | D4 i D6, ordre aleatori real (a D3, mateixes files que D4, el paper sí el marca) |
| C222, C311, C422, C510 | 2, 2, 3, 0 | 0 | 2, 1, 1, 2 | Columnes eliminades que la targeta no esmenta, el C311 de D7 (a D3/D4 el paper el marca), files amb `?` eliminades a D7, i els `?` que desapareixen a D6 i D7 |

El motor troba tots els codis del paper, i cap dels 11 falsos positius és un
error del motor. Cadascun, explicat amb les dades, a
`docs/validacio_census_income.md`.

Aquest resultat és d'abans de T-43. Amb els C5xx a les files aparellades,
s'espera que el C530 de D6 (l'equilibri de classes, que elimina files) passi a
ser un fals negatiu i que els C510 de D6 i D7 (els `?` desapareixen perquè
s'eliminen files) deixin de sortir: la Taula 1 fa servir la taxonomia del
paper. Cal tornar a executar `validate_census_income.py` per confirmar-ho.

---

## 15. Convencions i on trobar més informació

### Convencions
- **Git Flow** (`docs/GIT_FLOW.md`): branques `main` i `develop`
  protegides; el treball es fa en `feature/*` i entra per pull request.
- **Missatges de commit** amb prefix: `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:`.
- **CI** (`.github/workflows/ci.yml`): a cada push i PR, `ruff`, `pytest`
  i build de la imatge Docker.
- **Docstrings** en català, format Sphinx (`:param:`, `:return:`), curts:
  què fa la funció; el perquè de les decisions va a `decisions_tfg.txt`.
- **Una carpeta numerada per execució**: cap resultat es sobreescriu mai.
- **Resultats i errors separats**: cada fase té el seu CSV, i les
  fallades van sempre a `failures.csv`.

### Documents

Índex amb l'ordre de lectura recomanat: `docs/README.md`.
