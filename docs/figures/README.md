# Figures de la memòria

Generades amb `src/figures/` (un mòdul per figura) a partir del magatzem de
l'execució de referència, run_9 (decisió T-30): PNG a 300 ppp, amb la
mateixa paleta i el mateix format de números que la interfície
(`ui/palette.py`, `ui/fmt.py`). Cada gràfic de la interfície té la seva
taula; aquí, les dades són als marts.

| Fitxer | Pregunta | Origen |
|---|---|---|
| `fig_funnel.png` | Quants datasets passen cada filtre de la Fase 0? | `mart_funnel` |
| `fig_versions_timeline.png` | Quantes versions té cada dataset elegible, i quan es van publicar? | `dim_version`, `dim_dataset` |
| `fig_code_frequency.png` | Amb quina freqüència surt cada codi i cada perspectiva? | `mart_code_frequency` |
| `fig_breaking_share.png` | Quina proporció de les comparacions fetes té almenys un canvi trencador? | `mart_breaking_share` |
| `fig_changes_by_quarter.png` | Com evolucionen els canvis al llarg del temps, per perspectiva? | `mart_changes_by_quarter` |
| `fig_criterion_comparison.png` | Els datasets del Criteri A (tags) i del B (sessions) canvien de manera diferent? | `mart_criterion_comparison` |
| `fig_census_validation.png` | Com encerta el motor els codis de la Taula 1 del paper (Census Income)? | `mart_census_validation` |

## Com es regeneren

Des de l'arrel del repositori, amb el magatzem ja construït
(`python src/build_warehouse.py --run-dir data/run_9`):

```bash
python src/figures/make_all.py                 # totes
python src/figures/make_all.py fig_funnel      # només una
python src/figures/make_all.py --warehouse data/warehouse/run_<id>.duckdb --out <carpeta>
```

## Per llegir-les

- `fig_funnel`: escala logarítmica, perquè la mostra és de milers i els
  elegibles, una desena.
- `fig_code_frequency` i `fig_changes_by_quarter`: un canvi és un codi en una
  taula; `pulsia/fr-bench-pdf2md` en té 1.861 dels 1.868, perquè compara
  centenars de fitxers per versió.
- `fig_breaking_share` i `fig_criterion_comparison`: només compten les
  comparacions que s'han pogut fer (49 de 52 a run_9); el Criteri A en té
  només 2, i el seu interval és molt ample.
- `fig_census_validation`: C510 no té cap columna (precisió 0, recall sense
  definir: el motor el marca dues vegades i el paper cap).
