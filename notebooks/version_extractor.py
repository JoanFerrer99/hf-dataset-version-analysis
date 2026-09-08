"""
US-201 + US-202: extracció de versions per als datasets elegibles (Fase 1).

Per cada dataset marcat elegible per `eligibility_scan.classify_dataset`
(`data/eligibility_report_<N>_<run_id>.csv`), extreu la seqüència completa i
ordenada de "versions" amb les seves metadades (data, autors, mida
aproximada). El concepte de "versió" depèn de quin criteri va decidir
l'elegibilitat d'aquell dataset -- es reutilitza directament la columna
`eligibility_reason` ja calculada, no es recalcula el criteri aquí:

  - **Criteri A** (tags explícits): cada TAG és una versió (US-201 literal).
    `commit_sha` ve directament de `GitRefInfo.target_commit` (l'API el
    dona sense cap crida addicional); data/autors via UNA crida
    `list_repo_commits(revision=tag_name)` per tag.
  - **Criteri B** (sense tags, elegible per dispersió temporal de commits):
    ~65-70% dels datasets elegibles cauen aquí (verificat sobre
    `eligibility_report_2000_5.csv`: 8/11 amb `num_tags=0`). Una
    implementació literal de "llistar tags" deixaria buida la majoria de
    la població elegible, així que cada SESSIÓ de treball (commits
    substantius agrupats per buit temporal, `validate_eligible.
    cluster_commit_times` -- LA MATEIXA lògica ja validada a US-108, no
    una reimplementació) es tracta com una versió inferida.

Totes dues fonts conflueixen al mateix `VersionRow`, amb `version_source`
explícit ("tag" | "commit_session") perquè el nivell de confiança de cada
fila quedi clar: un tag és un senyal deliberat del mantenidor; una sessió
és una heurística inferida (mateixes cauteles que el Criteri B a
`docs/us108_validation_report.md`).

Nota important sobre l'API: `huggingface_hub` no distingeix autor de
committer com el git natiu -- `GitCommitInfo.authors` és l'únic camp
disponible (`list[str]` de noms d'usuari). El camp `authors` d'aquest
mòdul reflecteix aquesta limitació.

Ús:
  python version_extractor.py --input ../data/eligibility_report_2000_5.csv
  python version_extractor.py --skip-size  # sense list_repo_tree (més ràpid)

Output:
  data/versions_<run_id>.csv, data/versions_summary_<run_id>.json
  data/failures.csv (fallades de dataset sencer, source="version_extraction")
"""

import argparse
import json
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
from eligibility_scan import bare_clone, determine_commit_substantive
from validate_eligible import cluster_commit_times

log = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "data")
DEFAULT_INPUT = os.path.join(OUTPUT_DIR, "eligibility_report_2000_5.csv")
FAILURES_LOG_PATH = os.path.join(OUTPUT_DIR, "failures.csv")

MAX_COMMITS = 50  # mateix límit que classify_dataset()/gather_evidence_for_dataset(), per coherència

RETRY_CONFIG: dict = {
    "max_retries": errors.DEFAULT_MAX_RETRIES,
    "base_wait_s": errors.DEFAULT_BASE_WAIT_S,
    "max_wait_s": errors.DEFAULT_MAX_WAIT_S,
}


