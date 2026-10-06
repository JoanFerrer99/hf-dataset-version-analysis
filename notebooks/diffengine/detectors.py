"""
L5: un detector per família de codis, sobre les columnes i files ja
aparellades. Cada detector retorna una llista de `Change` amb evidència i
confiança.
"""

from bisect import bisect_left
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from diffengine.columns import ColumnAlignment, ColumnMatch, order_changed
from diffengine.config import EngineConfig
from diffengine.load import NULL_TOKEN, NUMERIC, OPAQUE, TEXT, Table
from diffengine.output import Change
from diffengine.rows import RowAlignment, cell_tokens, is_identifier_like, is_row_number, is_sequence, paired_values
from diffengine.transforms import analyze_mapping, distribution_distance, fit_numeric, is_perturbation, normalize_value

# Ajustos que són un subtipus de C322 (`identity` no és un canvi; `round` és C321).
_C322_FITS = {"factor", "linear", "minmax", "standardization", "normalization", "log", "sqrt", "reciprocal", "exp"}


@dataclass
class Context:
    old: Table
    new: Table
    cols: ColumnAlignment
    rows: RowAlignment
    config: EngineConfig
    identifiers: set[str] = field(default_factory=set)
    row_numbers: set[str] = field(default_factory=set)
    explained: dict[str, str] = field(default_factory=dict)
    relabeled: dict[str, dict] = field(default_factory=dict)
    representation: set[str] = field(default_factory=set)
    kind_changed: set[str] = field(default_factory=set)
    c510_columns: set[str] = field(default_factory=set)

    def paired(self, m: ColumnMatch) -> tuple[pd.Series, pd.Series]:
        pairs = self.rows.pairs
        return paired_values(self.old, m.old, pairs[:, 0]), paired_values(self.new, m.new, pairs[:, 1])


def _family(kind: str) -> str:
    return "numeric" if kind == NUMERIC else ("opaque" if kind == OPAQUE else "categorical")


def _change(code: str, m: ColumnMatch | None = None, **kw) -> Change:
    if m is not None:
        kw.setdefault("column", m.new)
        kw.setdefault("old_column", m.old if m.old != m.new else None)
    return Change(code, **kw)


# --- Columnes: C210, C221, C222, C223 ----------------------------------------


def detect_column_set(ctx: Context) -> list[Change]:
    out = []
    if order_changed(ctx.old, ctx.new, ctx.cols):
        out.append(Change("C210", evidence={"old_order": list(ctx.old.values.columns),
                                            "new_order": list(ctx.new.values.columns)}))
    for n in ctx.cols.added:
        origin = ctx.cols.derived.get(n)
        out.append(Change("C221", column=n, subtype="derived" if origin else "unexplained",
                          evidence={"origin": origin, "kind": ctx.new.columns[n].kind}))
    for o in ctx.cols.removed:
        out.append(Change("C222", old_column=o, subtype=ctx.cols.removed_subtypes.get(o, "unexplained"),
                          evidence={"kind": ctx.old.columns[o].kind,
                                    "null_share": float(ctx.old.values[o].isna().mean())}))
    for m in ctx.cols.matches:
        if m.old != m.new:
            out.append(_change("C223", m, confidence=m.validity,
                               evidence={"method": m.method, **m.detail}))
    for oh in ctx.cols.one_hot:
        out.append(Change("C311", old_column=oh["old"], subtype="one_hot", evidence=oh))
    return out


# --- Tipus: C311, C321 ---------------------------------------------------------


def detect_kinds(ctx: Context) -> list[Change]:
    out = []
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        fo, fn = _family(ko.kind), _family(kn.kind)
        if "opaque" in (fo, fn):
            continue
        if fo != fn:
            ctx.kind_changed.add(m.old)
            old_based = fo if ctx.config.kind_change_by_old_kind else fn
            code = "C311" if old_based == "categorical" else "C321"
            out.append(_change(code, m, subtype="to_numeric" if fn == "numeric" else "to_categorical",
                               evidence={"old_kind": ko.kind, "new_kind": kn.kind,
                                         "old_dtype": ko.raw_dtype, "new_dtype": kn.raw_dtype}))
        elif fo == "numeric" and not ko.integer and kn.integer and len(ctx.rows.pairs):
            x, y = ctx.paired(m)
            fit = fit_numeric(x.to_numpy(float), y.to_numpy(float), ctx.config.column_match_min_validity)
            if fit is not None and fit.kind == "round":
                ctx.kind_changed.add(m.old)
                out.append(_change("C321", m, subtype="real_to_integer", confidence=fit.validity,
                                   evidence={"fit": fit.kind, "old_dtype": ko.raw_dtype, "new_dtype": kn.raw_dtype}))
    return out


