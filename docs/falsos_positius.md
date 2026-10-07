# Falsos positius i preguntes obertes

Aquest document recull, en un sol lloc, tots els casos en què el motor no
coincideix amb la Taula 1 del paper (Census Income) i les preguntes que en
surten. L'estudi complet és a `docs/census_income_paper_method.md`.

## Com es mesura

Cada versió D1–D7 es compara amb **D0 = `adult.data`** de la UCI (32.561
files), i la llista de codis del motor es contrasta amb la Taula 1:

- **Fals positiu (FP):** el motor marca un codi que el paper no marca.
- **Fals negatiu (FN):** el paper marca un codi que el motor no troba.

Resultat: **26 encerts, 12 FP i 0 FN** (precisió 68,4%, recall 100%). El
motor troba tots els canvis que marca el paper.

## Com va etiquetar el paper

El paper diu que va etiquetar combinant la **targeta** de cada repositori
(la descripció que hi posa l'autor) amb una **inspecció manual**:

- **Columnes i tipus:** les etiquetes surten de la targeta. Per exemple, D4
  diu "race feature is removed" (C222), D5 "adding two new columns" (C221) i
  D6 "balanced version" (C530).
- **Files:** les etiquetes quadren amb **comptar files** respecte a
  `adult.data`:

| Versió | Files | Respecte a les 32.561 d'`adult.data` | Taula 1 |
|---|---|---|---|
| D1, D2, D5 | 32.561 | igual | ni C421 ni C422 |
| D3, D4 | 12.211 | menys | C422 |
| D6 | 22.416 | menys | C422 |
| D7 | 45.222 | més | C421 |

El motor, en canvi, mira **quines** files són, no quantes n'hi ha. Per això
troba canvis que la targeta no esmenta i que el recompte no mostra.

## Els 12 falsos positius, un per un

| Versió | El motor diu | Què hi ha a les dades | Tipus |
|---|---|---|---|
| D3 | C421: s'afegeixen files | 3.534 files (29%) no són a `adult.data`: vénen d'`adult.test`. Com que D3 té menys files en total, el recompte només mostra C422 | Canvi real que el recompte amaga |
| D4 | C421: s'afegeixen files | Igual que D3 | Canvi real que el recompte amaga |
| D6 | C421: s'afegeixen files | Part de les files vénen d'`adult.test` | Canvi real que el recompte amaga |
| D3 | C222: s'elimina `education-num` | L'autor del repositori esborra la columna `education` (text) i posa `education-num` amb el nom `education` | Canvi real no documentat |
| D6 | C222: s'elimina `fnlwgt` | La columna no hi és | Canvi real no documentat |
| D4 | C410: canvia l'ordre de files | Files en ordre aleatori. D3 ve del mateix repositori i allà el paper sí que marca C410 | La taula no és coherent |
| D6 | C410: canvia l'ordre de files | Files en ordre aleatori | Canvi real no documentat |
| D7 | C410: canvia l'ordre de files | D7 conserva l'ordre d'`adult.data`. 14 files d'`adult.data` amb un `?` s'aparellen amb files d'`adult.test` idèntiques en tota la resta | **Error del motor** (indecidible amb les dades) |
| D7 | C422: s'eliminen files | S'eliminen les 2.399 files d'`adult.data` que tenien algun `?` | Canvi real que el recompte amaga (D7 té més files en total) |
| D6 | C510: canvien els valors absents | Abans hi havia `?` a 3 columnes; ara no n'hi ha cap | Canvi real; vegeu més avall |
| D7 | C510: canvien els valors absents | Igual que D6 | Canvi real; vegeu més avall |
| D7 | C311: canvia el tipus de les categòriques | Totes les columnes de text passen a ser nombres (codificació). A D3/D4 el paper marca C311 i C312 pel mateix canvi; a D7 només C312 | La taula no és coherent |

**En resum:** 11 dels 12 són canvis reals de les dades que la targeta no
documenta o que comptar files no deixa veure. Només un (C410 a D7) és un
error del motor.

## C510 quan s'eliminen files (D6 i D7)

**Què passa a les dades.** A `adult.data` hi ha valors absents (`?`) a tres
columnes: `workclass` (5,6% de les files), `occupation` (5,7%) i
`native-country` (1,8%). A D6 i D7 no n'hi ha cap. Cap valor absent s'ha
omplert: les files que en tenien s'han eliminat senceres.

**Per què el motor marca C510.** El paper defineix C510 com "the
presence/absence of missing values in the columns" (§4). Les columnes
passen de *tenir* valors absents a *no tenir-ne*. El paper també diu que
aquests canvis "can be a consequence of the addition/removal of rows.
However, we consider them separately". Per a un pipeline és rellevant: el
pas d'imputar valors absents deixa de fer falta.

**Per què el paper no el marca.** A D7 tampoc no marca C422: com que D7 té
més files que `adult.data`, comptant files no es veu que se n'han eliminat.
La targeta de D6 parla de l'equilibri de classes, però no dels valors
absents.

## Per què ara sí que apareix C421 a D7

D7 té 45.222 files: les 30.162 d'`adult.data` sense `?` i, a continuació,
les 15.060 d'`adult.test` sense `?` (la fila 30.162 de D7 és la primera
d'`adult.test`). Comparada amb `adult.data`, té **15.046 files noves**:
C421, com el paper.

Durant l'estudi, D3, D4, D6 i D7 es van comparar amb `adult.data` +
`adult.test` junts, perquè les seves files surten de totes dues
publicacions. Amb aquella D0, D7 no tenia cap fila nova i el C421 no
apareixia. Ara D0 és `adult.data` per a totes les versions, com al paper.

## El commit de la branca `refs/convert/parquet` (agost de 2025)

El commit `792da71` ("Update parquet files", autor `parquet-converter`) és
del repositori `ETdanR/adult_income`, que és **D6, no D7**. No s'ha de
detectar com a C421:

- **El fa un bot de Hugging Face, no l'autor.** Hugging Face crea
  automàticament aquesta branca per al visor web: converteix els fitxers a
  parquet. Té un sol commit, sense cap commit anterior ("0 Parent(s)"), i
  no hi ha cap versió anterior amb què comparar.
- **No afegeix cap fila.** `default/train/0000.parquet` té exactament les
  mateixes 11.208 files, en el mateix ordre, que `train_data.csv`, i
  `default/validation/0000.parquet` les mateixes 2.240 que
  `validation_data.csv`. És la mateixa dada en un altre format: seria C100
  (format de fitxer), que és fora d'abast.
- **Ni tan sols és completa.** El bot deixa fora `experiment_data.csv`,
  perquè "experiment" no és un nom de partició que reconegui. A D7, la
  branca parquet conté `adult_meta.json` (una fila de metadades) en lloc de
  les dades.

Per això el pipeline només mira les branques de l'autor (`main` i les que
creï) i no les branques `refs/convert/*` del bot.

