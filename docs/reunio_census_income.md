# Reunió: resposta al feedback i estat de la validació

Resposta als dos correus i resum de l'estat del treball. Els detalls són a
`docs/falsos_positius.md` i a `docs/census_income_paper_method.md`.

---

## 1. El canvi a `architecture.md`

La modificació de la secció 5 eren dues línies de la taula de mòduls: el
separador tenia tres columnes (`|---|---|---|`) per a una taula de dues, i
a la fila de `run_pipeline.py` hi faltava la `|` final. **Totes dues
correccions ja són a la versió actual.**

Des d'aquella versió (3 d'octubre), el document s'ha actualitzat amb el
motor nou i la nova organització del repositori:

- `notebooks/` ara és `src/` (eren scripts, no notebooks), i els
  experiments són a `experiments/`.
- La secció 5 descriu també els mòduls del motor de detecció de canvis
  (`src/diffengine/`), ordenats com les perspectives de la taxonomia.
- La secció 13.2 té el resultat actual de Census Income.
- `docs/README.md` dona l'ordre de lectura de tota la documentació.

## 2. La sortida de l'escaneig d'elegibilitat

Exemple real (`data/run_8/funnel_summary_2000_8.json`):

```
eligible                          11
ineligible                      1894
access_restricted                 87
errors                             8
eligible_proportion           0.0058
eligible_proportion_of_attempts 0.0055
estimated_eligible_in_population 6197
```

**a) Mostrar com es calcula cada proporció.** D'acord. Quedaria així:

```
eligible_proportion                0.0058 (11/1905)   elegibles / classificats sense error
eligible_proportion_of_attempts    0.0055 (11/2000)   elegibles / tots els intents
```

**b) `estimated_eligible_in_population`.** És respecte a la **població
recorreguda** (`population_scanned`), no a tot Hugging Face. En una
execució completa coincideixen (a `run_8`, 1.068.504 datasets); amb
`--max-scanned` no. Es calcula com `eligible_proportion × population_scanned`
(0,0058 × 1.068.504 ≈ 6.197). D'acord a canviar-ho:

- **Nom explícit:** `estimated_eligible_in_scanned_population`.
- **Per decidir la mida de la mostra, millor la proporció sobre tots els
  intents**, com dius: els inaccessibles i els errors també es perden.

Però el número que realment importa per fixar la mostra és un altre: **quants
datasets acaben comparats**. No tots els elegibles tenen dades tabulars per
comparar:

| `run_8` (mostra de 2.000) | Datasets | Sobre els intents |
|---|---|---|
| Elegibles | 11 | 0,55% |
| Amb alguna taula comparada | 4 | 0,20% |
| Amb algun canvi detectat | 3 | 0,15% |

Els altres 7 elegibles no tenen res a comparar:
- 4 no toquen cap fitxer tabular (per exemple, repositoris d'àudio o
  d'imatge);
- 2 només tenen taules que apareixen o desapareixen senceres entre
  versions;
- 1 té el mateix contingut a les dues versions. **Proposta:** afegir a la sortida la
proporció de datasets comparats sobre els intents i la mida de mostra
necessària per a un objectiu: **mostra ≈ objectiu / proporció**. Amb un
0,20%, per comparar 50 datasets calen uns 25.000 intents. És una estimació
feta amb una sola execució. La proporció d'elegibles varia entre el 0,35% i
el 0,85% segons l'execució (sis execucions de 2.000), així que caldria un
marge.

**c) `eligible` i `eligible_total`.** Són el mateix número: es van afegir des
de dos llocs del codi. Es deixarà només `eligible`.

## 3. D6: quin fitxer

D6 és **`ETdanR/adult_income`**
(`huggingface.co/datasets/ETdanR/adult_income`), versió del 31 de maig de
2025 (commit `780110a`, on es van pujar les dades; després només ha
canviat el README). Té tres fitxers:

| Fitxer | Files |
|---|---|
| `train_data.csv` | 11.208 |
| `validation_data.csv` | 2.240 |
| `experiment_data.csv` | 8.968 |

