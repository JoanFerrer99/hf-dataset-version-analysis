"""
C5xx: característiques de les dades. C510 valors absents, C520 correlacions,
C530 distribució. Segons el paper (§4), es reporten encara que siguin
conseqüència d'afegir o eliminar files.
"""

import numpy as np
import pandas as pd
from scipy import stats

from diffengine.detectors.common import Context, change
from diffengine.load import NUMERIC, OPAQUE, TEXT
from diffengine.output import Change
from diffengine.transforms import distribution_distance, normalize_value


def detect_missing(ctx: Context) -> list[Change]:
    """
    C510, tres casos per columna:
    1. cel·les de files aparellades que passen de nul a valor (`imputed...`) o al revés (`masking`) (P1);
    2. canvi del token d'absent (`?` → buit): `representation` (P5);
    3. si no hi ha cap 1, la proporció de nuls de la columna canvia: `rate`.
    """
    out = []
    cfg = ctx.config
    for m in ctx.cols.matches:
        if cfg.null_transition_is_c510 and len(ctx.rows.pairs) and ctx.comparable(m):
            out += _null_transitions(ctx, m)
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        o_null, n_null = ctx.old.values[m.old].isna(), ctx.new.values[m.new].isna()
        if cfg.report_representation and o_null.any() and n_null.any() and ko.missing_tokens != kn.missing_tokens \
                and ko.missing_tokens and kn.missing_tokens:
            out.append(change("C510", m, subtype="representation",
                              evidence={"old_tokens": sorted(ko.missing_tokens), "new_tokens": sorted(kn.missing_tokens)}))
        if m.old in ctx.c510_columns:
            continue
        rate = _rate_change(o_null, n_null, cfg)
        if rate is not None:
            out.append(change("C510", m, subtype="rate", confidence=1 - rate["p_value"], evidence=rate))
    return out


def _null_transitions(ctx: Context, m) -> list[Change]:
    a, b = ctx.paired(m)
    na, nb = a.isna().to_numpy(), b.isna().to_numpy()
    imputed, masked = na & ~nb, ~na & nb
    out = []
    if imputed.any():
        out.append(change("C510", m, subtype=_imputed_label(b[imputed].to_numpy(), ctx.old.values[m.old]),
                          n_affected=int(imputed.sum()), share_affected=float(imputed.mean())))
    if masked.any():
        out.append(change("C510", m, subtype="masking", n_affected=int(masked.sum()),
                          share_affected=float(masked.mean())))
    if out:
        ctx.c510_columns.add(m.old)
    return out


def _imputed_label(values: np.ndarray, reference: pd.Series) -> str:
    """Amb quin valor s'han omplert els nuls: la mitjana, la mediana, la moda, una constant o valors diversos."""
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


def _rate_change(o_null: pd.Series, n_null: pd.Series, cfg) -> dict | None:
    """Prova de dues proporcions; cal un efecte d'almenys `c510_min_rate_delta` i p < `alpha`."""
    p1, p2, n1, n2 = o_null.mean(), n_null.mean(), len(o_null), len(n_null)
    if not n1 or not n2 or abs(p1 - p2) < cfg.c510_min_rate_delta:
        return None
    p = (o_null.sum() + n_null.sum()) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    pval = float(2 * stats.norm.sf(abs(p1 - p2) / se)) if se > 0 else 0.0
    if pval >= cfg.alpha:
        return None
    return {"old_rate": float(p1), "new_rate": float(p2), "p_value": pval}


