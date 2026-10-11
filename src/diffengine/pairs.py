"""
L0, segona part: aparellar les taules de dues revisions i comparar-les.

- Cada revisió es llista amb l'API (`list_revision`) i se'n resolen les
  taules (`units.resolve_units`).
- `pair_units` aparella les taules per nom de partició. Una taula d'un sol
  fitxer sense parella prova pel camí, pel contingut (fitxer reanomenat) i
  pel nom amb una altra extensió (canvi de format).
- `compare_pair` descarrega i compara cada parell, i li posa un estat:
  `ok`, `identical_content` (mateix hash: no es descarrega), `absent_old`,
  `absent_new`, `download_failed`, `parse_failed`, `too_large_profile_only`
  o `excluded`. Una fallada mai es converteix en codis de canvi.

Les crides al Hub passen per `call(fn, *args, **kwargs)`: qui fa servir el
motor hi posa la seva política de reintents. Així el motor no depèn del
pipeline.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from huggingface_hub import hf_hub_download, list_repo_tree

from diffengine.config import DEFAULT_CONFIG, EngineConfig
from diffengine.engine import diff_tables
from diffengine.load import ParseError, Table, load_table
from diffengine.output import ENGINE_VERSION, DiffResult, changes_frame, status_frame
from diffengine.units import RepoLayout, resolve_units

Call = Callable[..., object]


def direct_call(fn, *args, **kwargs):
    """`call` per defecte: sense reintents."""
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
        `too_large_profile_only` o `excluded` (fitxer tabular canviat que no és
        cap taula; el motiu és a `info["reason"]`).
    """

    key: str
    old_files: tuple[str, ...]
    new_files: tuple[str, ...]
    status: str = "pending"
    result: DiffResult | None = None
    info: dict = field(default_factory=dict)


def list_revision(repo_id: str, revision: str, token: str | None, call: Call = direct_call) -> Revision:
    """Llista fitxers (amb mida i hash de contingut) i resol les taules d'una revisió."""
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
    """`(taules per clau subset/split, fitxers sols per ruta)`."""
    tables, singles = {}, {}
    for u in rev.layout.units:
        if u.naming == "single" or (u.naming in ("hf_shards", "numbered") and config.concat_shards):
            tables[f"{u.subset}/{u.split}"] = u.files
        else:
            for f in u.files:
                singles[f] = f
    return tables, singles


def pair_units(old: Revision, new: Revision, config: EngineConfig = DEFAULT_CONFIG) -> list[UnitPair]:
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
            pairs.append(UnitPair(target, (path,), (target,), info={"renamed_from": path}))
            unmatched_old.remove(path)
            unmatched_new.remove(target)
    by_stem = {os.path.splitext(p)[0]: p for p in unmatched_new}
    for path in list(unmatched_old):
        target = by_stem.get(os.path.splitext(path)[0])
        if target in unmatched_new:
            pairs.append(UnitPair(target, (path,), (target,), info={"format_change": True}))
            unmatched_old.remove(path)
            unmatched_new.remove(target)
    pairs += [UnitPair(p, (p,), ()) for p in unmatched_old]
    pairs += [UnitPair(p, (), (p,)) for p in unmatched_new]

    for p in pairs:
        old_ext = {os.path.splitext(f)[1] for f in p.old_files}
        new_ext = {os.path.splitext(f)[1] for f in p.new_files}
        if p.old_files and p.new_files and old_ext != new_ext:
            p.info["format_change"] = True
        if not p.old_files:
            p.status = "absent_old"
        elif not p.new_files:
            p.status = "absent_new"
        elif [old.content_ids[f] for f in p.old_files] == [new.content_ids[f] for f in p.new_files]:
            p.status = "identical_content"

    # Fitxers tabulars exclosos (decisió U1/U3): no es comparen, però si han
    # canviat queden registrats amb el motiu.
    in_pairs = {f for p in pairs for f in p.old_files + p.new_files}
    excluded = {**old.layout.excluded, **new.layout.excluded}
    for path in sorted(set(excluded) - in_pairs):
        if old.content_ids.get(path) != new.content_ids.get(path):
            pairs.append(UnitPair(path, (path,) if path in old.sizes else (), (path,) if path in new.sizes else (),
                                  status="excluded", info={"reason": excluded[path]}))
    return pairs


def _concat(tables: list[Table]) -> Table:
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
    """Descarrega i compara un parell `pending`. Omple `status` i `result`."""
    if pair.status != "pending":
        return pair
    total = sum(old.sizes[f] for f in pair.old_files) + sum(new.sizes[f] for f in pair.new_files)
    if total > config.max_unit_bytes:
        pair.status = "too_large_profile_only"
        pair.info["bytes"] = total
        return pair
    try:
        try:
            old_table = _load_files(repo_id, old.revision, pair.old_files, token, call, config)
            new_table = _load_files(repo_id, new.revision, pair.new_files, token, call, config)
        except ParseError:
            raise
        except Exception as exc:
            raise DownloadFailed(str(exc)) from exc
    except DownloadFailed as exc:
        pair.status, pair.info["error"] = "download_failed", str(exc)[:300]
        return pair
    except ParseError as exc:
        pair.status, pair.info["error"] = "parse_failed", str(exc)[:300]
        return pair
    pair.result = diff_tables(old_table, new_table, config)
    pair.status = "ok"
    return pair


def revision_rows(repo_id: str, old_rev: str, new_rev: str, pairs: list[UnitPair],
                  config: EngineConfig = DEFAULT_CONFIG) -> tuple[list[dict], list[dict]]:
    """
    Converteix els parells comparats en files de sortida.

    :return: `(canvis, estats)`: una fila per canvi detectat (format llarg de
        `output.changes_frame`) i una fila d'estat per parell.
    """
    changes, statuses = [], []
    for p in pairs:
        key = {"repo_id": repo_id, "old_rev": old_rev, "new_rev": new_rev,
               "file_path": ",".join(p.new_files) or None,
               "old_file_path": ",".join(p.old_files) if p.old_files != p.new_files else None}
        result = p.result or DiffResult(p.status)
        result.status = p.status
        result.info = {**result.info, **p.info}
        changes += changes_frame(result, key, ENGINE_VERSION, config.hash()).to_dict("records")
        statuses += status_frame(result, {**key, "unit": p.key}).to_dict("records")
    return changes, statuses


def compare_revisions(repo_id: str, old_rev: str, new_rev: str, token: str | None, call: Call = direct_call,
                      config: EngineConfig = DEFAULT_CONFIG) -> list[UnitPair]:
    """Compara totes les taules de dues revisions (les de contingut idèntic no es descarreguen)."""
    old = list_revision(repo_id, old_rev, token, call)
    new = list_revision(repo_id, new_rev, token, call)
    pairs = pair_units(old, new, config)
    for pair in pairs:
        compare_pair(repo_id, pair, old, new, token, call, config)
    return pairs
