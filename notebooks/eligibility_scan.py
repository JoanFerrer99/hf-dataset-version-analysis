"""
Fase 0 (mostreig + elegibilitat) i Fase 2 (classificació de canvis).

  - Mostreig: reservoir sampling uniforme sobre tota la població de HF.
  - Elegibilitat: Criteri A (>=2 tags + >=2 commits substantius) o
    Criteri B (>=2 branches + >=2 sessions de commits substantius).
  - Classificació (`run_classification`): codis de la taxonomia per als
    datasets elegibles d'un CSV ja generat.

Ús:
  python eligibility_scan.py --sample-size 2000 --threads 4 --seed 42
  python eligibility_scan.py --sample-size 200 --max-scanned 5000  # prova ràpida, esbiaixada
  python eligibility_scan.py --classify-eligible ../data/eligibility_report_2000_5.csv

Output:
  data/eligibility_report_<N>_<run_id>.csv, data/funnel_summary_<N>_<run_id>.json
  data/change_classification_<run_id>.csv (amb --classify-eligible)
  data/failures.csv
"""

import os
import sys
import json
import random
import shutil
import argparse
import logging
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Iterator

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

import change_diff
import errors
from errors import ErrorCategory


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

NON_SUBSTANTIVE_FILES = {
    "README.md",
    ".gitattributes",
    "dataset_infos.json",
    ".gitignore",
    "LICENSE",
    "LICENSE.md",
    "CITATION.cff",
    ".github",
    ".gitmodules",
    "setup.py",
    "setup.cfg",
    "changelog.json",
}

NON_SUBSTANTIVE_PATH_PREFIXES = ("meta/", "meta_data/", ".github/")

NON_SUBSTANTIVE_EXTENSIONS = (".md", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".lock")

SUBSTANTIVE_DATA_EXTENSIONS = (
    ".parquet", ".csv", ".tsv", ".arrow", ".feather", ".orc",
    ".jsonl", ".ndjson",
    ".npy", ".npz", ".pt", ".pth", ".safetensors", ".h5", ".hdf5",
    ".tar.gz", ".tgz", ".zip", ".tar",
    ".mp4", ".avi", ".mov", ".wav", ".mp3", ".flac",
    ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp",
)

NON_SUBSTANTIVE_TITLE_KEYWORDS = {
    "readme", "metadata", ".gitattributes", "dataset_infos",
    "license", "citation", "typo", "fix typo", "update docs",
}

MIN_SUBSTANTIVE_GAP_HOURS = 6.0
GIT_CLONE_TIMEOUT_S = 30
GIT_SHOW_TIMEOUT_S = 10

_git_missing_warned = False

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FAILURES_LOG_PATH = os.path.join(OUTPUT_DIR, "failures.csv")

RETRY_CONFIG: dict = dict(errors.DEFAULT_RETRY_CONFIG)

load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    log.error("Cap token HF detectat. Crea un fitxer .env amb HF_TOKEN=hf_xxx")
    sys.exit(1)

api = HfApi(token=HF_TOKEN)
log.info("Token HF carregat correctament.")


def iter_all_dataset_ids():
    """
    Genera l'id de cada dataset habilitat de HF, sense ordenar.
    `expand=["disabled"]` redueix el payload per dataset al mínim.

    :return: generador de `str` (`owner/name`). Si la paginació falla, es
        registra l'error i el generador s'atura (no es propaga).
    """
    try:
        for dataset in api.list_datasets(limit=None, expand=["disabled"]):
            if dataset.disabled:
                continue
            yield dataset.id
    except Exception as exc:
        log.error(f"Error iterant datasets: {exc}")


