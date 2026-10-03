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

## 2. Conceptes previs (fora del projecte)

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

### 2.2 Git LFS i el "clon bare" sense contingut

Els fitxers grans es guarden amb **Git LFS** (Large File Storage): el
repositori Git només conté un **punter** de text de ~130 bytes per
fitxer, i el contingut real viu en un magatzem a part.

Això ens permet una tècnica clau del projecte:

```
git clone --bare --filter=blob:none https://huggingface.co/datasets/<id>
```

- `--bare`: no crea còpia de treball (no hi ha fitxers desplegats).
- `--filter=blob:none`: no baixa el contingut dels fitxers.

Resultat: tenim **tot l'historial** (quins commits hi ha i quins fitxers
toca cadascun) **sense descarregar cap byte de dades**. Després, `git
show --name-status <commit>` sobre aquest clon local diu quins fitxers
ha modificat un commit, sense cap crida de xarxa. L'API de HF no exposa
aquesta informació, i per això cal clonar (històries d'usuari US-301 i US-302,
consultar `docs/taiga/taiga_user_stories.md`). 

Requereix `git` instal·lat al sistema.

### 2.3 L'API de Hugging Face (`huggingface_hub`)

Llibreria Python oficial. Les crides que fem servir:

| Crida | Per a què | On |
|---|---|---|
| `HfApi.list_datasets` | Recórrer tota la població de datasets | Fase 0 |
| `list_repo_refs` | Tags i branques d'un repositori | Fases 0, 1, 2 |
| `list_repo_commits` | Historial de commits (branca per defecte) | Fases 0, 1, 2 |
| `list_repo_tree` | Fitxers d'una revisió, amb la mida real (LFS resolt) | Fase 1, `extension_report.py` |
| `hf_hub_download` | Descarregar un fitxer concret a una revisió concreta | Fase 2, validació |

Totes necessiten un **token** de HF (rol "Read" és suficient), que es
llegeix de la variable d'entorn `HF_TOKEN` (fitxer `.env`).

Detall que sorprèn: `list_repo_tree` retorna un **generador**; la
petició HTTP es fa en iterar-lo, no en cridar-lo. Per això el codi el
consumeix sencer (`list(...)`) dins de la funció de reintent (vegeu 2.4).

### 2.4 Límits de l'API: errors 429 i 403

- **429 Too Many Requests**: HF limita les peticions per segon. Sense
  reintents, una execució de 1000 datasets va perdre el 59% de la mostra.
  Solució: reintentar amb espera exponencial (10s, 20s, 40s...) més un
  soroll aleatori ("jitter") perquè els threads no reintentin tots alhora.
- **403 Forbidden**: el dataset és *gated* (cal acceptar condicions a la
  web) o privat. És permanent: no es reintenta. Aquests datasets
  s'exclouen dels càlculs de proporcions però es compten a part.

Tota la lògica és a `notebooks/errors.py`; la justificació completa, a
`docs/decisions_tfg.txt` (T-02).

### 2.5 La taxonomia de canvis

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

### 2.6 Census Income: el cas de referència

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
| **Fitxer substantiu** | Fitxer amb dades reals, no metadades ni documentació. Es decideix per la ruta i l'extensió (secció 7.3). | inevstigat a la funció `is_substantive_path` |
| **Commit substantiu** | Commit que modifica almenys un fitxer substantiu. Si no s'ha pogut clonar, es dedueix del títol del commit. | investigat a la funció `determine_commit_substantive_with_paths` |
| **Sessió de treball** | Grup de commits substantius propers en el temps: ordenats per data, en comença una de nova quan dos consecutius estan separats per **més de 6 hores**. Evita comptar com a versions diferents els 5 commits que una eina de pujada fa en 10 minuts. Hi ha una sola implementació, compartida per totes les fases. | agrupat en la funció `cluster_commit_times` |
| **Dataset elegible** | Dataset amb ≥2 versions reals, i per tant estudiable. Criteri A o B (secció 7.2). | definit a la funció `classify_dataset` |
| **Criteri A** | ≥2 tags i ≥2 commits substantius. |
| **Criteri B** | ≥2 branques i commits substantius repartits en ≥2 sessions. | investigació de 2 sessions a la funció `has_time_dispersed_substantive_commits` |
| **Versió** | Criteri A: cada tag. Criteri B: cada sessió (representada pel seu commit més recent). | extracció a `version_extractor.extract_versions_for_dataset` |
| **Unitat de canvi** | Què es compara a la Fase 2. Criteri A: cada commit substantiu contra el commit anterior. Criteri B: el final de cada sessió contra el final de l'anterior. | classificat després de`classify_dataset` |
| **Fitxer tabular** | `.parquet`, `.csv` o `.tsv`. L'únic tipus que es descarrega i es compara. | es defineix a la funció `change_diff.is_tabular_path` |
| **Embut (funnel)** | Recompte de la Fase 0: mostra → elegibles / no elegibles / inaccessibles / errors. | contat a la funció `compute_funnel_stats` |

