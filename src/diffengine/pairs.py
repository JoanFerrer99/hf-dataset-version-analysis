"""
Pas 1 (segona part): comparar el dataset de dues revisions.

Aquí comença una comparació de revisions (una unitat de canvi):
`compare_revisions` fa el pas 1 i crida `engine.diff_tables` (passos 3 i 4);
`revision_rows` converteix els canvis en files de sortida (pas 5), i
`status_row`, l'estat de la comparació.

- Cada revisió es llista amb l'API (`list_revision`) i se'n troben els
  fitxers del dataset (`datafiles.dataset_files`).
- `compare_datasets` descarrega i compara el dataset de les dues revisions, i
  li posa un estat: `ok`, `identical_content` (els mateixos fitxers, amb el
  mateix contingut: no es descarrega), `absent_old` o `absent_new` (una de
  les revisions no té cap fitxer de dades), `no_data` (no en té cap de les
  dues), `download_failed`, `parse_failed` o `too_large`. Només les `ok` tenen
  canvis: una fallada mai es converteix en codis.

Les crides al Hub passen per `call(fn, *args, **kwargs)`: qui fa servir el
motor hi posa la seva política de reintents. Així el motor no depèn del
pipeline.
"""

from collections.abc import Callable
from dataclasses import dataclass

from huggingface_hub import hf_hub_download, list_repo_tree

from diffengine.config import DEFAULT_CONFIG, EngineConfig
from diffengine.datafiles import DatasetFiles, dataset_files
from diffengine.engine import diff_tables
from diffengine.load import ParseError, Table, load_files
from diffengine.output import DiffResult

Call = Callable[..., object]


def direct_call(fn, *args, **kwargs):
    """
    Fa una crida sense reintents. És el valor per defecte del paràmetre `call`.

    :param fn: funció a cridar.
    :return: el que retorni `fn(*args, **kwargs)`.
    """
    return fn(*args, **kwargs)


@dataclass
class Revision:
    revision: str
    sizes: dict[str, int]
    content_ids: dict[str, str]
    data: DatasetFiles


@dataclass
class Comparison:
    """
    La comparació del dataset entre dues revisions.

    :ivar old: els fitxers del dataset a la revisió antiga.
    :ivar new: els fitxers del dataset a la revisió nova.
    :ivar size_bytes: la mida dels fitxers de les dues revisions, sumades (la que es compara amb el límit).
    :ivar status: `pending` fins que es compara; després `ok`, `identical_content`, `absent_old`,
        `absent_new`, `no_data`, `download_failed`, `parse_failed` o `too_large`.
    :ivar result: els canvis, si l'estat és `ok`.
    """

    old: DatasetFiles
    new: DatasetFiles
    size_bytes: int = 0
    status: str = "pending"
    result: DiffResult | None = None


def list_revision(repo_id: str, revision: str, token: str | None, call: Call = direct_call,
                  config: EngineConfig = DEFAULT_CONFIG) -> Revision:
    """
    Llista els fitxers d'una revisió (amb mida i identificador de contingut) i
    en troba els del dataset.

    :param repo_id: repositori de Hugging Face (`propietari/nom`).
    :param revision: commit a llistar.
    :param token: token d'accés a Hugging Face, o `None`.
    :param call: funció per fer les crides a l'API (permet afegir-hi reintents).
    :param config: llindars del motor (els formats tabulars).
    :return: la revisió: mides, identificadors de contingut i fitxers del dataset.
    """
    entries = call(
        lambda: list(list_repo_tree(repo_id, repo_type="dataset", revision=revision, recursive=True, token=token)))
    files = [e for e in entries if getattr(e, "size", None) is not None]
    sizes = {e.path: e.size for e in files}
    content_ids = {e.path: (e.lfs.sha256 if getattr(e, "lfs", None) else e.blob_id) for e in files}
    return Revision(revision, sizes, content_ids, dataset_files(list(sizes), config.formats))


def pair_datasets(old: Revision, new: Revision) -> Comparison:
    """
    Prepara la comparació de dues revisions i li posa l'estat inicial:
    `no_data`, `absent_old`, `absent_new`, `identical_content` (els mateixos
    fitxers, en el mateix ordre i amb el mateix contingut) o `pending`.

    :param old: revisió antiga.
    :param new: revisió nova.
    :return: la comparació, encara sense descarregar res.
    """
    size = sum(old.sizes[f] for f in old.data.files) + sum(new.sizes[f] for f in new.data.files)
    comparison = Comparison(old.data, new.data, size)
    if not old.data.files and not new.data.files:
        comparison.status = "no_data"
    elif not old.data.files:
        comparison.status = "absent_old"
    elif not new.data.files:
        comparison.status = "absent_new"
    elif old.data.files == new.data.files and all(old.content_ids[f] == new.content_ids[f] for f in old.data.files):
        comparison.status = "identical_content"
    return comparison