def reservoir_sample_dataset_ids(
    dataset_iter: Iterable,
    sample_size: int,
    max_scanned: int | None = None,
    rng: random.Random | None = None,
    show_progress: bool = True,
) -> tuple[list[str], int]:
    """
    Algorisme R de Vitter: cada dataset té probabilitat `sample_size / N`
    de ser seleccionat. Memòria O(sample_size), mai la població sencera.

    :param dataset_iter: iterable d'ids o d'objectes amb `.id`.
    :param sample_size: mida del reservori.
    :param max_scanned: límit d'elements a recórrer (només proves; esbiaixa).
    :param rng: font d'aleatorietat (per a tests deterministes).
    :param show_progress: barra `tqdm`.
    :return: `(ids seleccionats, nombre d'elements vistos)`.
    """
    rng = rng or random
    reservoir: list[str] = []
    n_seen = 0

    pbar = None
    if show_progress:
        pbar = tqdm(
            desc=f"Escaneig reservoir sampling (objectiu: {sample_size} datasets)",
            unit=" datasets", dynamic_ncols=True,
        )

    try:
        for item in dataset_iter:
            n_seen += 1
            dataset_id = item.id if hasattr(item, "id") else str(item)

            if len(reservoir) < sample_size:
                reservoir.append(dataset_id)
            else:
                j = rng.randint(0, n_seen - 1)
                if j < sample_size:
                    reservoir[j] = dataset_id

            if pbar is not None:
                pbar.update(1)
                pbar.set_postfix({"reservori": len(reservoir), "vist": n_seen})

            if max_scanned and n_seen >= max_scanned:
                break
    finally:
        if pbar is not None:
            pbar.close()

    log.info(f"Escaneig completat: {n_seen} datasets vistos, {len(reservoir)} a la mostra.")
    return reservoir, n_seen

def classify_dataset(dataset_id: str, tags_only: bool = False, classify_changes: bool = False) -> dict:
    """
    Decideix si un dataset és elegible i, opcionalment, en classifica els
    canvis.

    - Criteri A: >=2 tags i >=2 commits substantius.
    - Criteri B: >=2 branches i commits substantius en >=2 sessions.

    Recorre fins a 50 commits sobre un clon bare. Sense `classify_changes`,
    retorna tan bon punt el dataset és elegible.

    :param dataset_id: dataset (`owner/name`).
    :param tags_only: només permet el Criteri A.
    :param classify_changes: classifica també els canvis dels fitxers
        tabulars. Unitat de canvi: commit vs el seu pare (Criteri A) o
        límit entre sessions (Criteri B). Descarrega contingut real: només
        per a datasets ja elegibles.
    :return: fila del report: `dataset_id`, `num_tags`, `num_branches`,
        `num_commits_substantive`, `eligible`, `eligibility_reason`,
        `status` (`classified`/`access_restricted`/`error`),
        `error_category`, `error` (truncat a 120 caràcters) i
        `change_labels` (`[]` si `classify_changes=False`).
    """
    result = {
        "dataset_id": dataset_id,
        "num_tags": 0,
        "num_branches": 0,
        "num_commits_substantive": 0,
        "eligible": False,
        "eligibility_reason": "",
        "status": "classified",
        "error_category": "",
        "error": "",
        "change_labels": [],
    }

    try:
        refs = errors.with_retry(
            list_repo_refs, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
            **RETRY_CONFIG,
        )
        tags = refs.tags if refs.tags else []
        branches = refs.branches if refs.branches else []
        result["num_tags"] = len(tags)
        result["num_branches"] = len(branches)

        commits_scanned = 0
        num_commits_substantive = 0
        substantive_times: list[datetime] = []
        substantive_commits: list[tuple[int, object, list[str]]] = []

        if len(tags) >= 2 or (not tags_only and len(branches) >= 2):
            commits = errors.with_retry(
                list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
                **RETRY_CONFIG,
            )
            with bare_clone(dataset_id) as clone_dir:
                for i, commit in enumerate(commits):
                    commits_scanned += 1

                    is_substantive, changed_paths = determine_commit_substantive_with_paths(commit, clone_dir)
                    if is_substantive:
                        num_commits_substantive += 1
                        commit_time = getattr(commit, "created_at", None)
                        if commit_time is not None:
                            substantive_times.append(commit_time)
                        if classify_changes and changed_paths:
                            substantive_commits.append((i, commit, changed_paths))

                    if not result["eligible"]:
                        if len(tags) >= 2 and num_commits_substantive >= 2:
                            result["eligible"] = True
                            result["eligibility_reason"] = "Criteri A: tags>=2 amb commits substantius"
                        elif not tags_only and len(branches) >= 2 and has_time_dispersed_substantive_commits(
                            substantive_times
                        ):
                            result["eligible"] = True
                            result["eligibility_reason"] = (
                                "Criteri B: substantive_commits>=2 dispersos "
                                f">={MIN_SUBSTANTIVE_GAP_HOURS}h"
                            )

                    if result["eligible"] and not classify_changes:
                        result["num_commits_substantive"] = num_commits_substantive
                        return result

                    if commits_scanned >= 50:
                        break

            if classify_changes and substantive_commits:
                if result["eligibility_reason"].startswith("Criteri B"):
                    result["change_labels"] = classify_session_boundary_tabular_changes(
                        dataset_id, substantive_commits, HF_TOKEN, RETRY_CONFIG,
                    )
                else:
                    for i, commit, changed_paths in substantive_commits:
                        if i + 1 < len(commits):
                            parent_commit = commits[i + 1]
                            result["change_labels"].extend(
                                classify_commit_tabular_changes(
                                    dataset_id, changed_paths, parent_commit.commit_id, commit.commit_id, HF_TOKEN,
                                    RETRY_CONFIG,
                                )
                            )

        result["num_commits_substantive"] = num_commits_substantive
        if not result["eligible"]:
            result["eligibility_reason"] = (
                "ineligible: tags<2 i "
                f"(branches<2 o substantive_commits<2 amb {commits_scanned} commits revisats)"
            )

    except Exception as exc:
        category = errors.classify_error(exc)
        retries_attempted = RETRY_CONFIG["max_retries"] if category in errors.RETRIED_CATEGORIES else 0

        result["error_category"] = category.value
        result["error"] = str(exc)[:120]
        result["status"] = (
            "access_restricted" if category == ErrorCategory.ACCESS_RESTRICTED else "error"
        )

        errors.append_failure_row(
            FAILURES_LOG_PATH,
            dataset_id=dataset_id,
            category=category,
            message=str(exc),
            retries_attempted=retries_attempted,
            source="sampling",
        )

    return result


