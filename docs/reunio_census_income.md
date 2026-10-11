# Reunió: resposta al feedback i estat de la validació

Resposta als dos correus i resum de l'estat del treball. Els detalls són a
`docs/validacio_census_income.md` i `docs/engine.md`.

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

## 2. L'escaneig d'elegibilitat: què hem canviat

**a) Les fórmules.** Afegides a `architecture.md` (secció 7.4), amb
l'exemple de `run_8`:

```
eligible_proportion                0.0058 (11/1905)   elegibles / classificats sense error
eligible_proportion_of_attempts    0.0055 (11/2000)   elegibles / tots els intents
```

**b) Només compten els datasets tabulars.** El problema de fons de
l'estimació era que molts elegibles no tenien res per comparar. A `run_8`:

| `run_8` (mostra de 2.000) | Datasets | Sobre els intents |
|---|---|---|
| Elegibles | 11 | 0,55% |
| Amb alguna taula comparada | 4 | 0,20% |
| Amb algun canvi detectat | 3 | 0,15% |

Dels 7 elegibles sense res a comparar, 4 no tocaven cap fitxer tabular
(repositoris d'àudio, d'imatge...), 2 només tenien taules que apareixien o
desapareixien senceres, i 1 tenia el mateix contingut a les dues versions.

Per això ara **un commit només compta per a l'elegibilitat si toca un
fitxer de dades tabular** (`.parquet`, `.csv`, `.tsv`, `.json`, `.jsonl`),
amb la mateixa definició que fa servir el motor. Un dataset de vídeo o
d'àudio ja no és elegible. Com a informació complementària, el report
porta per a cada dataset la proporció de fitxers de dades que són tabulars
(`tabular_file_share`), però no decideix res.

**c) L'estimació, sobre tots els intents.** Ara és:

- `estimated_eligible_in_scanned_population` = elegibles / tots els intents
  × població recorreguda. El nom diu que és la població **recorreguda**
  (que coincideix amb tot Hugging Face només si no s'ha fet servir
  `--max-scanned`).
- `attempts_per_eligible` = tots els intents / elegibles. **És el número
  per fixar la mostra**: per tenir N datasets elegibles cal una mostra
  d'unes N × `attempts_per_eligible`. Els inaccessibles, els errors i els no
  elegibles hi queden inclosos.

Amb `run_8` (criteri antic): 2.000 / 11 = 181,8 intents per elegible. Amb
el criteri tabular, cada elegible té dades per comparar, però la proporció
serà més baixa. Una nova execució de la Fase 0 ho dirà; la proporció
d'elegibles ja variava entre el 0,35% i el 0,85% segons l'execució (sis
execucions de 2.000), així que caldrà un marge.

**d) `eligible` i `eligible_total`.** Eren redundants: valien sempre el
mateix, perquè tots dos eren el nombre de files amb `eligible = True` del
report. Hi eren per com havia crescut el codi:

- **`eligible`** (juliol) forma part de l'**embut**. Amb `ineligible`,
  `access_restricted` i `errors` suma la mida de la mostra (a `run_8`:
  11 + 1.894 + 87 + 8 = 2.000), i és el numerador de les proporcions.
- **`eligible_total`** (setembre) es va afegir en crear l'orquestrador
  (`run_pipeline.py`), que el llegia per saber si calia executar les
  Fases 1 i 2, i es va posar al costat del desglossament per criteri
  (`eligible_Criteri_A` + `eligible_Criteri_B`: a `run_8`, 4 + 7 = 11).

Ara només hi ha `eligible`, i l'orquestrador llegeix aquest camp.

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

## 6. Què queda per fer

1. Una nova execució de la Fase 0 amb el criteri tabular, per tenir la
   proporció d'elegibles i `attempts_per_eligible` reals.
2. Integrar el joc de proves del nou company quan arribi.

## 7. Preguntes

1. **Mida de la mostra:** quants datasets comparats voldries tenir? Amb
   `attempts_per_eligible` es pot calcular la mostra.
2. **Les files de la Taula 1 es van etiquetar comptant-les?** D3, D4 i D6
   també tenen files noves (d'`adult.test`), i D7 també n'elimina.
3. **S'havien d'etiquetar els canvis que la targeta no documenta?** Per
   exemple, `fnlwgt` eliminada a D6 o l'ordre aleatori de D4 i D6.
4. **Codificar categories com a nombres:** C311 + C312 (com a D3/D4) o
   només C312 (com a D7)?
5. **C510 per files eliminades:** seguim el text del paper (es reporta) o
   la taula (no es reporta)?
