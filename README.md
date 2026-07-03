# HF Dataset Version Analysis

Mostreig aleatori de datasets de Hugging Face per estimar quants tenen 2 o mes versions.

## Quickstart

```bash
source venv/bin/activate
python notebooks/random_sample_analysis.py --sample-size 50 --threads 4 --seed 42
python notebooks/random_sample_analysis.py --sample-size 1000 --threads 8 --seed 42
```

Per estimacio principal, no passis `--max-scanned` (escaneig complet de la poblacio disponible).

## Criteri d'elegibilitat

- Elegible nomes si `num_versions_detected >= 2`
- `num_versions_detected` es calcula com `num_tags + num_branches` (refs Git del dataset)

## Sortida

- `data/eligibility_report_N.csv`
- `data/funnel_summary_N.json`

## Variables utils

- `--sample-size`: mida de la mostra
- `--threads`: processament en paral·lel
- `--max-scanned`: limit opcional nomes per proves rapides
- `--seed`: mostra reproduible