@dataclass
class VersionRow:
    """
    Una versió (tag o sessió de commits) d'un dataset elegible.

    :ivar dataset_id: identificador del dataset (`owner/name`).
    :ivar version_label: nom del tag, o `f"session-{n}"` (1 = més antiga)
        per a versions inferides per sessió de commits.
    :ivar version_order: posició cronològica dins d'aquest dataset (1 = més
        antiga), assignada per `order_versions_by_date` -- MAI per ordre
        alfabètic del nom del tag.
    :ivar version_source: `"tag"` (Criteri A) o `"commit_session"`
        (Criteri B) -- indica el nivell de confiança de la fila.
    :ivar commit_sha: SHA del commit representatiu d'aquesta versió (el que
        apunta el tag, o el commit més recent de la sessió).
    :ivar commit_date: data ISO 8601 del commit representatiu, o `None` si
        l'API no la proporciona per aquest commit.
    :ivar authors: noms d'usuari (`GitCommitInfo.authors`) units per coma,
        sense duplicats; `""` si buit o si la crida ha fallat. L'API no
        distingeix autor de committer -- és l'únic camp disponible.
    :ivar approx_size_bytes: suma de `RepoFile.size` (ja resolta per a LFS,
        mai el punter) de tot l'arbre en aquesta revisió. `None` si
        `--skip-size` o si `list_repo_tree` ha fallat per aquesta versió.
    :ivar session_commit_count: nombre de commits agregats en aquesta
        sessió (només rellevant per a `version_source="commit_session"`;
        sempre `1` per a `"tag"`).
    :ivar status: `"ok"`, `"ok_no_size"` (`--skip-size`), `"commit_error"`
        (la metadada del tag ha fallat -- només possible per a `"tag"`) o
        `"size_error"` (`list_repo_tree` ha fallat per aquesta versió).
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
    Assigna `version_order` cronològic (1 = més antiga) a una llista de
    diccionaris de versió d'UN mateix dataset, mutant-los in-place i
    retornant-los ja ordenats.

    :param versions: diccionaris amb almenys la clau `commit_date` (`str`
        ISO 8601, o `None`).
    :return: la mateixa llista de diccionaris, ordenada cronològicament;
        les entrades amb `commit_date=None` s'ordenen al final (mai es
        descarten) i entre elles preserven l'ordre original (`sort` és
        estable).
    """
    ordered = sorted(versions, key=lambda v: (v.get("commit_date") is None, v.get("commit_date") or ""))
    for i, v in enumerate(ordered, start=1):
        v["version_order"] = i
    return ordered


def sum_tree_size(entries: Iterable) -> int:
    """
    Suma la mida (`.size`) de totes les entrades d'un arbre de repositori
    (`list_repo_tree`), ignorant les que no en tenen (`RepoFolder`).

    :param entries: iterable de `RepoFile`/`RepoFolder` (o qualsevol objecte
        amb atribut opcional `.size`).
    :return: suma total en bytes (`0` si `entries` és buit).
    """
    return sum(getattr(e, "size", 0) or 0 for e in entries)


def format_authors(authors: list[str] | None) -> str:
    """
    Uneix una llista de noms d'usuari en una cadena separada per comes,
    eliminant duplicats i preservant l'ordre d'aparició.

    :param authors: `GitCommitInfo.authors`, o `None`/llista buida.
    :return: `""` si `authors` és `None` o buit; en cas contrari, els noms
        únics units per `","`.
    """
    if not authors:
        return ""
    seen: list[str] = []
    for a in authors:
        if a not in seen:
            seen.append(a)
    return ",".join(seen)


def build_sessions_from_commits(commits: list, clone_dir: str | None) -> list[dict]:
    """
    Agrupa una llista de commits en sessions de treball substantives,
    reutilitzant `eligibility_scan.determine_commit_substantive` (mateixa
    lògica que decideix l'elegibilitat via Criteri B) i `validate_eligible.
    cluster_commit_times` (mateix llindar `MIN_SUBSTANTIVE_GAP_HOURS`).

    Els commits substantius sense `created_at` s'ignoren (no poden entrar a
    cap sessió temporal), igual que ja fa `cluster_commit_times` amb els
    `None` -- comportament consistent amb la resta del pipeline.

    :param commits: commits tal com els retorna `list_repo_commits` (amb
        `.title`/`.commit_id`/`.created_at`/`.authors`).
    :param clone_dir: directori d'un clonatge "bare" ja fet (`bare_clone`),
        o `None` si el clonatge ha fallat (es recorre a l'heurística de
        títol per a tots els commits, vegeu `determine_commit_substantive`).
    :return: llista de diccionaris, un per sessió detectada, en ordre
        cronològic (`commit_sha`/`commit_date` són els del commit MÉS
        RECENT de la sessió -- l'estat final d'aquesta versió; `authors` és
        la unió sense duplicats de tots els commits de la sessió;
        `session_commit_count`). Llista buida si cap commit és substantiu o
        cap en té data.
    """
    dated_substantive = [
        c for c in commits
        if getattr(c, "created_at", None) is not None and determine_commit_substantive(c, clone_dir)
    ]
    if not dated_substantive:
        return []

    by_time: dict = {}
    for c in dated_substantive:
        by_time.setdefault(c.created_at, []).append(c)

    session_time_clusters = cluster_commit_times([c.created_at for c in dated_substantive])

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
# Funcions amb crides a l'API (mockejables al namespace del mòdul)
# ---------------------------------------------------------------------------