>Un fitxer *substantiu* compta per a l'**elegibilitat** (inclou vídeo, àudio, tensors...), però només els *tabulars* entren a la **classificació**.

### Identificadors que es troben al codi i als documents

- **Fase 0 / 1 / 2 / 3**: les etapes del pipeline (secció 6).
  Els missatges de log "FASE 1/2/3" dins de `run_sampling` són passos
  interns de la Fase 0 (mostreig, classificació, escriptura).
- **US-xxx**: històries d'usuari de la planificació a Taiga
  (`docs/taiga/taiga_user_stories.md`). P.e. US-302 = detecció real de
  fitxers modificats.
- **M-xx, T-xx, A-xx**: decisions metodològiques, tècniques i d'abast,
  a `docs/decisions_tfg.txt`.

---

## 4. Posar-ho en marxa

Passos complets (token, `.env`, Docker) al `README.md`. Resum:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "HF_TOKEN=hf_..." > .env          # token de HF amb rol "Read"

python notebooks/run_pipeline.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova ràpida
python notebooks/run_pipeline.py --sample-size 2000 --threads 4 --seed 42                    # execució real

pytest                                 # tests (no fan cap crida de xarxa)
ruff check notebooks tests             # lint
```

- Cal `git` al sistema (la imatge Docker ja l'inclou).
- Sense arguments, els scripts mostren l'ajuda i surten, perquè una
  crida accidental no engegui una execució de diverses hores.
- Una execució real de 2000 datasets recorre tota la població de HF:
  compta amb hores, no minuts.

---

## 5. Estructura del repositori

```
notebooks/      Codi del pipeline (scripts Python, no és un paquet)
tests/          Tests pytest, un fitxer per mòdul; l'API sempre simulada
data/           Resultats de les execucions (vegeu secció 10)
docs/           Documentació (vegeu secció 15)
Dockerfile, docker-compose.yml, requirements.txt, ruff.toml
.github/workflows/  CI: lint + tests + build de la imatge
```

Mòduls de `notebooks/`:

| Fitxer | Què fa |
|---|---|---|
| `run_pipeline.py` | **Orquestrador**: executa Fase 0 → 1 → 2 i desa tot en una carpeta per execució 
| `eligibility_scan.py` | Fase 0 (mostreig i elegibilitat) i Fase 2 (classificació de canvis) |
| `version_extractor.py` | Fase 1 (extreu les metadades de la seqüència de versions) |
| `change_diff.py` | Motor que compara dues versions d'un fitxer i en treu els codis |
| `errors.py` | Reintents, classificació d'errors, registre de fallades |
| `extension_report.py` | Recompte d'extensions de fitxer dels elegibles, no cridat per l'orquestrador |
| `validate_census_income.py` | Valida el motor contra Census Income, també executable aÏllat de l'orquestrador |

Puntualitzacions:

- **La Fase 2 viu a `eligibility_scan.py`, no a `change_diff.py`.**
  `change_diff.py` només sap comparar dues taules ja carregades. Qui
  decideix *quines* revisions i *quins* fitxers comparar és
  `classify_dataset`, que ja recorre els commits per decidir
  l'elegibilitat (decisió T-08).
- **`eligibility_scan.py` surt amb error en importar-lo si no troba
  `HF_TOKEN`.** Per això la CI defineix un token fictici per als tests.

---

## 6. Visió general del pipeline

```
 Població HF (~1M datasets)
        │
        ▼
 FASE 0  Mostreig i elegibilitat          eligibility_scan.run_sampling
        │  mostra aleatòria de N (2000 p.e.) → quins tenen ≥2 versions reals amb canvis substantius
        │  sortida: eligibility_report_*.csv  (~0.5% elegibles)
        ▼
 FASE 1  Extracció de versions            version_extractor.run_extraction
        │  per a cada elegible: llista ordenada de versions amb data,
        │  autors i mida.  sortida: versions_*.csv
        ▼
 FASE 2  Classificació de canvis          eligibility_scan.run_classification
        │  per a cada elegible: compara versions consecutives dels
        │  fitxers tabulars → codis de la taxonomia
        │  sortida: change_classification_*.csv
        ▼
 FASE 3  Esquema de dades               (pendent)
