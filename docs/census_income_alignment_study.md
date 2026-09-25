# Estudi — com afinar la comparativa amb Census Income

> Motivat per una pregunta directa: la comparativa contra el ground
> truth de Census Income actualment no és exacta -- són els diffs la
> millor opció? Com es podria arreglar? Aquest document estudia les
> opcions i en recomana una.
>
> **ACTUALITZACIÓ: l'opció recomanada (1, transcripció manual) ja s'ha
> fet.** Joan ha transcrit a mà la Taula 1 del paper (mirant la imatge
> original) per a D1-D7. La comparativa codi per codi real -- Precisió
> 60.6%, Recall 76.9%, F1 67.8% -- ja està documentada a `docs/
> census_income_validation_report.md`, secció "Comparativa codi per
> codi". Aquest document es manté com a registre de les opcions
> considerades i com a base per als propers passos (secció final).

## És el motor de diffing el problema?

En part sí, en part no -- i val la pena separar-ho:

**Part que SÍ era un problema real, i ja s'ha corregit** (Decisió T-16):
l'heurística de renom de columnes (C223) aparellava columnes per posició
ordinal, que es trencava sistemàticament quan una columna es reordenava o
s'eliminava abans d'una altra de renombrada. Confirmat empíricament sobre
D3 (Census Income): `fnlwgt`->`capital_loss`, `education-num`->
`final_weight` eren aparellaments purament accidentals, sense cap relació
semàntica. Corregit amb aparellament per nom normalitzat -- vegeu `docs/
census_income_validation_report.md`, secció "Bug real trobat i corregit".
Això demostra que SÍ val la pena seguir revisant el motor: no tot el
desajust amb el paper és culpa del ground truth.

**Part que NO és un problema del motor**: la resta del desajust prové
d'una limitació d'integritat de les DADES DE REFERÈNCIA (el ground
truth), no de la tècnica de diffing en si -- vegeu més avall.

## Per què la comparativa no és exacta: el veritable coll d'ampolla

La Taula 1 del paper es va extreure d'un PDF que **no conserva
l'alineació de columnes** d'una taula amb marques "✔" -- només els
totals per fila (per dataset) i per columna (per codi) es poden llegir
amb fiabilitat del text extret. Es pot saber, per exemple, que D3 té 7
marques en total, però NO quines 7 de les 14 columnes són. Aquesta
limitació ja està documentada (`docs/decisions_tfg.txt`, T-08) i és
**estructural**: cap millora del motor de diffing la soluciona, perquè
el problema no és "detectem malament", és "no sabem contra què comparar
codi per codi".

## Opcions per arreglar-ho

1. **Transcriure la Taula 1 a mà des de la imatge original del paper**
   (no el PDF amb text extret, sinó mirant la pàgina/imatge directament).
   És l'ÚNICA manera de tenir un ground truth cel·la a cel·la fiable.
   Trenca l'automatització d'aquest pas concret (és feina manual, no un
   script), però és l'única via real cap a una comparació exacta.
2. **Demanar la taula original a l'autor del paper** (el director). Si
   existeix en un format estructurat (full de càlcul, CSV), evitaria la
   transcripció manual -- val la pena preguntar-ho abans d'assumir que
   cal transcriure-la.
3. **Acceptar el límit i informar sempre per total agregat** -- és
   l'opció ja implementada i documentada honestament (`docs/
   census_income_validation_report.md`). No requereix feina addicional,
   però mai permetrà dir "el nostre motor coincideix amb el paper codi
   per codi en un X%".
4. **Un cop transcrita la taula (opció 1 o 2), construir una matriu de
   confusió real** (codi per codi: vertader positiu / fals positiu / fals
   negatiu per a cadascun dels 14 codis tabulars sobre D1-D7) -- NOMÉS
   possible després de (1) o (2); sense ground truth cel·la a cel·la, una
   matriu de confusió no es pot construir amb integritat (inventar-la
   seria pitjor que no tenir-la).

## Recomanació (no una decisió tancada)

La combinació **(1) o (2) + (4)** és l'única via real cap a "clavar la
comparativa" -- però és feina manual (transcripció) fora de l'abast d'una
sessió de codi, i depèn de si el director té la taula original disponible
(opció 2, més ràpida si existeix) abans de assumir que cal transcriure-la
a mà (opció 1). Mentrestant, l'opció 3 (ja implementada) és l'única
honesta sense aquesta feina prèvia.

**El motor de diffing en si no necessita cap canvi addicional per a
aquest objectiu concret** -- l'única millora pendent identificada
(l'heurística de renom) ja s'ha corregit (T-16). Si en el futur es
transcriu la Taula 1 i la matriu de confusió resultant revela patrons
sistemàtics nous (p.e. un codi concret amb muntes falsos negatius), això
sí que podria motivar revisar altres heurístiques (llindars de `diff_
distribution`/`diff_correlation`, actualment un 5% fix -- vegeu `docs/
taiga/taxonomy.md`, "Tècniques alternatives considerades") -- però no
abans de tenir un ground truth fiable amb què comparar-los.

## Pas pendent (actualitzat)

L'opció 2 (demanar la taula original al director) ha quedat superada --
ja es va transcriure a mà (opció 1). Els passos pendents ara són els que
la comparativa real ha revelat (`docs/census_income_validation_report.md`,
"Comparativa codi per codi"):
1. Investigar per què C312 (valors d'una columna categòrica) mai es
   detecta correctament (0 TP, 3 FN) -- possible llindar massa estricte
   o solapament conceptual amb C530.
2. Investigar per què C221/C322 es sobre-detecten sistemàticament
   (precisió 20% i 0%) -- possible manca de llindar de sensibilitat a
   `diff_numeric_values`, o revisió manual incompleta del propi paper.

Cap d'aquests dos punts s'ha corregit en aquesta sessió -- són candidats
per a un treball futur, un cop es confirmi amb el director si val la pena
prioritzar-los.