def fetch_tags(dataset_id: str, hf_token: str | None, retry_config: dict) -> list:
    """
    Llista tots els tags d'un dataset, amb reintent (`list_repo_refs` és
    "eager": fa la crida HTTP immediatament, no cal cap tancament especial
    a diferència de `fetch_tree_size_bytes`).

    :param dataset_id: identificador del dataset (`owner/name`).
    :param hf_token: token HF, passat explícitament a la crida.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :return: `refs.tags` (`list[GitRefInfo]`, cadascun amb `.name` i
        `.target_commit`), o `[]` si el dataset no en té cap.
    :raises Exception: repropaga qualsevol excepció de `list_repo_refs`
        després d'exhaurir els reintents -- el cridant ho tracta com una
        fallada de dataset sencer.
    """
    refs = errors.with_retry(
        list_repo_refs, repo_id=dataset_id, repo_type="dataset", token=hf_token, **retry_config
    )
    return list(refs.tags or [])


def fetch_commit_metadata(dataset_id: str, revision: str, hf_token: str | None, retry_config: dict):
    """
    Obté el commit corresponent a una revisió concreta (tag o SHA), amb
    data i autors. L'API no exposa una consulta "un sol commit"
    independent: `list_repo_commits(revision=...)` retorna l'historial que
    acaba en aquesta revisió (el primer element és el commit `revision`
    mateix).

    :param dataset_id: identificador del dataset (`owner/name`).
    :param revision: nom del tag (o SHA) a consultar.
    :param hf_token: token HF, passat explícitament a la crida.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :return: el primer `GitCommitInfo` de la llista retornada, o `None` si
        la llista és buida (no hauria de passar per a un tag vàlid, però es
        tracta com a cas possible).
    :raises Exception: repropaga qualsevol excepció de `list_repo_commits`
        després d'exhaurir els reintents -- el cridant ho tracta com un
        error parcial d'aquesta versió (`status="commit_error"`), no com
        una fallada de tot el dataset.
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
    Suma la mida real de tot l'arbre del repositori en una revisió
    concreta, via `list_repo_tree(..., recursive=True)`.

    DISSENY -- `list_repo_tree` és un GENERADOR (`Iterable[RepoFile |
    RepoFolder]` lazy: el seu propi docstring a `huggingface_hub` mostra
    literalment `<generator object HfApi.list_repo_tree ...>` abans de
    consumir-lo). Si es passés la funció tal qual a `errors.with_retry
    (list_repo_tree, ...)`, `with_retry` només rebria l'objecte generador
    (encara sense fer cap crida HTTP) i mai capturaria una excepció real --
    aquesta sortiria més tard, en iterar-lo FORA del `try/except` de
    `with_retry`, sense cap reintent. Per això es passa un tancament de
    mida zero que el CONSUMEIX SENCER (`list(...)`) dins de la crida
    reintentada.

    `expand=True` no es fa servir: només aporta `last_commit`/`security`
    (i encareix la crida al servidor, paginant de 50 en 50 en lloc de
    1000), cap dels dos necessari aquí -- `RepoFile.size` ja és la mida
    real (resolta per a LFS, no el punter) sense `expand`.

    :param dataset_id: identificador del dataset (`owner/name`).
    :param commit_sha: revisió (SHA de commit) a inspeccionar.
    :param hf_token: token HF, passat explícitament a la crida.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :return: suma total en bytes de `RepoFile.size` de tot l'arbre.
    :raises Exception: repropaga qualsevol excepció després d'exhaurir els
        reintents -- el cridant ho tracta com `status="size_error"` per a
        aquesta versió concreta, no com una fallada de tot el dataset.
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


# ---------------------------------------------------------------------------
# Orquestració per dataset
# ---------------------------------------------------------------------------


def _extract_tag_versions(dataset_id: str, hf_token: str | None, retry_config: dict) -> list[dict]:
    """
    Versions = tags (Criteri A). Cada tag dona una versió; si la metadada
    (data/autors) d'un tag concret falla, la versió es conserva amb
    `status="commit_error"` en lloc de descartar-se -- un error puntual no
    hauria d'esborrar la resta de versions conegudes del dataset.

    :param dataset_id: identificador del dataset (`owner/name`).
    :param hf_token: token HF.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :return: llista de diccionaris de versió (sense `version_order` encara).
    :raises Exception: propaga qualsevol fallada de `fetch_tags` (fallada
        inicial, tot el dataset es tracta com a error).
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