```

Les Fases 1 i 2 només treballen amb els elegibles: ~11 datasets de
2000, no tota la mostra. És el que fa viable descarregar contingut.

---

## 7. Fase 0 — Mostreig i elegibilitat

Codi: `eligibility_scan.py` (`run_sampling`). Objectiu: estimar quina
proporció de datasets de HF té més d'una versió real, i obtenir-ne la
llista dins de la mostra.

### 7.1 Mostreig per reservori

No es poden processar ~1M datasets (límits de l'API, secció 2.4), i
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

Per a cada dataset de la mostra:

1. `list_repo_refs` → nombre de tags i de branques. Si té menys de 2 de
   cadascun, és no elegible i s'acaba aquí (el cas majoritari: una sola
   crida).
2. Si no: `list_repo_commits` i clon bare (2.2).
3. Es recorren fins a 50 commits, del més nou al més vell, i per a
   cadascun es decideix si és substantiu (7.3).
4. Elegible si es compleix:
   - **Criteri A**: ≥2 tags i ≥2 commits substantius; o
   - **Criteri B**: ≥2 branques i els commits substantius formen ≥2
     sessions (separades per >6h).
5. Sense classificació de canvis, retorna tan bon punt és elegible.

Observacions:
- Els commits que s'analitzen són els de la branca per defecte. El
  nombre de branques del Criteri B només fa de filtre d'entrada.
- `--tags-only` només permet el Criteri A.
- Per què el Criteri B exigeix sessions separades: la primera versió del
  criteri comptava commits, i una validació manual de 13 elegibles va
  donar només un 38.5% de precisió. Les eines de pujada generen molts
  commits seguits que no són versions diferents (decisió M-02,
  `docs/us108_validation_report.md`). Amb sessions, la mateixa revisió
  va donar 11/11.

### 7.3 Què és un fitxer substantiu (`is_substantive_path`)

Es decideix en aquest ordre:

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

Si el clon falla, es recorre al títol del commit
(`is_substantive_commit`): no substantiu si conté paraules com "readme",
"license", "typo". És menys precís.

### 7.4 Sortida i mètriques

`write_results` escriu el report per dataset i un resum de l'embut:

- `eligible_proportion` = elegibles / (elegibles + no elegibles). Els
  inaccessibles (403) i els errors **no** compten al denominador: no
  sabem si ho serien.
- `eligible_proportion_of_attempts` = elegibles / tots els intents.
- `estimated_eligible_in_population`: extrapolació a tota la població.

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
  Fase 0).

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

### 8.1 `extension_report.py`: quins fitxers tenen els elegibles

Script aïllat. Respon: quin percentatge dels fitxers dels elegibles és
tabular, i quants elegibles tenen algun fitxer tabular (és a dir, sobre
quants s'aplicarà de veritat la Fase 2). Mira només la revisió actual
de cada repositori (`fetch_tree_paths`), no l'historial.

---

## 9. Fase 2 — Classificació de canvis

Codi: `eligibility_scan.run_classification` → `classify_dataset(...,
classify_changes=True)`, i el motor `change_diff.py`. És l'única fase que
**descarrega contingut real**, i per això només s'aplica als elegibles
(la classificació de tota la mostra baixaria centenars de GB).

### 9.1 Què es compara

1. Es tornen a recórrer els commits (fins a 50) i es guarden els
   substantius amb els fitxers que toquen.
2. Es formen les **unitats de canvi** (decisió T-13):
   - Criteri A: cada commit substantiu contra el commit anterior de
     l'historial.
   - Criteri B: el commit més recent de cada sessió contra el de la
     sessió anterior, sobre tots els fitxers tocats a la sessió nova.
     Els commits dins d'una mateixa sessió no es comparen entre ells.
3. Per a cada unitat, dels fitxers modificats es queden els **tabulars**,
   fins a 5 (`MAX_TABULAR_FILES_PER_COMMIT`; alguns datasets parteixen
   les dades en desenes de fitxers i sense límit trigaven hores).
4. Cada fitxer es descarrega a les dues revisions i es carrega sencer
   amb pandas (`download_tabular_file_at_revision`; per què pandas:
   decisió T-15).
5. `classify_file_change` hi aplica el motor:
   - fitxer que no existia abans → C421 (afegir files);
   - fitxer que ja no existeix → C422 (eliminar files);
   - si existeix a totes dues → `compute_all_diffs` + `classify_diffs`.

### 9.2 El motor de diffing (`change_diff.py`)

`compute_all_diffs(before, after)` rep dos `DataFrame` i crida 9
funcions pures independents. Cadascuna retorna fets ("la columna X ha
desaparegut"), i `compute_all_diffs` els converteix en un booleà per
codi. `classify_diffs` crea un `ChangeLabel` per a cada codi detectat.

| Funció | Codis | Com detecta el canvi |
|---|---|---|
| `diff_columns` | C210, C221, C222, C223 | Diferència entre els conjunts de noms de columna. És un renom si una columna eliminada i una d'afegida tenen el mateix nom normalitzat (minúscules, sense `-_. `) i tipus de la mateixa família (decisió T-12). L'ordre es mira sobre les columnes comunes. |
| `diff_column_types` | C311, C321 | El `dtype` d'una columna comuna ha canviat. |
| `diff_categorical_values` | C312 | Columnes no numèriques: han aparegut o desaparegut categories. |
| `diff_numeric_values` | C322 | Columnes numèriques: `mean`, `std`, `min` o `max` canvien més d'un 5% (decisió T-16). |
| `diff_row_count` | C421, C422 | El nombre de files creix o decreix. |
| `diff_row_order` | C410 | Es calcula un hash per fila; si el conjunt de hashes és el mateix però en un altre ordre, és una reordenació (decisió T-11). |
| `diff_missingness` | C510 | La proporció de nuls d'una columna ha canviat. |
| `diff_correlation` | C520 | La matriu de correlació (Pearson) de les columnes numèriques varia més de 0.05. |
| `diff_distribution` | C530 | Quartils (numèriques, tolerància 5%) o freqüència de cada categoria (variació > 0.05). |

### 9.3 Limitacions conegudes

Convé tenir-les presents abans d'interpretar resultats:

- **Columnes comunes = mateix nom.** Totes les funcions menys
  `diff_columns` comparen només columnes amb el mateix nom a les dues
  versions. Si una columna es reanomena, el seu contingut no es compara.
- **Renoms semàntics** (`sex` → `is_male`) no es detecten com a renom:
  surten com una columna eliminada més una d'afegida (C222 + C221).
- **C410 només detecta reordenació pura**: si, a més, hi ha qualsevol
  altre canvi de contingut, no es detecta.
- **C421/C422 són aproximats**: sense un identificador estable de fila
  només se sap si el nombre de files creix o decreix, no quines files.
  Un fitxer que no s'ha pogut descarregar es tracta igual que un fitxer
  inexistent.
- **Columnes no hashables** (àudio o imatge llegits com a diccionaris)
  s'exclouen de valors, distribució i ordre.
- **El CSV de sortida no diu de quin fitxer ve cada etiqueta.** Si
  canvien diversos fitxers entre les mateixes dues versions, el mateix
  codi surt repetit (`docs/multi_file_repos_investigation.md`).

---

## 10. Fitxers que es generen

Cada execució de `run_pipeline.py` crea **`data/run_<id>/`** (número
incremental, mai sobreescriu) i hi desa tot:

| Fitxer | Fase | Contingut |
|---|---|---|
| `eligibility_report_<N>_<k>.csv` | 0 | Una fila per dataset de la mostra: `dataset_id, num_tags, num_branches, num_commits_substantive, eligible, eligibility_reason, status, error_category, error`. `status` = `classified`, `access_restricted` (403) o `error`. |
| `funnel_summary_<N>_<k>.json` | 0 | Resum de l'embut (secció 7.4): població recorreguda, elegibles per criteri, inaccessibles, errors, proporcions. |
| `versions_<k>.csv` | 1 | Una fila per versió: `dataset_id, version_label, version_order, version_source, commit_sha, commit_date, authors, approx_size_bytes, session_commit_count, status`. |
| `change_classification_<k>.csv` | 2 | Una fila per codi detectat en un fitxer d'una unitat de canvi: `dataset_id, version_from, version_to, code, description, is_breaking`. `version_from`/`version_to` són SHA de commit. |
| `failures.csv` | totes | Només si hi ha fallades: `timestamp, source, dataset_id, error_category, error_message, retries_attempted`. `source` indica la fase. |

`N` = `--sample-size`; `<k>` = número que posa cada fase. Amb
`--input-csv` no hi ha Fase 0 i el CSV d'entrada no es copia a la
carpeta.

Els scripts aïllats escriuen directament a `data/`:
`extension_report_<k>.csv`/`.json` i `census_income_*_<k>.csv`. Els
resultats de referència de Census Income estan arxivats a
`data/census_income/`.

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
- Si el clon falla, no s'atura res: es fa servir l'heurística de títol.
  Si `git` no està instal·lat, s'avisa un sol cop per execució.

---

## 12. Cost (Ordre - O(cost)) i complexitat

El cost no el posa el càlcul local, sinó **les crides a l'API i els
bytes descarregats**. Per això les decisions limiten *quantes* crides i
descàrregues es fan.

**Fase 0** (tota la població i la mostra):
- Recórrer la població: una passada paginada (~1M ids), temps O(total),
  memòria O(N).
- `classify_dataset` per dataset: 1 crida `list_repo_refs`; en la
  majoria s'acaba aquí. Si no: 1 `list_repo_commits` + 1 clon (només
  historial) + fins a 50 `git show` locals, sense xarxa.

**Fase 1** (només elegibles):
- Criteri A: 1 `list_repo_refs` + per tag, 1 `list_repo_commits` i 1
  `list_repo_tree`.
- Criteri B: 1 `list_repo_commits` + 1 clon + per sessió, 1
  `list_repo_tree`.

**Fase 2** (només elegibles, l'única que baixa dades):
- Per unitat de canvi: fins a 5 fitxers × 2 descàrregues completes
  (queden a la caché local de HF). Baixar el contingut complet de totes
  les versions de 11 elegibles es va estimar en 151 GB (un sol dataset en
  pesava 78): per això el límit de fitxers i el filtre d'elegibles.
- `compute_all_diffs` sobre un fitxer de `r` files i `c` columnes,
  amb les dues taules a memòria: majoritàriament O(r·c); l'ordre de
  files hi afegeix O(r log r) per ordenar hashes; la correlació és
  O(r·c²). Tot vectoritzat amb pandas, sense bucles per fila.

Límits fixos: 50 commits per dataset (`MAX_COMMITS`), 5 fitxers per
unitat de canvi, 30 s per clonar, 10 s per `git show`.

---

## 13. Validació i resultats

### 13.1 Tests

`tests/` té un fitxer per mòdul (224 tests). L'API de HF sempre se
simula amb `monkeypatch`: els tests no necessiten xarxa ni token real.
`tests/conftest.py` afegeix `notebooks/` al `sys.path`.

### 13.2 Validació del motor amb Census Income

`validate_census_income.py` compara D1-D7 amb D0 (secció 2.6) amb el
mateix motor de la Fase 2 i contrasta el resultat amb la Taula 1 del
paper, codi per codi, sense C100 (decisió T-14). Per a cada versió i
codi: vertader positiu (TP) si el paper i el motor el marquen, fals
negatiu (FN) si només el paper, fals positiu (FP) si només el motor.

Resultat actual (`data/census_income/census_income_paper_comparison_by_code_5.csv`):
***precisió 76.9%** (20/26)

| Codi | TP | FN | FP | Lectura |
|---|---|---|---|---|
| C210, C421, C422 | 2, 1, 3 | 0 | 0 | Encert total |
| C223 | 5 | 2 | 0 | Perd els renoms semàntics (9.3) |
| C410 | 3 | 1 | 0 | Perd la reordenació barrejada amb altres canvis |
| C221 | 1 | 0 | 4 | Sobredetecció: en part, renoms semàntics comptats com a eliminar + afegir |
| C222 | 2 | 0 | 2 | Mateixa causa |
| C312 | 0 | 3 | 1 | Mai encertat. Hipòtesi no verificada: els valors canvien en columnes que també es reanomenen, i aquestes no es comparen (9.3) |
| C322 | 0 | 0 | 2 | Els 2 FP que queden són diferències reals per sobre del 5% |
| C311, C530 | 2, 1 | 0 | 1 | Un FP cadascun |

D6 té una ambigüitat: el repositori té tres fitxers candidats i el paper
no diu quin va fer servir; probablement n'hem triat un altre.

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
- **Execucions numerades**: cap resultat es sobreescriu mai.
- **Resultats i errors separats**: cada fase té el seu CSV, i les
  fallades van sempre a `failures.csv`.

### Documents
| Document | Què hi trobaràs |
|---|---|
| `README.md` | Instal·lació, token, Docker, ordres |
| `docs/decisions_tfg.txt` | Totes les decisions amb el seu perquè |
| `docs/taxonomy.md` | La taxonomia completa i concepte `is_breaking` explicat|
| `docs/taiga/taiga_user_stories.md` | Històries d'usuari (US-xxx) |
| `docs/us108_validation_report.md` | Validació manual del criteri d'elegibilitat |
| `docs/multi_file_repos_investigation.md` | Notes sobre repositoris amb diversos fitxers tabulars |
| `docs/paper_techniques_ml_models_change.md` | Notes sobre l'estudi de referència de canvis en models |
| `docs/GIT_FLOW.md` | Model de branques |
