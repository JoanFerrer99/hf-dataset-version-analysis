# US-108 — Validació (semi-)automàtica dels datasets elegibles

> **Generat automàticament** per `notebooks/validate_eligible.py` (2026-07-29T20:21:23.952669), a partir de `/app/data/eligibility_report_2000_4.csv` (10 datasets elegibles). **Aquest fitxer es regenera sencer a cada execució del script -- no l'editis manualment**, els canvis es perdrien a la següent execució.

## Metodologia

Per cada dataset elegible, `notebooks/validate_eligible.py` recull:
- Tots els tags (per Criteri A).
- Fins a 50 commits, anotats amb `eligibility_scan.determine_commit_substantive` -- LA MATEIXA lògica que decideix l'elegibilitat a `classify_dataset` (inspecció real de fitxers via clonatge "bare", US-302, amb fallback a l'heurística de títol si el clonatge falla).

Els commits substantius s'agrupen en **sessions de treball** (`cluster_commit_times`): un cop ordenats cronològicament, una nova sessió comença quan dos commits CONSECUTIUS estan separats per més de 6.0h -- el MATEIX llindar que decideix l'elegibilitat via Criteri B (`eligibility_scan.MIN_SUBSTANTIVE_GAP_HOURS` = 6.0h), un únic concepte de "separació genuïna" en lloc de dos llindars independents que es puguin desincronitzar.

Tot i fer servir el mateix llindar, el recompte de sessions NO és redundant amb el Criteri B: aquest només exigeix que l'interval entre el primer i l'últim commit substantiu sigui prou gran (pot complir-se amb una sola sessió densa + un commit outlier allunyat, o amb diversos salts petits que sumen un interval gran sense que cap parell CONSECUTIU superi 6.0h). El recompte de sessions ho detecta.

**Aquesta comprovació NOMÉS s'aplica al Criteri B.** El Criteri A (tags explícits) mai ha exigit dispersió temporal a `classify_dataset` -- la presència de >=2 tags ja és un senyal deliberat de versionat per part del mantenidor, i la validació manual original de US-108 el va trobar 100% fiable sense cap comprovació temporal. Aplicar el recompte de sessions també al Criteri A seria un criteri més estricte, inventat a la capa de l'informe, que no reflectiria fidelment el disseny real del pipeline.

- **TP** (automàtic): Criteri A sempre, o Criteri B amb >=2 sessions clarament diferenciades.
- **REVIEW**: Criteri B amb només 1 sessió -- cal revisió humana (no vol dir necessàriament fals positiu).
- **ERROR**: no s'ha pogut recollir evidència (accés restringit, xarxa, etc.).

## Resultat per dataset

| # | Dataset | Criteri | Veredicte | Evidència | Raonament |
|---|---|---|---|---|---|
| 1 | [dl-qft-team/DeepSeek-R1-Distill-Llama-8B-dvts-prm-completions](https://huggingface.co/datasets/dl-qft-team/DeepSeek-R1-Distill-Llama-8B-dvts-prm-completions) | B | **TP** | 12 subst. / 4 sessions | 4 sessions de treball clarament diferenciades (>6.0h de buit entre commits substantius). |
| 2 | [mothnaZl/QwQ-32B-best_of_n-VLLM-Skywork-o1-Open-PRM-Qwen-2.5-7B-completions](https://huggingface.co/datasets/mothnaZl/QwQ-32B-best_of_n-VLLM-Skywork-o1-Open-PRM-Qwen-2.5-7B-completions) | B | **TP** | 3 subst. / 3 sessions | 3 sessions de treball clarament diferenciades (>6.0h de buit entre commits substantius). |
| 3 | [zacapa/SO101_FMB_ACT_08](https://huggingface.co/datasets/zacapa/SO101_FMB_ACT_08) | A | **TP** | 25 subst. / 6 sessions | Elegible via Criteri A (tags explícits) -- no s'exigeix dispersió temporal: la presència de >=2 tags ja és un senyal deliberat de versionat per part del mantenidor, independentment de quan es van crear. |
| 4 | [BrunoM42/robocasa_target_HeatKebabSandwich](https://huggingface.co/datasets/BrunoM42/robocasa_target_HeatKebabSandwich) | A | **TP** | 3 subst. / 2 sessions | Elegible via Criteri A (tags explícits) -- no s'exigeix dispersió temporal: la presència de >=2 tags ja és un senyal deliberat de versionat per part del mantenidor, independentment de quan es van crear. |
| 5 | [google-research-datasets/natural_questions](https://huggingface.co/datasets/google-research-datasets/natural_questions) | B | **TP** | 7 subst. / 5 sessions | 5 sessions de treball clarament diferenciades (>6.0h de buit entre commits substantius). |
| 6 | [theayos/libero_spatial_image](https://huggingface.co/datasets/theayos/libero_spatial_image) | A | **TP** | 11 subst. / 3 sessions | Elegible via Criteri A (tags explícits) -- no s'exigeix dispersió temporal: la presència de >=2 tags ja és un senyal deliberat de versionat per part del mantenidor, independentment de quan es van crear. |
| 7 | [FudgeTechLab/LeRobot_Blue_Cube_PnP](https://huggingface.co/datasets/FudgeTechLab/LeRobot_Blue_Cube_PnP) | B | **TP** | 50 subst. / 3 sessions | 3 sessions de treball clarament diferenciades (>6.0h de buit entre commits substantius). |
| 8 | [GermanEval/germeval_14](https://huggingface.co/datasets/GermanEval/germeval_14) | B | **TP** | 5 subst. / 2 sessions | 2 sessions de treball clarament diferenciades (>6.0h de buit entre commits substantius). |
| 9 | [BrunoM42/robocasa_target_SearingMeat](https://huggingface.co/datasets/BrunoM42/robocasa_target_SearingMeat) | A | **TP** | 3 subst. / 2 sessions | Elegible via Criteri A (tags explícits) -- no s'exigeix dispersió temporal: la presència de >=2 tags ja és un senyal deliberat de versionat per part del mantenidor, independentment de quan es van crear. |
| 10 | [community-datasets/qa_zre](https://huggingface.co/datasets/community-datasets/qa_zre) | B | **TP** | 5 subst. / 3 sessions | 3 sessions de treball clarament diferenciades (>6.0h de buit entre commits substantius). |

## Agregat

| Mètrica | Valor |
|---|---|
| Total elegibles | 10 |
| Criteri A | 4 |
| Criteri B | 6 |
| **TP** (Criteri A, o Criteri B amb >=2 sessions) | 10 |
| **REVIEW** (Criteri B amb 1 sessió, cal revisió humana) | 0 |
| ERROR | 0 |
| Precisió automàtica estimada (TP / total) | 10/10 = 100.0% |

## Limitacions

- El veredicte **TP** és una inferència automàtica basada en la dispersió temporal de sessions, no una inspecció manual del contingut real de cada versió. Segueix sent una heurística -- més robusta que la versió purament basada en títol, però no una confirmació humana definitiva (US-108, criteri d'acceptació 2).
- El veredicte **REVIEW** no implica necessàriament un fals positiu: una sola actualització real posterior a la creació és legítimament una segona versió encara que només generi una separació d'un sol "salt" -- cal ull humà per confirmar-ho.
- Aquest informe substitueix qualsevol versió anterior de `docs/us108_validation_report.md` a cada execució; si es vol conservar una anàlisi concreta, cal desar-la a part (o consultar l'historial de git) abans de tornar a executar `validate_eligible.py`.
