# HF Dataset Version Analysis

Mostreig aleatori de datasets de Hugging Face per estimar quants tenen 2 o més versions reals.

## Quickstart

```bash
source venv/bin/activate
python notebooks/random_sample_analysis.py --sample-size 10 --threads 2 --seed 42
python notebooks/random_sample_analysis.py --sample-size 500 --threads 8
```

## Criteri d'elegibilitat

- `num_tags >= 2`
- o bé `num_commits_substantive >= 2`

## Sortida

- `data/eligibility_report_N.csv`
- `data/funnel_summary_N.json`

## Variables útils

- `--sample-size`: mida de la mostra
- `--threads`: processament en paral·lel
- `--max-scanned`: límit d'escaneig per proves ràpides
- `--seed`: mostra reproduïble