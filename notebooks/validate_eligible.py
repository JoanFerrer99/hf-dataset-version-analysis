"""
US-108: eina de suport per a la validació dels datasets elegibles de
l'execució de referència (`data/eligibility_report_<N>_<run_id>.csv` --
vegeu `docs/architecture.md` per saber quina és l'execució de referència
vigent).

Aquest script recull, per cada dataset marcat elegible per
`classify_dataset`, l'evidència necessària per confirmar el criteri
assignat (US-108, criteri d'acceptació 2):

  - Tots els tags trobats (Criteri A).
  - Fins a 50 commits, anotats amb `eligibility_scan.determine_commit_
    substantive` -- LA MATEIXA lògica que `classify_dataset` (inspecció
    real de fitxers via clonatge "bare", US-302, amb fallback a
    l'heurística de títol si el clonatge falla), no una reimplementació
    que es pugui desincronitzar.
  - Els commits substantius agrupats en "sessions" de treball (gaps grans
    entre commits consecutius) per detectar automàticament si l'elegibilitat
    ve d'una separació temporal genuïna o d'un sol commit outlier allunyat.

Genera, a cada execució (US-108, criteri d'acceptació 4 -- automatització):
  - `data/us108_validation_worksheet.json`: evidència completa, reproduïble.
  - `docs/us108_validation_report.md`: informe llegible amb un veredicte
    TP/REVIEW/ERROR automàtic per dataset (vegeu `generate_markdown_report`).
    Es REGENERA sencer a cada execució -- no s'ha d'editar manualment.

Ús:
  python validate_eligible.py
  python validate_eligible.py --input ../data/eligibility_report_2000_2.csv
  python validate_eligible.py --output ../data/us108_validation_worksheet.json
  python validate_eligible.py --no-report  # només el worksheet JSON
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

import errors
from eligibility_scan import MIN_SUBSTANTIVE_GAP_HOURS, bare_clone, determine_commit_substantive

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(SCRIPT_DIR, "..", "data", "eligibility_report_2000_2.csv")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "..", "data", "us108_validation_worksheet.json")
DEFAULT_REPORT_OUTPUT = os.path.join(SCRIPT_DIR, "..", "docs", "us108_validation_report.md")

MAX_COMMITS = 50  # mateix límit que classify_dataset(), per coherència

RETRY_CONFIG: dict = {
    "max_retries": errors.DEFAULT_MAX_RETRIES,
    "base_wait_s": errors.DEFAULT_BASE_WAIT_S,
    "max_wait_s": errors.DEFAULT_MAX_WAIT_S,
}


@dataclass
class CommitEvidence:
    """
    Evidència d'un sol commit, anotada amb la mateixa lògica de
    substantivitat que `classify_dataset`.

    :ivar sha: hash del commit.
    :ivar title: títol del commit tal com el retorna l'API.
    :ivar created_at: data del commit en format ISO 8601, o `None` si
        l'API no la proporciona per aquest commit.
    :ivar is_substantive: resultat de `determine_commit_substantive` --
        inspecció real de fitxers (o heurística de títol com a fallback).
    """

    sha: str
    title: str
    created_at: str | None
    is_substantive: bool


def cluster_commit_times(
    commit_times: list[datetime | None], gap_hours: float = MIN_SUBSTANTIVE_GAP_HOURS
) -> list[list[datetime]]:
    """
    Agrupa dates de commits en "sessions" de treball diferenciades: un cop
    ordenades, una nova sessió comença quan dos commits consecutius estan
    separats per més de `gap_hours` hores. Funció pura, sense crides a
    l'API -- útil per distingir automàticament si la separació temporal
    d'un dataset elegible ve de múltiples actualitzacions genuïnes o d'un
    sol commit outlier que allarga l'interval mínim/màxim sense representar
    una sessió de treball real.

    :param commit_times: dates (`datetime`) en qualsevol ordre; els
        elements `None` s'ignoren.
    :param gap_hours: buit mínim, en hores, entre dos commits consecutius
        perquè es considerin sessions diferents.
    :return: llista de llistes de `datetime`, cadascuna una sessió,
        ordenades cronològicament; llista buida si no hi ha cap data vàlida.
    """
    valid_times = sorted(t for t in commit_times if t is not None)
    if not valid_times:
        return []

    clusters: list[list[datetime]] = [[valid_times[0]]]
    for t in valid_times[1:]:
        if (t - clusters[-1][-1]) > timedelta(hours=gap_hours):
            clusters.append([t])
        else:
            clusters[-1].append(t)
    return clusters


def summarize_commits(commits: list, clone_dir: str | None = None) -> dict:
    """
    Anota una llista de commits (objectes amb `.commit_id`/`.title`/
    `.created_at`, com els retornats per `list_repo_commits`) amb
    `determine_commit_substantive` i les agrupa en sessions de treball.

    :param commits: llista d'objectes commit (o qualsevol objecte amb
        atributs `title`, `commit_id` i opcionalment `created_at`).
    :param clone_dir: directori d'un clonatge "bare" ja fet (vegeu
        `eligibility_scan.bare_clone`), o `None` si no n'hi ha (es
        recorre a l'heurística de títol per a tots els commits).
    :return: diccionari amb ``"commits"`` (llista de `CommitEvidence` com
        a `dict`), ``"num_substantive"`` (recompte d'entrades
        substantives) i ``"num_sessions"`` (`len(cluster_commit_times(...))`
        sobre les dates dels commits substantius -- vegeu
        `cluster_commit_times`).
    """
    entries = []
    substantive_times: list[datetime | None] = []
    for commit in commits:
        sha = getattr(commit, "commit_id", None) or getattr(commit, "oid", None) or ""
        title = getattr(commit, "title", "") or ""
        created_at = getattr(commit, "created_at", None)
        is_sub = determine_commit_substantive(commit, clone_dir)
        entries.append(
            CommitEvidence(
                sha=str(sha),
                title=title,
                created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                is_substantive=is_sub,
            )
        )
        if is_sub:
            substantive_times.append(created_at)

    return {
        "commits": [asdict(e) for e in entries],
        "num_substantive": sum(1 for e in entries if e.is_substantive),
        "num_sessions": len(cluster_commit_times(substantive_times)),
    }


def gather_evidence_for_dataset(api: HfApi, hf_token: str, dataset_id: str, eligibility_reason: str) -> dict:
    """
    Recull l'evidència d'un dataset elegible: tots els tags i fins a
    `MAX_COMMITS` commits (mateix límit que `classify_dataset`), anotats
    amb `determine_commit_substantive` i agrupats en sessions.

    :param api: instància `HfApi` ja autenticada.
    :param hf_token: token HF (es passa explícitament a cada crida, com
        fa `eligibility_scan.classify_dataset`).
    :param dataset_id: identificador del dataset (`owner/name`).
    :param eligibility_reason: motiu d'elegibilitat original, tal com
        consta a `data/eligibility_report_*.csv` (es copia literalment al
        resultat perquè el revisor sàpiga quin criteri ha de confirmar).
    :return: diccionari amb ``dataset_id``, ``eligibility_reason``,
        ``url``, ``tags``, ``commits``, ``num_substantive`` i
        ``num_sessions`` (de `summarize_commits`). Si alguna crida falla,
        el diccionari inclou ``error`` amb el missatge i la resta de
        camps queden buits/per defecte.
    """
    result = {
        "dataset_id": dataset_id,
        "eligibility_reason": eligibility_reason,
        "url": f"https://huggingface.co/datasets/{dataset_id}",
        "tags": [],
        "commits": [],
        "num_substantive": 0,
        "num_sessions": 0,
        "error": "",
    }
    try:
        refs = errors.with_retry(
            list_repo_refs, repo_id=dataset_id, repo_type="dataset", token=hf_token, **RETRY_CONFIG
        )
        result["tags"] = [t.name for t in (refs.tags or [])]

        commits = list(
            errors.with_retry(
                list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=hf_token, **RETRY_CONFIG
            )
        )[:MAX_COMMITS]

        with bare_clone(dataset_id) as clone_dir:
            result.update(summarize_commits(commits, clone_dir))
    except Exception as exc:
        category = errors.classify_error(exc)
        result["error"] = f"[{category.value}] {exc}"
    return result


def classify_dataset_evidence(evidence: dict) -> dict:
    """
    Deriva un veredicte automàtic de coherència, aplicant la comprovació
    de sessions NOMÉS al Criteri B -- reflectint fidelment el disseny de
    `classify_dataset`, on el Criteri A (tags explícits) MAI ha exigit
    dispersió temporal: la presència de >=2 tags ja és un senyal
    deliberat de versionat per part del mantenidor (la validació manual
    original de US-108 el va trobar 100% fiable sense cap comprovació
    temporal). Aplicar el recompte de sessions també al Criteri A seria
    inventar un criteri més estricte a la capa de l'informe que el que
    realment va decidir l'elegibilitat.

    :param evidence: entrada del worksheet (com la retorna
        `gather_evidence_for_dataset`), amb almenys ``eligibility_reason``,
        ``num_sessions`` i ``error``.
    :return: diccionari amb ``verdict`` (``"ERROR"`` si no s'ha pogut
        recollir evidència; ``"TP"`` directament per al Criteri A, o si
        `num_sessions >= 2` per al Criteri B; ``"REVIEW"`` en cas
        contrari) i ``reasoning`` (frase curta explicant el veredicte).
    """
    if evidence.get("error"):
        return {"verdict": "ERROR", "reasoning": f"No s'ha pogut recollir evidència: {evidence['error']}"}

    if evidence.get("eligibility_reason", "").startswith("Criteri A"):
        return {
            "verdict": "TP",
            "reasoning": (
                "Elegible via Criteri A (tags explícits) -- no s'exigeix dispersió "
                "temporal: la presència de >=2 tags ja és un senyal deliberat de "
                "versionat per part del mantenidor, independentment de quan es van crear."
            ),
        }

    num_sessions = evidence.get("num_sessions", 0)
    if num_sessions >= 2:
        return {
            "verdict": "TP",
            "reasoning": (
                f"{num_sessions} sessions de treball clarament diferenciades "
                f"(>{MIN_SUBSTANTIVE_GAP_HOURS}h de buit entre commits substantius)."
            ),
        }
    return {
        "verdict": "REVIEW",
        "reasoning": (
            f"Elegible via Criteri B amb només {num_sessions} sessió detectada "
            f"(buit de {MIN_SUBSTANTIVE_GAP_HOURS}h) -- l'interval mínim/màxim entre "
            f"commits supera {MIN_SUBSTANTIVE_GAP_HOURS}h però cap parell CONSECUTIU "
            "ho fa (p.e. diversos salts petits que sumen un interval gran); revisar "
            "manualment si representa una versió real o una única sessió de treball."
        ),
    }


def generate_markdown_report(output: dict) -> str:
    """
    Genera el contingut Markdown complet de l'informe de validació US-108
    a partir del worksheet ja construït, amb un veredicte TP/REVIEW/ERROR
    automàtic per dataset (`classify_dataset_evidence`).

    :param output: diccionari tal com l'escriu el bloc ``__main__``
        (``generated_at``, ``source_csv``, ``n_datasets``, ``datasets``).
    :return: contingut Markdown complet (`str`), pensat per sobreescriure
        `docs/us108_validation_report.md` sencer a cada execució.
    """
    datasets = output["datasets"]
    total = len(datasets)

    rows = []
    tp = review = error = crit_a = crit_b = 0
    for i, ds in enumerate(datasets, start=1):
        verdict_info = classify_dataset_evidence(ds)
        verdict = verdict_info["verdict"]
        tp += verdict == "TP"
        review += verdict == "REVIEW"
        error += verdict == "ERROR"

        reason = ds.get("eligibility_reason", "")
        criterion = "A" if reason.startswith("Criteri A") else ("B" if reason.startswith("Criteri B") else "?")
        crit_a += criterion == "A"
        crit_b += criterion == "B"

        evidence_str = f"{ds.get('num_substantive', 0)} subst. / {ds.get('num_sessions', 0)} sessions"
        rows.append(
            f"| {i} | [{ds['dataset_id']}]({ds['url']}) | {criterion} | **{verdict}** | "
            f"{evidence_str} | {verdict_info['reasoning']} |"
        )

    precision_line = (
        f"| Precisió automàtica estimada (TP / total) | {tp}/{total} = {tp / total:.1%} |"
        if total
        else "| Precisió automàtica estimada (TP / total) | N/A (0 elegibles) |"
    )

    lines = [
        "# US-108 — Validació (semi-)automàtica dels datasets elegibles",
        "",
        f"> **Generat automàticament** per `notebooks/validate_eligible.py` "
        f"({output['generated_at']}), a partir de `{output['source_csv']}` "
        f"({total} datasets elegibles). **Aquest fitxer es regenera sencer a "
        "cada execució del script -- no l'editis manualment**, els canvis es "
        "perdrien a la següent execució.",
        "",
        "## Metodologia",
        "",
        "Per cada dataset elegible, `notebooks/validate_eligible.py` recull:",
        "- Tots els tags (per Criteri A).",
        "- Fins a 50 commits, anotats amb `eligibility_scan.determine_commit_"
        "substantive` -- LA MATEIXA lògica que decideix l'elegibilitat a "
        "`classify_dataset` (inspecció real de fitxers via clonatge \"bare\", "
        "US-302, amb fallback a l'heurística de títol si el clonatge falla).",
        "",
        "Els commits substantius s'agrupen en **sessions de treball** "
        "(`cluster_commit_times`): un cop ordenats cronològicament, una nova "
        "sessió comença quan dos commits CONSECUTIUS estan separats per més "
        f"de {MIN_SUBSTANTIVE_GAP_HOURS}h -- el MATEIX llindar que decideix "
        "l'elegibilitat via Criteri B (`eligibility_scan."
        f"MIN_SUBSTANTIVE_GAP_HOURS` = {MIN_SUBSTANTIVE_GAP_HOURS}h), un únic "
        "concepte de \"separació genuïna\" en lloc de dos llindars "
        "independents que es puguin desincronitzar.",
        "",
        "Tot i fer servir el mateix llindar, el recompte de sessions NO és "
        "redundant amb el Criteri B: aquest només exigeix que l'interval "
        "entre el primer i l'últim commit substantiu sigui prou gran (pot "
        "complir-se amb una sola sessió densa + un commit outlier allunyat, "
        "o amb diversos salts petits que sumen un interval gran sense que "
        f"cap parell CONSECUTIU superi {MIN_SUBSTANTIVE_GAP_HOURS}h). El "
        "recompte de sessions ho detecta.",
        "",
        "**Aquesta comprovació NOMÉS s'aplica al Criteri B.** El Criteri A "
        "(tags explícits) mai ha exigit dispersió temporal a "
        "`classify_dataset` -- la presència de >=2 tags ja és un senyal "
        "deliberat de versionat per part del mantenidor, i la validació "
        "manual original de US-108 el va trobar 100% fiable sense cap "
        "comprovació temporal. Aplicar el recompte de sessions també al "
        "Criteri A seria un criteri més estricte, inventat a la capa de "
        "l'informe, que no reflectiria fidelment el disseny real del pipeline.",
        "",
        "- **TP** (automàtic): Criteri A sempre, o Criteri B amb >=2 sessions "
        "clarament diferenciades.",
        "- **REVIEW**: Criteri B amb només 1 sessió -- cal revisió humana "
        "(no vol dir necessàriament fals positiu).",
        "- **ERROR**: no s'ha pogut recollir evidència (accés restringit, "
        "xarxa, etc.).",
        "",
        "## Resultat per dataset",
        "",
        "| # | Dataset | Criteri | Veredicte | Evidència | Raonament |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
        "## Agregat",
        "",
        "| Mètrica | Valor |",
        "|---|---|",
        f"| Total elegibles | {total} |",
        f"| Criteri A | {crit_a} |",
        f"| Criteri B | {crit_b} |",
        f"| **TP** (Criteri A, o Criteri B amb >=2 sessions) | {tp} |",
        f"| **REVIEW** (Criteri B amb 1 sessió, cal revisió humana) | {review} |",
        f"| ERROR | {error} |",
        precision_line,
        "",
        "## Limitacions",
        "",
        "- El veredicte **TP** és una inferència automàtica basada en la "
        "dispersió temporal de sessions, no una inspecció manual del "
        "contingut real de cada versió. Segueix sent una heurística -- més "
        "robusta que la versió purament basada en títol, però no una "
        "confirmació humana definitiva (US-108, criteri d'acceptació 2).",
        "- El veredicte **REVIEW** no implica necessàriament un fals "
        "positiu: una sola actualització real posterior a la creació és "
        "legítimament una segona versió encara que només generi una "
        "separació d'un sol \"salt\" -- cal ull humà per confirmar-ho.",
        "- Aquest informe substitueix qualsevol versió anterior de "
        "`docs/us108_validation_report.md` a cada execució; si es vol "
        "conservar una anàlisi concreta, cal desar-la a part (o consultar "
        "l'historial de git) abans de tornar a executar "
        "`validate_eligible.py`.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="US-108: recull evidència (tags/commits) dels datasets elegibles i genera un informe de validació.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="CSV de referència (eligibility_report_*.csv).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Fitxer JSON de sortida (worksheet).")
    parser.add_argument(
        "--report-output", default=DEFAULT_REPORT_OUTPUT,
        help="Fitxer Markdown de l'informe de validació (es regenera sencer cada execució).",
    )
    parser.add_argument(
        "--no-report", action="store_true",
        help="No generar l'informe Markdown, només el worksheet JSON.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    load_dotenv()
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx", file=sys.stderr)
        sys.exit(1)
    api = HfApi(token=hf_token)

    df = pd.read_csv(args.input)
    eligible = df[df["eligible"] == True]  # noqa: E712
    print(f"Recollint evidència per a {len(eligible)} datasets elegibles de {args.input}...")

    worksheet = []
    for _, row in eligible.iterrows():
        print(f"  - {row['dataset_id']} ({row['eligibility_reason']})")
        evidence = gather_evidence_for_dataset(api, hf_token, row["dataset_id"], row["eligibility_reason"])
        worksheet.append(evidence)

    output = {
        "generated_at": datetime.now().isoformat(),
        "source_csv": os.path.abspath(args.input),
        "n_datasets": len(worksheet),
        "datasets": worksheet,
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nWorksheet escrit a: {args.output}")

    if not args.no_report:
        report_md = generate_markdown_report(output)
        os.makedirs(os.path.dirname(args.report_output), exist_ok=True)
        with open(args.report_output, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"Informe escrit a: {args.report_output}")
