# US-108 — Validació manual dels 13 datasets elegibles (execució de referència)

> **Estat: primer esborrany (Claude Code), pendent de confirmació final
> per Joan.** Aquest document recull l'evidència real (tags/commits,
> extreta en directe de l'API de HF) per als 13 datasets marcats elegibles
> a `data/eligibility_report_1000_3.csv` (N=949.991, n=1000, execució de
> referència citada a `docs/architecture.md`), i una primera classificació
> raonada de cadascun com a vertader positiu (TP) o fals positiu (FP). La
> classificació es basa en un criteri objectiu i verificable (dispersió
> temporal dels commits substantius, vegeu metodologia), però la decisió
> final de si aquest document tanca el criteri d'acceptació 2 de US-108
> correspon a Joan (i, si cal, al director) — no a aquest assistent.

## Metodologia

Per a cada dataset elegible, `notebooks/validate_eligible.py` ha recollit:
- Tots els tags (per Criteri A).
- Fins a 50 commits (`list_repo_commits`, mateix límit que
  `classify_dataset`), cadascun anotat amb `is_substantive_commit`

Evidència completa: `data/us108_validation_worksheet.json` (no seguit
encara per git en aquesta branca, reproduïble executant
`python notebooks/validate_eligible.py`; els altres fitxers `data/*.csv`/
`*.json` d'execucions anteriors ja estan versionats com a evidència, així
que caldrà decidir si aquest es committeja igual quan es tanqui US-108).

**Criteri de classificació aplicat (nou, no forma part encara del
pipeline):** un dataset es considera **TP (vertader positiu)** si els
seus commits substantius estan **separats en el temps per esdeveniments
d'actualització clarament diferenciats** (típicament, hores/dies/mesos de
diferència, amb un patró de treball reprès, no una ràfega contínua). Es
considera **FP (fals positiu)** quan TOTS els commits substantius formen
part d'una **única sessió de pujada/creació** (segons a minuts de
diferència), encara que el nombre de commits sigui alt: moltes eines
d'anotació/captura de dades (p.e. LeRobot) generen desenes de commits
automàtics en una sola sessió, cadascun amb un títol que passa l'heurística
(`"Upload folder using huggingface_hub"`, `"Delete folder ..."`) sense
representar cap "versió" nova en el sentit que interessa a l'estudi.

Aquest criteri (dispersió temporal) **no estava implementat** a
`classify_dataset()` -- és exactament la limitació que motiva la
recomanació de la secció "Conclusions" més avall.

## Resultat per dataset

