"""
L'índex del motor: com es comparen dues versions d'un dataset, en 5 passos.

    Pas 1. Trobar les taules que es comparen     units.py, pairs.py
    Pas 2. Llegir cada taula                     load.py
    Pas 3. Aparellar columnes i files            columns.py, rows.py, transforms.py
             3a. columnes pel nom
             3b. files
             3c. columnes pel contingut (si en troba, torna a 3b)
    Pas 4. Detectar els canvis                   detectors/
    Pas 5. Escriure el resultat                  output.py

Hi ha dues maneres d'entrar:

- `pairs.compare_revisions` (el fa servir el pipeline): dues revisions d'un
  repositori. Fa el pas 1 i, per a cada parell de taules, crida `diff_tables`.
- `diff_bytes`: dos fitxers sols (validació de Census Income, tests). Comença
  al pas 2.

Aquest fitxer es llegeix de dalt a baix: primer les entrades, després una
funció per pas.
"""

import hashlib
from dataclasses import replace

import pandas as pd

from diffengine.columns import ColumnAlignment, align_by_content, align_by_name, classify_leftovers
from diffengine.config import DEFAULT_CONFIG, EngineConfig
from diffengine.detectors import DETECTORS, PAIRED_DETECTORS, ROW_DETECTORS, Context, find_identifiers
from diffengine.load import NUMERIC, ParseError, Table, load_table
from diffengine.output import Change, DiffResult
from diffengine.rows import RowAlignment, align_rows


# --- Entrades -------------------------------------------------------------------


def diff_bytes(old_data: bytes, old_ext: str, new_data: bytes, new_ext: str,
               config: EngineConfig = DEFAULT_CONFIG) -> DiffResult:
    """
    Compara dues versions d'un fitxer (pas 2 i següents). Si són idèntiques
    byte a byte, no cal llegir-les. Un canvi de format (C100) és fora d'abast.
    """
    if hashlib.sha256(old_data).digest() == hashlib.sha256(new_data).digest() and old_ext == new_ext:
        return DiffResult("identical_content")
    try:
        old = load_table(old_data, old_ext, config)      # Pas 2
        new = load_table(new_data, new_ext, config)
    except ParseError as exc:
        return DiffResult("parse_failed", info={"error": str(exc)[:300]})
    return diff_tables(old, new, config)


def diff_tables(old: Table, new: Table, config: EngineConfig = DEFAULT_CONFIG) -> DiffResult:
    """Compara dues taules ja llegides (passos 3 i 4) i en retorna els canvis."""
    cols, rows = match_columns_and_rows(old, new, config)   # Pas 3
    changes = detect_changes(old, new, cols, rows, config)  # Pas 4
    info = {**_alignment_summary(rows), "stable_columns": rows.stable_columns,
            "format_old": old.fmt, "format_new": new.fmt, "dialect_old": old.dialect, "dialect_new": new.dialect}
    return DiffResult("ok", changes, info)


# --- Pas 3: aparellar columnes i files ----------------------------------------------


def match_columns_and_rows(old: Table, new: Table,
                           config: EngineConfig) -> tuple[ColumnAlignment, RowAlignment]:
    """
    Decideix quina columna i quina fila noves corresponen a quines antigues.

    Columnes i files depenen les unes de les altres: per reconèixer una columna
    reanomenada pel contingut cal saber quines files són la mateixa, i una
    columna reconeguda ajuda a reconèixer files. Per això s'alternen, com a
    màxim dues vegades.
    """
    cols = align_by_name(old, new)                          # 3a. columnes pel nom
    rows = align_rows(old, new, cols.pairs(), config)       # 3b. files
    for _ in range(2):
        if not (cols.removed and cols.added):
            break
        if not align_by_content(old, new, cols, rows, config):  # 3c. columnes pel contingut
            break
        rows = align_rows(old, new, cols.pairs(), config)   # 3b de nou, amb les columnes noves
    classify_leftovers(old, new, cols, config)              # columnes sense parella: afegides o eliminades
    _adopt_kind_of_empty_columns(old, new, cols.pairs())
    return cols, rows


# --- Pas 4: detectar els canvis -----------------------------------------------------


def detect_changes(old: Table, new: Table, cols: ColumnAlignment, rows: RowAlignment,
                   config: EngineConfig) -> list[Change]:
    """
    Executa cada detector (`detectors/`, un per perspectiva de la taxonomia)
    sobre el que s'ha aparellat. Als canvis que depenen de les files
    aparellades s'hi afegeix com s'han aparellat (evidència) i se'n limita la
    confiança si l'aparellament és dubtós.
    """
    ctx = Context(old, new, cols, rows, config)
    find_identifiers(ctx)
    alignment = _alignment_summary(rows)
    changes = []
    for detector in DETECTORS:
        found = detector(ctx)
        for c in found:
            if detector in PAIRED_DETECTORS:
                c.evidence = {**alignment, **c.evidence}
            if detector in ROW_DETECTORS:
                c.confidence = min(c.confidence, _row_confidence(c, old, new, rows))
        changes += found
    return changes


# --- Detalls ------------------------------------------------------------------------


def _alignment_summary(rows: RowAlignment) -> dict:
    return {"row_alignment": rows.method, "key_columns": rows.key_columns,
            "matched_row_share": round(rows.matched_share, 4), "ambiguous_share": round(rows.ambiguous_share, 4)}


def _row_confidence(change: Change, old: Table, new: Table, rows: RowAlignment) -> float:
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