# --- Valors: C312, C322, transicions de nuls (C510) ----------------------------


def _imputed_label(values: np.ndarray, reference: pd.Series) -> str:
    if len(np.unique(values)) != 1:
        return "imputed"
    v = float(values[0]) if isinstance(values[0], (int, float, np.number)) else values[0]
    if isinstance(v, float) and reference.dtype.kind == "f":
        ref = reference.dropna()
        for name, stat in (("mean", ref.mean()), ("median", ref.median())):
            if np.isclose(v, stat, rtol=1e-3):
                return f"imputed_constant:{name}"
        if len(ref.mode()) and np.isclose(v, ref.mode().iloc[0]):
            return "imputed_constant:mode"
    return "imputed_constant:value"


def detect_values(ctx: Context) -> list[Change]:
    out = []
    if not len(ctx.rows.pairs):
        return out
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        if m.old in ctx.kind_changed or m.old in ctx.row_numbers or OPAQUE in (ko.kind, kn.kind) \
                or _family(ko.kind) != _family(kn.kind):
            continue
        a, b = ctx.paired(m)
        na, nb = a.isna().to_numpy(), b.isna().to_numpy()

        if ctx.config.null_transition_is_c510:
            imputed, masked = na & ~nb, ~na & nb
            if imputed.any():
                ctx.c510_columns.add(m.old)
                label = _imputed_label(b[imputed].to_numpy(), ctx.old.values[m.old])
                out.append(_change("C510", m, subtype=label, n_affected=int(imputed.sum()),
                                   share_affected=float(imputed.mean())))
            if masked.any():
                ctx.c510_columns.add(m.old)
                out.append(_change("C510", m, subtype="masking", n_affected=int(masked.sum()),
                                   share_affected=float(masked.mean())))

        if ko.kind == NUMERIC:
            out += _numeric_values(ctx, m, a, b, ko, kn)
        else:
            out += _categorical_values(ctx, m, a, b)
    return out


def _numeric_values(ctx, m, a, b, ko, kn) -> list[Change]:
    x, y = a.to_numpy(float), b.to_numpy(float)
    both = ~(np.isnan(x) | np.isnan(y))
    if not both.any():
        return []
    scale = max(np.nanmax(np.abs(y[both])), 1e-12)
    changed = ~np.isclose(x[both], y[both], rtol=ctx.config.numeric_rel_tolerance, atol=1e-9 * scale)
    n_changed = int(changed.sum())
    if n_changed == 0:
        style_changed = abs(ko.exponent_share - kn.exponent_share) > 0.5 or ko.decimal_comma != kn.decimal_comma
        if ctx.config.report_representation and style_changed:
            return [_change("C322", m, subtype="representation",
                            evidence={"exponent_share": [ko.exponent_share, kn.exponent_share],
                                      "decimal_comma": [ko.decimal_comma, kn.decimal_comma]})]
        return []
    share = n_changed / both.sum()
    if is_sequence(ctx.old, m.old) and is_sequence(ctx.new, m.new):
        # Comptador de posició (p.e. `episode_index`) desplaçat per files inserides o eliminades.
        return [_change("C322", m, subtype="renumbered", n_affected=n_changed, share_affected=float(share))]
    if n_changed >= ctx.config.min_explained_rows:
        fit = fit_numeric(x, y, ctx.config.column_match_min_validity, explain_changed=True)
        if fit is not None and fit.kind in _C322_FITS:
            ctx.explained[m.old] = fit.kind
            return [_change("C322", m, subtype=fit.kind, n_affected=n_changed,
                            share_affected=float(share), confidence=fit.validity,
                            evidence={"fit": fit.kind, **fit.params})]
    if is_perturbation(x, y):
        ctx.explained[m.old] = "perturbation"
        residual = (y - x)[both]
        return [_change("C322", m, subtype="perturbation", n_affected=n_changed, share_affected=float(share),
                        evidence={"residual_std": float(np.std(residual))})]
    return [_change("C322", m, subtype="cell_edits", n_affected=n_changed, share_affected=float(share))]