## Calia un motor tan complet?

Comparació amb les **mateixes dades** i la mateixa D0 (`adult.data`):

| | Precisió | Recall | F1 | Codis del paper trobats |
|---|---|---|---|---|
| Motor antic (diferències simples: noms de columna, recompte de files, estadístics) | 72,0% | 69,2% | 70,6% | 18 de 26 |
| Motor actual | 68,4% | 100% | 81,3% | 26 de 26 |

- **El motor antic coincideix amb el paper en les files perquè fa el
  mateix que el paper: compta files.** Per això no veu les files
  d'`adult.test` a D3/D4/D6 ni les eliminades a D7.
- **Però perd 8 dels 26 codis del paper:** canvis de tipus i de valors
  (C311, C312) i d'ordre (C210, C410) a D3/D4, i el C312 de D7. Per
  detectar-los cal aparellar les columnes pel contingut, perquè estan
  reanomenades (`sex` → `is_male`, `income` → `over_threshold`).
- **Els seus FP són errors:** una columna reanomenada de manera no
  evident surt com a afegida (C221 a D3, D4, D6 i D7) i eliminada (C222 a
  D3 i D6). Els FP del motor actual són, gairebé tots, canvis reals.

Per tant, per reproduir la Taula 1 n'hi hauria prou amb comptar files, però
no per trobar tots els canvis que hi ha: amb diferències simples es perd
gairebé un terç dels codis del paper.

## Respostes a les notes sobre les decisions

- **U1 (els fitxers d'un mateix split són un sol dataset): confirmada.**
- **U2 (una taula que apareix sencera no és C421): el FN de D7 no venia
  d'aquí,** sinó de la definició de D0 (secció anterior).
- **U4 (límit de 500 MB per taula): no afecta Census Income.** El límit
  només s'aplica al pipeline, i el fitxer més gran de Census fa 4,1 MB.

## Preguntes per al director

1. **Les files es van etiquetar comptant-les?** La Taula 1 quadra amb
   comparar el nombre de files amb `adult.data`. Però D3, D4 i D6 també
   contenen files d'`adult.test` (C421), i D7 n'elimina 2.399 (C422).
2. **S'havien d'etiquetar els canvis que la targeta no documenta?** Per
   exemple, `fnlwgt` eliminada a D6, `education-num` eliminada a D3, o
   l'ordre aleatori de D4 i D6.
3. **Mateix canvi, codis diferents.** Codificar categories com a enters és
   C311 + C312 a D3/D4 i només C312 a D7. Quin és el criteri?
4. **C510 per files eliminades.** El text del paper diu que es reporta;
   la taula no ho fa a D6 ni a D7. El motor segueix el text: és correcte?
