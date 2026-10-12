"""
Fase 1: la llista ordenada de versions de cada dataset elegible, amb data,
autors i mida aproximada.

Què és una versió depèn del criteri que va fer elegible el dataset (columna
`eligibility_reason`, no es recalcula):
  - Criteri A: cada tag és una versió (una marca deliberada de l'autor).
  - Criteri B: cada sessió de commits que toquen dades tabulars és una
    versió, representada pel seu commit més recent. Els commits són els que
    va trobar la Fase 0 (`tabular_commits.csv`, al costat del report): no es
    tornen a llistar ni es clona res. Les sessions es fan amb la mateixa
    funció que la Fase 0 (`eligibility_scan.cluster_commit_times`).

Cada versió porta `version_source` (`tag` o `commit_session`) perquè la
confiança no és la mateixa. L'API no distingeix autor de committer: `authors`
és l'únic camp disponible.

Ús:
  python version_extractor.py --input ../data/run_8/eligibility_report.csv

Output (en una carpeta nova, `data/run_<id>/`):
  versions.csv, failures.csv (si hi ha fallades)
"""

import argparse
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import list_repo_commits, list_repo_refs, list_repo_tree

import errors
import eligibility_scan as es
from eligibility_scan import TabularCommit, cluster_commit_times

log = logging.getLogger(__name__)

# Qui executa la fase hi posa el de la carpeta de l'execució (`es.new_run_dir`).
FAILURES_LOG_PATH = es.FAILURES_LOG_PATH

RETRY_CONFIG: dict = dict(errors.DEFAULT_RETRY_CONFIG)


@dataclass
class VersionRow:
    """
    Una versió d'un dataset elegible (una fila de `versions.csv`).

    :ivar dataset_id: dataset.
    :ivar version_label: nom del tag, o `session-<n>` (1 = més antiga).
    :ivar version_order: posició cronològica (1 = més antiga).
    :ivar version_source: `"tag"` o `"commit_session"`.
    :ivar commit_sha: commit del tag, o el més recent de la sessió.
    :ivar commit_date: data ISO 8601, o `None`.
    :ivar authors: noms d'usuari units per coma, sense duplicats.
    :ivar approx_size_bytes: mida total de l'arbre en aquesta revisió, o `None`.
    :ivar session_commit_count: commits de la sessió (1 per a un tag).
    :ivar status: `ok`, `ok_no_size`, `commit_error` o `size_error`.
    """

    dataset_id: str
    version_label: str
    version_order: int | None
    version_source: str
    commit_sha: str
    commit_date: str | None
    authors: str
    approx_size_bytes: int | None
    session_commit_count: int
    status: str


# ---------------------------------------------------------------------------
# Funcions pures
# ---------------------------------------------------------------------------


def order_versions_by_date(versions: list[dict]) -> list[dict]:
    """
    Ordena les versions d'un dataset per `commit_date` i n'assigna
    `version_order` (1 = més antiga). Les que no tenen data van al final.
    """
    ordered = sorted(versions, key=lambda v: (v.get("commit_date") is None, v.get("commit_date") or ""))
    for i, v in enumerate(ordered, start=1):
        v["version_order"] = i
    return ordered


def sum_tree_size(entries: Iterable) -> int:
    """Suma `.size` de les entrades de `list_repo_tree` (les carpetes no en tenen)."""
    return sum(getattr(e, "size", 0) or 0 for e in entries)


def format_authors(authors: list[str] | None) -> str:
    """Uneix els autors per comes, sense duplicats i en ordre d'aparició."""
    if not authors:
        return ""
    seen: list[str] = []
    for a in authors:
        if a not in seen:
            seen.append(a)
    return ",".join(seen)


def build_sessions_from_commits(tabular_commits: list[TabularCommit]) -> list[dict]:
    """
    Agrupa els commits tabulars d'un dataset en sessions (`cluster_commit_times`).

    :param tabular_commits: commits tabulars que va trobar la Fase 0; els que
        no tenen data s'ignoren.
    :return: una entrada per sessió, en ordre cronològic: `commit_sha` i
        `commit_date` del commit més recent, `authors` (unió) i
        `session_commit_count`.
    """
    dated_tabular = [c for c in tabular_commits if c.created_at is not None]
    if not dated_tabular:
        return []

    by_time: dict = {}
    for c in dated_tabular:
        by_time.setdefault(c.created_at, []).append(c)

    session_time_clusters = cluster_commit_times([c.created_at for c in dated_tabular])

    sessions = []
    for time_cluster in session_time_clusters:
        session_commits = [c for t in time_cluster for c in by_time[t]]
        latest = max(session_commits, key=lambda c: c.created_at)
        authors: list[str] = []
        for c in session_commits:
            for a in getattr(c, "authors", None) or []:
                if a not in authors:
                    authors.append(a)
        sessions.append({
            "commit_sha": getattr(latest, "commit_id", None) or getattr(latest, "oid", None) or "",
            "commit_date": latest.created_at.isoformat() if hasattr(latest.created_at, "isoformat") else latest.created_at,
            "authors": authors,
            "session_commit_count": len(session_commits),
        })
    return sessions