def is_substantive_commit(commit_title: str) -> bool:
    """
    Heurística de reserva quan no hi ha clon: el commit és substantiu si el
    títol no conté cap paraula de `NON_SUBSTANTIVE_TITLE_KEYWORDS`.

    :param commit_title: títol del commit (pot ser `None`).
    :return: `False` si el títol és buit o conté alguna paraula clau.
    """
    if not commit_title:
        return False

    title_lower = commit_title.lower()

    for keyword in NON_SUBSTANTIVE_TITLE_KEYWORDS:
        if keyword in title_lower:
            return False

    return True


def is_substantive_path(path: str) -> bool:
    """
    Decideix si un fitxer és dades reals (i no metadada), en aquest ordre:

    1. Prefix a `NON_SUBSTANTIVE_PATH_PREFIXES` -> no (fins i tot un `.parquet`).
    2. Nom a `NON_SUBSTANTIVE_FILES` o extensió a `NON_SUBSTANTIVE_EXTENSIONS` -> no.
    3. Extensió a `SUBSTANTIVE_DATA_EXTENSIONS` -> sí.
    4. Qualsevol altre cas -> sí per defecte (registrat amb `log.debug`).

    :param path: ruta relativa dins del repositori.
    """
    if path.startswith(NON_SUBSTANTIVE_PATH_PREFIXES):
        return False

    basename = path.rsplit("/", 1)[-1]
    if basename in NON_SUBSTANTIVE_FILES:
        return False
    if basename.endswith(NON_SUBSTANTIVE_EXTENSIONS):
        return False
    if not basename.endswith(SUBSTANTIVE_DATA_EXTENSIONS):
        log.debug(f"is_substantive_path: extensió no classificada, fail-open: {path}")

    return True