def _categorical_values(ctx, m, a, b) -> list[Change]:
    mapping = analyze_mapping(a, b, ctx.config.column_match_min_validity, ctx.config.min_explained_rows)
    if mapping.kind == "identity":
        return []
    if mapping.kind in ("relabel", "anonymization"):
        ctx.relabeled[m.old] = mapping.mapping
    if mapping.kind == "representation":
        ctx.representation.add(m.old)
    n = int((a.notna() & b.notna()).sum())
    evidence = {"mapping": dict(list(mapping.mapping.items())[:50])} if mapping.mapping else {}
    return [_change("C312", m, subtype=mapping.kind, n_affected=mapping.changed,
                    share_affected=mapping.changed / max(n, 1), confidence=mapping.validity, evidence=evidence)]


# --- Files: C410, C421, C422 ---------------------------------------------------


def _lis_length(seq: np.ndarray) -> int:
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


def detect_order(ctx: Context) -> list[Change]:
    # L'ordre es jutja només amb parelles segures: ni còpies idèntiques (no se sap
    # quina és quina) ni files editades (la parella és probable, no segura).
    pairs = ctx.rows.certain_pairs
    if len(pairs) < 2:
        return []
    order = pairs[np.argsort(pairs[:, 0], kind="stable")]
    seq = order[:, 1]
    if np.all(np.diff(seq) > 0):
        return []
    lis = _lis_length(seq)
    sample = order if len(order) <= 5000 else order[np.linspace(0, len(order) - 1, 5000).astype(int)]
    tau = stats.kendalltau(sample[:, 0], sample[:, 1]).statistic
    new_sorted = _sorted_by(ctx.new, [m.new for m in ctx.cols.matches])
    old_sorted = _sorted_by(ctx.old, [m.old for m in ctx.cols.matches if m.new == new_sorted]) if new_sorted else None
    subtype = f"sorted_by:{new_sorted}" if new_sorted and not old_sorted else None
    return [Change("C410", subtype=subtype, n_affected=len(seq) - lis, share_affected=1 - lis / len(seq),
                   evidence={"kendall_tau": float(tau), "lis_share": lis / len(seq)})]


def _row_tokens(table: Table, columns: list[str]) -> pd.Series:
    parts = [cell_tokens(table, c) for c in columns]
    if not parts:
        return pd.Series([""] * table.n_rows)
    out = parts[0]
    for p in parts[1:]:
        out = out + "\x1f" + p
    return out


def _removed_subtype(ctx: Context, removed: np.ndarray, kept: np.ndarray) -> tuple[str, dict]:
    cfg = ctx.config
    old = ctx.old
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
        rule = _predicate(ctx, cols, removed, kept)
        if rule:
            return "predicate", {"rule": rule}
    return "unexplained", {}


def _predicate(ctx: Context, cols: list[str], removed: np.ndarray, kept: np.ndarray) -> str | None:
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


def detect_rows(ctx: Context) -> list[Change]:
    out = []
    old_cols = [m.old for m in ctx.cols.matches]
    new_cols = [m.new for m in ctx.cols.matches]
    old_rows = _row_tokens(ctx.old, old_cols).to_numpy()
    new_rows = _row_tokens(ctx.new, new_cols).to_numpy()
    old_set, new_set = set(old_rows), set(new_rows)

    added = ctx.rows.unmatched_new
    if len(added):
        dup = np.array([new_rows[i] in old_set for i in added])
        for flag, subtype in ((True, "duplicate_of_existing"), (False, "new")):
            n = int(np.sum(dup == flag))
            if n:
                out.append(Change("C421", subtype=subtype, n_affected=n, share_affected=n / max(ctx.new.n_rows, 1)))

    removed = ctx.rows.unmatched_old
    if len(removed):
        dup = np.array([old_rows[i] in new_set for i in removed])
        if dup.any():
            n = int(dup.sum())
            out.append(Change("C422", subtype="duplicate_removed", n_affected=n,
                              share_affected=n / max(ctx.old.n_rows, 1)))
        rest = removed[~dup]
        if len(rest):
            kept = np.setdiff1d(np.arange(ctx.old.n_rows), removed)
            subtype, evidence = _removed_subtype(ctx, rest, kept)
            out.append(Change("C422", subtype=subtype, n_affected=len(rest),
                              share_affected=len(rest) / max(ctx.old.n_rows, 1), evidence=evidence))
    return out


