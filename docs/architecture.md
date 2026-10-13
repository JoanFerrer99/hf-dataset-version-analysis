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
| C410 | Ordre de files | Conjunt de files |
| C421 | Afegir fila | Conjunt de files |
| C422 | Eliminar fila | Conjunt de files |
| C510 | Valors absents (missings) | Característiques estadístiques |
| C520 | Correlacions | Característiques estadístiques |
| C530 | Distribució de les dades | Característiques estadístiques |

Decisions d'abast: **C100 no es classifica** (el director va indicar que
no interessa), així que el projecte treballa amb els altres 14 codis. I
la taxonomia només té sentit sobre **fitxers tabulars** (files i
columnes): àudio, vídeo, imatges o tensors queden fora de la
classificació. La taxonomia classifica el *dataset*, no l'ús que se'n
fa: no sap quina columna és el "target" d'un model.

**Canvi trencador (`is_breaking`)**: heurística pròpia del projecte.
Un canvi és trencador si probablement fa **fallar l'execució** d'un 
pipeline que llegeix les dades per nom, posició o tipus: C210, C222,
C223, C311, C321 i C410. Els altres codis poden degradar un model sense
fer fallar res, i es marquen com a no trencadors. Detall a `docs/taxonomy.md`.

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
| **Fitxer de dades tabular** | Fitxer substantiu i tabular (`.parquet`, `.csv`, `.tsv`, `.json`, `.jsonl`). És el que fa elegible un dataset i el que compara el motor. | funció `is_tabular_data_path` |
| **Commit tabular** | Commit que modifica almenys un fitxer de dades tabular. Cal el clon per saber-ho: sense clon, no compta. | funció `is_tabular_commit` |
| **Candidat** | Dataset de la mostra amb ≥2 tags o ≥2 branques: l'únic al qual es mira la llista de fitxers i, si té dades tabulars, els commits (secció 7.2). | funció `classify_dataset` |
| **Sessió de treball** | Grup de commits tabulars propers en el temps: ordenats per data, en comença una de nova quan dos consecutius estan separats per **més de 6 hores**. Evita comptar com a versions diferents els 5 commits que una eina de pujada fa en 10 minuts. Hi ha una sola implementació, compartida per totes les fases. | agrupat en la funció `cluster_commit_times` |
| **Dataset elegible** | Dataset amb ≥2 versions reals, i per tant estudiable. Criteri A o B (secció 7.2). | definit a la funció `classify_dataset` |
| **Criteri A** | ≥2 tags i ≥2 commits tabulars. | funció `eligibility_criterion` |
| **Criteri B** | ≥2 branques i commits tabulars repartits en ≥2 sessions. | funció `eligibility_criterion` (sessions: `has_time_dispersed_substantive_commits`) |
| **Versió** | Criteri A: cada tag. Criteri B: cada sessió (representada pel seu commit més recent). | extracció a `version_extractor.extract_versions_for_dataset` |
| **Unitat de canvi** | Què es compara a la Fase 2. Criteri A: cada commit tabular contra el commit anterior. Criteri B: el final de cada sessió contra el final de l'anterior. | funció `change_units` |
| **Fitxer tabular** | `.parquet`, `.csv`, `.tsv`, `.json` o `.jsonl`. L'únic tipus que es descarrega i es compara. | es defineix a la funció `diffengine.units.is_tabular_path` |
| **Shard** | Fitxer amb només una part de les files d'un split.
| **Taula** | Els shards del split s'uneixen en ordre en una sola taula.


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