def _load_files(repo_id: str, revision: str, files: tuple[str, ...], token: str | None, call: Call,
                config: EngineConfig) -> Table:
    """
    Descarrega i llegeix els fitxers del dataset en una revisió.

    :param repo_id: repositori de Hugging Face.
    :param revision: commit.
    :param files: fitxers del dataset.
    :param token: token d'accés, o `None`.
    :param call: funció per fer les crides a l'API.
    :param config: llindars del motor.
    :return: el dataset llegit (tots els fitxers, units en ordre).
    """
    local = [call(hf_hub_download, repo_id=repo_id, repo_type="dataset", filename=path, revision=revision,
                  token=token) for path in files]
    return load_files(local, config)


class DownloadFailed(Exception):
    pass


def compare_datasets(repo_id: str, comparison: Comparison, old: Revision, new: Revision, token: str | None,
                     call: Call = direct_call, config: EngineConfig = DEFAULT_CONFIG) -> Comparison:
    """
    Descarrega i compara el dataset de les dues revisions, si la comparació és
    pendent, i n'actualitza l'estat i el resultat. Una fallada de descàrrega o
    de lectura queda com a estat, mai com a canvis.

    :param repo_id: repositori de Hugging Face.
    :param comparison: comparació de `pair_datasets` (es modifica).
    :param old: revisió antiga.
    :param new: revisió nova.
    :param token: token d'accés, o `None`.
    :param call: funció per fer les crides a l'API.
    :param config: llindars del motor.
    :return: la mateixa comparació, amb l'estat i el resultat omplerts.
    """
    if comparison.status != "pending":
        return comparison
    if comparison.size_bytes > config.max_dataset_bytes:
        comparison.status = "too_large"
        return comparison
    try:
        try:
            old_table = _load_files(repo_id, old.revision, comparison.old.files, token, call, config)
            new_table = _load_files(repo_id, new.revision, comparison.new.files, token, call, config)
        except ParseError:
            raise
        except Exception as exc:
            raise DownloadFailed(str(exc)) from exc
    except DownloadFailed:
        comparison.status = "download_failed"
        return comparison
    except ParseError:
        comparison.status = "parse_failed"
        return comparison
    comparison.result = diff_tables(old_table, new_table, config)
    comparison.status = "ok"
    return comparison


def revision_rows(repo_id: str, old_rev: str, new_rev: str, comparison: Comparison) -> list[dict]:
    """
    Converteix els canvis d'una comparació en files de sortida.

    :param repo_id: repositori de Hugging Face.
    :param old_rev: commit antic.
    :param new_rev: commit nou.
    :param comparison: la comparació ja feta.
    :return: una fila per canvi, amb `dataset_id`, `version_from`, `version_to` i `code`.
    """
    changes = comparison.result.changes if comparison.result is not None else []
    return [{"dataset_id": repo_id, "version_from": old_rev, "version_to": new_rev, "code": c.code} for c in changes]


def status_row(repo_id: str, old_rev: str, new_rev: str, comparison: Comparison) -> dict:
    """
    L'estat de la comparació, també si no té cap codi: així es distingeix
    "sense canvis" (`ok` sense codis, `identical_content`) de "no s'ha pogut
    comparar" (`too_large`, `parse_failed`...).

    :param repo_id: repositori de Hugging Face.
    :param old_rev: commit antic.
    :param new_rev: commit nou.
    :param comparison: la comparació ja feta.
    :return: `dataset_id`, `version_from`, `version_to`, `status`, `n_codes`
        (codis diferents), `format_from`/`format_to` i `n_files_from`/`n_files_to`
        (el format i el nombre de fitxers del dataset a cada versió) i
        `size_bytes` (la mida de les dues versions, sumades).
    """
    return {"dataset_id": repo_id, "version_from": old_rev, "version_to": new_rev, "status": comparison.status,
            "n_codes": len(comparison.result.codes) if comparison.result is not None else 0,
            "format_from": comparison.old.fmt, "format_to": comparison.new.fmt,
            "n_files_from": len(comparison.old.files), "n_files_to": len(comparison.new.files),
            "size_bytes": comparison.size_bytes}


def compare_revisions(repo_id: str, old_rev: str, new_rev: str, token: str | None, call: Call = direct_call,
                      config: EngineConfig = DEFAULT_CONFIG) -> Comparison:
    """
    Compara el dataset de dues revisions d'un repositori. És la funció que fa
    servir el pipeline. Si els fitxers no han canviat, no es descarreguen.

    :param repo_id: repositori de Hugging Face.
    :param old_rev: commit antic.
    :param new_rev: commit nou.
    :param token: token d'accés, o `None`.
    :param call: funció per fer les crides a l'API (p.e. amb reintents).
    :param config: llindars del motor.
    :return: la comparació, amb el seu estat i, si s'ha fet, el resultat.
    """
    old = list_revision(repo_id, old_rev, token, call, config)
    new = list_revision(repo_id, new_rev, token, call, config)
    return compare_datasets(repo_id, pair_datasets(old, new), old, new, token, call, config)