@contextmanager
def bare_clone(dataset_id: str) -> Iterator[str | None]:
    """
    Clona el repositori amb `git clone --bare --filter=blob:none`: només
    l'historial (commits, arbres, noms de fitxer), cap contingut. El token
    va per variables d'entorn de git, no a la línia d'ordres, perquè no
    surti a `ps`. El directori temporal s'esborra en sortir.

    :param dataset_id: dataset (`owner/name`).
    :yield: ruta del clon, o `None` si ha fallat (el cridant recorre a
        l'heurística de títol). Si falta `git`, s'avisa un sol cop per procés.
    """
    global _git_missing_warned

    tmp_dir = tempfile.mkdtemp(prefix="hf_bare_clone_")
    url = f"https://huggingface.co/datasets/{dataset_id}"
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {HF_TOKEN}",
    }
    try:
        result = subprocess.run(
            ["git", "clone", "--bare", "--filter=blob:none", "--quiet", url, tmp_dir],
            env=env, capture_output=True, timeout=GIT_CLONE_TIMEOUT_S,
        )
        if result.returncode != 0:
            log.debug(f"bare_clone: git clone ha fallat per a {dataset_id} (retorn {result.returncode})")
        yield tmp_dir if result.returncode == 0 else None
    except FileNotFoundError:
        if not _git_missing_warned:
            log.error(
                "bare_clone: 'git' no és al PATH es desactiva per a TOTA la " \
                "resta de l'escaneig i es recorre a l'heurística de títol per a cada dataset. "
                "Instal·la 'git' al sistema/imatge Docker."
            )
            _git_missing_warned = True
        yield None
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug(f"bare_clone: error clonant {dataset_id}: {exc}")
        yield None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def get_changed_files(clone_dir: str, commit_sha: str) -> list[str] | None:
    """
    Fitxers tocats per un commit (`git show --name-status`), en local sobre
    el clon bare.

    :return: llista de rutes, o `None` si `git` falla.
    """
    try:
        result = subprocess.run(
            ["git", "show", "--name-status", "--format=", commit_sha],
            cwd=clone_dir, capture_output=True, text=True, timeout=GIT_SHOW_TIMEOUT_S,
        )
        if result.returncode != 0:
            return None

        paths = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            columns = line.split("\t")
            if len(columns) >= 2:
                paths.append(columns[-1])
        return paths
    except (subprocess.TimeoutExpired, OSError):
        return None


def determine_commit_substantive_with_paths(commit, clone_dir: str | None) -> tuple[bool, list[str] | None]:
    """
    Un commit és substantiu si toca algun fitxer substantiu. Si no hi ha
    clon o `git show` falla, s'usa l'heurística de títol.

    :param commit: commit de `list_repo_commits`.
    :param clone_dir: clon bare, o `None`.
    :return: `(és_substantiu, fitxers_tocats)`; `fitxers_tocats` és `None`
        si s'ha fet servir l'heurística de títol.
    """
    if clone_dir is not None:
        changed_paths = get_changed_files(clone_dir, commit.commit_id)
        if changed_paths is not None:
            return any(is_substantive_path(p) for p in changed_paths), changed_paths

    return is_substantive_commit(commit.title), None


def determine_commit_substantive(commit, clone_dir: str | None) -> bool:
    """Com `determine_commit_substantive_with_paths`, només el booleà."""
    return determine_commit_substantive_with_paths(commit, clone_dir)[0]


MAX_TABULAR_FILES_PER_COMMIT = 5


def classify_commit_tabular_changes(
    dataset_id: str, changed_paths: list[str], version_from: str, version_to: str, hf_token: str | None,
    retry_config: dict,
) -> list[dict]:
    """
    Classifica una unitat de canvi: descarrega cada fitxer tabular canviat
    (com a màxim `MAX_TABULAR_FILES_PER_COMMIT`) a les dues revisions i el
    compara.

    :param changed_paths: fitxers tocats; els no tabulars s'ignoren.
    :param version_from: SHA de la revisió anterior.
    :param version_to: SHA de la revisió posterior.
    :param retry_config: configuració de reintent (també per a les descàrregues).
    :return: un `dict` (`ChangeLabel`) per codi detectat en algun fitxer.
    """
    labels = []
    tabular_paths = [p for p in changed_paths if change_diff.is_tabular_path(p)]
    for path in tabular_paths[:MAX_TABULAR_FILES_PER_COMMIT]:
        before_df = change_diff.download_tabular_file_at_revision(dataset_id, path, version_from, hf_token, retry_config)
        after_df = change_diff.download_tabular_file_at_revision(dataset_id, path, version_to, hf_token, retry_config)
        for label in change_diff.classify_file_change(dataset_id, before_df, after_df, version_from, version_to):
            labels.append(asdict(label))
    return labels


