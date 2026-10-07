"""C4xx: canvis en el conjunt de files. Les files ja les ha aparellat L4 (`rows.align_rows`)."""

from bisect import bisect_left
from functools import reduce

import numpy as np
import pandas as pd
from scipy import stats

from diffengine.detectors.common import Context, change
from diffengine.load import NULL_TOKEN, NUMERIC, OPAQUE, TEXT, Table
from diffengine.output import Change
from diffengine.rows import cell_tokens


def detect_order(ctx: Context) -> list[Change]:
    """
    C410: les files aparellades segures (ni còpies idèntiques ni files editades)
    no conserven l'ordre. Files desordenades = les que no són a la subseqüència
    creixent més llarga. Subtipus `sorted_by:<col>` si la nova està ordenada per una columna.
    """
    pairs = ctx.rows.certain_pairs
    if len(pairs) < 2:
        return []
    order = pairs[np.argsort(pairs[:, 0], kind="stable")]
    seq = order[:, 1]
    if np.all(np.diff(seq) > 0):
        return []
    lis = _longest_increasing_subsequence(seq)
    sample = order if len(order) <= 5000 else order[np.linspace(0, len(order) - 1, 5000).astype(int)]
    tau = stats.kendalltau(sample[:, 0], sample[:, 1]).statistic
    new_sorted = _sorted_by(ctx.new, [m.new for m in ctx.cols.matches])
    old_sorted = _sorted_by(ctx.old, [m.old for m in ctx.cols.matches if m.new == new_sorted]) if new_sorted else None
    subtype = f"sorted_by:{new_sorted}" if new_sorted and not old_sorted else None
    return [change("C410", subtype=subtype, n_affected=len(seq) - lis, share_affected=1 - lis / len(seq),
                   evidence={"kendall_tau": float(tau), "lis_share": lis / len(seq)})]


def _longest_increasing_subsequence(seq: np.ndarray) -> int:
    tails: list[int] = []
    for v in seq:
        i = bisect_left(tails, v)
        if i == len(tails):
            tails.append(v)
        else:
            tails[i] = v
    return len(tails)


def _sorted_by(table: Table, columns: list[str]) -> str | None:
    for c in columns:
        s = table.values[c].dropna()
        if len(s) > 2 and s.nunique() > 2 and (s.is_monotonic_increasing or s.is_monotonic_decreasing):
            return c
    return None


def detect_rows(ctx: Context) -> list[Change]:
    """
    C421: files noves sense parella (`duplicate_of_existing` si és còpia d'una
    que ja hi era, si no `new`). C422: files antigues sense parella
    (`duplicate_removed`, o el motiu: `had_nulls`, `outlier`, `predicate`, `all_rows`).
    """
    out = []
    old_rows = _row_tokens(ctx.old, [m.old for m in ctx.cols.matches])
    new_rows = _row_tokens(ctx.new, [m.new for m in ctx.cols.matches])

    added = ctx.rows.unmatched_new
    if len(added):
        is_copy = np.isin(new_rows[added], old_rows)
        for flag, subtype in ((True, "duplicate_of_existing"), (False, "new")):
            n = int(np.sum(is_copy == flag))
            if n:
                out.append(change("C421", subtype=subtype, n_affected=n, share_affected=n / max(ctx.new.n_rows, 1)))

    removed = ctx.rows.unmatched_old
    if len(removed):
        is_copy = np.isin(old_rows[removed], new_rows)
        if is_copy.any():
            n = int(is_copy.sum())
            out.append(change("C422", subtype="duplicate_removed", n_affected=n,
                              share_affected=n / max(ctx.old.n_rows, 1)))
        rest = removed[~is_copy]
        if len(rest):
            kept = np.setdiff1d(np.arange(ctx.old.n_rows), removed)
            subtype, evidence = _why_removed(ctx, rest, kept)
            out.append(change("C422", subtype=subtype, n_affected=len(rest),
                              share_affected=len(rest) / max(ctx.old.n_rows, 1), evidence=evidence))
    return out


def _row_tokens(table: Table, columns: list[str]) -> np.ndarray:
    """Cada fila com un sol text (valors de les columnes aparellades), per reconèixer còpies."""
    if not columns:
        return np.array([""] * table.n_rows, dtype=object)
    return reduce(lambda a, b: a + "\x1f" + b, (cell_tokens(table, c) for c in columns)).to_numpy()


def _why_removed(ctx: Context, removed: np.ndarray, kept: np.ndarray) -> tuple[str, dict]:
    """Què tenen en comú les files eliminades: totes, les que tenien nuls, valors extrems, o una regla."""
    cfg, old = ctx.config, ctx.old
    cols = [m.old for m in ctx.cols.matches if old.columns[m.old].kind != OPAQUE]
    if not len(kept):
        return "all_rows", {}
    if not len(removed) or not cols:
        return "unexplained", {}
    nulls = old.values[cols].isna().any(axis=1).to_numpy()
    if nulls[removed].mean() >= cfg.row_subtype_min_validity and nulls[kept].mean() <= 1 - cfg.row_subtype_min_validity:
        return "had_nulls", {}
    for c in cols:
        if old.columns[c].kind != NUMERIC or c in ctx.identifiers:
            continue
        x = old.values[c].to_numpy(float)
        sd = np.nanstd(x)
        if not sd:
            continue
        z = np.abs((x - np.nanmean(x)) / sd)
        if np.nanmean(z[removed] > 2.5) >= cfg.row_subtype_min_validity and np.nanmean(z[kept] > 2.5) <= 0.01:
            return "outlier", {"column": c}
    if len(removed) >= 5:
        rule = _removal_rule(ctx, cols, removed, kept)
        if rule:
            return "predicate", {"rule": rule}
    return "unexplained", {}


def _removal_rule(ctx: Context, cols: list[str], removed: np.ndarray, kept: np.ndarray) -> str | None:
    """Un arbre de decisió de profunditat 2 que separi les files eliminades de les que queden."""
    from sklearn.tree import DecisionTreeClassifier, export_text

    df = ctx.old.values[cols]
    feats = []
    for c in cols:
        if ctx.old.columns[c].kind == NUMERIC:
            feats.append(df[c].fillna(df[c].median()).rename(c))
        elif ctx.old.columns[c].kind != TEXT:
            # Un predicat només pot fer servir valors de les files eliminades: els 20 més freqüents.
            values = df[c].fillna(NULL_TOKEN)
            for v in values.iloc[removed].value_counts().index[:20]:
                feats.append((values == v).astype(int).rename(f"{c}={v}"))
    if not feats:
        return None
    X = pd.concat(feats, axis=1)
    y = np.zeros(len(df), dtype=int)
    y[removed] = 1
    idx = np.concatenate([removed, kept])
    tree = DecisionTreeClassifier(max_depth=2, random_state=0).fit(X.iloc[idx], y[idx])
    pred = tree.predict(X.iloc[idx])
    tp = np.sum((pred == 1) & (y[idx] == 1))
    precision = tp / max(np.sum(pred == 1), 1)
    recall = tp / max(len(removed), 1)
    if min(precision, recall) >= ctx.config.row_subtype_min_validity:
        return export_text(tree, feature_names=list(X.columns), max_depth=2)
    return None