| # | Dataset | Criteri | Classificació | Raonament (evidència) |
|---|---|---|---|---|
| 1 | [ni25y/training-pick-up](https://huggingface.co/datasets/ni25y/training-pick-up) | B (19/20 subst.) | **FP** | Els 19 commits substantius cauen tots entre 00:22 i 02:22 del mateix dia (2026-04-08), ~1.5h. Patró LeRobot (`Upload folder`/`Delete files data/chunk*`): una sola sessió d'exportació. |
| 2 | [selvamask/SelvaMask](https://huggingface.co/datasets/selvamask/SelvaMask) | B (13/21 subst.) | **FP** | Tots els commits substantius (create/upload/delete d'imatges) cauen entre 19:30 i 20:28 del 2026-01-27 (~1h). Els commits del 29/01 (26h després) són tots "Update README.md", NO substantius. |
| 3 | [manro99/pusht_xarm_video](https://huggingface.co/datasets/manro99/pusht_xarm_video) | B (16/16 subst.) | **FP** | Tots els 16 commits entre 22:06 i 22:38 del mateix dia (2024-05-25), ~32 min. Sessió única. |
| 4 | [riversnow/jenga_training_dataset](https://huggingface.co/datasets/riversnow/jenga_training_dataset) | B (7/7 subst.) | **FP** | Tots els 7 commits entre 20:26 i 20:28 del mateix dia (2025-07-01), ~2 min. Sessió única. |
| 5 | [triton7777/eval_so100_test_pi0_mix_orange](https://huggingface.co/datasets/triton7777/eval_so100_test_pi0_mix_orange) | B (2/3 subst.) | **FP** | Els 3 commits (incl. "initial commit") entre 14:51:30 i 14:51:38, 8 segons. Un sol esdeveniment de creació dividit en 3 commits. |
| 6 | [AdilZtn/grab_red_cube_test_25](https://huggingface.co/datasets/AdilZtn/grab_red_cube_test_25) | A (tags v2.1/v3.0) | **TP** | Dos grups de commits clarament separats: 2025-07-16 (creació, tag v2.1) i 2025-09-16 (~2 mesos després: delete files antics + upload nous, tag v3.0). Actualització real i diferenciada. |
| 7 | [sucrammal/plant_square_pour_2](https://huggingface.co/datasets/sucrammal/plant_square_pour_2) | B (50/50 subst., **límit de 50 assolit**) | **FP** | Els 50 commits revisats (pot haver-n'hi més enllà del límit) formen un flux continu i dens ("Upload folder"/"Delete folder ./data,./videos,./meta") entre 00:39 i 02:50 del mateix dia (2025-04-20), ~2h10. Sense separació real entre "versions". |
| 8 | [hyzhang01/GCA_instruction](https://huggingface.co/datasets/hyzhang01/GCA_instruction) | A (tags v2.1/v3.0) | **TP** | Mateix patró que #6: dos grups clarament separats, 2025-11-07 i 2025-11-12 (5 dies), cadascun amb upload+delete+readme, i tag propi per grup. |
| 9 | [autobio-bench/screw_loose-blender](https://huggingface.co/datasets/autobio-bench/screw_loose-blender) | B (4/5 subst.) | **TP** | Commits separats per ~2 mesos (2025-05-14 creació, 2025-07-10 actualització amb delete de `meta/stats.json` + nou upload). Actualització real i diferenciada en el temps. |
| 10 | [filwsyl/video_tags](https://huggingface.co/datasets/filwsyl/video_tags) | A (tags 1.1.3/v1.4/v1.5) | **TP** | Historial genuí de **2+ anys** (2022-05 a 2024-09), amb missatges de commit descriptius i no automàtics ("Remove deprecated tasks", "Fix `license` metadata"). El cas més convincent dels 13. |
| 11 | [cgeorgiaw/merfish](https://huggingface.co/datasets/cgeorgiaw/merfish) | B (41/45 subst.) | **FP** | Els commits substantius repeteixen LITERALMENT el mateix títol ("trying yet again to make work for both streaming settings") desenes de vegades en ~20 minuts (2025-05-20, 15:59–16:16). Sessió de depuració iterativa, no versions. |
| 12 | [imageomics/TreeOfLife-200M](https://huggingface.co/datasets/imageomics/TreeOfLife-200M) | B (18/21 subst.) | **TP** | Historial genuí de **7+ mesos** (2025-10 a 2026-05), commits tipus PR ben descrits ("Add text embeddings...", "BioCLIP 2.5 Huge Training Data Update..."). Dataset mantingut activament. |
| 13 | [oakwood/efe_br-54](https://huggingface.co/datasets/oakwood/efe_br-54) | B (4/5 subst.) | **FP** | Els 5 commits entre 05:40:44 i 05:40:52, 8 segons. Creació atòmica única. |

## Agregat

| Mètrica | Valor |
|---|---|
| Total elegibles revisats | 13 |
| Vertaders positius (TP) | 5 (AdilZtn, hyzhang01, autobio-bench, filwsyl, imageomics) |
| Falsos positius (FP) | 8 (ni25y, selvamask, manro99, riversnow, triton7777, sucrammal, cgeorgiaw, oakwood) |
| **Precisió estimada** | **5/13 ≈ 38.5%** |
| Precisió — només Criteri A | 3/3 = 100% (AdilZtn, hyzhang01, filwsyl) |
| Precisió — només Criteri B | 2/10 = 20% (autobio-bench, imageomics) |

## Patró identificat

**8 dels 13 elegibles (61.5%) provenen d'un únic patró de fals positiu:**
datasets de robòtica/captura de dades en format LeRobot
(`chunk*/episode_*`, missatges `"Upload folder using huggingface_hub"` /
`"Delete folder ..."`) on una eina automàtica genera desenes de commits en
una sola sessió de pujada (segons/minuts de diferència). Cada commit
individual és tècnicament "substantiu" segons `is_substantive_commit`
(no conté cap paraula clau de manteniment/documentació), però el conjunt
representa **una sola versió del dataset**, no múltiples.

**Nota destacable**: el Criteri A (100% de precisió en aquesta mostra, 3/3)
és molt més fiable que el Criteri B (20%, 2/10) en aquesta mostra. Com que
el Criteri A ja exigeix ≥2 commits substantius (des del canvi documentat a
`docs/architecture.md`), la diferència de precisió no ve d'aquest
requisit, sinó que els datasets amb tags explícits tendeixen a tenir
actualitzacions genuïnament espaiades en el temps (els seus mantenidors
tagegen versions reals), mentre que el Criteri B (fallback sense tags) cau
sovint en aquest patró d'"un sol esdeveniment, molts commits".

## Conclusions i recomanació (criteri d'acceptació 4 de US-108)

Amb una precisió estimada del ~38.5% (i només ~20% per al Criteri B en
solitari), **es recomana replantejar el Criteri B abans de continuar a
l'Epic 3**, tal com preveu el criteri d'acceptació 4 de la user story.

**Proposta concreta:**
afegir un requisit de **dispersió temporal mínima** entre els commits
substantius comptats pel Criteri B (p.e., que almenys 2 commits
substantius estiguin separats per més d'una hora, o d'un dia), en lloc de
comptar-los sense considerar quan es van fer. Aquest canvi:
- Eliminaria els 6 falsos positius de "sessió única" (#1, #3, #4, #5, #7,
  #13) i el cas de repetició literal (#11, `cgeorgiaw/merfish`).
- És coherent amb -- i probablement un pas previ barat a -- US-301/US-302
  (detecció real de fitxers modificats), ja que no requereix inspeccionar
  contingut, només reordenar la lògica existent per timestamp.
- Es podria implementar i re-executar sobre la mostra de referència en
  poc temps per confirmar si la precisió millora abans d'escalar-ho.

## Limitacions d'aquesta validació

- Mostra petita (13 datasets): els percentatges no són generalitzables amb
  gaire marge d'error; útils com a senyal de disseny, no com a mètrica
  final per a la memòria sense ampliar la mostra.
- `sucrammal/plant_square_pour_2` (#7) va assolir el límit de 50 commits
  revisats: podria tenir història anterior no vista (encara que, donat el
  patró dens i continu observat, és improbable que canviï la conclusió).
- La classificació TP/FP d'aquest document és un primer pas raonat fet per
  Claude Code a partir de timestamps i títols de commit -- NO una
  inspecció del contingut real de cada dataset. Coincideix amb el criteri
  d'acceptació 2 de US-108 ("confirmar/desmentir el criteri assignat").