La frase de l'arquitectura era d'una versió antiga, quan es feia servir
només `train_data.csv`. Ara:

- La targeta diu que és **un sol dataset equilibrat partit en tres
  fitxers**, i per això els comparem **concatenats** (22.416 files: 11.208
  de cada classe d'ingressos).
- Hem provat també cada fitxer per separat: els tres donen exactament els
  mateixos codis.
- Hi ha una branca `refs/convert/parquet` amb un commit de l'agost de 2025.
  És una còpia automàtica de Hugging Face per al visor web, amb les mateixes
  files que els CSV (sense `experiment_data.csv`). No és una versió nova.

Resultat de D6 contra la Taula 1:

- **Coincideixen** C223 (renoms), C422 (s'eliminen files per equilibrar) i
  C530 (canvia la distribució de la classe).
- **El motor marca a més:**
  - C222: `fnlwgt` no hi és;
  - C410: files en ordre aleatori;
  - C421: algunes files vénen d'`adult.test`;
  - C510: no queden valors absents.

  Tots quatre són canvis reals que la targeta no esmenta.

## 4. Validació amb Census Income

Cada versió D1–D7 es compara amb `adult.data` de la UCI (D0), com fa el
paper:

| | Precisió | Recall | Codis del paper trobats |
|---|---|---|---|
| Motor anterior (diferències simples) | 72,0% | 69,2% | 18 de 26 |
| **Motor actual** | 68,4% | **100%** | **26 de 26** |

- **El motor troba tots els canvis que marca el paper.**
- **Calia un motor més complet:** amb diferències simples (noms de columna
  i recompte de files) es perden 8 dels 26 codis. Són canvis de tipus, de
  valors i d'ordre en columnes reanomenades (`sex` → `is_male`, `income` →
  `over_threshold`), que només es troben aparellant les columnes pel
  contingut.
- **Dels 12 codis que el motor marca i el paper no, 11 són canvis reals.**
  - El paper sembla decidir les files comptant-les respecte a
    `adult.data`: menys files → C422 (D3, D4, D6), més files → C421 (D7).
    Però D3, D4 i D6 també contenen files d'`adult.test`, i D7 també
    n'elimina.
  - El paper agafa les etiquetes de la targeta de cada repositori, i
    algunes columnes eliminades no hi surten.
  - El restant (un canvi d'ordre a D7) és un error del motor.

## 5. Joc de proves del nou company

Perquè es pugui fer servir directament, el format més útil és el mateix que
Census Income:

- parells de fitxers (versió antiga i nova);
- la llista de codis esperats per a cada parell, com a
  `tests/fixtures/census_income_labels.csv`.

Així es pot puntuar amb els mateixos scripts. Els casos que més ajudarien
són els que la Taula 1 no cobreix: C322 (canvis numèrics), C520
(correlacions) i C510 quan s'omplen valors absents.

## 6. Què farem

1. A la sortida de l'escaneig: les fórmules al costat de cada proporció, el
   nom `estimated_eligible_in_scanned_population`, treure `eligible_total`,
   i la proporció de datasets comparats amb la mida de mostra necessària.
2. Integrar el joc de proves del nou company quan arribi.

## 7. Preguntes

1. **Mida de la mostra:** quants datasets comparats voldries tenir? Amb la
   proporció actual (0,20% dels intents) es pot calcular la mostra.
2. **Les files de la Taula 1 es van etiquetar comptant-les?** D3, D4 i D6
   també tenen files noves (d'`adult.test`), i D7 també n'elimina.
3. **S'havien d'etiquetar els canvis que la targeta no documenta?** Per
   exemple, `fnlwgt` eliminada a D6 o l'ordre aleatori de D4 i D6.
4. **Codificar categories com a nombres:** C311 + C312 (com a D3/D4) o
   només C312 (com a D7)?
5. **C510 per files eliminades:** seguim el text del paper (es reporta) o
   la taula (no es reporta)?
