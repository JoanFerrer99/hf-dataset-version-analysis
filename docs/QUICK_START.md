# ⚡ Quick Start Guide

## 🚀 Executar l'anàlisi en 3 passos

### 1. Setup
```bash
cd ~/Documentos/UNIVERSITAT/TFG/hf-dataset-version-analysis
source venv/bin/activate
# Assegurar que HF_TOKEN està a ~/.env
```

### 2. Run
```bash
# Prova ràpida (10 datasets)
python notebooks/random_sample_analysis.py 10 2

# Anàlisi principal (500 datasets)
python notebooks/random_sample_analysis.py 500 8
```

### 3. Results
```
✅ data/eligibility_report_500.csv    → CSV detallat
✅ data/funnel_summary_500.json       → Resum estadístic
```

---

## 📖 Documentació Completa

Per a explicació detallada sobre:
- **Què és "elegible"** (2 versions o més)
- **Com es detecten** versions (tags + commits substantius)
- **Interpretació d'output**
- **Limitacions i metodologia**

👉 Veure: **[README.md](../README.md)**


✅ Dataset elegible = ≥2 versions reals (detectades per tags o commits substantius)
