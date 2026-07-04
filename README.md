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

Un dataset és **elegible** si té **2 o més versions genuïnes**, detectades per:
- **Tags/refs versionades** (explícites): p.e., `v1.0`, `v2.0`, etc.
- **Commits substantius** (implícits): canvis reals al dataset, sense ser només actualizacions de README o metadata.

## Sortida

- `data/eligibility_report_N_version.csv`
- `data/funnel_summary_N_version.json`

## Variables utils

- `--sample-size`: mida de la mostra
- `--threads`: processament en paral·lel
- `--max-scanned`: limit opcional nomes per proves rapides
- `--seed`: mostra reproduible