# ---------------------------------------------------------------------------
# Crides a l'API
# ---------------------------------------------------------------------------


def fetch_tags(dataset_id: str, hf_token: str | None, retry_config: dict) -> list:
    """
    :return: tags del dataset (`GitRefInfo`, amb `.name` i `.target_commit`).
    :raises Exception: si `list_repo_refs` falla després dels reintents.
    """
    refs = errors.with_retry(
        list_repo_refs, repo_id=dataset_id, repo_type="dataset", token=hf_token, **retry_config
    )
    return list(refs.tags or [])


def fetch_commit_metadata(dataset_id: str, revision: str, hf_token: str | None, retry_config: dict):
    """
    Commit d'una revisió (tag o SHA), amb data i autors. L'API no té
    consulta d'un sol commit: és el primer de `list_repo_commits(revision=...)`.

    :return: el `GitCommitInfo`, o `None` si la llista és buida.
    """
    commits = list(
        errors.with_retry(
            list_repo_commits, repo_id=dataset_id, repo_type="dataset", revision=revision,
            token=hf_token, **retry_config,
        )
    )
    return commits[0] if commits else None


def fetch_tree_size_bytes(dataset_id: str, commit_sha: str, hf_token: str | None, retry_config: dict) -> int:
    """
    Mida real (LFS resolt) de tot l'arbre del repositori en una revisió.

    `list_repo_tree` és un generador: es consumeix sencer DINS de
    `with_retry` perquè els errors HTTP, que surten en iterar, es reintentin.

    :return: bytes totals.
    """
    entries = errors.with_retry(
        lambda: list(
            list_repo_tree(
                repo_id=dataset_id, repo_type="dataset", revision=commit_sha,
                recursive=True, token=hf_token,
            )
        ),
        **retry_config,
    )
    return sum_tree_size(entries)


def _extract_tag_versions(dataset_id: str, hf_token: str | None, retry_config: dict) -> list[dict]:
    """
    Una versió per tag (Criteri A). Si falla la metadada d'un tag, la versió
    es conserva amb `status="commit_error"`.
    """
    tags = fetch_tags(dataset_id, hf_token, retry_config)

    versions = []
    for tag in tags:
        status = "ok"
        commit_date = None
        authors: list[str] = []
        try:
            commit = fetch_commit_metadata(dataset_id, tag.name, hf_token, retry_config)
            if commit is not None:
                commit_date = commit.created_at.isoformat() if hasattr(commit.created_at, "isoformat") else commit.created_at
                authors = list(commit.authors or [])
        except Exception as exc:
            status = "commit_error"
            log.debug(f"_extract_tag_versions: metadada fallida per a {dataset_id}@{tag.name}: {exc}")

        versions.append({
            "version_label": tag.name,
            "version_source": "tag",
            "commit_sha": tag.target_commit,
            "commit_date": commit_date,
            "authors": authors,
            "session_commit_count": 1,
            "status": status,
        })
    return versions


def _extract_session_versions(tabular_commits: list[TabularCommit]) -> list[dict]:
    """
    Una versió per sessió de commits tabulars (Criteri B). No fa cap crida a
    l'API: els commits són els que va trobar la Fase 0.
    """
    sessions = build_sessions_from_commits(tabular_commits)

    return [
        {
            "version_label": f"session-{i}",
            "version_source": "commit_session",
            "commit_sha": session["commit_sha"],
            "commit_date": session["commit_date"],
            "authors": session["authors"],
            "session_commit_count": session["session_commit_count"],
            "status": "ok",
        }
        for i, session in enumerate(sessions, start=1)
    ]


def extract_versions_for_dataset(
    dataset_id: str,
    eligibility_reason: str,
    hf_token: str | None,
    retry_config: dict,
    compute_size: bool = True,
    tabular_commits: list[TabularCommit] | None = None,
) -> list[VersionRow]:
    """
    Versions d'un dataset elegible: per tag si `eligibility_reason` comença
    per "Criteri A", per sessió en qualsevol altre cas.

    :param compute_size: calcula `approx_size_bytes` (1 crida per versió).
    :param tabular_commits: commits tabulars desats per la Fase 0 (Criteri B).
        Si no n'hi ha (report d'una execució anterior), es tornen a buscar.
    :return: `VersionRow` en ordre cronològic.
    :raises Exception: només si falla la crida inicial (tags o commits);
        els errors d'una versió concreta queden al seu `status`.
    """
    if eligibility_reason.startswith("Criteri A"):
        versions = _extract_tag_versions(dataset_id, hf_token, retry_config)
    else:
        if tabular_commits is None:
            tabular_commits = es.find_tabular_commits_again(dataset_id)
        versions = _extract_session_versions(tabular_commits)

    versions = order_versions_by_date(versions)

    rows = []
    for v in versions:
        status = v["status"]
        approx_size_bytes = None
        if compute_size:
            try:
                approx_size_bytes = fetch_tree_size_bytes(dataset_id, v["commit_sha"], hf_token, retry_config)
            except Exception as exc:
                if status == "ok":
                    status = "size_error"
                log.debug(f"extract_versions_for_dataset: mida fallida per a {dataset_id}@{v['commit_sha']}: {exc}")
        elif status == "ok":
            status = "ok_no_size"

        rows.append(VersionRow(
            dataset_id=dataset_id,
            version_label=v["version_label"],
            version_order=v["version_order"],
            version_source=v["version_source"],
            commit_sha=v["commit_sha"],
            commit_date=v["commit_date"],
            authors=format_authors(v["authors"]),
            approx_size_bytes=approx_size_bytes,
            session_commit_count=v["session_commit_count"],
            status=status,
        ))
    return rows


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------