def group_substantive_commits_into_sessions(
    substantive_commits: list[tuple[int, object, list[str]]],
) -> list[list[tuple[int, object, list[str]]]]:
    """
    Agrupa commits substantius en sessions amb `cluster_commit_times`.

    :param substantive_commits: triples `(índex, commit, fitxers_tocats)`;
        els commits sense `created_at` s'ignoren.
    :return: sessions de la més recent a la més antiga (sense ordre dins
        de cada sessió).
    """
    dated = [t for t in substantive_commits if getattr(t[1], "created_at", None) is not None]
    if not dated:
        return []

    by_time: dict[datetime, list[tuple[int, object, list[str]]]] = {}
    for triple in dated:
        by_time.setdefault(triple[1].created_at, []).append(triple)

    time_clusters = cluster_commit_times([triple[1].created_at for triple in dated])
    return [
        [triple for t in time_cluster for triple in by_time[t]]
        for time_cluster in reversed(time_clusters)
    ]


def classify_session_boundary_tabular_changes(
    dataset_id: str, substantive_commits: list[tuple[int, object, list[str]]], hf_token: str | None,
    retry_config: dict,
) -> list[dict]:
    """
    Classificació per al Criteri B: per cada parell de sessions consecutives
    compara el commit més recent de cada una, sobre la unió dels fitxers
    tocats a la sessió posterior. Els commits dins d'una sessió no es
    comparen entre ells.

    :return: etiquetes acumulades de `classify_commit_tabular_changes`.
    """
    sessions = group_substantive_commits_into_sessions(substantive_commits)
    if len(sessions) < 2:
        return []

    labels: list[dict] = []
    for newer_session, older_session in zip(sessions, sessions[1:]):
        version_to_commit = max(newer_session, key=lambda triple: triple[1].created_at)[1]
        version_from_commit = max(older_session, key=lambda triple: triple[1].created_at)[1]
        changed_paths = sorted({path for _, _, paths in newer_session for path in paths})
        labels.extend(
            classify_commit_tabular_changes(
                dataset_id, changed_paths, version_from_commit.commit_id, version_to_commit.commit_id,
                hf_token, retry_config,
            )
        )
    return labels


def has_time_dispersed_substantive_commits(
    commit_times: list[datetime | None], min_gap_hours: float = MIN_SUBSTANTIVE_GAP_HOURS
) -> bool:
    """
    Condició temporal del Criteri B: les dates formen >=2 sessions.

    :param commit_times: dates dels commits substantius (`None` s'ignoren).
    :param min_gap_hours: buit mínim entre sessions.
    """
    return len(cluster_commit_times(commit_times, gap_hours=min_gap_hours)) >= 2


