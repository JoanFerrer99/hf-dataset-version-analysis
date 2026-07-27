# Tècniques aprofitables de "How do Machine Learning Models Change?" (Castaño et al., 2025)

> Anàlisi del paper adjuntat (Castaño, Cabañas, Salmerón, Lo, Martínez-Fernández —
> arXiv:2411.09645) per extreure tècniques reutilitzables per a aquest TFG.
> **Important**: el paper estudia com canvien **models** de ML a Hugging Face
> (via commits/releases), no **datasets**. L'objecte d'estudi és diferent,
> però la infraestructura (mateixa plataforma HF, mateix `HfApi`, mateix
> mecanisme de commits/tags/branches) i diverses decisions metodològiques
> són directament transferibles. Aquest document només recull el que és
> vàlid reaprofitar; no repeteix el contingut del paper que no aplica aquí
> (BNs/DBNs sobre seqüències de canvi, anàlisi de metadades de pesos de
> model, etc. — fora d'abast d'aquest TFG).

## 1. Categorització per interval temporal entre commits — valida el fix del Criteri B

**El que fan (secció 4.3.2, RQ1.2)**: classifiquen cada interval entre
commits consecutius en 4 categories basades en la distribució real
observada (no llindars arbitraris): `<1h` (87.8% dels 680.966 commits!),
`1h-1dia` (8.0%), `1dia-1setmana` (2.1%), `>1setmana` (2.1%). Troben que
els commits `<1h` representen "very rapid, potentially automated, or
near-continuous development activity", mentre que els separats per
`>1setmana` reflecteixen actualitzacions "batched" i deliberades.

**Per què és rellevant aquí**: és exactament la mateixa lògica que motiva
la proposta de revisió del Criteri B a
`docs/criterion_b_time_dispersion_proposal.md` (branca
`feature/criterion-b-time-dispersion`): commits molt junts en el temps
solen ser una única sessió automàtica, no versions diferenciades. El fet
que un estudi independent, sobre >680K commits reals de HF (encara que de
models, no datasets), arribi a la mateixa conclusió qualitativa (que
"junt en el temps" ≈ "mateixa sessió, no maduresa/versió real") és
evidència externa a favor de l'enfocament triat per a US-108, no només
una intuïció pròpia sobre els 13 casos observats.

**Diferència a tenir en compte**: ells fan servir aquesta categorització
per a *anàlisi descriptiva* (com varien els tipus de commit segons
l'interval), no per decidir *elegibilitat*. El nostre ús (llindar dur
per excloure/incloure un dataset) és més estricte. La seva distribució
empírica (87.8% de commits en <1h) també suggereix que un llindar d'1h
és probablement massa baix per capturar sessions completes — consistent
amb el que ha mostrat la nostra pròpia anàlisi de sensibilitat (1h només
filtra 3/8 falsos positius; calen 24-48h per filtrar-ne 7-8/8).

## 2. Clonat "bare" de Git + `git show --name-only` — tècnica directa per US-301/US-302

**El que fan (secció 4.2.1)**: per obtenir la llista real de fitxers
modificats en cada commit (informació que l'API de HF no sempre exposa
completa), clonen temporalment cada repositori amb `git clone --bare
--filter=blob:none` (bare clone, sense checkout, amb filtratge de blobs
per eficiència) i executen `git show --name-only <sha>` per cada commit
obtingut via l'API de HF.

