# Quick Start

```bash
source venv/bin/activate
python notebooks/random_sample_analysis.py --sample-size 50 --threads 4 --seed 42
```

Per la mostra principal:

```bash
python notebooks/random_sample_analysis.py --sample-size 1000 --threads 8 --seed 42
```

Per escaneig complet de la poblacio, no indiquis `--max-scanned`.

Elegibilitat estricta: nomes compta com elegible si el dataset te 2 o mes versions detectades (`num_tags + num_branches >= 2`).

Resultats:
- `data/eligibility_report_N.csv`
- `data/funnel_summary_N.json`
