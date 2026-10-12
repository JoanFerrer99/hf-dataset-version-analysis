"""
Pas 1 (segona part): aparellar les taules de dues revisions i comparar-les.

Aquí comença una comparació de revisions: `compare_revisions` fa el pas 1 i
crida `engine.diff_tables` (passos 3 i 4) per a cada parell; `revision_rows`
converteix els canvis en files de sortida (pas 5).

- Cada revisió es llista amb l'API (`list_revision`) i se'n resolen les
  taules (`units.resolve_units`).
- `pair_units` aparella les taules per nom de partició. Una taula d'un sol
  fitxer sense parella prova pel camí, pel contingut (fitxer reanomenat) i
  pel nom amb una altra extensió (canvi de format).
- `compare_pair` descarrega i compara cada parell, i li posa un estat:
  `ok`, `identical_content` (mateix hash: no es descarrega), `absent_old`,
  `absent_new`, `download_failed`, `parse_failed`, `too_large` o
  `excluded`. Només les `ok` tenen canvis: una fallada mai es converteix en
  codis.

Les crides al Hub passen per `call(fn, *args, **kwargs)`: qui fa servir el
motor hi posa la seva política de reintents. Així el motor no depèn del
pipeline.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
from huggingface_hub import hf_hub_download, list_repo_tree

from diffengine.config import DEFAULT_CONFIG, EngineConfig
from diffengine.engine import diff_tables
from diffengine.load import ParseError, Table, load_table
from diffengine.output import DiffResult
from diffengine.units import RepoLayout, resolve_units

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
    layout: RepoLayout


@dataclass
class UnitPair:
    """
    :ivar key: `subset/split` per a taules, o la ruta per a fitxers sols.
    :ivar status: `pending` fins que es compara; després `ok`, `identical_content`,
        `absent_old`, `absent_new`, `download_failed`, `parse_failed`,
        `too_large` o `excluded` (fitxer tabular canviat que no és cap taula).
    """

    key: str
    old_files: tuple[str, ...]
    new_files: tuple[str, ...]
    status: str = "pending"
    result: DiffResult | None = None


def list_revision(repo_id: str, revision: str, token: str | None, call: Call = direct_call) -> Revision:
    """
    Llista els fitxers d'una revisió (amb mida i identificador de contingut) i
    en troba les taules.

    :param repo_id: repositori de Hugging Face (`propietari/nom`).
    :param revision: commit a llistar.
    :param token: token d'accés a Hugging Face, o `None`.
    :param call: funció per fer les crides a l'API (permet afegir-hi reintents).
    :return: la revisió: mides, identificadors de contingut i taules.
    """
    entries = call(
        lambda: list(list_repo_tree(repo_id, repo_type="dataset", revision=revision, recursive=True, token=token)))
    files = [e for e in entries if getattr(e, "size", None) is not None]
    sizes = {e.path: e.size for e in files}
    content_ids = {e.path: (e.lfs.sha256 if getattr(e, "lfs", None) else e.blob_id) for e in files}
    readme = None
    if "README.md" in sizes:
        try:
            local = call(hf_hub_download, repo_id=repo_id, repo_type="dataset", filename="README.md",
                         revision=revision, token=token)
            with open(local, encoding="utf-8", errors="replace") as f:
                readme = f.read()
        except Exception:
            readme = None
    return Revision(revision, sizes, content_ids, resolve_units(list(sizes), readme))


def _units(rev: Revision, config: EngineConfig) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """
    Separa les taules d'una revisió en dos grups: les que s'aparellen pel nom de
    la partició i els fitxers que s'aparellen per la ruta.

    :param rev: revisió ja llistada.
    :param config: llindars del motor (si es concatenen els fitxers partits).
    :return: `(taules per nom de partició, fitxers sols per ruta)`.
    """
    tables, singles = {}, {}
    for u in rev.layout.units:
        # Una taula d'un sol fitxer, o partida en shards o episodis numerats (si
        # `concat_shards`), es compara sencera i s'aparella pel nom de la partició.
        # Els fitxers d'una partició amb noms sense relació van cadascun pel seu compte.
        if u.naming == "single" or (u.naming in ("hf_shards", "numbered") and config.concat_shards):
            tables[f"{u.subset}/{u.split}"] = u.files
        else:
            for f in u.files:
                singles[f] = f
    return tables, singles


def pair_units(old: Revision, new: Revision, config: EngineConfig = DEFAULT_CONFIG) -> list[UnitPair]:
    """
    Aparella les taules de dues revisions. Per nom de partició; si una taula
    d'un sol fitxer no troba parella, per la ruta, després pel contingut
    (fitxer reanomenat) i després pel nom amb una altra extensió. A cada parella
    li posa l'estat inicial (`pending`, `identical_content`, `absent_old`,
    `absent_new` o `excluded`).

    :param old: revisió antiga.
    :param new: revisió nova.
    :param config: llindars del motor.
    :return: una parella per taula, inclosos els fitxers exclosos que han canviat.
    """
    old_tables, old_singles = _units(old, config)
    new_tables, new_singles = _units(new, config)
    pairs: list[UnitPair] = []

    for key in sorted(set(old_tables) | set(new_tables)):
        a, b = old_tables.get(key, ()), new_tables.get(key, ())
        if a and b:
            pairs.append(UnitPair(key, a, b))
        elif len(a) == 1:
            old_singles[a[0]] = a[0]  # una taula d'un sol fitxer sense parella: s'aparella com a fitxer
        elif len(b) == 1:
            new_singles[b[0]] = b[0]
        else:
            pairs.append(UnitPair(key, a, b))

    unmatched_old = [p for p in old_singles if p not in new_singles]
    unmatched_new = [p for p in new_singles if p not in old_singles]
    for path in sorted(set(old_singles) & set(new_singles)):
        pairs.append(UnitPair(path, (path,), (path,)))
    by_content = {new.content_ids[p]: p for p in unmatched_new}
    for path in list(unmatched_old):
        target = by_content.get(old.content_ids[path])
        if target in unmatched_new:
            pairs.append(UnitPair(target, (path,), (target,)))
            unmatched_old.remove(path)
            unmatched_new.remove(target)
    by_stem = {os.path.splitext(p)[0]: p for p in unmatched_new}
    for path in list(unmatched_old):
        target = by_stem.get(os.path.splitext(path)[0])
        if target in unmatched_new:
            pairs.append(UnitPair(target, (path,), (target,)))
            unmatched_old.remove(path)
            unmatched_new.remove(target)
    pairs += [UnitPair(p, (p,), ()) for p in unmatched_old]
    pairs += [UnitPair(p, (), (p,)) for p in unmatched_new]

    for p in pairs:
        if not p.old_files:
            p.status = "absent_old"
        elif not p.new_files:
            p.status = "absent_new"
        elif [old.content_ids[f] for f in p.old_files] == [new.content_ids[f] for f in p.new_files]:
            p.status = "identical_content"

    # Fitxers tabulars que no formen part de cap taula (fora de cap partició, metadades
    # d'un repositori de media o un altre format): no es comparen, però si han canviat
    # queden a la llista amb l'estat `excluded`, perquè no es perdin en silenci.
    in_pairs = {f for p in pairs for f in p.old_files + p.new_files}
    excluded = {**old.layout.excluded, **new.layout.excluded}
    for path in sorted(set(excluded) - in_pairs):
        if old.content_ids.get(path) != new.content_ids.get(path):
            pairs.append(UnitPair(path, (path,) if path in old.sizes else (), (path,) if path in new.sizes else (),
                                  status="excluded"))
    return pairs


def _concat(tables: list[Table]) -> Table:
    """
    Uneix en una sola taula els shards d'un split (o els episodis numerats),
    posant les files de cada shard a continuació de les de l'anterior, en
    ordre. Una columna només es considera d'enters si ho és a tots els shards.

    :param tables: els shards ja llegits, en ordre.
    :return: la taula sencera.
    :raises ParseError: si les parts no tenen les mateixes columnes.
    """
    first = tables[0]
    if any(list(t.values.columns) != list(first.values.columns) for t in tables[1:]):
        raise ParseError("els shards no comparteixen esquema")
    values = pd.concat([t.values for t in tables], ignore_index=True)
    raw = pd.concat([t.raw for t in tables], ignore_index=True) if all(t.raw is not None for t in tables) else None
    columns = dict(first.columns)
    for name, col in columns.items():
        col.integer = all(t.columns[name].integer for t in tables if name in t.columns)
    return Table(first.fmt, values, columns, raw=raw, dialect=first.dialect)


def _load_files(repo_id: str, revision: str, files: tuple[str, ...], token: str | None, call: Call,
                config: EngineConfig) -> Table:
    """
    Descarrega i llegeix els fitxers d'una taula en una revisió.

    :param repo_id: repositori de Hugging Face.
    :param revision: commit.
    :param files: fitxers de la taula.
    :param token: token d'accés, o `None`.
    :param call: funció per fer les crides a l'API.
    :param config: llindars del motor.
    :return: la taula llegida (concatenada si n'hi ha més d'un).
    """
    tables = []
    for path in files:
        local = call(hf_hub_download, repo_id=repo_id, repo_type="dataset", filename=path,
                     revision=revision, token=token)
        with open(local, "rb") as f:
            tables.append(load_table(f.read(), os.path.splitext(path)[1], config))
    return tables[0] if len(tables) == 1 else _concat(tables)


class DownloadFailed(Exception):
    pass


def compare_pair(repo_id: str, pair: UnitPair, old: Revision, new: Revision, token: str | None,
                 call: Call = direct_call, config: EngineConfig = DEFAULT_CONFIG) -> UnitPair:
    """
    Descarrega i compara una parella de taules pendent, i n'actualitza l'estat
    i el resultat. Una fallada de descàrrega o de lectura queda com a estat, mai
    com a canvis.

    :param repo_id: repositori de Hugging Face.
    :param pair: parella a comparar (es modifica).
    :param old: revisió antiga.
    :param new: revisió nova.
    :param token: token d'accés, o `None`.
    :param call: funció per fer les crides a l'API.
    :param config: llindars del motor.
    :return: la mateixa parella, amb l'estat i el resultat omplerts.
    """
    if pair.status != "pending":
        return pair
    total = sum(old.sizes[f] for f in pair.old_files) + sum(new.sizes[f] for f in pair.new_files)
    if total > config.max_unit_bytes:
        pair.status = "too_large"
        return pair
    try:
        try:
            old_table = _load_files(repo_id, old.revision, pair.old_files, token, call, config)
            new_table = _load_files(repo_id, new.revision, pair.new_files, token, call, config)
        except ParseError:
            raise
        except Exception as exc:
            raise DownloadFailed(str(exc)) from exc
    except DownloadFailed:
        pair.status = "download_failed"
        return pair
    except ParseError:
        pair.status = "parse_failed"
        return pair
    pair.result = diff_tables(old_table, new_table, config)
    pair.status = "ok"
    return pair


def revision_rows(repo_id: str, old_rev: str, new_rev: str, pairs: list[UnitPair]) -> list[dict]:
    """
    Converteix els canvis de les parelles comparades en files de sortida.

    :param repo_id: repositori de Hugging Face.
    :param old_rev: commit antic.
    :param new_rev: commit nou.
    :param pairs: parelles ja comparades.
    :return: una fila per canvi, amb `dataset_id`, `version_from`,
        `version_to`, `file_path` i `code`.
    """
    return [{"dataset_id": repo_id, "version_from": old_rev, "version_to": new_rev,
             "file_path": ",".join(p.new_files), "code": c.code}
            for p in pairs if p.result is not None for c in p.result.changes]


def compare_revisions(repo_id: str, old_rev: str, new_rev: str, token: str | None, call: Call = direct_call,
                      config: EngineConfig = DEFAULT_CONFIG) -> list[UnitPair]:
    """
    Compara totes les taules de dues revisions d'un repositori. És la funció que
    fa servir el pipeline. Les taules amb el mateix contingut no es descarreguen.

    :param repo_id: repositori de Hugging Face.
    :param old_rev: commit antic.
    :param new_rev: commit nou.
    :param token: token d'accés, o `None`.
    :param call: funció per fer les crides a l'API (p.e. amb reintents).
    :param config: llindars del motor.
    :return: una parella per taula, cadascuna amb el seu estat i, si s'ha comparat, el resultat.
    """
    old = list_revision(repo_id, old_rev, token, call)
    new = list_revision(repo_id, new_rev, token, call)
    pairs = pair_units(old, new, config)
    for pair in pairs:
        compare_pair(repo_id, pair, old, new, token, call, config)
    return pairs