**Per què és rellevant aquí**: **US-301** ("Investigar si
`commit.files`/`commit.changed_files` és accessible a la versió
instal·lada de `huggingface_hub`") és exactament el problema que
resolen. Si la investigació de US-301 confirma que `huggingface_hub` NO
exposa la llista de fitxers per commit (com sospitava la user story
original), aquesta és la solució ja validada per un altre equip sobre el
mateix tipus de repositoris (HF): no cal descarregar el contingut dels
fitxers, només clonar en mode bare+blob-filtered (ràpid, poc espai) i
cridar `git show --name-only`. Directament aplicable a **US-302**
(detecció real de fitxers modificats, actualment basada només en
l'heurística de títol `is_substantive_commit`).

**Cost/limitació que ells mateixos reporten**: ho apliquen a una mostra
de 100K models; per a la nostra població elegible (desenes-centenars de
datasets, no 950K) el cost és molt més baix i, per tant, encara més
viable que per a ells.

## 3. Exclusió d'outliers amb activitat massiva — paral·lel amb el patró LeRobot

**El que fan (secció 4.2.1)**: exclouen explícitament repositoris amb
>500 commits de l'anàlisi agregada principal, "to ensure the
representativeness of typical development practices and mitigate the
skewing effect of outlier repositories with an exceptionally high number
of commits (e.g., automated or bulk updates)".

**Per què és rellevant aquí**: és conceptualment el mateix problema que
el patró LeRobot identificat a US-108 (eines automàtiques que generen
desenes de commits en una sola sessió). Ells ho resolen amb un llindar
absolut de recompte de commits (>500); nosaltres ho abordem amb dispersió
temporal (Secció 1 d'aquest document / proposta del Criteri B). Són
tècniques complementàries, no excloents: es podria considerar, com a
guarda addicional de baix cost, descartar (o marcar per revisió manual)
qualsevol dataset amb un nombre de commits extremadament alt en un
interval curt, encara que passi el criteri de dispersió temporal amb un
únic parell de commits llunyans (cas no cobert explícitament per la
proposta actual, que només mira `min`/`max` de les dates).

## 4. Classificació amb LLM + validació humana rigorosa — metodologia per a l'Epic 3 (taxonomia)

**El que fan (secció 4.2.2 i Fig. 4)**: per classificar cada commit
segons la seva taxonomia (15 categories ML-específiques), fan servir un
procés en dues fases:

1. **Refinament del prompt (entrenament)**: mostra curada de 143 commits,
   codificada per 2 anotadors independents (IRR verificat amb Cohen's
   Kappa), consens per resoldre discrepàncies → ground truth. Iteren el
   prompt 6 vegades fins passar de Kappa=0.1765 (prompt inicial) a
   Kappa=0.9068 (acord LLM-humans).
2. **Test final (generalització)**: mostra independent de 384 commits
   (mida calculada amb la mateixa fórmula estadística que ja fem servir
   a `docs/README.md` per a la mida de mostra, 95% CI, marge d'error 5%),
   amb el mateix procés de doble anotació + Kappa (0.8150 entre humans,
   0.8568 LLM-vs-humans) per confirmar que el prompt no estava
   sobreajustat a l'entrenament.
3. Validació automàtica final (format JSON correcte, sense duplicats).

**Per què és rellevant aquí**: aquesta és exactament la metodologia que
caldrà per a **US-303/US-305** (classificar els canvis detectats segons
els 15 codis C100-C530 de `docs/taiga/taxonomy.md`). En comptes
d'inventar un procés de validació des de zero, es pot adaptar
directament:
- Fer servir un LLM (p.e. Gemini Flash o equivalent) amb un prompt
  iteratiu, mesurant Cohen's Kappa contra una mostra petita codificada
  per Joan (i, si es pot, un segon anotador) abans d'escalar.
- Reutilitzar el mateix marc estadístic ja emprat per a la mida de
  mostra de US-107 per dimensionar un conjunt de test de validació de la
  classificació (Epic 3), en lloc d'una mida arbitrària.
- **Nota de disseny important del seu prompt** (Fig. 4, "Core
  Principles"): "Ignore standard platform boilerplate (e.g., 'with
  huggingface_hub') for classification purposes" i "Use Unknown for
  commits with an unclear purpose... Do not guess." — dues regles
  directament aplicables (vegeu Secció 6 d'aquest document).

## 5. Estructura de "Threats to Validity" — plantilla per a la memòria

**El que fan (secció 7)**: separen les amenaces a la validesa en 5
categories estàndard (Construct, Conclusion, Internal, External,
Reliability), cadascuna amb la mitigació concreta aplicada. Per exemple,
a "External Validity" reconeixen explícitament que el domini de HF està
esbiaixat cap a NLP i que els seus resultats de releases només
representen models amb tags Git explícits (1.655 de >1,6M models).

**Per què és rellevant aquí**: `docs/decisions_tfg.txt` ja identifica
riscos (R-01, R-02, R-03) però no els organitza en aquesta estructura
formal de 5 categories. És una plantilla directa per a la secció
"Amenaces a la validesa" de la memòria del TFG, i encaixa amb amenaces ja
conegudes del nostre propi estudi: p.e. `eligible_proportion_of_attempts`
(vegeu `compute_funnel_stats` a `eligibility_scan.py`) assumeix que els
datasets amb accés restringit/error tenen elegibilitat similar als
classificables — una amenaça de Construct/Conclusion Validity anàloga a
les que ells discuteixen.

## 6. Exclusió de "boilerplate" de plataforma — alternativa/complement al fix del Criteri B

**El que fan**: el seu prompt de classificació instrueix explícitament
al LLM a ignorar missatges genèrics de la plataforma (`"with
huggingface_hub"`) a l'hora de classificar, i defineixen una categoria
pròpia "Sharing" precisament per a aquest tipus de commits (`"Upload
folder using huggingface_hub"`), separant-la d'altres tipus de canvi
reals.

**Per què és rellevant aquí**: `is_substantive_commit()`
(`notebooks/eligibility_scan.py`) ja exclou paraules clau de
manteniment/documentació (`readme`, `typo`, `license`...) però **no**
exclou explícitament els títols "boilerplate" generats per eines
automàtiques de pujada com `"Upload folder using huggingface_hub"` o
`"Delete folder using huggingface_hub"` — exactament els títols que
dominen el patró LeRobot identificat a US-108. Afegir aquests patrons a
`NON_SUBSTANTIVE_TITLE_KEYWORDS` seria un canvi encara més petit que la
dispersió temporal (una línia, sense tocar la lògica de `classify_dataset`)
i probablement complementari: filtraria el soroll a l'origen en lloc de
confiar només en la separació temporal. **No implementat encara** —
val la pena avaluar-lo com a alternativa o complement a la proposta de
`docs/criterion_b_time_dispersion_proposal.md` abans de triar un enfocament
definitiu.

## Resum: prioritzat i referenciat a les user stories existents

| Tècnica | User story relacionada | Estat |
|---|---|---|
| Dispersió temporal entre commits substantius | US-108 (validació), Criteri B | Proposta implementada a `feature/criterion-b-time-dispersion` |
| Exclusió de títols "boilerplate" (`"Upload folder using huggingface_hub"`) | US-108, Criteri B | Idea, no implementada — avaluar com a alternativa/complement |
| Bare clone + `git show --name-only` per fitxers reals per commit | US-301, US-302 | Tècnica validada externament, pendent d'aplicar |
| Exclusió d'outliers per volum de commits | US-302 (relacionat) | Idea, no implementada |
| LLM + validació humana (Kappa) per a la taxonomia de 15 codis | US-303, US-304, US-305 | Metodologia de referència, pendent d'adoptar quan comenci l'Epic 3 |
| Estructura de 5 categories per "Threats to Validity" | Memòria del TFG (transversal) | Plantilla directa, pendent d'aplicar a la redacció |