# --- Valors absents a nivell de fitxer: C510 -----------------------------------


def detect_missing(ctx: Context) -> list[Change]:
    out = []
    cfg = ctx.config
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        o_null, n_null = ctx.old.values[m.old].isna(), ctx.new.values[m.new].isna()
        if cfg.report_representation and o_null.any() and n_null.any() and ko.missing_tokens != kn.missing_tokens \
                and ko.missing_tokens and kn.missing_tokens:
            out.append(_change("C510", m, subtype="representation",
                               evidence={"old_tokens": sorted(ko.missing_tokens), "new_tokens": sorted(kn.missing_tokens)}))
        if m.old in ctx.c510_columns:
            continue
        rows_changed = len(ctx.rows.unmatched_old) or len(ctx.rows.unmatched_new)
        if cfg.row_change_suppresses_c510 and len(ctx.rows.pairs) and rows_changed:
            continue  # P12: cap cel·la aparellada no ha canviat; el canvi de proporció ve de les files
        p1, p2, n1, n2 = o_null.mean(), n_null.mean(), len(o_null), len(n_null)
        if abs(p1 - p2) < cfg.c510_min_rate_delta or not n1 or not n2:
            continue
        p = (o_null.sum() + n_null.sum()) / (n1 + n2)
        se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
        pval = 2 * stats.norm.sf(abs(p1 - p2) / se) if se > 0 else 0.0
        if pval < cfg.alpha:
            out.append(_change("C510", m, subtype="rate", confidence=float(1 - pval),
                               evidence={"old_rate": float(p1), "new_rate": float(p2), "p_value": float(pval)}))
    return out


# --- Correlació: C520 -----------------------------------------------------------


def _group_rare(s: pd.Series, min_count: int = 5) -> pd.Series:
    counts = s.value_counts()
    rare = counts.index[counts < min_count]
    return s.where(~s.isin(rare), "\x00other") if len(rare) else s


def _assoc(x: pd.Series, y: pd.Series, kx: str, ky: str) -> float | None:
    df = pd.DataFrame({"x": x.to_numpy(), "y": y.to_numpy()}).dropna()
    if kx != NUMERIC:
        df["x"] = _group_rare(df["x"])
    if ky != NUMERIC:
        df["y"] = _group_rare(df["y"])
    if len(df) < 20:
        return None
    if kx == NUMERIC and ky == NUMERIC:
        if df["x"].nunique() < 2 or df["y"].nunique() < 2:
            return None
        return float(stats.spearmanr(df["x"], df["y"]).statistic)
    if kx != NUMERIC and ky != NUMERIC:
        table = pd.crosstab(df["x"], df["y"])
        if min(table.shape) < 2:
            return None
        chi2, _, _, expected = stats.chi2_contingency(table, correction=False)
        if (expected >= 5).mean() < 0.8:
            return None  # regla de Cochran: amb comptes esperats tan petits, la V no és fiable
        n = table.to_numpy().sum()
        r, k = table.shape
        phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
        rc, kc = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
        denom = min(kc - 1, rc - 1)
        return float(np.sqrt(phi2 / denom)) if denom > 0 else None
    num, cat = (df["x"], df["y"]) if kx == NUMERIC else (df["y"], df["x"])
    groups = num.groupby(cat.to_numpy())
    total = ((num - num.mean()) ** 2).sum()
    between = (groups.size() * (groups.mean() - num.mean()) ** 2).sum()
    return float(np.sqrt(between / total)) if total > 0 else None


