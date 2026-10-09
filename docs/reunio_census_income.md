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

**c) `eligible` i `eligible_total`.** Sí, són redundants: valen sempre el
mateix, perquè tots dos són el nombre de files amb `eligible = True` del
report. Hi són per com ha crescut el codi, no perquè signifiquin coses
diferents:

- **`eligible`** (juliol) forma part de l'**embut**. Amb `ineligible`,
  `access_restricted` i `errors` suma la mida de la mostra (a `run_8`:
  11 + 1.894 + 87 + 8 = 2.000), i és el numerador de les dues proporcions.
- **`eligible_total`** (setembre) es va afegir en crear l'orquestrador
  (`run_pipeline.py`), que el llegeix per saber si cal executar les Fases 1
  i 2 (si és 0, s'aturen). També es va posar al costat del desglossament
  per criteri: `eligible_Criteri_A` + `eligible_Criteri_B` (a `run_8`,
  4 + 7 = 11).

**Què farem:** deixar només `eligible`, fer que l'orquestrador llegeixi
aquest camp, i mantenir el desglossament per criteri amb la suma explícita
(`11 = 4 (A) + 7 (B)`).

## 3. D6: quin fitxer i què hi ha

**Quin dataset és.** D6 és **`ETdanR/adult_income`**
(`huggingface.co/datasets/ETdanR/adult_income`). Té tres commits, tots del
31 de maig de 2025: el commit inicial, la pujada de les dades (`780110a`) i
un canvi al README. Fem servir `780110a`.

**Què diu la targeta.** "A balanced version of the UCI Adult dataset, split
into training, validation, and test sets". La van preparar per a un
projecte d'atacs adversaris sobre models tabulars.

**Els tres fitxers.** Cada fitxer està equilibrat al 50% entre les dues
classes d'ingressos:

| Fitxer | Files | `>50K` | `<=50K` |
|---|---|---|---|
| `train_data.csv` | 11.208 | 5.604 | 5.604 |
| `validation_data.csv` | 2.240 | 1.120 | 1.120 |
| `experiment_data.csv` | 8.968 | 4.484 | 4.484 |
| **Total** | **22.416** | **11.208** | **11.208** |

**Com es va construir** (deduït de les dades):

- Parteix de la **UCI completa** (`adult.data` + `adult.test`), sense les
  files amb valors absents: 45.222 files, de les quals exactament **11.208
  són `>50K`**, el mateix nombre que té D6. Per tant, D6 conté totes les
  files `>50K` i el mateix nombre de files `<=50K` triades, i després les
  reparteix en tres fitxers.
- Té files d'`adult.test`: 2.147 combinacions de valors de D6 només
  existeixen a `adult.test`.
- **No té `fnlwgt`** i fa servir altres noms: `educational-num` en lloc
  d'`education-num` i `gender` en lloc de `sex`. Aquests noms coincideixen
  amb la versió de l'Adult que circula a Kaggle (`adult.csv`, 48.842
  files), i probablement en parteix.
- No té cap valor absent (`?`).

**Per què l'arquitectura parlava de "tres fitxers candidats".** El paper
només dona la URL del repositori. El motor anterior comparava només
`train_data.csv`, i no sabíem si el paper havia fet servir aquest, un altre
o tots tres. Ara:

- comparem **els tres concatenats**, perquè la targeta diu que són un sol
  dataset partit;
- hem provat també cada fitxer per separat (`experiments/census_variants/`):
  els tres donen **exactament els mateixos codis**, així que la tria no
  canvia el resultat.

**La branca `refs/convert/parquet`.** Té un commit de l'agost de 2025
("Update parquet files"). És una còpia automàtica que fa Hugging Face per
al visor web: conté les mateixes files, en el mateix ordre, que
`train_data.csv` i `validation_data.csv`, i no inclou `experiment_data.csv`
("experiment" no és un nom de partició que reconegui). No és una versió
nova del dataset.

**Resultat de D6 contra la Taula 1**, comparant amb `adult.data`:

| Codi | Taula 1 | Motor | Què hi ha a les dades |
|---|---|---|---|
| C223 | sí | sí | Renoms: `educational-num`, `gender` |
| C422 | sí | sí | S'eliminen files: en queden 22.416 de 32.561, per equilibrar classes |
| C530 | sí | sí | La distribució de la classe passa de 24% `>50K` a 50% |
| C222 | — | sí | `fnlwgt` no hi és |
| C410 | — | sí | Les files estan en ordre aleatori |
| C421 | — | sí | Hi ha files d'`adult.test` |
| C510 | — | sí | Els valors absents de `workclass`, `occupation` i `native-country` desapareixen |

Els tres codis de la taula surten de la targeta ("balanced"); els quatre
que només marca el motor són canvis reals que la targeta no esmenta.

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
