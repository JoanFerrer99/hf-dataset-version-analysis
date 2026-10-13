"""
C3xx, canvis en una columna concreta.

- C311/C321: canvia el tipus (categòrica ↔ numèrica). El codi es tria pel
  tipus antic: C311 si la columna era categòrica, C321 si era numèrica. Si
  el canvi és una correspondència u a u entre valors (codificar categories
  com a enters, p.e. `Private` → 2), també han canviat els valors del
  domini: s'hi afegeix C312 `recoded`.
- C312/C322: canvien els valors. Es comparen cel·la a cel·la a les files
  aparellades, i el subtipus diu què ho explica: una transformació
  (`factor`, `log`…), un mapatge de categories (`relabel`, `merge`…), només
  el format (`representation`) o edicions soltes (`cell_edits`).
"""

import numpy as np
import pandas as pd

from diffengine.columns import ColumnMatch
from diffengine.detectors.common import Context, change, family
from diffengine.load import NUMERIC
from diffengine.output import Change
from diffengine.rows import cell_tokens, is_sequence
from diffengine.transforms import analyze_mapping, fit_numeric, is_bijection, is_perturbation

# Ajustos que són un subtipus de C322 (`identity` no és un canvi; `round` és C321).
C322_FITS = {"factor", "linear", "minmax", "standardization", "normalization", "log", "sqrt", "reciprocal", "exp"}


def detect_kinds(ctx: Context) -> list[Change]:
    """
    Canvis de tipus d'una columna (categòrica ↔ numèrica, real → enter). Es
    codifica pel tipus antic: C311 si era categòrica, C321 si era numèrica.
    Marca a `ctx.kind_changed` les columnes que canvien de tipus, perquè no se'n
    comparin els valors.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :return: els canvis trobats.
    """
    out = []
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        fo, fn = family(ko.kind), family(kn.kind)
        if "opaque" in (fo, fn):
            continue
        if fo != fn:
            # Canvi de família (categòrica ↔ numèrica): el codi depèn del tipus antic
            # (`kind_change_by_old_kind`), i els valors d'aquesta columna ja no es comparen.
            ctx.kind_changed.add(m.old)
            old_based = fo if ctx.config.kind_change_by_old_kind else fn
            code = "C311" if old_based == "categorical" else "C321"
            out.append(change(code, m, subtype="to_numeric" if fn == "numeric" else "to_categorical"))
            recoding = _recoding(ctx, m)
            if recoding is not None:
                out.append(recoding)
        elif fo == "numeric" and not ko.integer and kn.integer and len(ctx.rows.pairs):
            x, y = ctx.paired(m)
            fit = fit_numeric(x.to_numpy(float), y.to_numpy(float), ctx.config.column_match_min_validity)
            if fit is not None and fit.kind == "round":
                ctx.kind_changed.add(m.old)
                out.append(change("C321", m, subtype="real_to_integer"))
    return out


def _recoding(ctx: Context, m: ColumnMatch) -> Change | None:
    """
    Si un canvi de tipus és una correspondència u a u entre valors (codificar
    categories com a enters), també han canviat els valors: C312 `recoded`. Un
    canvi només de format ("1" → 1) no compta.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :param m: parella de columnes.
    :return: el canvi, o `None` si no és una recodificació.
    """
    pairs = ctx.rows.reliable_pairs
    if len(pairs) < 10:
        return None
    a = cell_tokens(ctx.old, m.old).iloc[pairs[:, 0]].reset_index(drop=True)
    b = cell_tokens(ctx.new, m.new).iloc[pairs[:, 1]].reset_index(drop=True)
    ok, _ = is_bijection(a, b, ctx.config.column_match_min_validity)
    if not ok or a.nunique() < 2 or (a == b).mean() >= ctx.config.column_match_min_validity:
        return None
    return change("C312", m, subtype="recoded")


def detect_values(ctx: Context) -> list[Change]:
    """
    Canvis de valors (C312 per a categòriques, C322 per a numèriques), comparant
    cel·la a cel·la les files aparellades.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :return: els canvis trobats.
    """
    out = []
    if not len(ctx.rows.pairs):
        return out
    for m in ctx.cols.matches:
        if not ctx.comparable(m):
            continue
        a, b = ctx.paired(m)
        if ctx.old.columns[m.old].kind == NUMERIC:
            out += _numeric_values(ctx, m, a, b)
        else:
            out += _categorical_values(ctx, m, a, b)
    return out


def _numeric_values(ctx: Context, m: ColumnMatch, a: pd.Series, b: pd.Series) -> list[Change]:
    """
    Explica com han canviat els valors d'una columna numèrica, en aquest ordre:
    només el format (`representation`), un comptador renumerat (`renumbered`), una
    fórmula (`factor`, `log`...), soroll (`perturbation`) o cel·les soltes
    (`cell_edits`).

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :param m: parella de columnes.
    :param a: valors antics a les files aparellades.
    :param b: valors nous, alineats amb `a`.
    :return: zero o un canvi.
    """
    ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
    x, y = a.to_numpy(float), b.to_numpy(float)
    both = ~(np.isnan(x) | np.isnan(y))
    if not both.any():
        return []
    scale = max(np.nanmax(np.abs(y[both])), 1e-12)
    n_changed = int((~np.isclose(x[both], y[both], rtol=ctx.config.numeric_rel_tolerance, atol=1e-9 * scale)).sum())
    if n_changed == 0:
        # Els mateixos valors, escrits d'una altra manera (coma decimal, notació científica).
        style_changed = abs(ko.exponent_share - kn.exponent_share) > 0.5 or ko.decimal_comma != kn.decimal_comma
        if ctx.config.report_representation and style_changed:
            return [change("C322", m, subtype="representation")]
        return []

    if is_sequence(ctx.old, m.old) and is_sequence(ctx.new, m.new):
        return [change("C322", m, subtype="renumbered")]
    if n_changed >= ctx.config.min_explained_rows:
        fit = fit_numeric(x, y, ctx.config.column_match_min_validity, explain_changed=True)
        if fit is not None and fit.kind in C322_FITS:
            ctx.explained[m.old] = fit.kind
            return [change("C322", m, subtype=fit.kind)]
    if is_perturbation(x, y):
        ctx.explained[m.old] = "perturbation"
        return [change("C322", m, subtype="perturbation")]
    return [change("C322", m, subtype="cell_edits")]


def _categorical_values(ctx: Context, m: ColumnMatch, a: pd.Series, b: pd.Series) -> list[Change]:
    """
    Explica com han canviat els valors d'una columna de categories (reetiquetatge,
    fusió, divisió, només format o cel·les soltes).

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :param m: parella de columnes.
    :param a: valors antics a les files aparellades.
    :param b: valors nous, alineats amb `a`.
    :return: zero o un canvi.
    """
    mapping = analyze_mapping(a, b, ctx.config.column_match_min_validity, ctx.config.min_explained_rows)
    if mapping.kind == "identity":
        return []
    if mapping.kind in ("relabel", "anonymization"):
        ctx.relabeled[m.old] = mapping.mapping
    if mapping.kind == "representation":
        ctx.representation.add(m.old)
    return [change("C312", m, subtype=mapping.kind)]