def detect_correlation(ctx: Context) -> list[Change]:
    cfg = ctx.config
    cols = []
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        if m.old in ctx.identifiers or m.old in ctx.kind_changed or OPAQUE in (ko.kind, kn.kind):
            continue
        if TEXT in (ko.kind, kn.kind):
            continue
        if ko.kind != NUMERIC and (ctx.old.values[m.old].nunique() > 50 or ctx.new.values[m.new].nunique() > 50):
            continue
        cols.append(m)
    cols = cols[: cfg.c520_max_columns]
    out = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            ka, kb = ctx.old.columns[a.old].kind, ctx.old.columns[b.old].kind
            r_old = _assoc(ctx.old.values[a.old], ctx.old.values[b.old], ka, kb)
            r_new = _assoc(ctx.new.values[a.new], ctx.new.values[b.new], ka, kb)
            if r_old is None or r_new is None or abs(r_new - r_old) < cfg.c520_min_delta:
                continue
            # Prova de Fisher z per a la diferència (exacta per a Spearman, aproximada
            # per a V de Cramér i eta): amb poques files, |Δ| ≥ 0.1 sol no n'hi ha prou.
            n1, n2 = ctx.old.n_rows, ctx.new.n_rows
            if min(n1, n2) <= 3:
                continue
            z = np.arctanh(np.clip(r_old, -0.9999, 0.9999)) - np.arctanh(np.clip(r_new, -0.9999, 0.9999))
            pval = float(2 * stats.norm.sf(abs(z) / np.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))))
            if pval >= cfg.alpha:
                continue
            out.append(Change("C520", column=f"{a.new}|{b.new}", confidence=1 - pval,
                              evidence={"old": r_old, "new": r_new, "p_value": pval,
                                        "measure": "spearman" if ka == kb == NUMERIC else "cramers_v/eta"}))
    return out


# --- Distribució: C530 -----------------------------------------------------------


def detect_distribution(ctx: Context) -> list[Change]:
    cfg = ctx.config
    out = []
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        if m.old in ctx.identifiers or m.old in ctx.kind_changed or OPAQUE in (ko.kind, kn.kind) \
                or TEXT in (ko.kind, kn.kind):
            continue
        if cfg.transformation_suppresses_c530 and m.old in ctx.explained:
            continue
        a, b = ctx.old.values[m.old].dropna(), ctx.new.values[m.new].dropna()
        if len(a) < 20 or len(b) < 20:
            continue
        if ko.kind != NUMERIC:
            if m.old in ctx.relabeled:
                a = a.map(lambda v: ctx.relabeled[m.old].get(v, v))
            if m.old in ctx.representation:
                a, b = a.map(normalize_value), b.map(normalize_value)
        distance, pval, measure = distribution_distance(a, b, ko.kind == NUMERIC)
        if distance >= cfg.c530_min_distance and pval < cfg.alpha:
            out.append(_change("C530", m, confidence=1 - pval,
                               evidence={"measure": measure, "distance": distance, "p_value": pval}))
    return out


DETECTORS = (detect_column_set, detect_kinds, detect_values, detect_order, detect_rows, detect_missing,
             detect_correlation, detect_distribution)


def find_identifiers(ctx: Context) -> None:
    """
    Columnes que identifiquen files, no variables: la clau, les que tenen nom
    d'identificador i valors únics, els números de fila i les seqüències
    (`episode_index`). No entren a C520 ni C530. Els números de fila tampoc a
    C322: es renumeren com a conseqüència de C421/C422.
    """
    ctx.identifiers = set(ctx.rows.key_columns)
    for m in ctx.cols.matches:
        s = ctx.old.values[m.old]
        if is_row_number(ctx.old, m.old) and is_row_number(ctx.new, m.new):
            ctx.row_numbers.add(m.old)
            ctx.identifiers.add(m.old)
        elif (is_identifier_like(m.old) and s.notna().all() and s.is_unique) or \
                (is_sequence(ctx.old, m.old) and is_sequence(ctx.new, m.new)):
            ctx.identifiers.add(m.old)