def detect_correlation(ctx: Context) -> list[Change]:
    """
    C520: la relació entre dues columnes canvia. Mesura segons els tipus:
    Spearman (numèrica-numèrica), V de Cramér (categòrica-categòrica),
    raó de correlació eta (numèrica-categòrica). Cal |Δ| ≥ `c520_min_delta`
    i una prova de Fisher z amb p < `alpha`.
    """
    cfg = ctx.config
    cols = [m for m in ctx.cols.matches if _is_variable(ctx, m)][: cfg.c520_max_columns]
    out = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            ka, kb = ctx.old.columns[a.old].kind, ctx.old.columns[b.old].kind
            r_old = _association(ctx.old.values[a.old], ctx.old.values[b.old], ka, kb)
            r_new = _association(ctx.new.values[a.new], ctx.new.values[b.new], ka, kb)
            if r_old is None or r_new is None or abs(r_new - r_old) < cfg.c520_min_delta:
                continue
            n1, n2 = ctx.old.n_rows, ctx.new.n_rows
            if min(n1, n2) <= 3:
                continue
            z = np.arctanh(np.clip(r_old, -0.9999, 0.9999)) - np.arctanh(np.clip(r_new, -0.9999, 0.9999))
            pval = float(2 * stats.norm.sf(abs(z) / np.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))))
            if pval >= cfg.alpha:
                continue
            out.append(change("C520", column=f"{a.new}|{b.new}", confidence=1 - pval,
                              evidence={"old": r_old, "new": r_new, "p_value": pval,
                                        "measure": "spearman" if ka == kb == NUMERIC else "cramers_v/eta"}))
    return out


def _is_variable(ctx: Context, m) -> bool:
    """Columna que té sentit correlacionar: no identificador, mateix tipus, ni opaca, ni text, ≤ 50 categories."""
    ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
    if m.old in ctx.identifiers or m.old in ctx.kind_changed or OPAQUE in (ko.kind, kn.kind) or TEXT in (ko.kind, kn.kind):
        return False
    return ko.kind == NUMERIC or (ctx.old.values[m.old].nunique() <= 50 and ctx.new.values[m.new].nunique() <= 50)


def _association(x: pd.Series, y: pd.Series, kx: str, ky: str) -> float | None:
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
        return _cramers_v(pd.crosstab(df["x"], df["y"]))
    num, cat = (df["x"], df["y"]) if kx == NUMERIC else (df["y"], df["x"])
    groups = num.groupby(cat.to_numpy())
    total = ((num - num.mean()) ** 2).sum()
    between = (groups.size() * (groups.mean() - num.mean()) ** 2).sum()
    return float(np.sqrt(between / total)) if total > 0 else None


def _cramers_v(table: pd.DataFrame) -> float | None:
    """V de Cramér amb correcció de biaix; `None` si no compleix la regla de Cochran (comptes esperats ≥ 5)."""
    if min(table.shape) < 2:
        return None
    chi2, _, _, expected = stats.chi2_contingency(table, correction=False)
    if (expected >= 5).mean() < 0.8:
        return None
    n = table.to_numpy().sum()
    r, k = table.shape
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
    rc, kc = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
    denom = min(kc - 1, rc - 1)
    return float(np.sqrt(phi2 / denom)) if denom > 0 else None


def _group_rare(s: pd.Series, min_count: int = 5) -> pd.Series:
    """Categories amb menys de 5 files → una sola categoria `other` (si no, les mesures són inestables)."""
    counts = s.value_counts()
    rare = counts.index[counts < min_count]
    return s.where(~s.isin(rare), "\x00other") if len(rare) else s


def detect_distribution(ctx: Context) -> list[Change]:
    """
    C530: la distribució d'una columna canvia (KS per a numèriques, variació
    total per a categòriques; distància ≥ `c530_min_distance` i p < `alpha`).
    Sense identificadors ni text; si una transformació ja l'explica, P8.
    """
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
            # Es compara després de desfer el reetiquetatge o el canvi de format (ja són C312).
            if m.old in ctx.relabeled:
                a = a.map(lambda v: ctx.relabeled[m.old].get(v, v))
            if m.old in ctx.representation:
                a, b = a.map(normalize_value), b.map(normalize_value)
        distance, pval, measure = distribution_distance(a, b, ko.kind == NUMERIC)
        if distance >= cfg.c530_min_distance and pval < cfg.alpha:
            out.append(change("C530", m, confidence=1 - pval,
                              evidence={"measure": measure, "distance": distance, "p_value": pval}))
    return out
