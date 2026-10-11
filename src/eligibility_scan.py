"""
Fase 0 (mostreig i elegibilitat) i Fase 2 (classificació de canvis).

Què volem saber: quins datasets de Hugging Face tenen més d'una versió de
dades tabulars, i per tant es poden estudiar. Com que n'hi ha ~1 milió, es
treballa sobre una mostra.

1. **Mostreig** (`reservoir_sample_dataset_ids`): mostra aleatòria uniforme
   de tota la població amb l'algorisme de reservori, sense carregar-la mai
   sencera a memòria.
2. **Elegibilitat** (`classify_dataset`): un dataset és elegible si té
   - Criteri A: >=2 tags i >=2 commits que toquen dades tabulars; o
   - Criteri B: >=2 branques i commits que toquen dades tabulars repartits
     en >=2 sessions de treball (separades per més de 6 hores).
   Per saber quins fitxers toca cada commit es fa un clon de git sense
   contingut (`bare_clone`) i `git show` en local, sense crides a l'API.
   Només compten els fitxers de dades tabulars (`is_tabular_data_path`):
   són els únics que el motor pot comparar.
3. **Resum de l'embut** (`compute_funnel_stats`): proporció d'elegibles i
   quants intents calen per elegible, per fixar la mida de la mostra.
4. **Classificació** (`run_classification`): per als elegibles, compara
   versions consecutives amb el motor (`diffengine`) i escriu els canvis.

Per llegir el codi: `classify_dataset` és el centre de tot; les funcions
que crida apareixen a sota en el mateix ordre.
Detall: `docs/architecture.md`, seccions 7 i 9.

Ús:
  python eligibility_scan.py --sample-size 2000 --threads 4 --seed 42
  python eligibility_scan.py --sample-size 200 --max-scanned 5000  # prova ràpida, esbiaixada
  python eligibility_scan.py --classify-eligible ../data/run_12/eligibility_report.csv

Output (cada execució en una carpeta nova, `data/run_<id>/`):
  eligibility_report.csv, funnel_summary.json   (mostreig)
  change_classification.csv                     (--classify-eligible)
  failures.csv                                  (si hi ha fallades)
"""

import functools
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
from dataclasses import dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Iterator

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm
from huggingface_hub import HfApi, list_repo_commits, list_repo_refs

import errors
from diffengine import pairs, units
from diffengine.output import classification_frame
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

MIN_SUBSTANTIVE_GAP_HOURS = 6.0
MAX_COMMITS = 50  # commits revisats per dataset, del més nou al més vell
ELIGIBILITY_REASONS = {
    "A": "Criteri A: tags>=2 i >=2 commits amb dades tabulars",
    "B": f"Criteri B: commits amb dades tabulars en >=2 sessions (separades >{MIN_SUBSTANTIVE_GAP_HOURS}h)",
    None: "no elegible: cap criteri es compleix",
}
GIT_CLONE_TIMEOUT_S = 30
GIT_SHOW_TIMEOUT_S = 10

