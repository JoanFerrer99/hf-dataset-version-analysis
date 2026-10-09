# Reunió: validació del motor amb Census Income

Resum per a la reunió. Els detalls de cada cas són a
`docs/falsos_positius.md` i a `docs/census_income_paper_method.md`.

## 1. Què hem fet

Hem comparat els canvis que detecta el motor amb la **Taula 1 del paper**
(PROFES 2026), que etiqueta a mà 7 versions de Census Income publicades a
Hugging Face (D1–D7) respecte a l'original de la UCI (D0).

## 2. Com va etiquetar el paper

- **D0 és `adult.data`** de la UCI (32.561 files). La UCI també publica
  `adult.test` (16.281 files), i D3, D4, D6 i D7 en contenen files.
- **Columnes i tipus:** les etiquetes surten de la targeta (descripció) de
  cada repositori. Per exemple, D4: "race feature is removed" → C222.
- **Files:** les etiquetes quadren amb **comptar files** respecte a
  `adult.data`: menys files → C422 (D3, D4, D6); més files → C421 (D7).

## 3. Resultat

Comparant totes les versions amb `adult.data`:

| | Precisió | Recall | Codis del paper trobats |
|---|---|---|---|
| Motor anterior (diferències simples) | 72,0% | 69,2% | 18 de 26 |
| **Motor actual** | 68,4% | **100%** | **26 de 26** |

**El motor troba tots els canvis que marca el paper.**

## 4. Per què calia un motor més complet

Amb diferències simples (noms de columna, recompte de files, estadístics)
es reprodueixen les etiquetes de files del paper, perquè el paper també
compta files. Però **es perden 8 dels 26 codis**: canvis de tipus, de valors
i d'ordre en columnes que s'han reanomenat (`sex` → `is_male`, `income` →
`over_threshold`). Per trobar-los cal aparellar les columnes pel contingut,
no pel nom.

## 5. Els 12 falsos positius

Codis que el motor marca i el paper no:

- **11 són canvis reals de les dades** que la targeta no documenta o que
  comptar files no deixa veure:
  - D3, D4 i D6 contenen files d'`adult.test` (C421), però com que en tenen
    menys en total, el recompte només mostra C422;
  - D7 elimina les 2.399 files amb valors absents (C422 i C510), però com
    que té més files en total, el recompte només mostra C421;
  - columnes eliminades que la targeta no esmenta (`education-num` a D3,
    `fnlwgt` a D6) i files desordenades (D4, D6);
  - D7 converteix les categories en nombres: és C311 + C312, com el paper
    marca a D3/D4, però a D7 el paper només hi posa C312.
- **1 és un error del motor:** a D7, 14 files d'`adult.data` amb un valor
  absent són idèntiques en tota la resta a files d'`adult.test`, i el motor
  les aparella i hi veu un canvi d'ordre (C410).

## 6. Altres comprovacions

- **El commit "Update parquet files" (agost de 2025) no és un C421.** El fa
  un bot de Hugging Face en una branca a part per al visor web, i conté
  les mateixes files, en el mateix ordre, que els CSV. És un canvi de format
  (C100), fora d'abast. És del repositori de D6, no de D7.
- **C510 quan s'eliminen files.** El text del paper diu que es reporta
  ("we consider them separately"), però la Taula 1 no ho fa a D6 ni a D7. El
  motor segueix el text.

## 7. Preguntes

1. **Les files es van etiquetar comptant-les?** D3, D4 i D6 també tenen
   files noves (d'`adult.test`), i D7 també n'elimina.
2. **S'havien d'etiquetar els canvis que la targeta no documenta?** Per
   exemple, `fnlwgt` eliminada a D6 o l'ordre aleatori de D4 i D6.
3. **Codificar categories com a nombres:** C311 + C312 (com a D3/D4) o
   només C312 (com a D7)?
4. **C510 per files eliminades:** seguim el text del paper (es reporta) o
   la taula (no es reporta)?