def _extract_session_versions(dataset_id: str, hf_token: str | None, retry_config: dict) -> list[dict]:
    """
    Versions = sessions de treball (Criteri B), via `build_sessions_from_
    commits` sobre fins a `MAX_COMMITS` commits (mateix límit que
    `classify_dataset`/`gather_evidence_for_dataset`, per coherència amb el
    que ja va decidir l'elegibilitat d'aquest dataset).

    :param dataset_id: identificador del dataset (`owner/name`).
    :param hf_token: token HF.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :return: llista de diccionaris de versió (sense `version_order` encara);
        `[]` si no s'ha detectat cap sessió (no hauria de passar per a un
        dataset elegible via Criteri B, ja que aquest va exigir >=2 commits
        substantius dispersos -- indicaria una divergència respecte al run
        d'elegibilitat original, p.e. el dataset ha canviat des d'aleshores).
    :raises Exception: propaga qualsevol fallada de `list_repo_commits`
        inicial (fallada inicial, tot el dataset es tracta com a error).
    """
    commits = list(
        errors.with_retry(
            list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=hf_token, **retry_config,
        )
    )[:MAX_COMMITS]

    with bare_clone(dataset_id) as clone_dir:
        sessions = build_sessions_from_commits(commits, clone_dir)

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
) -> list[VersionRow]:
    """
    Extreu totes les versions d'UN dataset elegible, bifurcant segons quin
    criteri el va fer elegible (`eligibility_reason`, tal com consta a
    `data/eligibility_report_*.csv` -- no es recalcula el criteri aquí).

    :param dataset_id: identificador del dataset (`owner/name`).
    :param eligibility_reason: motiu d'elegibilitat original; `"Criteri A"`
        -> versions per tag, qualsevol altre valor (`"Criteri B..."`) ->
        versions per sessió de commits.
    :param hf_token: token HF.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :param compute_size: si `True` (per defecte), calcula `approx_size_
        bytes` per a cada versió via `fetch_tree_size_bytes` (una crida
        `list_repo_tree` per versió). Si `False`, s'estalvien aquestes
        crides i `status="ok_no_size"`.
    :return: llista de `VersionRow` ordenada cronològicament
        (`order_versions_by_date`); `[]` si el dataset no té cap versió
        detectable (0 tags, o 0 sessions -- aquest segon cas seria una
        divergència respecte al run d'elegibilitat original).
    :raises Exception: propaga qualsevol fallada de la crida INICIAL
        (`fetch_tags` o `list_repo_commits`) -- el cridant (`run_extraction`)
        ho distingeix de "legítimament 0 versions" i ho registra com a
        fallada de tot el dataset. Els errors PARCIALS (metadada d'un tag,
        o mida d'una versió concreta) NO es propaguen: es reflecteixen en
        `status` de la fila afectada, la resta de versions es conserven.
    """
    if eligibility_reason.startswith("Criteri A"):
        versions = _extract_tag_versions(dataset_id, hf_token, retry_config)
    else:
        versions = _extract_session_versions(dataset_id, hf_token, retry_config)

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
    Llegeix els datasets elegibles de `input_csv` i n'extreu les versions
    seqüencialment (sense `ThreadPoolExecutor`: la població elegible és
    petita -- 11 datasets a `eligibility_report_2000_5.csv` -- cost
    trivial fins i tot en sèrie, evita reobrir preguntes de concurrència de
    `bare_clone` sense cap benefici real a aquesta escala). Una fallada de
    dataset sencer es registra i NO atura la resta de l'execució.

    :param input_csv: ruta del CSV de datasets elegibles (`eligibility_
        report_*.csv`, amb columnes `dataset_id`/`eligible`/
        `eligibility_reason`).
    :param output_csv: ruta on escriure el CSV de versions (una fila per
        `VersionRow`).
    :param hf_token: token HF.
    :param retry_config: mateix format que `RETRY_CONFIG`.
    :param compute_size: es passa tal qual a `extract_versions_for_dataset`.
    :return: diccionari de resum: `timestamp`, `source_csv`, `n_eligible`,
        `n_via_tags`, `n_via_sessions`, `n_dataset_level_failures`,
        `n_rows_written`. També s'escriu a `output_csv` com a efecte
        secundari (fallades parcials es reflecteixen a `data/failures.csv`
        via `errors.append_failure_row`, `source="version_extraction"`).
    """
    df = pd.read_csv(input_csv)
    eligible = df[df["eligible"] == True]  # noqa: E712

    all_rows: list[VersionRow] = []
    n_via_tags = n_via_sessions = n_dataset_level_failures = 0

    for _, row in eligible.iterrows():
        dataset_id = row["dataset_id"]
        eligibility_reason = row["eligibility_reason"]
        log.info(f"Extraient versions: {dataset_id} ({eligibility_reason})")
        try:
            rows = extract_versions_for_dataset(
                dataset_id, eligibility_reason, hf_token, retry_config, compute_size
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


def get_next_run_id(output_dir: str, prefix: str = "versions_") -> int:
    """
    Determina el següent número de run inspeccionant els `<prefix><run_id>
    .csv` ja existents a `output_dir`, perquè cada execució generi sortides
    numerades sense sobreescriure les anteriors (adaptació d'`eligibility_
    scan.get_next_run_id`, que va lligat al patró `<sample_size>_<run_id>`
    -- aquí no hi ha `sample_size`).

    :param output_dir: directori on es guarden els resultats (`OUTPUT_DIR`).
    :param prefix: prefix dels fitxers a considerar.
    :return: el `run_id` més alt trobat + 1 (o `1` si no n'hi ha cap).
    """
    max_id = 0
    for filename in os.listdir(output_dir):
        if filename.startswith(prefix) and filename.endswith(".csv"):
            id_str = filename[len(prefix):-4]
            try:
                max_id = max(max_id, int(id_str))
            except ValueError:
                pass
    return max_id + 1


def parse_args() -> argparse.Namespace:
    """
    Defineix i parseja els arguments de la CLI. Sense arguments, mostra
    l'ajuda i surt (mateix guard que `eligibility_scan.parse_args`).

    :return: `argparse.Namespace` amb `input`, `output`, `skip_size`,
        `retry_max_attempts`, `retry_base_wait`, `retry_max_wait`.
    """
    parser = argparse.ArgumentParser(
        description="US-201/US-202: extreu la seqüència de versions (tags o sessions de commits) dels datasets elegibles.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="CSV de datasets elegibles (eligibility_report_*.csv).")
    parser.add_argument(
        "--output", default=None,
        help="CSV de sortida. Per defecte: data/versions_<run_id>.csv, numerat automàticament.",
    )
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

    run_id = get_next_run_id(OUTPUT_DIR)
    output_csv = args.output or os.path.join(OUTPUT_DIR, f"versions_{run_id}.csv")

    print(f"Extraient versions per als datasets elegibles de {args.input}...")
    summary = run_extraction(args.input, output_csv, hf_token, retry_config, compute_size=not args.skip_size)

    summary_path = os.path.join(OUTPUT_DIR, f"versions_summary_{run_id}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 65}")
    print("  RESUM EXTRACCIÓ DE VERSIONS")
    print(f"{'=' * 65}")
    for k, v in summary.items():
        print(f"  {k:<30} {v}")
    print(f"{'=' * 65}")
    print(f"\n  CSV:  {output_csv}")
    print(f"  JSON: {summary_path}")
    print(f"  Fallades (detall): {FAILURES_LOG_PATH}\n")
