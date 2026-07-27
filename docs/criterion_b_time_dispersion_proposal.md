# Proposta: dispersió temporal mínima al Criteri B (branca `feature/criterion-b-time-dispersion`)

> **Estat: proposta, NO fusionada a `main`/`develop`.** Implementada i
> testejada en una branca separada per revisar-la abans de decidir si
> s'incorpora. Motivada per `docs/us108_validation_report.md`, que troba
> que el Criteri B (branches, sense tags) té una precisió de només 20%
> (2/10) sobre la mostra de 13 datasets elegibles validats manualment.

## Problema

`classify_dataset()` marcava un dataset elegible pel Criteri B tan bon
punt trobava 2 commits amb un títol "substantiu" (`is_substantive_commit`),
sense mirar QUAN es van fer. Eines com LeRobot (captura de dades de
robòtica) generen desenes de commits automàtics —`"Upload folder using
huggingface_hub"`, `"Delete folder ./data/chunk*"`— en una sola sessió de
pujada de segons o minuts. Cada commit individual passa l'heurística de
títol (no conté cap paraula clau de manteniment), però el conjunt
representa **una sola versió**, no múltiples: exactament el patró
identificat en 8 dels 13 elegibles de la mostra de referència.

## Canvi proposat

Nova funció pura `has_time_dispersed_substantive_commits(commit_times,
min_gap_hours)` (`notebooks/eligibility_scan.py`): donada una llista de
dates de commits ja considerats substantius, retorna `True` només si n'hi
ha >=2 I la diferència entre el més antic i el més recent és >=
`min_gap_hours`.

Dins de `classify_dataset()`, el Criteri B ara exigeix aquesta dispersió
temporal a més de `branches >= 2`. El Criteri A **no es toca** — la
validació manual el troba fiable al 100% (3/3) en aquesta mostra, i
`docs/us108_validation_report.md` només recomana revisar el Criteri B.

Cost afegit: cap crida a l'API nova. Només cal conservar `created_at` dels
commits ja obtinguts (`list_repo_commits` ja el proporciona) enlloc de
descartar-lo.

## Anàlisi de sensibilitat (offline, sense noves crides a l'API)

Reutilitzant `data/us108_validation_worksheet.json` (evidència real ja
recollida per US-108, amb timestamps de commits per als 13 elegibles) i
la classificació manual TP/FP de `docs/us108_validation_report.md`, s'ha
simulat el nou Criteri B amb diferents llindars de `min_gap_hours`:

| Llindar | Elegibles restants | TP conservats | FP conservats | Precisió |
|---|---|---|---|---|
| (sense canvi, actual) | 13 | 5/5 | 8/8 | 38.5% |
| 1h | 8 | 5/5 | 3/8 | 62.5% |
| 2h | 8 | 5/5 | 3/8 | 62.5% |
| 4h | 7 | 5/5 | 2/8 | 71.4% |
| 6h | 6 | 5/5 | 1/8 | 83.3% |
| **24h (per defecte proposat)** | **6** | **5/5** | **1/8** | **83.3%** |
| 48h | 5 | 5/5 | 0/8 | **100%** |
| 72h – 336h (2 setm.) | 5 | 5/5 | 0/8 | 100% |

Observacions:
- **Cap llindar entre 1h i 2 setmanes exclou cap dels 5 vertaders
  positius** — el fix no introdueix falsos negatius en aquesta mostra.
- Amb 1h (el meu primer valor per defecte, abans d'aquesta anàlisi) només
  es filtren 3/8 falsos positius: alguns patrons LeRobot densos duren
  >1h (p.e. `ni25y/training-pick-up`, ~1.5h; `sucrammal/plant_square_pour_2`,
  ~2h10).
- A partir de 48h, el resultat és **perfecte sobre aquesta mostra** (0
  falsos positius, 5 vertaders positius): l'únic cas que sobreviu a 24h
  (`cgeorgiaw/merfish`, títols repetits literalment durant una sessió de
  depuració) desapareix a 48h.

**Per què 24h i no 48h com a valor per defecte**: amb només 13 datasets a
la mostra, triar el llindar que optimitza exactament aquests 13 casos és
un risc de sobreajustament (el llindar "òptim" podria no generalitzar a
la resta de la població). 24h és un valor conceptualment defensable per
si mateix (una separació d'un dia sencer suggereix clarament una sessió
de treball represa, no continuada) i ja recupera la major part del
guany de precisió (38.5% → 83.3%) sense apropar-se tant al límit exacte
observat en aquesta mostra petita. **Aquest valor és negociable** —
`MIN_SUBSTANTIVE_GAP_HOURS` és una constant única al capçal del mòdul,
trivial de canviar un cop hi hagi més dades o el director hi opini.

## Com reproduir l'anàlisi de sensibilitat

```python
import json
from datetime import datetime, timedelta

with open("data/us108_validation_worksheet.json") as f:
    data = json.load(f)

def dispersed(times, min_gap_hours):
    valid = [t for t in times if t is not None]
    return len(valid) >= 2 and (max(valid) - min(valid)) >= timedelta(hours=min_gap_hours)

for ds in data["datasets"]:
    if not ds["eligibility_reason"].startswith("Criteri B"):
        continue  # Criteri A no es toca
    times = [datetime.fromisoformat(c["created_at"])
             for c in ds["commits"] if c["is_substantive"] and c["created_at"]]
    print(ds["dataset_id"], dispersed(times, min_gap_hours=24.0))
```

(Requereix `data/us108_validation_worksheet.json`, generat per
`python notebooks/validate_eligible.py`; no fa cap crida nova a l'API.)

## Limitacions i pròxims passos

- Mostra de validació molt petita (n=13). Abans de fusionar aquesta
  proposta caldria, idealment, re-executar `classify_dataset()` amb el
  nou criteri sobre una mostra fresca (no la mateixa usada per triar el
  llindar) i tornar a mesurar la precisió, per evitar avaluar el canvi
  amb les mateixes dades que han inspirat el llindar.
- No s'ha canviat el Criteri A ni la resta del pipeline (`errors.py`,
  reservoir sampling, etc.) — diff mínim, limitat a
  `has_time_dispersed_substantive_commits` i al bloc de `classify_dataset`
  que decideix el Criteri B.
- `write_results()` ara compta `eligible_Criteri_B` amb
  `.str.startswith("Criteri B")` (com ja es feia per al Criteri A) perquè
  el text de `eligibility_reason` inclou ara el llindar (`"...dispersos
  >=24.0h"`).
- Tests nous a `tests/test_eligibility_scan.py`:
  `TestHasTimeDispersedSubstantiveCommits` (funció pura, 5 tests) i dos
  tests d'integració a `TestClassifyDatasetResultShape` (commits dispersos
  → elegible; commits agrupats → no elegible). 46/46 tests passen.