def run_extraction(
    input_csv: str,
    output_csv: str,
    hf_token: str | None,
    retry_config: dict,
    compute_size: bool = True,
) -> dict:
    """
    Extreu les versions de tots els elegibles de `input_csv`, en sèrie, i
    les escriu a `output_csv`. Una fallada de dataset es registra a
    `failures.csv` i no atura la resta.

    :return: resum: `timestamp`, `source_csv`, `n_eligible`, `n_via_tags`,
        `n_via_sessions`, `n_dataset_level_failures`, `n_rows_written`.
    """
    df = pd.read_csv(input_csv)
    eligible = df[df["eligible"] == True]  # noqa: E712
    saved = es.load_tabular_commits(input_csv)  # commits tabulars desats per la Fase 0

    all_rows: list[VersionRow] = []
    n_via_tags = n_via_sessions = n_dataset_level_failures = 0

    for _, row in eligible.iterrows():
        dataset_id = row["dataset_id"]
        eligibility_reason = row["eligibility_reason"]
        log.info(f"Extraient versions: {dataset_id} ({eligibility_reason})")
        try:
            rows = extract_versions_for_dataset(
                dataset_id, eligibility_reason, hf_token, retry_config, compute_size, saved.get(dataset_id)
            )
            all_rows.extend(rows)
            if eligibility_reason.startswith("Criteri A"):
                n_via_tags += 1
            else:
                n_via_sessions += 1
        except Exception as exc:
            n_dataset_level_failures += 1
            category = errors.classify_error(exc)
            retries_attempted = retry_config["max_retries"] if category in errors.RETRIED_CATEGORIES else 0
            errors.append_failure_row(
                FAILURES_LOG_PATH, dataset_id=dataset_id, category=category,
                message=str(exc), retries_attempted=retries_attempted, source="version_extraction",
            )
            log.warning(f"run_extraction: fallada de dataset sencer {dataset_id}: {exc}")

    out_df = pd.DataFrame([asdict(r) for r in all_rows])
    out_df.to_csv(output_csv, index=False, encoding="utf-8")

    return {
        "timestamp": datetime.now().isoformat(),
        "source_csv": os.path.abspath(input_csv),
        "n_eligible": len(eligible),
        "n_via_tags": n_via_tags,
        "n_via_sessions": n_via_sessions,
        "n_dataset_level_failures": n_dataset_level_failures,
        "n_rows_written": len(all_rows),
    }


def parse_args() -> argparse.Namespace:
    """Arguments de la CLI. Sense cap argument mostra l'ajuda i surt."""
    parser = argparse.ArgumentParser(
        description="US-201/US-202: extreu la seqüència de versions (tags o sessions de commits) dels datasets elegibles.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="CSV de datasets elegibles (eligibility_report.csv).")
    parser.add_argument(
        "--skip-size", action="store_true",
        help="No calcular approx_size_bytes (estalvia una crida list_repo_tree per versió).",
    )
    parser.add_argument(
        "--retry-max-attempts", type=int, default=errors.DEFAULT_MAX_RETRIES,
        help="Nombre màxim de reintents davant rate limiting (429) o errors transitoris.",
    )
    parser.add_argument(
        "--retry-base-wait", type=float, default=errors.DEFAULT_BASE_WAIT_S,
        help="Espera inicial (segons) abans del primer reintent; es duplica a cada intent.",
    )
    parser.add_argument(
        "--retry-max-wait", type=float, default=errors.DEFAULT_MAX_WAIT_S,
        help="Espera màxima (segons) entre reintents (topall del backoff exponencial).",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    load_dotenv()
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx", file=sys.stderr)
        sys.exit(1)

    retry_config = {
        "max_retries": args.retry_max_attempts,
        "base_wait_s": args.retry_base_wait,
        "max_wait_s": args.retry_max_wait,
    }

    run_dir = es.new_run_dir()
    FAILURES_LOG_PATH = es.FAILURES_LOG_PATH
    output_csv = os.path.join(run_dir, "versions.csv")

    print(f"Extraient versions per als datasets elegibles de {args.input}...")
    summary = run_extraction(args.input, output_csv, hf_token, retry_config, compute_size=not args.skip_size)

    print(f"\n{'=' * 65}")
    print("  RESUM EXTRACCIÓ DE VERSIONS")
    print(f"{'=' * 65}")
    for k, v in summary.items():
        print(f"  {k:<30} {v}")
    print(f"{'=' * 65}")
    print(f"\n  CSV: {output_csv}")
    print(f"  Fallades (detall): {FAILURES_LOG_PATH}\n")
