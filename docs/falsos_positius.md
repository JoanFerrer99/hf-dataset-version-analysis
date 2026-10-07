# Falsos positius i preguntes obertes

Aquest document recull, en un sol lloc, tots els casos en què el motor no
coincideix amb la Taula 1 del paper (Census Income) i les preguntes que en
surten. L'estudi complet és a `docs/census_income_paper_method.md`.

## Com es mesura

Per a cada versió D1–D7 de Census Income, es compara la llista de codis que
dona el motor amb la que marca la Taula 1 del paper:

- **Fals positiu (FP):** el motor marca un codi que el paper no marca.
- **Fals negatiu (FN):** el paper marca un codi que el motor no troba.

Resultat actual: **25 encerts, 8 FP i 1 FN** (precisió 75,8%, recall 96,2%).

## D'on venen les etiquetes del paper

El paper explica que va etiquetar combinant la **targeta** de cada
repositori (la descripció que hi posa l'autor) amb una **inspecció manual**.
Hem comprovat que gairebé totes les etiquetes de la Taula 1 surten de la
targeta. Per exemple, la de D4 diu "race feature is removed" (C222), la de
D5 "adding two new columns" (C221) i la de D6 "balanced version" (C530).

En canvi, el motor compara les dades directament. Per això troba canvis que
hi són però que la targeta no esmenta. Aquesta és la causa de gairebé tots
els desacords.

## Els 9 desacords, un per un

| Versió | El motor diu | El paper diu | Què hi ha a les dades | Tipus |
|---|---|---|---|---|
| D3 | C222: s'elimina `education-num` | — | L'autor del repositori esborra la columna `education` (text) i posa `education-num` amb el nom `education` | Canvi real no documentat |
| D4 | C410: canvia l'ordre de files | — | Les files estan en ordre aleatori. D3 ve del mateix repositori i amb el mateix procés, i allà el paper sí que marca C410 | La taula no és coherent |
| D6 | C222: s'elimina `fnlwgt` | — | La columna no hi és | Canvi real no documentat |
| D6 | C410: canvia l'ordre de files | — | Les files estan en ordre aleatori | Canvi real no documentat |
| D6 | C510: canvien els valors absents | — | Abans hi havia `?` a 3 columnes; ara no n'hi ha cap | Canvi real; vegeu la secció següent |
| D7 | C510: canvien els valors absents | — | Igual que D6 | Canvi real; vegeu la secció següent |
| D7 | C422: s'eliminen files | — | S'eliminen les 3.620 files que tenien algun `?` | Canvi real no documentat |
| D7 | C311: canvia el tipus de les categòriques | Només C312 | Totes les columnes de text passen a ser nombres (codificació). A D3/D4 el paper hi marca C311 i C312 pel mateix canvi | La taula no és coherent |
| D7 | — (FN) | C421: s'afegeixen files | Depèn de amb què es compari; vegeu més avall | Definició de D0 |

**En resum:** cap desacord és un error del motor. Sis són canvis reals que
la targeta no explica, i tres són casos en què la taula no aplica el mateix
criteri a dues versions equivalents.

## C510 quan s'eliminen files (D6 i D7)

**Què passa a les dades.** A la versió original (D0) hi ha valors absents
(`?`) a tres columnes: `workclass` (5,7% de les files), `occupation` (5,8%) i
`native-country` (1,8%). A D6 i D7 no n'hi ha cap. Hem comprovat que cap
valor absent s'ha omplert: les files que en tenien s'han eliminat senceres.

**Per què el motor marca C510.** El paper defineix C510 com "the
presence/absence of missing values in the columns" (§4). Aquí les columnes
passen de *tenir* valors absents a *no tenir-ne*. El paper també diu que
aquests canvis "can be a consequence of the addition/removal of rows.
However, we consider them separately". Per a un pipeline, el canvi és
rellevant: el pas d'imputar valors absents deixa de fer falta.

**Per què el paper no el marca.** A D7, el paper tampoc no marca C422, i
s'hi eliminen 3.620 files: els autors no van veure aquesta eliminació, i
per tant tampoc el canvi de nuls que comporta. La targeta de D6 parla de
l'equilibri de classes, però no dels valors absents.

**Decisió presa:** seguir el text del paper i mantenir C510. Una versió
anterior del motor l'amagava per coincidir amb la taula (decisió P12); es
va retirar.

## Per què no apareix C421 a D7

**C421 vol dir "s'afegeixen files a una taula que ja existia".**

**1. A la validació de Census Income.** D7 té 45.222 files. Totes són de
la UCI: són les 48.842 files de `adult.data` + `adult.test` menys les 3.620
que tenen `?`.

- Si D0 és només `adult.data` (32.561 files), D7 té 15.060 files noves
  (les de `adult.test`), i el motor marcaria C421 com el paper.
- Si D0 és la UCI completa (les dues), D7 no té cap fila nova: només n'ha
  perdut (C422).

Comparem cada versió amb la publicació de la UCI de la qual surten les
seves files. D3, D4, D6 i D7 barregen les dues publicacions, i per tant D0
és la UCI completa. Amb aquest criteri, el C421 de D7 no hi és. És un
desacord de definició, no d'error. Si es comparés amb `adult.data`, el C421
de D7 apareixeria, però D3 i D4 passarien a tenir un C421 que el paper no
marca (també tenen files de test).

**2. El commit de la branca `refs/convert/parquet` (agost de 2025).** El
commit de la captura (`792da71`, "Update parquet files", autor
`parquet-converter`) és del repositori `ETdanR/adult_income`, que és
**D6, no D7**. No s'ha de detectar com a C421:

- **El fa un bot de Hugging Face, no l'autor.** Hugging Face crea
  automàticament aquesta branca per al visor web: converteix els fitxers del
  dataset a parquet. Té un sol commit, sense cap commit anterior ("0
  Parent(s)"), i per tant no hi ha cap versió anterior amb què comparar.
- **No afegeix cap fila.** Hem comparat els fitxers:
  `default/train/0000.parquet` té exactament les mateixes 11.208 files, en
  el mateix ordre, que `train_data.csv`, i `default/validation/0000.parquet`
  les mateixes 2.240 que `validation_data.csv`. És la mateixa dada en un
  altre format: seria C100 (format de fitxer), que és fora d'abast.
- **Ni tan sols és completa.** El bot no inclou `experiment_data.csv`,
  perquè "experiment" no és un nom de partició que reconegui. A D7, la
  branca parquet conté `adult_meta.json` (una fila de metadades) en lloc de
  les dades.

Per això el pipeline només mira les branques de l'autor (`main` i les que
creï) i no les branques `refs/convert/*` del bot. Si les mirés, compararia
cada dataset amb una còpia d'ell mateix en un altre format, o amb una part.

## Respostes a les notes sobre les decisions

- **U1 (els fitxers d'un mateix split són un sol dataset): confirmada.**
- **U2 (una taula que apareix sencera no és C421): el FN de D7 no ve
  d'aquí.** La validació de Census compara dos fitxers directament i no fa
  servir l'aparellament de taules on s'aplica U2. El FN ve de la definició
  de D0 (secció anterior).
- **U4 (límit de 500 MB per taula): no afecta Census Income.** El límit
  només s'aplica al pipeline, i el fitxer més gran de Census fa 4,1 MB.
  Tots es descarreguen i es comparen sencers.

## Preguntes per al director

1. **Amb quina D0 es va comparar cada versió?** D1, D2 i D5 són còpies
   d'`adult.data`, però D3, D4, D6 i D7 contenen també files d'`adult.test`.
   Amb `adult.data`, D7 té C421 (com a la taula) però D3 i D4 també en
   tindrien.
2. **S'havien d'etiquetar els canvis que la targeta no documenta?** Per
   exemple, `fnlwgt` eliminada a D6, files amb `?` eliminades a D7, o
   l'ordre aleatori de D4 i D6.
3. **Mateix canvi, codis diferents.** Codificar categories com a enters és
   C311 + C312 a D3/D4 i només C312 a D7. Quin és el criteri?
4. **C510 per files eliminades.** El text del paper diu que es reporta;
   la taula no ho fa a D6 ni a D7. El motor segueix el text: és correcte?
