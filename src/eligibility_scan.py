"""
Fase 0 (mostreig i elegibilitat) i Fase 2 (classificació de canvis).

Què volem saber: quins datasets de Hugging Face tenen més d'una versió de
dades tabulars, i per tant es poden estudiar. Com que n'hi ha ~1 milió, es
treballa sobre una mostra.

1. **Mostreig** (`reservoir_sample_dataset_ids`): mostra aleatòria uniforme
   de tota la població amb l'algorisme de reservori, sense carregar-la mai
   sencera a memòria.
2. **Elegibilitat** (`classify_dataset`), en tres filtres, del més barat al
   més car; un dataset que no passa un filtre ja no arriba al següent:
   1. Té >=2 tags o >=2 branques? Una crida a l'API (`list_repo_refs`).
   2. La versió actual té algun fitxer de dades tabular? Una crida a l'API
      (`list_current_files`) que dona la llista de fitxers, sense clonar
      res. D'aquí surt també quina part dels fitxers de dades són tabulars
      (`tabular_file_share`), que queda al report.
   3. Els commits toquen dades tabulars prou vegades?
      - Criteri A: >=2 tags i >=2 commits que toquen dades tabulars; o
      - Criteri B: >=2 branques i commits que toquen dades tabulars
        repartits en >=2 sessions de treball (separades per més de 6 hores).
      Per saber quins fitxers toca cada commit es fa un clon de git sense
      contingut i limitat als últims commits (`bare_clone`), i `git show`
      en local, sense crides a l'API.
   Només compten els fitxers de dades tabulars (`is_tabular_data_path`):
   són els únics que el motor pot comparar.
3. **Resultats** (`write_results`): el report per dataset, el resum de
   l'embut (`compute_funnel_stats`: proporció d'elegibles i quants intents
   calen per elegible, per fixar la mida de la mostra) i la llista de
   commits tabulars de cada elegible (`tabular_commits.csv`).
4. **Classificació** (`run_classification`, Fase 2): per als elegibles,
   compara versions consecutives amb el motor (`diffengine`) i escriu els
   canvis. Llegeix els commits tabulars que ha desat la Fase 0: no torna a
   llistar commits ni a clonar.

Per llegir el codi: `classify_dataset` és el centre de tot; les funcions
que crida apareixen a sota en el mateix ordre.
Detall: `docs/architecture.md`, seccions 7 i 9.

Ús:
  python eligibility_scan.py --sample-size 2000 --threads 4 --seed 42
  python eligibility_scan.py --sample-size 200 --max-scanned 5000  # prova ràpida, esbiaixada
  python eligibility_scan.py --classify-eligible ../data/run_8/eligibility_report.csv

Output (cada execució en una carpeta nova, `data/run_<id>/`):
  eligibility_report.csv, funnel_summary.json, tabular_commits.csv   (mostreig)
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
from huggingface_hub import HfApi, dataset_info, list_repo_commits, list_repo_refs

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
TABULAR_COMMITS_FILE = "tabular_commits.csv"
INTERNAL_FIELDS = ("tabular_commits", "num_data_files", "tabular_file_share")

# Motiu que queda al report: el criteri que es compleix, o el filtre on s'atura el dataset.
ELIGIBILITY_REASONS = {
    "A": "Criteri A: tags>=2 i >=2 commits amb dades tabulars",
    "B": f"Criteri B: commits amb dades tabulars en >=2 sessions (separades >{MIN_SUBSTANTIVE_GAP_HOURS}h)",
    "no_version_marks": "no elegible: menys de 2 tags i menys de 2 branques",
    "no_tabular_files": "no elegible: cap fitxer de dades tabular a la versió actual",
    "no_tabular_commits": "no elegible: no hi ha prou commits amb dades tabulars",
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

def classify_dataset(dataset_id: str, tags_only: bool = False) -> dict:
    """
    Decideix si un dataset és elegible (Fase 0).

    Passos, del més barat al més car (si un falla, el dataset no és elegible i
    no es fa cap pas més):
      1. `list_repo_refs`: ha de tenir >=2 tags o >=2 branques.
      2. `list_current_files`: la versió actual ha de tenir algun fitxer de
         dades tabular (`tabular_file_share` > 0).
      3. `list_repo_commits` i un clon sense contingut (`bare_clone`):
         `find_tabular_commits` troba els commits que toquen dades tabulars, i
         `eligibility_criterion` decideix si es compleix el Criteri A o el B.
         Si és elegible, aquests commits es guarden (`tabular_commits`): són
         els que fan servir les Fases 1 i 2, sense tornar-los a buscar.

    :param dataset_id: dataset (`owner/name`).
    :param tags_only: només permet el Criteri A.
    :return: diccionari amb els camps del report + interns sobre els commits tabulars
    """
    result = {
        "dataset_id": dataset_id,
        "num_tags": 0,
        "num_branches": 0,
        "num_tabular_commits": 0,
        "eligible": False,
        "eligibility_reason": "",
        "status": "classified",
        "error_category": "",
        "error": "",
        "tabular_commits": [],
        "num_data_files": None,
        "tabular_file_share": None,
    }

    try:
        refs = errors.with_retry(
            list_repo_refs, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
            **RETRY_CONFIG,
        )
        n_tags, n_branches = len(refs.tags or []), len(refs.branches or [])
        result["num_tags"], result["num_branches"] = n_tags, n_branches

        # Pas 1: sense 2 marques de versió (tags o branques), no hi ha res a comparar.
        if n_tags < 2 and (tags_only or n_branches < 2):
            result["eligibility_reason"] = ELIGIBILITY_REASONS["no_version_marks"]
            return result

        # Pas 2: quins fitxers té la versió actual i quina part de les dades és tabular (es guarda,
        # però no s'escriu). Sense cap fitxer de dades tabular, no cal llistar els commits ni clonar.
        result["num_data_files"], result["tabular_file_share"] = tabular_file_share(list_current_files(dataset_id))
        if not result["tabular_file_share"]:
            result["eligibility_reason"] = ELIGIBILITY_REASONS["no_tabular_files"]
            return result

        # Pas 3: quins dels últims commits toquen dades tabulars, i quin criteri es compleix.
        commits = list(errors.with_retry(
            list_repo_commits, repo_id=dataset_id, repo_type="dataset", token=HF_TOKEN,
            **RETRY_CONFIG,
        ))[:MAX_COMMITS]
        with bare_clone(dataset_id) as clone_dir:
            tabular = find_tabular_commits(commits, clone_dir)
        result["num_tabular_commits"] = len(tabular)
        criterion = eligibility_criterion(n_tags, n_branches, [commits[i] for i in tabular], tags_only)
        if criterion is None:
            result["eligibility_reason"] = ELIGIBILITY_REASONS["no_tabular_commits"]
            return result
        result["eligible"] = True
        result["eligibility_reason"] = ELIGIBILITY_REASONS[criterion]
        result["tabular_commits"] = tabular_commit_records(commits, tabular)

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


def list_current_files(dataset_id: str) -> list[str]:
    """
    Fitxers de la versió actual del repositori, amb una sola crida a l'API
    (`dataset_info`), sense clonar res. Dona la mateixa llista que el clon
    (comprovat amb els 29 candidats de `run_8`) i triga uns 0,2 s.

    :param dataset_id: dataset (`owner/name`).
    :return: rutes dels fitxers dins del repositori.
    """
    info = errors.with_retry(dataset_info, repo_id=dataset_id, token=HF_TOKEN, **RETRY_CONFIG)
    return [sibling.rfilename for sibling in (info.siblings or [])]


def tabular_file_share(paths: list[str]) -> tuple[int, float | None]:
    """
    De tots els fitxers de dades d'un repositori, quina proporció són
    tabulars. Si és 0 (o no hi ha cap fitxer de dades), el dataset no és
    elegible i no es clona. La proporció queda al report: un repositori de
    vídeo amb un parquet d'índex tindrà una proporció baixa.

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
    Clona el repositori sense cap contingut i només amb l'historial recent:

    - `--bare`: sense còpia de treball (cap fitxer desplegat).
    - `--filter=blob:none`: sense el contingut de cap fitxer; només els
      commits i els arbres (quins fitxers hi ha a cada commit).
    - `--depth=MAX_COMMITS + 1`: només els últims 50 commits, els que es
      revisen, més el pare del més vell, que cal per saber què va canviar.
      Amb un historial llarg, el clon fa la meitat de mida o menys.

    El token va per variables d'entorn de git, no a la línia d'ordres, perquè
    no surti a `ps`. El directori temporal s'esborra en sortir.

    :param dataset_id: dataset (`owner/name`).
    :yield: ruta del clon, o `None` si ha fallat. Sense clon no se sap quins
        fitxers toca cada commit, i cap commit compta. Si falta `git`, s'avisa
        un sol cop per procés.
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
            ["git", "clone", "--bare", "--filter=blob:none", f"--depth={MAX_COMMITS + 1}", "--quiet", url, tmp_dir],
            env=env, capture_output=True, timeout=GIT_CLONE_TIMEOUT_S,
        )
        if result.returncode != 0:
            log.debug(f"bare_clone: git clone ha fallat per a {dataset_id} (retorn {result.returncode})")
        yield tmp_dir if result.returncode == 0 else None
    except FileNotFoundError:
        if not _git_missing_warned:
            log.error(
                "bare_clone: 'git' no és al PATH es desactiva per a TOTA la " \
                "resta de l'escaneig: sense clon, cap commit compta i cap dataset pot ser elegible. "
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


@dataclass(frozen=True)
class TabularCommit:
    """
    Un commit que toca dades tabulars d'un dataset elegible. La Fase 0 els
    desa a `tabular_commits.csv`, i les Fases 1 (versions per sessió) i 2
    (parelles que es comparen) els llegeixen d'allà, sense tornar a llistar
    els commits ni a clonar.

    :ivar commit_id: SHA del commit.
    :ivar parent_id: SHA del commit anterior de l'historial, o `None` si és el
        més vell dels revisats (no se'n coneix l'anterior).
    :ivar created_at: data del commit.
    :ivar authors: autors del commit.
    """

    commit_id: str
    parent_id: str | None
    created_at: datetime | None
    authors: tuple[str, ...] = ()


def tabular_commit_records(commits: list, tabular: list[int]) -> list[TabularCommit]:
    """
    Converteix els commits tabulars en `TabularCommit`, amb el commit anterior
    de cadascun (el següent de la llista, que va del més nou al més vell).

    :param commits: commits de `list_repo_commits`, del més nou al més vell.
    :param tabular: posicions dels commits tabulars (`find_tabular_commits`).
    :return: un `TabularCommit` per commit tabular, en el mateix ordre.
    """
    return [
        TabularCommit(
            commit_id=commits[i].commit_id,
            parent_id=commits[i + 1].commit_id if i + 1 < len(commits) else None,
            created_at=getattr(commits[i], "created_at", None),
            authors=tuple(getattr(commits[i], "authors", None) or ()),
        )
        for i in tabular
    ]


def save_tabular_commits(rows: list[dict], path: str) -> None:
    """
    Escriu els commits tabulars de tots els elegibles en un sol CSV: una fila
    per commit (`dataset_id, commit_id, parent_id, created_at, authors`).

    :param rows: files de `classify_dataset` (només en tenen els elegibles).
    :param path: ruta de `tabular_commits.csv`.
    """
    records = [
        {"dataset_id": row["dataset_id"], "commit_id": c.commit_id, "parent_id": c.parent_id,
         "created_at": c.created_at.isoformat() if c.created_at else None, "authors": ",".join(c.authors)}
        for row in rows for c in row.get("tabular_commits") or []
    ]
    pd.DataFrame(records, columns=["dataset_id", "commit_id", "parent_id", "created_at", "authors"]).to_csv(
        path, index=False, encoding="utf-8")


def load_tabular_commits(report_csv: str) -> dict[str, list[TabularCommit]]:
    """
    Llegeix els commits tabulars que la Fase 0 va desar al costat d'un
    `eligibility_report.csv`.

    :param report_csv: ruta del report; el fitxer es busca a la mateixa carpeta.
    :return: per a cada dataset elegible, els seus commits tabulars, del més nou
        al més vell. Buit si el report és d'una versió anterior del pipeline,
        que no desava aquest fitxer.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(report_csv)), TABULAR_COMMITS_FILE)
    if not os.path.exists(path):
        log.warning(f"No hi ha {TABULAR_COMMITS_FILE} al costat de {report_csv}: "
                    "es tornaran a buscar els commits tabulars de cada elegible.")
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    saved: dict[str, list[TabularCommit]] = {}
    for row in df.itertuples(index=False):
        saved.setdefault(row.dataset_id, []).append(TabularCommit(
            commit_id=row.commit_id,
            parent_id=row.parent_id or None,
            created_at=datetime.fromisoformat(row.created_at) if row.created_at else None,
            authors=tuple(a for a in row.authors.split(",") if a),
        ))
    return saved


def find_tabular_commits_again(dataset_id: str) -> list[TabularCommit]:
    """
    Torna a fer la Fase 0 per a un sol dataset i en retorna els commits
    tabulars. Només fa falta per als reports d'execucions anteriors, que no
    tenen `tabular_commits.csv`.

    :param dataset_id: dataset (`owner/name`).
    :return: els commits tabulars, o una llista buida si ja no és elegible.
    """
    return classify_dataset(dataset_id)["tabular_commits"]


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


def change_units(tabular_commits: list["TabularCommit"], criterion: str) -> list[tuple[str, str]]:
    """
    Les parelles de revisions que es comparen a la Fase 2 (unitats de canvi,
    decisió T-13):

    - Criteri A: cada commit tabular contra el commit anterior de l'historial.
      El commit més vell dels revisats no té anterior conegut i no es compara.
    - Criteri B: el commit més recent de cada sessió contra el de la sessió
      anterior. Els commits d'una mateixa sessió no es comparen entre ells.

    :param tabular_commits: commits tabulars d'un dataset elegible, del més nou
        al més vell, tal com els desa la Fase 0.
    :param criterion: `"A"` o `"B"`.
    :return: parelles `(SHA antic, SHA nou)`, de la més recent a la més antiga.
    """
    if criterion == "A":
        return [(c.parent_id, c.commit_id) for c in tabular_commits if c.parent_id]
    sessions = group_commits_into_sessions(tabular_commits)
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
    sense els camps interns), el resum de l'embut (`funnel_summary.json`) i
    els commits tabulars dels elegibles (`tabular_commits.csv`), que fan
    servir les Fases 1 i 2.

    :param rows: files de `classify_dataset`.
    :param total_scanned: mida de la població recorreguda.
    :return: `(csv_path, json_path, summary)`.
    """
    df = pd.DataFrame(rows)

    csv_path = os.path.join(OUTPUT_DIR, "eligibility_report.csv")
    df.drop(columns=list(INTERNAL_FIELDS), errors="ignore").to_csv(csv_path, index=False, encoding="utf-8")
    save_tabular_commits(rows, os.path.join(OUTPUT_DIR, TABULAR_COMMITS_FILE))

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
    Fase 2: classifica els canvis de cada dataset elegible del CSV i escriu
    `change_classification.csv` a `OUTPUT_DIR`: una fila per taula, parell de
    versions i codi (`dataset_id, version_from, version_to, file_path, code,
    description, is_breaking`).

    Per a cada elegible:
      1. agafa els seus commits tabulars de `tabular_commits.csv`, el fitxer
         que la Fase 0 desa al costat del report (`load_tabular_commits`);
      2. `change_units` en forma les parelles de revisions, segons el criteri
         que el va fer elegible (columna `eligibility_reason`);
      3. `compare_change_units` les compara amb el motor.
    Una fallada d'un dataset queda a `failures.csv` i no atura la resta.

    :param input_csv: un `eligibility_report.csv`.
    :return: ruta de `change_classification.csv`.
    """
    df = pd.read_csv(input_csv)
    eligible = df[df["eligible"] == True]  # noqa: E712
    log.info(f"Classificant canvis de {len(eligible)} datasets elegibles de {input_csv}...")
    saved = load_tabular_commits(input_csv)

    all_changes: list[dict] = []
    for _, row in eligible.iterrows():
        dataset_id = row["dataset_id"]
        criterion = "A" if str(row["eligibility_reason"]).startswith("Criteri A") else "B"
        log.info(f"  - {dataset_id} (Criteri {criterion})")
        try:
            tabular_commits = saved[dataset_id] if dataset_id in saved else find_tabular_commits_again(dataset_id)
            all_changes += compare_change_units(dataset_id, change_units(tabular_commits, criterion),
                                                HF_TOKEN, RETRY_CONFIG)
        except Exception as exc:
            category = errors.classify_error(exc)
            errors.append_failure_row(
                FAILURES_LOG_PATH, dataset_id=dataset_id, category=category, message=str(exc),
                retries_attempted=RETRY_CONFIG["max_retries"] if category in errors.RETRIED_CATEGORIES else 0,
                source="classification",
            )
            log.warning(f"    Fallada ({category.value}): {dataset_id}")

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