_git_missing_warned = False

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
# Carpeta de l'execució en curs: `new_run_dir` la canvia per `data/run_<id>`.
OUTPUT_DIR = DATA_DIR
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
    Decideix si un dataset és elegible i, si es demana, en compara les versions.

    Tot surt d'un sol recorregut: es busquen els commits tabulars
    (`find_tabular_commits`), i amb aquesta llista
      1. es decideix el criteri d'elegibilitat (`eligibility_criterion`), i
      2. només si és elegible i `classify_changes`, es formen les parelles de
         revisions (`change_units`) i es comparen (`compare_change_units`).
    Cap pas posterior torna a mirar si els fitxers són tabulars: la llista ja
    només en conté.

    :param dataset_id: dataset (`owner/name`).
    :param tags_only: només permet el Criteri A.
    :param classify_changes: compara també les versions (Fase 2). Descarrega
        contingut real.
    :return: fila del report: `dataset_id`, `num_tags`, `num_branches`,
        `num_tabular_commits`, `num_data_files`, `tabular_file_share`,
        `eligible`, `eligibility_reason`, `status`
        (`classified`/`access_restricted`/`error`), `error_category`, `error`
        (truncat a 120 caràcters) i `change_labels` (una fila per canvi; `[]`
        si `classify_changes=False`).
    """
    result = {
        "dataset_id": dataset_id,
        "num_tags": 0,
        "num_branches": 0,
        "num_tabular_commits": 0,
        "num_data_files": None,
        "tabular_file_share": None,
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
        n_tags, n_branches = len(refs.tags or []), len(refs.branches or [])
        result["num_tags"], result["num_branches"] = n_tags, n_branches

        criterion = None
        if n_tags >= 2 or (not tags_only and n_branches >= 2):
            commits = list(errors.with_retry(
                list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
                **RETRY_CONFIG,
            ))[:MAX_COMMITS]
            with bare_clone(dataset_id) as clone_dir:
                if clone_dir is not None:
                    result["num_data_files"], result["tabular_file_share"] = tabular_file_share(
                        list_files_at_head(clone_dir) or []
                    )
                tabular = find_tabular_commits(commits, clone_dir)
            result["num_tabular_commits"] = len(tabular)
            criterion = eligibility_criterion(n_tags, n_branches, [commits[i] for i in tabular], tags_only)

            if criterion and classify_changes:
                result["change_labels"] = compare_change_units(
                    dataset_id, change_units(commits, tabular, criterion), HF_TOKEN, RETRY_CONFIG,
                )

        result["eligible"] = criterion is not None
        result["eligibility_reason"] = ELIGIBILITY_REASONS[criterion]

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


def is_tabular_data_path(path: str) -> bool:
    """
    Fitxer de dades tabular: el que fa elegible un dataset i el que compara el
    motor. Ha de ser dades (`is_substantive_path`, que exclou p.e. `meta/`) i
    tabular segons el motor (`diffengine.units.is_tabular_path`: `.parquet`,
    `.csv`, `.tsv`, `.json`, `.jsonl`, sense els JSON de metadades).
    """
    return is_substantive_path(path) and units.is_tabular_path(path)


def tabular_file_share(paths: list[str]) -> tuple[int, float | None]:
    """
    Informació complementària (no decideix l'elegibilitat): de tots els
    fitxers de dades d'un repositori, quina proporció són tabulars. Un
    repositori de vídeo amb un parquet d'índex tindrà una proporció baixa.

    :param paths: fitxers del repositori.
    :return: `(fitxers de dades, proporció tabular)`; proporció `None` si no hi ha dades.
    """
    data = [p for p in paths if is_substantive_path(p)]
    if not data:
        return 0, None
    return len(data), round(sum(units.is_tabular_path(p) for p in data) / len(data), 4)


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


def list_files_at_head(clone_dir: str) -> list[str] | None:
    """Tots els fitxers de la revisió actual, llegits del clon bare (sense xarxa)."""
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=clone_dir, capture_output=True, text=True, timeout=GIT_SHOW_TIMEOUT_S,
        )
        return result.stdout.splitlines() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def is_tabular_commit(commit, clone_dir: str | None) -> bool:
    """
    Un commit compta (per a l'elegibilitat i per a les versions) si toca algun
    fitxer de dades tabular (`is_tabular_data_path`).

    Cal saber quins fitxers toca, i això només ho dona el clon. Sense clon, o
    si `git show` falla, el commit no compta.

    :param commit: commit de `list_repo_commits`.
    :param clone_dir: clon bare, o `None`.
    :return: `True` si toca dades tabulars.
    """
    if clone_dir is None:
        return False
    changed_paths = get_changed_files(clone_dir, commit.commit_id)
    return bool(changed_paths) and any(is_tabular_data_path(p) for p in changed_paths)


def find_tabular_commits(commits: list, clone_dir: str | None) -> list[int]:
    """
    Posicions dels commits que toquen dades tabulars. Es guarda la posició, i
    no el commit, perquè el Criteri A necessita el commit anterior
    (`commits[i + 1]`, la llista va del més nou al més vell).

    :param commits: commits de `list_repo_commits`, del més nou al més vell.
    :param clone_dir: clon bare, o `None`.
    :return: posicions dins de `commits`, en el mateix ordre.
    """
    return [i for i, commit in enumerate(commits) if is_tabular_commit(commit, clone_dir)]


def eligibility_criterion(n_tags: int, n_branches: int, tabular_commits: list, tags_only: bool = False) -> str | None:
    """
    Aplica els dos criteris d'elegibilitat, per ordre.

    :param n_tags: nombre de tags del repositori.
    :param n_branches: nombre de branques.
    :param tabular_commits: commits que toquen dades tabulars.
    :param tags_only: només permet el Criteri A.
    :return: `"A"`, `"B"` o `None` (no elegible).
    """
    if n_tags >= 2 and len(tabular_commits) >= 2:
        return "A"
    if not tags_only and n_branches >= 2 and has_time_dispersed_substantive_commits(
        [getattr(c, "created_at", None) for c in tabular_commits]
    ):
        return "B"
    return None


def group_commits_into_sessions(commits: list) -> list[list]:
    """
    Agrupa commits en sessions amb `cluster_commit_times`.

    :param commits: commits amb `created_at`; els que no en tenen s'ignoren.
    :return: sessions de la més recent a la més antiga (sense ordre dins de cada sessió).
    """
    by_time: dict[datetime, list] = {}
    for c in commits:
        if getattr(c, "created_at", None) is not None:
            by_time.setdefault(c.created_at, []).append(c)
    clusters = cluster_commit_times(list(by_time))
    return [[c for t in cluster for c in by_time[t]] for cluster in reversed(clusters)]


def change_units(commits: list, tabular: list[int], criterion: str) -> list[tuple[str, str]]:
    """
    Les parelles de revisions que es comparen (unitats de canvi, decisió T-13):

    - Criteri A: cada commit tabular contra el commit anterior de l'historial.
      El commit més vell de la llista no té anterior conegut i no es compara.
    - Criteri B: el commit més recent de cada sessió contra el de la sessió
      anterior. Els commits d'una mateixa sessió no es comparen entre ells.

    :param commits: commits de `list_repo_commits`, del més nou al més vell.
    :param tabular: posicions dels commits tabulars (`find_tabular_commits`).
    :param criterion: `"A"` o `"B"`.
    :return: parelles `(SHA antic, SHA nou)`, de la més recent a la més antiga.
    """
    if criterion == "A":
        return [(commits[i + 1].commit_id, commits[i].commit_id) for i in tabular if i + 1 < len(commits)]
    sessions = group_commits_into_sessions([commits[i] for i in tabular])
    latest = [max(session, key=lambda c: c.created_at) for session in sessions]
    return [(older.commit_id, newer.commit_id) for newer, older in zip(latest, latest[1:])]


def compare_change_units(
    dataset_id: str, units_to_compare: list[tuple[str, str]], hf_token: str | None, retry_config: dict,
) -> list[dict]:
    """
    Compara amb el motor (`diffengine.pairs.compare_revisions`) cada parella
    de revisions, taula a taula (subset, split).

    :param dataset_id: dataset (`owner/name`).
    :param units_to_compare: parelles `(SHA antic, SHA nou)` de `change_units`.
    :param hf_token: token de Hugging Face.
    :param retry_config: configuració de reintent (també per a les descàrregues).
    :return: una fila per canvi (`dataset_id`, `version_from`, `version_to`, `file_path`, `code`).
    """
    retry = functools.partial(errors.with_retry, **retry_config)
    labels: list[dict] = []
    for old_rev, new_rev in units_to_compare:
        compared = pairs.compare_revisions(dataset_id, old_rev, new_rev, hf_token, call=retry)
        labels += pairs.revision_rows(dataset_id, old_rev, new_rev, compared)
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
    - `eligible_proportion_of_attempts`: elegibles / tots els intents
      (elegibles, no elegibles, inaccessibles i errors).
    - `estimated_eligible_in_scanned_population`: quants elegibles hi
      hauria a tota la població recorreguda (`total_scanned`), amb la
      proporció sobre tots els intents.
    - `attempts_per_eligible`: quants datasets cal provar per obtenir-ne un
      d'elegible. Serveix per fixar la mostra: per tenir N datasets
      elegibles (i per tant amb dades tabulars per comparar), cal una
      mostra d'unes N × `attempts_per_eligible`.

    :return: els recomptes més les mètriques (0 o `None` si el denominador és 0).
    """
    denom_valid = counts.eligible + counts.ineligible
    denom_attempts = denom_valid + counts.access_restricted + counts.errors

    eligible_proportion = round(counts.eligible / denom_valid, 4) if denom_valid else 0.0
    proportion_of_attempts = counts.eligible / denom_attempts if denom_attempts else 0.0

    return {
        "eligible": counts.eligible,
        "ineligible": counts.ineligible,
        "access_restricted": counts.access_restricted,
        "errors": counts.errors,
        "eligible_proportion": eligible_proportion,
        "eligible_proportion_of_attempts": round(proportion_of_attempts, 4),
        "estimated_eligible_in_scanned_population": int(round(proportion_of_attempts * counts.total_scanned)),
        "attempts_per_eligible": round(denom_attempts / counts.eligible, 1) if counts.eligible else None,
    }

def new_run_dir(parent: str | None = None) -> str:
    """
    Crea la carpeta d'una execució nova, `run_<id>` amb el número següent, i
    hi dirigeix tota la sortida d'aquest mòdul (`OUTPUT_DIR` i
    `FAILURES_LOG_PATH`). Com que cada execució té la seva carpeta, els
    fitxers de dins tenen noms fixos i mai se sobreescriu res.

    :param parent: on es crea (per defecte, `data/`).
    :return: la ruta de la carpeta creada.
    """
    global OUTPUT_DIR, FAILURES_LOG_PATH
    parent = parent or DATA_DIR
    os.makedirs(parent, exist_ok=True)
    ids = [int(n[4:]) for n in os.listdir(parent) if n.startswith("run_") and n[4:].isdigit()]
    run_dir = os.path.join(parent, f"run_{max(ids, default=0) + 1}")
    os.makedirs(run_dir)
    OUTPUT_DIR, FAILURES_LOG_PATH = run_dir, os.path.join(run_dir, "failures.csv")
    return run_dir


def write_results(rows: list[dict], total_scanned: int) -> tuple[str, str, dict]:
    """
    Escriu a `OUTPUT_DIR` el report per dataset (`eligibility_report.csv`,
    sense `change_labels`) i el resum de l'embut (`funnel_summary.json`).

    :param rows: files de `classify_dataset`.
    :param total_scanned: mida de la població recorreguda.
    :return: `(csv_path, json_path, summary)`.
    """
    df = pd.DataFrame(rows)

    csv_path = os.path.join(OUTPUT_DIR, "eligibility_report.csv")
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
        "eligible_Criteri_A": int(df["eligibility_reason"].str.startswith("Criteri A").sum()),
        "eligible_Criteri_B": int(df["eligibility_reason"].str.startswith("Criteri B").sum()),
        **compute_funnel_stats(counts),
    }

    json_path = os.path.join(OUTPUT_DIR, "funnel_summary.json")
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
    csv_path, json_path, summary = write_results(rows, total_scanned)

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


def run_classification(input_csv: str) -> str:
    """
    Fase 2: classifica els canvis de cada dataset elegible del CSV amb
    `classify_dataset(..., classify_changes=True)` i escriu
    `change_classification.csv` a `OUTPUT_DIR`: una fila per taula, parell de
    versions i codi (`dataset_id, version_from, version_to, file_path, code,
    description, is_breaking`).

    :param input_csv: un `eligibility_report.csv`.
    :return: ruta de `change_classification.csv`.
    """
    df = pd.read_csv(input_csv)
    eligible = df[df["eligible"] == True]  # noqa: E712
    log.info(f"Classificant canvis de {len(eligible)} datasets elegibles de {input_csv}...")

    all_changes: list[dict] = []
    for dataset_id in eligible["dataset_id"]:
        log.info(f"  - {dataset_id}")
        result = classify_dataset(dataset_id, classify_changes=True)
        if result["status"] != "classified":
            log.warning(f"    Fallada ({result['status']}): {dataset_id}")
            continue
        all_changes.extend(result["change_labels"])

    output_csv = os.path.join(OUTPUT_DIR, "change_classification.csv")
    classification_frame(all_changes).to_csv(output_csv, index=False, encoding="utf-8")
    log.info(f"Classificació escrita a {output_csv}")
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
            "(eligibility_report.csv) EN LLOC de fer un mostreig nou -- "
            "ignora --sample-size/--max-scanned/--threads/--seed/--tags-only. "
            "Útil per reclassificar un CSV d'un run previ sense tornar a "
            "mostrejar; per encadenar mostreig+extracció+classificació en una "
            "sola execució, useu src/run_pipeline.py en lloc d'aquest flag."
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

    new_run_dir()
    if args.classify_eligible:
        run_classification(args.classify_eligible)
    else:
        run_sampling(
            sample_size=args.sample_size,
            max_scanned=args.max_scanned,
            num_threads=args.threads,
            tags_only=args.tags_only,
        )
