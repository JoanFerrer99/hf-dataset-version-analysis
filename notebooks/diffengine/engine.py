"""
Orquestració: de dos fitxers (o dues taules ja carregades) a una llista de
canvis amb estat.

Les columnes i les files s'aparellen alternant (L3 ↔ L4): primer columnes
per nom, després files, després columnes per contingut sobre aquestes
files, i si apareixen renoms nous es tornen a aparellar les files (2
iteracions com a màxim).
"""

import hashlib

from diffengine.columns import align_by_content, align_by_name, classify_leftovers
from diffengine.config import DEFAULT_CONFIG, EngineConfig
from diffengine.detectors import DETECTORS, Context, detect_order, detect_rows, detect_values, find_identifiers
from diffengine.load import ParseError, Table, load_table
from diffengine.output import DiffResult
from diffengine.rows import align_rows

# Detectors que depenen de l'aparellament de files: la seva evidència inclou com
# s'han aparellat, i la confiança dels de files es limita pels parells no ambigus.
PAIRED_DETECTORS = {detect_values, detect_order, detect_rows}
ROW_DETECTORS = {detect_order, detect_rows}


def diff_tables(old: Table, new: Table, config: EngineConfig = DEFAULT_CONFIG) -> DiffResult:
    cols = align_by_name(old, new)
    rows = align_rows(old, new, cols.pairs(), config)
    for _ in range(2):
        if not (cols.removed and cols.added):
            break
        if not align_by_content(old, new, cols, rows, config):
            break
        rows = align_rows(old, new, cols.pairs(), config)
    classify_leftovers(old, new, cols, config)

    ctx = Context(old, new, cols, rows, config)
    ctx.identifiers = find_identifiers(old, rows, cols)
    alignment = {"row_alignment": rows.method, "key_columns": rows.key_columns,
                 "matched_row_share": round(rows.matched_share, 4), "ambiguous_share": round(rows.ambiguous_share, 4)}
    changes = []
    for detector in DETECTORS:
        found = detector(ctx)
        for c in found:
            if detector in PAIRED_DETECTORS:
                c.evidence = {**alignment, **c.evidence}
            if detector in ROW_DETECTORS:
                c.confidence = min(c.confidence, 1 - rows.ambiguous_share)
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