def cluster_commit_times(
    commit_times: list[datetime | None], gap_hours: float = MIN_SUBSTANTIVE_GAP_HOURS
) -> list[list[datetime]]:
    """
    Agrupa dates en sessions: ordenades, una sessió nova comença quan dos
    commits consecutius estan separats per MÉS de `gap_hours`. És l'única
    definició de sessió del pipeline (la fan servir les Fases 0, 1 i 2).

    :param commit_times: dates en qualsevol ordre; `None` s'ignoren.
    :return: sessions en ordre cronològic.
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


def classify_dataset_safe(args: tuple) -> dict | None:
    """
    `classify_dataset` per al pool de threads: captura qualsevol excepció
    no prevista perquè no aturi el pool.

    :param args: `(idx, dataset_id, tags_only)`.
    :return: la fila, o `None` si hi ha hagut una excepció inesperada.
    """
    idx, dataset_id, tags_only = args
    try:
        return classify_dataset(dataset_id, tags_only=tags_only)
    except Exception as exc:
        log.warning(f"[{idx}] Error inesperat classificant {dataset_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Estadístiques agregades de l'embut d'elegibilitat
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FunnelCounts:
    """
    Recomptes bruts d'una execució.

    :ivar total_scanned: mida de la població recorreguda.
    :ivar eligible: classificats amb èxit i elegibles.
    :ivar ineligible: classificats amb èxit i no elegibles.
    :ivar access_restricted: 403.
    :ivar errors: qualsevol altra fallada definitiva.
    """

    total_scanned: int
    eligible: int
    ineligible: int
    access_restricted: int
    errors: int


def compute_funnel_stats(counts: FunnelCounts) -> dict:
    """
    Mètriques de l'embut.

    - `eligible_proportion`: elegibles / classificats amb èxit (sense 403
      ni errors al denominador).
    - `eligible_proportion_of_attempts`: elegibles / tots els intents.
    - `estimated_eligible_in_population`: extrapolació a `total_scanned`,
      assumint que els inaccessibles tenen la mateixa proporció.

    :return: els recomptes més les tres mètriques (0 si el denominador és 0).
    """
    denom_valid = counts.eligible + counts.ineligible
    denom_attempts = denom_valid + counts.access_restricted + counts.errors

    eligible_proportion = round(counts.eligible / denom_valid, 4) if denom_valid else 0.0

    return {
        "eligible": counts.eligible,
        "ineligible": counts.ineligible,
        "access_restricted": counts.access_restricted,
        "errors": counts.errors,
        "eligible_proportion": eligible_proportion,
        "eligible_proportion_of_attempts": (
            round(counts.eligible / denom_attempts, 4) if denom_attempts else 0.0
        ),
        "estimated_eligible_in_population": (
            int(round(eligible_proportion * counts.total_scanned)) if denom_valid else 0
        ),
    }

def get_next_run_id(output_dir: str, sample_size: int) -> int:
    """
    Següent número de run per a aquest `sample_size`, a partir dels
    `funnel_summary_<sample_size>_<id>.json` existents.

    :return: id més alt + 1 (1 si no n'hi ha cap).
    """
    max_id = 0
    prefix = f"funnel_summary_{sample_size}_"

    for filename in os.listdir(output_dir):
        if filename.startswith(prefix) and filename.endswith(".json"):
            try:
                id_str = filename[len(prefix):-5]
                current_id = int(id_str)
                if current_id > max_id:
                    max_id = current_id
            except ValueError:
                pass

    return max_id + 1


def write_results(rows: list[dict], run_id: int, sample_size: int, total_scanned: int) -> tuple[str, str, dict]:
    """
    Escriu el report per dataset (CSV, sense `change_labels`) i el resum de
    l'embut (JSON).

    :param rows: files de `classify_dataset`.
    :param run_id: número de run.
    :param sample_size: mida demanada (va al nom dels fitxers).
    :param total_scanned: mida de la població recorreguda.
    :return: `(csv_path, json_path, summary)`.
    """
    df = pd.DataFrame(rows)

    csv_path = os.path.join(OUTPUT_DIR, f"eligibility_report_{sample_size}_{run_id}.csv")
    df.drop(columns=["change_labels"], errors="ignore").to_csv(csv_path, index=False, encoding="utf-8")

    total = len(rows)
    eligible = int(df["eligible"].sum())
    access_restricted = int((df["status"] == "access_restricted").sum())
    error_count = int((df["status"] == "error").sum())
    ineligible = total - eligible - access_restricted - error_count

    counts = FunnelCounts(
        total_scanned=total_scanned,
        eligible=eligible,
        ineligible=ineligible,
        access_restricted=access_restricted,
        errors=error_count,
    )

    summary = {
        "timestamp": datetime.now().isoformat(),
        "sampling_method": "reservoir_sampling_R_Vitter_uniform_no_bias",
        "sample_size": total,
        "population_scanned": total_scanned,
        "eligible_total": eligible,
        "eligible_Criteri_A": int(df["eligibility_reason"].str.startswith("Criteri A").sum()),
        "eligible_Criteri_B": int(df["eligibility_reason"].str.startswith("Criteri B").sum()),
        **compute_funnel_stats(counts),
    }

    json_path = os.path.join(OUTPUT_DIR, f"funnel_summary_{sample_size}_{run_id}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return csv_path, json_path, summary


# ---------------------------------------------------------------------------
# Orquestrador — Mode mostreig
# ---------------------------------------------------------------------------

def run_sampling(
    sample_size: int, max_scanned: int | None, num_threads: int, tags_only: bool = False
) -> tuple[str, str, dict]:
    """
    Fase 0 completa: mostreig, classificació d'elegibilitat en paral·lel i
    escriptura de resultats. No classifica canvis.

    :param sample_size: mida de la mostra.
    :param max_scanned: límit de població a recórrer (proves).
    :param num_threads: threads per a la classificació.
    :param tags_only: es passa a `classify_dataset`.
    :return: `(csv_path, json_path, summary)` de `write_results`.
    """
    log.info(f"FASE 1: Reservoir sampling (objectiu={sample_size}, max_scanned={max_scanned})")
    dataset_ids, total_scanned = reservoir_sample_dataset_ids(
        iter_all_dataset_ids(), sample_size, max_scanned
    )
    log.info(f"Mostra obtinguda: {len(dataset_ids)} datasets de {total_scanned} escanejats.")

    log.info(f"FASE 2: Classificant elegibilitat ({num_threads} threads, tags_only={tags_only})...")
    indexed = [(i, ds_id, tags_only) for i, ds_id in enumerate(dataset_ids)]
    rows: list[dict] = []

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(classify_dataset_safe, item): item for item in indexed}
        with tqdm(total=len(indexed), desc="Classificant datasets", unit=" ds") as pbar:
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    rows.append(result)
                pbar.update(1)
                pbar.set_postfix({"elegibles": sum(1 for r in rows if r["eligible"])})

    log.info(f"Classificació completada: {len(rows)} datasets processats.")

    log.info("FASE 3: Escrivint resultats...")
    run_id = get_next_run_id(OUTPUT_DIR, sample_size)
    csv_path, json_path, summary = write_results(rows, run_id, sample_size, total_scanned)

    print(f"\n{'='*65}")
    print(f"  RESUM EMBUT — mostra de {summary['sample_size']} datasets aleatoris")
    print(f"{'='*65}")
    for k, v in summary.items():
        print(f"  {k:<40} {v}")
    print(f"{'='*65}")
    print(f"\n  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")
    print(f"  Fallades (detall): {FAILURES_LOG_PATH}\n")

    return csv_path, json_path, summary


def _next_classification_run_id(output_dir: str) -> int:
    """Com `get_next_run_id`, per a `change_classification_<id>.csv`."""
    prefix = "change_classification_"
    max_id = 0
    for filename in os.listdir(output_dir):
        if filename.startswith(prefix) and filename.endswith(".csv"):
            try:
                max_id = max(max_id, int(filename[len(prefix):-4]))
            except ValueError:
                pass
    return max_id + 1


def run_classification(input_csv: str) -> str:
    """
    Fase 2: classifica els canvis de cada dataset elegible del CSV amb
    `classify_dataset(..., classify_changes=True)`.

    :param input_csv: `eligibility_report_*.csv`.
    :return: ruta de `change_classification_<id>.csv` (`dataset_id,
        version_from, version_to, code, description, is_breaking`).
    """
    df = pd.read_csv(input_csv)
    eligible = df[df["eligible"] == True]  # noqa: E712
    log.info(f"Classificant canvis de {len(eligible)} datasets elegibles de {input_csv}...")

    all_labels: list[dict] = []
    n_failed = 0
    for _, row in eligible.iterrows():
        dataset_id = row["dataset_id"]
        log.info(f"  - {dataset_id}")
        result = classify_dataset(dataset_id, classify_changes=True)
        if result["status"] != "classified":
            n_failed += 1
            log.warning(f"    Fallada ({result['status']}): {dataset_id}")
            continue
        all_labels.extend(result["change_labels"])

    run_id = _next_classification_run_id(OUTPUT_DIR)
    output_csv = os.path.join(OUTPUT_DIR, f"change_classification_{run_id}.csv")
    out_df = pd.DataFrame(all_labels, columns=["dataset_id", "version_from", "version_to", "code", "is_breaking"])
    out_df.insert(4, "description", out_df["code"].map(change_diff.CODE_DESCRIPTIONS))
    out_df.to_csv(output_csv, index=False, encoding="utf-8")

    print(f"\n{'=' * 65}")
    print("  RESUM CLASSIFICACIÓ DE CANVIS")
    print(f"{'=' * 65}")
    print(f"  Datasets elegibles           {len(eligible)}")
    print(f"  Datasets fallats             {n_failed}")
    print(f"  Etiquetes de canvi generades {len(all_labels)}")
    print(f"{'=' * 65}")
    print(f"\n  CSV: {output_csv}\n")

    return output_csv


# ---------------------------------------------------------------------------
# Punt d'entrada amb argparse
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """
    Arguments de la CLI. Sense cap argument mostra l'ajuda i surt, perquè
    una crida accidental no engegui una execució llarga.
    """
    parser = argparse.ArgumentParser(
        description="Filtratge de datasets de HF mitjançant mostreig (reservoir sampling).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--classify-eligible", default=None, metavar="CSV",
        help=(
            "Classifica els canvis (C210-C530) dels datasets elegibles d'aquest CSV "
            "(eligibility_report_*.csv) EN LLOC de fer un mostreig nou -- "
            "ignora --sample-size/--max-scanned/--threads/--seed/--tags-only. "
            "Útil per reclassificar un CSV d'un run previ sense tornar a "
            "mostrejar; per encadenar mostreig+extracció+classificació en una "
            "sola execució, useu notebooks/run_pipeline.py en lloc d'aquest flag."
        ),
    )
    parser.add_argument(
        "--tags-only", action="store_true",
        help=(
            "Nomes permet elegibilitat via Criteri A (tags); el Criteri B mai "
            "s'avalua. Segueix verificant els commits substantius del Criteri A."
        ),
    )
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=2000,
        help=(
            "Nombre de datasets a incloure a la mostra final (reservoir size). "
            "Per defecte 2000: marge d'error ±0.51pp a 95%% de confiança, "
            "assumint p=0.0137 (proporció real observada, vegeu README)."
        ),
    )
    parser.add_argument(
        "--max-scanned", "-m",
        type=int,
        default=None,
        help=(
            "Límit de datasets a escanejar en total. "
            "Útil per a proves ràpides. Sense valor = escaneig complet."
        ),
    )
    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=4,
        help="Nombre de threads per al processament paral·lel de la classificació.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Llavor aleatòria per a reproduïbilitat (opcional).",
    )
    parser.add_argument(
        "--retry-max-attempts",
        type=int,
        default=errors.DEFAULT_MAX_RETRIES,
        help="Nombre màxim de reintents davant rate limiting (429) o errors transitoris.",
    )
    parser.add_argument(
        "--retry-base-wait",
        type=float,
        default=errors.DEFAULT_BASE_WAIT_S,
        help="Espera inicial (segons) abans del primer reintent; es duplica a cada intent.",
    )
    parser.add_argument(
        "--retry-max-wait",
        type=float,
        default=errors.DEFAULT_MAX_WAIT_S,
        help="Espera màxima (segons) entre reintents (topall del backoff exponencial).",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        log.info(f"Llavor aleatòria fixada a {args.seed} per a reproduïbilitat.")

    RETRY_CONFIG.update(
        max_retries=args.retry_max_attempts,
        base_wait_s=args.retry_base_wait,
        max_wait_s=args.retry_max_wait,
    )

    if args.classify_eligible:
        run_classification(args.classify_eligible)
    else:
        run_sampling(
            sample_size=args.sample_size,
            max_scanned=args.max_scanned,
            num_threads=args.threads,
            tags_only=args.tags_only,
        )
