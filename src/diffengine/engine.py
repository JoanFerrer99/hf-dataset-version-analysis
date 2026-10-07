"""
Orquestració: de dos fitxers (o dues taules ja carregades) a la llista de canvis.

1. Columnes per nom (L3) i files (L4).
2. Si queden columnes sense parella, es busquen renoms pel contingut sobre les
   files aparellades i, si se'n troben, es tornen a aparellar les files
   (com a màxim 2 vegades: un renom pot millorar l'aparellament de files).
3. Cada detector (L5) busca els seus codis.
"""

import hashlib
from dataclasses import replace

import pandas as pd

from diffengine.columns import align_by_content, align_by_name, classify_leftovers
from diffengine.config import DEFAULT_CONFIG, EngineConfig
from diffengine.detectors import DETECTORS, PAIRED_DETECTORS, ROW_DETECTORS, Context, find_identifiers
from diffengine.load import NUMERIC, ParseError, Table, load_table
from diffengine.output import DiffResult
from diffengine.rows import align_rows

def _row_confidence(change, old: Table, new: Table, rows) -> float:
    """
    Proporció de parelles no ambigües; però la diferència de recompte de files
    és segura: si la taula perd 100 files, almenys 100 són C422.
    """
    unambiguous = 1 - rows.ambiguous_share
    surplus = {"C421": new.n_rows - old.n_rows, "C422": old.n_rows - new.n_rows}.get(change.code, 0)
    if surplus > 0 and change.n_affected:
        return max(unambiguous, min(1.0, surplus / change.n_affected))
    return unambiguous


def _adopt_kind_of_empty_columns(old: Table, new: Table, pairs: list[tuple[str, str]]) -> None:
    """
    Una columna sense cap valor no té tipus: pren el de la columna aparellada.
    Així, una columna buida que s'omple és C510 (valors nous), no C311/C321.
    """
    for o, n in pairs:
        for empty, ec, full, fc in ((old, o, new, n), (new, n, old, o)):
            if empty.values[ec].isna().all() and not full.values[fc].isna().all():
                kind = full.columns[fc].kind
                empty.columns[ec] = replace(empty.columns[ec], kind=kind, integer=full.columns[fc].integer)
                if kind == NUMERIC:
                    empty.values[ec] = pd.Series(float("nan"), index=empty.values.index)
                else:
                    empty.values[ec] = pd.Series(None, index=empty.values.index, dtype=object)


def diff_tables(old: Table, new: Table, config: EngineConfig = DEFAULT_CONFIG) -> DiffResult:
    """Compara dues taules ja carregades i en retorna els canvis (estat `ok`)."""
    cols = align_by_name(old, new)
    rows = align_rows(old, new, cols.pairs(), config)
    for _ in range(2):
        if not (cols.removed and cols.added):
            break
        if not align_by_content(old, new, cols, rows, config):
            break
        rows = align_rows(old, new, cols.pairs(), config)
    classify_leftovers(old, new, cols, config)
    _adopt_kind_of_empty_columns(old, new, cols.pairs())

    ctx = Context(old, new, cols, rows, config)
    find_identifiers(ctx)
    alignment = {"row_alignment": rows.method, "key_columns": rows.key_columns,
                 "matched_row_share": round(rows.matched_share, 4), "ambiguous_share": round(rows.ambiguous_share, 4)}
    changes = []
    for detector in DETECTORS:
        found = detector(ctx)
        for c in found:
            if detector in PAIRED_DETECTORS:
                c.evidence = {**alignment, **c.evidence}
            if detector in ROW_DETECTORS:
                c.confidence = min(c.confidence, _row_confidence(c, old, new, rows))
        changes += found

    info = {**alignment, "stable_columns": rows.stable_columns, "format_old": old.fmt, "format_new": new.fmt,
            "dialect_old": old.dialect, "dialect_new": new.dialect}
    return DiffResult("ok", changes, info)


def diff_bytes(old_data: bytes, old_ext: str, new_data: bytes, new_ext: str,
               config: EngineConfig = DEFAULT_CONFIG) -> DiffResult:
    """
    Compara dues versions d'un fitxer. Un canvi de format o de delimitador
    (C100, fora d'abast) queda a `info`, no com a codi.
    """
    if hashlib.sha256(old_data).digest() == hashlib.sha256(new_data).digest() and old_ext == new_ext:
        return DiffResult("identical_content")
    try:
        old = load_table(old_data, old_ext, config)
        new = load_table(new_data, new_ext, config)
    except ParseError as exc:
        return DiffResult("parse_failed", info={"error": str(exc)[:300]})
    return diff_tables(old, new, config)
