"""
US-108: eina de suport per a la validació manual dels datasets elegibles
de l'execució de referència (`data/eligibility_report_<N>_<run_id>.csv`,
per defecte la de referència del projecte: N=949.991, n=1000, 13
elegibles -- vegeu `docs/architecture.md`).

Aquest script NO decideix per si sol si un dataset és realment elegible:
recopila, per cada dataset marcat elegible per `classify_dataset`,
l'evidència necessària perquè un revisor humà pugui confirmar/desmentir el
criteri assignat (US-108, criteri d'acceptació 2):

  - Criteri A (tags>=2 amb commits substantius): llista completa de tags
    trobats, amb el títol i l'estat "substantiu" (segons
    `is_substantive_commit`, la mateixa heurística que fa servir
    `classify_dataset`) de cada commit revisat.
  - Criteri B (branches>=2 amb commits substantius): mateixa llista de
    commits, perquè es pugui comprovar manualment si els títols marcats
    com a "substantius" realment representen canvis reals de dataset (i
    no, p.e., missatges genèrics d'eines automàtiques de captura de dades
    que passen l'heurística de títol sense ser-ho).

Reutilitza `errors.with_retry`/`errors.classify_error` per a les crides a
l'API (mateix mecanisme de fiabilitat que `eligibility_scan.py`) i
`eligibility_scan.is_substantive_commit` per anotar els commits amb
l'EXACTA mateixa heurística que va decidir l'elegibilitat originalment
(important per a la validació: si es canviés la implementació de
`is_substantive_commit` sense actualitzar aquest script, els resultats ja
no reflectirien la classificació real).

Ús:
  python validate_eligible.py
  python validate_eligible.py --input ../data/eligibility_report_1000_3.csv
  python validate_eligible.py --output ../data/us108_validation_worksheet.json

Output:
  data/us108_validation_worksheet.json -- una entrada per dataset elegible
  amb els camps `dataset_id`, `eligibility_reason`, `tags` (llista de
  noms) i `commits` (llista de `{sha, title, created_at, is_substantive}`).
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

import errors
from eligibility_scan import is_substantive_commit

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(SCRIPT_DIR, "..", "data", "eligibility_report_1000_3.csv")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "..", "data", "us108_validation_worksheet.json")

MAX_COMMITS = 50  # mateix límit que classify_dataset(), per coherència

RETRY_CONFIG: dict = {
    "max_retries": errors.DEFAULT_MAX_RETRIES,
    "base_wait_s": errors.DEFAULT_BASE_WAIT_S,
    "max_wait_s": errors.DEFAULT_MAX_WAIT_S,
}


@dataclass
class CommitEvidence:
    """
    Evidència d'un sol commit, anotada amb l'heurística de substantivitat.

    :ivar sha: hash del commit.
    :ivar title: títol del commit tal com el retorna l'API.
    :ivar created_at: data del commit en format ISO 8601, o `None` si
        l'API no la proporciona per aquest commit.
    :ivar is_substantive: resultat de `is_substantive_commit(title)` --
        la mateixa heurística usada per `classify_dataset` per decidir
        l'elegibilitat via Criteri A/B.
    """

    sha: str
    title: str
    created_at: str | None
    is_substantive: bool


def summarize_commits(commits: list) -> dict:
    """
    Anota una llista de commits (objectes amb `.commit_id`/`.title`/
    `.created_at`, com els retornats per `list_repo_commits`) amb
    `is_substantive_commit`, sense fer cap crida a l'API -- funció pura,
    testejable amb fakes.

    :param commits: llista d'objectes commit (o qualsevol objecte amb
        atributs `title` i opcionalment `commit_id`/`created_at`).
    :return: diccionari amb ``"commits"`` (llista de `CommitEvidence`,
        com a `dict` via `asdict`) i ``"num_substantive"`` (recompte
        d'entrades amb `is_substantive=True`, el mateix nombre que
        `classify_dataset` hauria comptat per decidir l'elegibilitat).
    """
    entries = []
    for commit in commits:
        sha = getattr(commit, "commit_id", None) or getattr(commit, "oid", None) or ""
        title = getattr(commit, "title", "") or ""
        created_at = getattr(commit, "created_at", None)
        entries.append(
            CommitEvidence(
                sha=str(sha),
                title=title,
                created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                is_substantive=is_substantive_commit(title),
            )
        )
    return {
        "commits": [asdict(e) for e in entries],
        "num_substantive": sum(1 for e in entries if e.is_substantive),
    }


def gather_evidence_for_dataset(api: HfApi, hf_token: str, dataset_id: str, eligibility_reason: str) -> dict:
    """
    Recull l'evidència d'un dataset elegible: tots els tags i fins a
    `MAX_COMMITS` commits (mateix límit que `classify_dataset`), anotats
    amb `is_substantive_commit`.

    :param api: instància `HfApi` ja autenticada.
    :param hf_token: token HF (es passa explícitament a cada crida, com
        fa `eligibility_scan.classify_dataset`).
    :param dataset_id: identificador del dataset (`owner/name`).
    :param eligibility_reason: motiu d'elegibilitat original, tal com
        consta a `data/eligibility_report_*.csv` (es copia literalment al
        resultat perquè el revisor sàpiga quin criteri ha de confirmar).
    :return: diccionari amb ``dataset_id``, ``eligibility_reason``,
        ``url`` (enllaç directe a la pàgina del dataset a HF), ``tags``
        (llista de noms), ``commits`` i ``num_substantive`` (de
        `summarize_commits`). Si alguna crida falla, el diccionari inclou
        ``error`` amb el missatge i la resta de camps queden buits.
    """
    result = {
        "dataset_id": dataset_id,
        "eligibility_reason": eligibility_reason,
        "url": f"https://huggingface.co/datasets/{dataset_id}",
        "tags": [],
        "commits": [],
        "num_substantive": 0,
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
        result.update(summarize_commits(commits))
    except Exception as exc:
        category = errors.classify_error(exc)
        result["error"] = f"[{category.value}] {exc}"
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="US-108: recull evidència (tags/commits) dels datasets elegibles per a validació manual.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="CSV de referència (eligibility_report_*.csv).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Fitxer JSON de sortida (worksheet).")
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