```

- Cal `git` al sistema (la imatge Docker ja l'inclou).
- Sense arguments, els scripts mostren l'ajuda i surten, perquè una
  crida accidental no engegui una execució de diverses hores.
- Una execució real de 2000 datasets recorre tota la població de HF:
  compta amb hores, no minuts.

---

## 5. Estructura del repositori

```
src/                Codi del pipeline: un script per fase i el motor de detecció de canvis
  diffengine/       El motor, com a paquet de Python (s'explica a docs/validacio_census_income.md, secció 1)
tests/              Tests automàtics (pytest), sense xarxa
data/               Resultats de les execucions (secció 10)
docs/               Documentació (ordre de lectura: docs/README.md)
```

### 5.1 Fitxers del pipeline (`src/`)

| Fitxer | Què fa |
|---|---|---|
| `run_pipeline.py` | **Orquestrador.** Crea una carpeta nova per a l'execució i encadena les Fases 0, 1 i 2. |
| `eligibility_scan.py` | Fase 0 (mostra aleatòria i elegibilitat) i Fase 2 (classificació de canvis dels elegibles). Conté també el clon de git i el criteri de quins fitxers compten. |
| `version_extractor.py` | Fase 1: la llista ordenada de versions de cada elegible, amb data, autors i mida. |
| `errors.py` | Reintents davant els límits de l'API, classificació dels errors i registre de fallades a `failures.csv`. És una llibreria que es fa servir totes les fases. |
| `validate_census_income.py` | Valida el motor amb la Taula 1 del paper (Census Income). |
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
| `test_diffengine_units.py`, `test_diffengine_pairs.py`, `test_diffengine_load.py` | Passos 1 i 2 del motor |

### 5.4 Infraestructura

| Fitxer | Per a què |
|---|---|
| `requirements.txt` | Dependències amb versió fixada |
| `ruff.toml` | Regles de lint |
| `Dockerfile`, `docker-compose.yml` | Imatge per executar el pipeline sense instal·lar res; `docker-compose` hi defineix un servei per script (`run-pipeline`, `eligibility-scan`, `version-extractor`) |
| `.github/workflows/ci.yml` | A cada push: lint, tests i construcció de la imatge |
| `.github/workflows/docker-publish.yml` | Publica la imatge |

**Detalls a tenir en compte:**

- **La Fase 2 viu a `eligibility_scan.py`, no a `diffengine/`.** El motor
  sap comparar dues revisions; qui decideix *quines* es comparen és
  `classify_dataset`, que ja recorre els commits per decidir l'elegibilitat
  (decisió T-08).
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
        │  sortida: eligibility_report.csv, funnel_summary.json,
        │           tabular_commits.csv (els commits tabulars dels elegibles)
        ▼
 FASE 1  Extracció de versions            version_extractor.run_extraction
        │  per a cada elegible: llista ordenada de versions amb data,
        │  autors i mida.  sortida: versions.csv
        ▼
 FASE 2  Classificació de canvis          eligibility_scan.run_classification
        │  per a cada elegible: compara versions consecutives de les
        │  taules → codis de la taxonomia
        │  sortida: change_classification.csv
        ▼
 FASE 3  Esquema de dades               (pendent)
```

Les Fases 1 i 2 només treballen amb els elegibles (una desena de 2.000), no
amb tota la mostra. És el que fa viable descarregar contingut.

Opcions útils: `--input-csv <report>` salta la Fase 0 i fa servir un report
existent; `--skip-version-extraction` i `--skip-classification` ometen les
Fases 1 i 2; `--max-scanned` limita el recorregut (només per a proves, perquè
esbiaixa la mostra).

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
2. **La versió actual té dades tabulars?** `list_current_files` (una crida
   a l'API, uns 0,2 s, sense clonar) dona la llista de fitxers.
   `tabular_file_share` compta els fitxers de dades (sense metadades ni
   documentació, secció 7.3) i quina proporció són tabulars. Si no hi ha
   cap fitxer de dades tabular, el dataset no és elegible i no es llisten
   els commits ni es clona. Aquestes dues xifres es guarden en memòria
   (`INTERNAL_FIELDS`), però de moment no s'escriuen enlloc: només
   existeixen per als candidats, no per a tota la mostra. A `run_8`, 27 dels 29 candidats tenien dades tabulars.
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


### 7.3 Quins fitxers compten (`is_tabular_data_path`)

Un commit compta si toca un **fitxer de dades tabular**. Això són dues
condicions:

- **És dades, no metadades** (`is_substantive_path`, a sota).
- **És tabular** (`diffengine.units.is_tabular_path`): `.parquet`, `.csv`,
  `.tsv`, `.json` o `.jsonl`, excepte els JSON de metadades del Hub i de
  LeRobot. És la mateixa definició que fa servir el motor de la Fase 2, de
  manera que tot dataset elegible té alguna cosa que el motor pot comparar.

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
  Fase 0). Les sessions es fan amb els commits tabulars que va desar la
  Fase 0 (`tabular_commits.csv`): no es tornen a llistar ni es clona res.

Cada fila porta `version_source` (`tag` o `commit_session`) perquè la
confiança no és la mateixa: un tag és una marca deliberada del
mantenidor; una sessió és una inferència.

Altres detalls:
- `approx_size_bytes`: suma de la mida de tots els fitxers de la
  revisió (`list_repo_tree`, una crida per versió; `--skip-size` l'omet).
- `authors`: l'API no distingeix autor de *committer*; és l'únic camp
  disponible.
- Errors parcials (la data d'un tag, la mida d'una versió) no fan perdre
  el dataset: queden al camp `status` (`commit_error`, `size_error`).

---

## 9. Fase 2 — Classificació de canvis

Codi: `eligibility_scan.run_classification` (llegeix els commits tabulars
de la Fase 0, en forma les parelles i les compara) i el motor
`src/diffengine/` (**`docs/validacio_census_income.md`**, secció 1). És l'única fase que **descarrega contingut real**,
i per això només s'aplica als elegibles (la classificació de tota la
mostra baixaria centenars de GB).

### 9.1 Què es compara

1. `load_tabular_commits` llegeix els commits tabulars de cada elegible
   que va desar la Fase 0 (`tabular_commits.csv`, a la mateixa carpeta que
   el report). Es comparen exactament els commits que van fer elegible el
   dataset, sense tornar a consultar l'historial.
2. `change_units` forma les **unitats de canvi** a partir de la mateixa llista de
  commits tabulars:
   - Criteri A: cada commit tabular contra el commit anterior de
     l'historial.
   - Criteri B: el commit més recent de cada sessió contra el de la
     sessió anterior. Els commits dins d'una mateixa sessió no es
     comparen entre ells.
3. `compare_change_units` crida el motor amb les dues revisions de cada
   unitat (`pairs.compare_revisions`). No cal tornar a mirar si els fitxers
   són tabulars: les unitats només surten de commits tabulars. El motor:
   - cada revisió es resol en **taules (subset, split)** amb les regles
     de la llibreria `datasets`. Els shards d'un split (secció 2.2) es
     descarreguen tots i s'uneixen en ordre en una sola taula, de manera
     que si la versió nova parteix les mateixes files en més o menys
     fitxers, no surt cap canvi;
   - les taules s'aparellen entre revisions; les que tenen el mateix hash
     de contingut no es descarreguen;
   - la resta es descarrega, es llegeix i es compara.
4. Cada parell de taules acaba amb un **estat** (`ok`,
   `identical_content`, `absent_old`/`absent_new`, `download_failed`,
   `parse_failed`, `too_large`, i `excluded` per als fitxers
   tabulars canviats que no són cap taula). Una fallada de descàrrega
   no es converteix mai en codis.

### 9.2 El motor (`diffengine/`)

Compara dues versions d'un dataset en 5 passos. `engine.py` n'és l'índex.

| Pas | Què fa | Mòduls |
|---|---|---|
| 1 | Trobar les taules que es comparen i quina va amb quina | `units.py`, `pairs.py` |
| 2 | Llegir cada taula i saber el tipus de cada columna | `load.py` |
| 3 | Aparellar columnes i files (3a columnes pel nom, 3b files, 3c columnes pel contingut) | `columns.py`, `rows.py`, `transforms.py` |
| 4 | Detectar els canvis, amb un fitxer per perspectiva de la taxonomia: `columns_set.py` (C2xx), `column_kind.py` (C3xx), `rows_set.py` (C4xx), `data.py` (C5xx); `common.py` és el que comparteixen | `detectors/` |
| 5 | Escriure el resultat | `output.py` |

`config.py` té tots els llindars, agrupats pels mateixos passos.

---

## 10. Fitxers que es generen

Cada execució de `run_pipeline.py` crea **`data/run_<id>/`** (número
incremental, mai sobreescriu) i hi desa tot:

| Fitxer | Fase | Contingut |
|---|---|---|
| `eligibility_report.csv` | 0 | Una fila per dataset de la mostra: `dataset_id, num_tags, num_branches, num_tabular_commits, eligible, eligibility_reason, status, error_category, error`. `eligibility_reason` diu el criteri que es compleix o el filtre on s'ha aturat. `status` = `classified`, `access_restricted` (403) o `error`. |
| `tabular_commits.csv` | 0 | Una fila per commit tabular de cada elegible: `dataset_id, commit_id, parent_id, created_at, authors`. `parent_id` és el commit anterior (buit per al més vell dels 50 revisats). El llegeixen les Fases 1 i 2. |
| `funnel_summary.json` | 0 | Resum de l'embut (secció 7.4): població recorreguda, quants passen cada filtre, elegibles per criteri, inaccessibles, errors, proporcions. |
| `versions.csv` | 1 | Una fila per versió: `dataset_id, version_label, version_order, version_source, commit_sha, commit_date, authors, approx_size_bytes, session_commit_count, status`. |
| `change_classification.csv` | 2 | Una fila per taula, parell de versions i codi: `dataset_id, version_from, version_to, file_path, code, description, is_breaking`. `version_from`/`version_to` són SHA de commit. |
| `failures.csv` | totes | Només si hi ha fallades: `timestamp, source, dataset_id, error_category, error_message, retries_attempted`. `source` indica la fase. |

L'únic número és el de la carpeta: a dins, els noms són fixos. Els scripts
executats sols (`eligibility_scan.py`, `version_extractor.py`) també creen
la seva carpeta. Amb `--input-csv` no hi ha Fase 0 i el CSV d'entrada no es
copia a la carpeta.

La validació de Census Income escriu a `data/census_income/run_<id>/`.

---

## 11. Gestió d'errors de l'API Hugging Face (`errors.py`)

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

## 12. Cost (Ordre - O(cost)) i complexitat

El cost no el posa el càlcul local, sinó **les crides a l'API i els
bytes descarregats**. Per això les decisions limiten *quantes* crides i
descàrregues es fan.

**Fase 0** (tota la població i la mostra):
- Recórrer la població: una passada paginada (~1M ids), temps O(total),
  memòria O(N).
- `classify_dataset` per dataset: 1 crida `list_repo_refs`; en la
  majoria (98,5% a `run_8`) s'acaba aquí. Per als candidats: 1
  `dataset_info` (llista de fitxers). Si tenen dades tabulars: 1
  `list_repo_commits` + 1 clon (51 commits, sense contingut, ~1 s) + fins
  a 50 `git show` locals, sense xarxa.

**Fase 1** (només elegibles):
- Criteri A: 1 `list_repo_refs` + per tag, 1 `list_repo_commits` i 1
  `list_repo_tree`.
- Criteri B: cap crida per trobar les sessions (fa servir
  `tabular_commits.csv`) + per sessió, 1 `list_repo_tree`.

**Fase 2** (només elegibles, l'única que baixa dades):
- Per unitat de canvi: 2 `list_repo_tree` (+ el README de cada
  revisió) i 2 descàrregues per cada taula amb contingut diferent (queden
  a la caché local de HF). Baixar el contingut complet de totes les
  versions de 11 elegibles es va estimar en 151 GB (un sol dataset en
  pesava 78): per això el salt per hash, el límit de bytes per taula
  (`max_unit_bytes`) i el filtre d'elegibles.
- Comparar una taula de `r` files i `c` columnes: majoritàriament O(r·c)
  per passada, vectoritzat.

Límits fixos: 50 commits per dataset (`MAX_COMMITS` a la Fase 1), 500 MB per taula,
30 s per clonar, 10 s per `git show`.

---

## 13. Validació i resultats

### 13.1 Tests

210 tests (secció 5.4). Cap necessita xarxa ni token: l'API de Hugging Face
se simula amb `monkeypatch`.

### 13.2 Validació del motor amb Census Income

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

---

## 14. Convencions i on trobar més informació

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
