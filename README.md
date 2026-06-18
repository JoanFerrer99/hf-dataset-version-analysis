# HuggingFace Dataset Version Analysis

## 📊 Objectiu

Determinar quins datasets de HuggingFace Hub (~ 150K) són **elegibles** per tenir múltiples versions reals.

Un dataset és **elegible** si té **2 o més versions genuïnes**, detectades per:
- **Tags/refs versionades** (explícites): p.e., `v1.0`, `v2.0`, etc.
- **Commits substantius** (implícits): canvis reals al dataset, sense ser només actualizacions de README o metadata.

## 🎯 Problema Resolt

**Metodologia correcta (sense biaix)**:
- Mostreig aleatori uniforme sobre **tota la población** de datasets (~150K)
- Algorithm: **Reservoir Sampling (Vitter)** per garantir que cada dataset té igual probabilitat
- Autenticació: **Token personal HF** (no API pública) per accedir a commits detallats

**Problema evitat**:
- ❌ Analitzar només els TOP 50 datasets més populars (biaix: els populars han tingut més manteniment)
- ✅ Mostra aleatòria real de tota la población

## 🔍 Com es Detecten les "Versions Reals"

### Criteri 1: Tags/References (Explicit Versioning)
```
Si dataset.tags >= 2  →  ELEGIBLE
```
Exemples: `v1.0`, `v2.0`, `release-1`, `stable`, etc.

### Criteri 2: Commits Substantius (Implicit Versioning)
```
Si commits_amb_canvis_reals >= 2  →  ELEGIBLE
```

**Commits que NO compten** (metadata-only):
- README, CITATION, LICENSE
- .gitattributes, .gitignore
- dataset_infos.json, model_cards

**Commits que SÍ compten**:
- Canvis en fitxers de dades
- Reorganització d'estructura
- Actualitzacions de contingut

**Detecció**: Es mira el títol del commit. Si NO conté keywords de metadata → es considera substantiu.

### Decisió Final
```python
if num_tags >= 2:
    eligible = True  # Via tags
elif num_substantive_commits >= 2:
    eligible = True  # Via commits
else:
    eligible = False
```

## 🚀 Execució

### Prerequisits
```bash
cd /home/joanferrer/Documentos/UNIVERSITAT/TFG/hf-dataset-version-analysis

# Crear entorn virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependències
pip install -r requirements.txt

# Configurar HF_TOKEN a ~/.env
echo "HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxx" >> ~/.env
```

### Executar l'Anàlisi

```bash
source venv/bin/activate

# Mostra petita de prova (10 datasets, 2 threads)
python notebooks/random_sample_analysis.py 10 2

# Mostra mitjana (200 datasets, 4 threads)
python notebooks/random_sample_analysis.py 200 4

# Anàlisi principal (500 datasets, 8 threads)
python notebooks/random_sample_analysis.py 500 8

# Mostra gran (1000 datasets, 8 threads)
python notebooks/random_sample_analysis.py 1000 8
```

**Paràmetres**:
- `SAMPLE_SIZE`: Quants datasets analitzar (per defecte: 500)
- `NUM_THREADS`: Processament paral·lel (per defecte: 4, màx: 8-12 depèn de sistema)

## 📊 Output

### 1. CSV de Detalls
**Localització**: `data/eligibility_report_N.csv`

Columnes:
| Campo | Descripció |
|-------|-----------|
| `dataset_id` | ID del dataset (p.e., `org/dataset-name`) |
| `has_tags` | Boolean: té algun tag? |
| `num_tags` | Nombre total de tags |
| `num_commits_total` | Commits analitzats (max 50) |
| `num_commits_with_data_changes` | Commits substantius detectats |
| `eligible` | Boolean: ≥2 versions? |
| `eligibility_reason` | `tags>=2`, `substantive_commits>=2`, o `insufficient_changes` |
| `error` | Missatge d'error si n'hi ha |

### 2. Resum JSON
**Localització**: `data/funnel_summary_N.json`

```json
{
  "timestamp": "2026-06-18T...",
  "sampling_method": "random_reservoir_sampling_uniform_no_bias",
  "authentication": "HF_TOKEN (personal account)",
  "sample_size": 500,
  "with_any_tag": 120,
  "with_2plus_tags": 85,
  "eligible_total": 142,
  "eligible_via_tags": 85,
  "eligible_via_commits": 57,
  "errors": 2,
  "eligible_proportion": 0.284,
  "estimated_eligible_in_population": 42600
}
```

**Interpretació**:
- `eligible_proportion`: % d'elegibles a la mostra (284% = ~28%)
- `estimated_eligible_in_population`: Estimació de datasets elegibles totals (150K × 0.284 ≈ 42.6K)

### 3. Console Output
```
✅ Token HF carregat del .env

[1/3] Mostreig aleatori de 500 datasets sobre TOTA la población
       (sense biaix de popularitat, autenticat amb HF_TOKEN)...
   Total de datasets vistos: 31945
       ✅ Mostra final: 500 datasets

[2/3] Classificant elegibilitat de cada dataset (paral·lel, 8 threads)...
       (analizant tags i commits amb token personal)...
   ... 50 datasets processats
   ... 100 datasets processats
   ...
       ✅ Processats: 500 datasets

[3/3] Escrivint resultats...
======================================================================
📊 RESUM EMBUT (mostra de 500 datasets aleatoris)
======================================================================
  timestamp: 2026-06-18T...
  sampling_method: random_reservoir_sampling_uniform_no_bias
  eligible_proportion: 0.284
  estimated_eligible_in_population: 42600
  ...
✅ CSV: data/eligibility_report_500.csv
✅ JSON: data/funnel_summary_500.json
✅ DataFrame: 500 files × 8 columnes
```

## 🏗️ Estructura del Projecte

```
notebooks/
  └── random_sample_analysis.py    ← Script principal (ACTUAL)
      
data/
  ├── eligibility_report_N.csv     ← Resultats detallats
  └── funnel_summary_N.json        ← Resum estadístic

src/                              ← (Futur) Processament post-análisis
extraction/
storage/
transformation/

tests/                            ← (Futur) Tests unitaris
```

## ⚡ Flux de Processament

```
1. RESERVOIR SAMPLING
   ├─ Iterem TOTS els datasets de HF (~150K)
   ├─ Vitter Algorithm: cada dataset té igual probabilitat
   └─ → Mostra aleatòria sense biaix

2. PROCESSAMENT PARAL·LEL (ThreadPoolExecutor)
   ├─ Per cada dataset a la mostra:
   │  ├─ 🏷️ Obtenir tags (list_repo_refs)
   │  └─ 📝 Analitzar commits (list_repo_commits)
   ├─ Classificar elegibilitat
   └─ → DataFrame amb resultats

3. ESTADÍSTIQUES & GUARDAMENT
   ├─ Calcular proporcions
   ├─ Estimar população total elegible
   ├─ Guardar CSV (full detall)
   └─ Guardar JSON (resum)
```

## 📈 Exemple d'Interpretació

Si executem amb mostra de 500:
```
eligible_proportion: 0.284
eligible_total: 142
```

**Interpretació**:
- De 500 datasets aleatoris, 142 (28.4%) són elegibles
- Estimem que de 150K datasets totals: 150,000 × 0.284 ≈ **42,600 datasets elegibles**