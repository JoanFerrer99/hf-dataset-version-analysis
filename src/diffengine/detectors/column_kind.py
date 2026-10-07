"""
C3xx: canvis en una columna. C311/C321: el tipus (categòrica ↔ numèrica).
C312/C322: els valors, comparats cel·la a cel·la sobre les files aparellades.
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
    """C311/C321: canvi de tipus, codificat pel tipus antic (P3); C321 `real_to_integer` si s'arrodoneix."""
    out = []
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        fo, fn = family(ko.kind), family(kn.kind)
        if "opaque" in (fo, fn):
            continue
        if fo != fn:
            ctx.kind_changed.add(m.old)
            old_based = fo if ctx.config.kind_change_by_old_kind else fn
            code = "C311" if old_based == "categorical" else "C321"
            out.append(change(code, m, subtype="to_numeric" if fn == "numeric" else "to_categorical",
                              evidence={"old_kind": ko.kind, "new_kind": kn.kind,
                                        "old_dtype": ko.raw_dtype, "new_dtype": kn.raw_dtype}))
            recoding = _recoding(ctx, m)
            if recoding is not None:
                out.append(recoding)
        elif fo == "numeric" and not ko.integer and kn.integer and len(ctx.rows.pairs):
            x, y = ctx.paired(m)
            fit = fit_numeric(x.to_numpy(float), y.to_numpy(float), ctx.config.column_match_min_validity)
            if fit is not None and fit.kind == "round":
                ctx.kind_changed.add(m.old)
                out.append(change("C321", m, subtype="real_to_integer", confidence=fit.validity,
                                  evidence={"fit": fit.kind, "old_dtype": ko.raw_dtype, "new_dtype": kn.raw_dtype}))
    return out


def _recoding(ctx: Context, m: ColumnMatch) -> Change | None:
    """
    P13: un canvi de tipus que és una bijecció entre valors (p.e. codificar
    categories com a enters) també canvia els valors del domini: C312 `recoded`.
    Un canvi només de format ("1" → 1) no ho és.
    """
    pairs = ctx.rows.reliable_pairs
    if len(pairs) < 10:
        return None
    a = cell_tokens(ctx.old, m.old).iloc[pairs[:, 0]].reset_index(drop=True)
    b = cell_tokens(ctx.new, m.new).iloc[pairs[:, 1]].reset_index(drop=True)
    ok, validity = is_bijection(a, b, ctx.config.column_match_min_validity)
    if not ok or a.nunique() < 2 or (a == b).mean() >= ctx.config.column_match_min_validity:
        return None
    mapping = dict(list(pd.Series(b.values, index=a.values).groupby(level=0).first().items())[:50])
    return change("C312", m, subtype="recoded", n_affected=int((a != b).sum()), confidence=validity,
                  evidence={"mapping": mapping})


def detect_values(ctx: Context) -> list[Change]:
    """C312 (categòriques) i C322 (numèriques): cel·les no nul·les que canvien a les files aparellades."""
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
    Per ordre: només ha canviat el format → `representation`; comptador de
    posició → `renumbered`; una transformació explica els canvis → el seu nom
    (`factor`, `log`...); soroll petit → `perturbation`; si no → `cell_edits`.
    """
    ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
    x, y = a.to_numpy(float), b.to_numpy(float)
    both = ~(np.isnan(x) | np.isnan(y))
    if not both.any():
        return []
    scale = max(np.nanmax(np.abs(y[both])), 1e-12)
    n_changed = int((~np.isclose(x[both], y[both], rtol=ctx.config.numeric_rel_tolerance, atol=1e-9 * scale)).sum())
    if n_changed == 0:
        style_changed = abs(ko.exponent_share - kn.exponent_share) > 0.5 or ko.decimal_comma != kn.decimal_comma
        if ctx.config.report_representation and style_changed:
            return [change("C322", m, subtype="representation",
                           evidence={"exponent_share": [ko.exponent_share, kn.exponent_share],
                                     "decimal_comma": [ko.decimal_comma, kn.decimal_comma]})]
        return []

    share = n_changed / both.sum()
    if is_sequence(ctx.old, m.old) and is_sequence(ctx.new, m.new):
        return [change("C322", m, subtype="renumbered", n_affected=n_changed, share_affected=float(share))]
    if n_changed >= ctx.config.min_explained_rows:
        fit = fit_numeric(x, y, ctx.config.column_match_min_validity, explain_changed=True)
        if fit is not None and fit.kind in C322_FITS:
            ctx.explained[m.old] = fit.kind
            return [change("C322", m, subtype=fit.kind, n_affected=n_changed, share_affected=float(share),
                           confidence=fit.validity, evidence={"fit": fit.kind, **fit.params})]
    if is_perturbation(x, y):
        ctx.explained[m.old] = "perturbation"
        return [change("C322", m, subtype="perturbation", n_affected=n_changed, share_affected=float(share),
                       evidence={"residual_std": float(np.std((y - x)[both]))})]
    return [change("C322", m, subtype="cell_edits", n_affected=n_changed, share_affected=float(share))]


def _categorical_values(ctx: Context, m: ColumnMatch, a: pd.Series, b: pd.Series) -> list[Change]:
    """El tipus de mapatge vell → nou: `relabel`, `anonymization`, `merge`, `split`, `representation`, `cell_edits`."""
    mapping = analyze_mapping(a, b, ctx.config.column_match_min_validity, ctx.config.min_explained_rows)
    if mapping.kind == "identity":
        return []
    if mapping.kind in ("relabel", "anonymization"):
        ctx.relabeled[m.old] = mapping.mapping
    if mapping.kind == "representation":
        ctx.representation.add(m.old)
    n = int((a.notna() & b.notna()).sum())
    evidence = {"mapping": dict(list(mapping.mapping.items())[:50])} if mapping.mapping else {}
    return [change("C312", m, subtype=mapping.kind, n_affected=mapping.changed,
                   share_affected=mapping.changed / max(n, 1), confidence=mapping.validity, evidence=evidence)]
