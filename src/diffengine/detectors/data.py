"""
C5xx: valors de les dades (Data Value, la taxonomia posterior al paper).

- C510 (Add missing): cel·les que passen de tenir valor a estar buides.
- C520 (Remove missing): cel·les que passen de buides a tenir valor.
- C530 (Update value not involving missing): canvia la distribució d'una
  columna (`distribution`) o la correlació entre dues (`correlation`), mirant
  només les cel·les que tenen valor a totes dues versions.

Es fan servir només les files aparellades: les afegides i les eliminades ja
són C421/C422, i així els C5xx en són disjunts. Si no hi ha cap fila
aparellada, es mira la taula sencera: C510 o C520 segons si la proporció de
buits puja o baixa, i C530 només on no canvia (decisió T-43).
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
    Canvis en els valors absents, per columna: C510 si se n'afegeixen, C520 si
    se n'eliminen. Amb files aparellades, es miren les seves cel·les; si no
    n'hi ha cap, la proporció de buits de tota la columna (subtipus `rate`).

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :return: els canvis trobats.
    """
    out = []
    paired = len(ctx.rows.pairs) > 0
    for m in ctx.cols.matches:
        if paired:
            if ctx.comparable(m):
                out += _null_transitions(ctx, m)
            continue
        direction = _rate_direction(ctx.old.values[m.old].isna(), ctx.new.values[m.new].isna(), ctx.config)
        if direction:
            ctx.missing_changed.add(m.old)
            out.append(change("C510" if direction > 0 else "C520", m, subtype="rate"))
    return out


def _null_transitions(ctx: Context, m) -> list[Change]:
    """
    Cel·les de files aparellades que passen de tenir valor a estar buides
    (C510 `masking`) o al revés (C520, amb el subtipus de com s'han omplert).
    Amb `missing_by_cell = False`, només compta el percentatge net de buits.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :param m: parella de columnes.
    :return: zero, un o dos canvis.
    """
    a, b = ctx.paired(m)
    na, nb = a.isna().to_numpy(), b.isna().to_numpy()
    if not ctx.config.missing_by_cell:
        net = int(nb.sum()) - int(na.sum())
        out = [change("C510" if net > 0 else "C520", m, subtype="rate")] if net else []
    else:
        emptied, filled = ~na & nb, na & ~nb
        out = []
        if emptied.any():
            out.append(change("C510", m, subtype="masking"))
        if filled.any():
            out.append(change("C520", m, subtype=_imputed_label(b[filled].to_numpy(), ctx.old.values[m.old])))
    if out:
        ctx.missing_changed.add(m.old)
    return out


def _imputed_label(values: np.ndarray, reference: pd.Series) -> str:
    """
    Amb quin valor s'han omplert els buits: la mitjana, la mediana, la moda,
    una constant o valors diferents.

    :param values: valors nous de les cel·les que abans eren buides.
    :param reference: la columna antiga, per calcular-ne la mitjana i la mediana.
    :return: el subtipus (`imputed_constant:mean`, `imputed_constant:median`,
        `imputed_constant:mode`, `imputed_constant:value` o `imputed`).
    """
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


def _rate_direction(o_null: pd.Series, n_null: pd.Series, cfg) -> int:
    """
    Sense files aparellades: prova si la proporció de buits d'una columna ha
    canviat prou. Cal una diferència mínima i que la prova de dues proporcions
    ho confirmi.

    :param o_null: per a cada fila antiga, si és buida.
    :param n_null: per a cada fila nova, si és buida.
    :param cfg: llindars del motor.
    :return: 1 si puja, -1 si baixa, 0 si no canvia prou.
    """
    p1, p2, n1, n2 = o_null.mean(), n_null.mean(), len(o_null), len(n_null)
    if not n1 or not n2 or abs(p1 - p2) < cfg.missing_min_rate_delta:
        return 0
    p = (o_null.sum() + n_null.sum()) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    pval = float(2 * stats.norm.sf(abs(p1 - p2) / se)) if se > 0 else 0.0
    return (1 if p2 > p1 else -1) if pval < cfg.alpha else 0


def detect_correlation(ctx: Context) -> list[Change]:
    """
    Canvis de correlació entre parelles de columnes (C530 `correlation`). La
    mesura depèn dels tipus: Spearman per a dues numèriques, V de Cramér per a
    dues categòriques, i la raó de correlació per a una de cada. Amb files
    aparellades, es mesura a les mateixes files a totes dues versions, només
    on les dues columnes tenen valor. Cal una diferència mínima i que una prova
    estadística la confirmi.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :return: un canvi per cada parella de columnes amb correlació diferent.
    """
    cfg = ctx.config
    cols = [m for m in ctx.cols.matches if _is_variable(ctx, m)][: cfg.correlation_max_columns]
    paired = len(ctx.rows.pairs) > 0
    if paired:
        values = {m.old: ctx.paired(m) for m in cols}
    else:
        values = {m.old: (ctx.old.values[m.old], ctx.new.values[m.new]) for m in cols}
        cols = [m for m in cols if m.old not in ctx.missing_changed]
    out = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            (xa, xb), (ya, yb) = values[a.old], values[b.old]
            if paired:
                keep = (xa.notna() & xb.notna() & ya.notna() & yb.notna()).to_numpy()
                xa, xb, ya, yb = xa[keep], xb[keep], ya[keep], yb[keep]
            ka, kb = ctx.old.columns[a.old].kind, ctx.old.columns[b.old].kind
            r_old, r_new = _association(xa, ya, ka, kb), _association(xb, yb, ka, kb)
            if r_old is None or r_new is None or abs(r_new - r_old) < cfg.correlation_min_delta:
                continue
            n1, n2 = len(xa), len(xb)
            if min(n1, n2) <= 3:
                continue
            z = np.arctanh(np.clip(r_old, -0.9999, 0.9999)) - np.arctanh(np.clip(r_new, -0.9999, 0.9999))
            pval = float(2 * stats.norm.sf(abs(z) / np.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))))
            if pval >= cfg.alpha:
                continue
            out.append(change("C530", column=f"{a.new}|{b.new}", subtype="correlation"))
    return out


def _is_variable(ctx: Context, m) -> bool:
    """
    Diu si té sentit mesurar la correlació d'una columna: no identifica files,
    no canvia de tipus, no és complexa ni text lliure, i si és categòrica té 50
    valors diferents com a màxim.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :param m: parella de columnes.
    :return: `True` si es pot fer servir.
    """
    ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
    if m.old in ctx.identifiers or m.old in ctx.kind_changed or OPAQUE in (ko.kind, kn.kind) or TEXT in (ko.kind, kn.kind):
        return False
    return ko.kind == NUMERIC or (ctx.old.values[m.old].nunique() <= 50 and ctx.new.values[m.new].nunique() <= 50)


def _association(x: pd.Series, y: pd.Series, kx: str, ky: str) -> float | None:
    """
    Mesura la relació entre dues columnes, d'una mateixa versió, amb la mesura
    que correspon als seus tipus.

    :param x: primera columna.
    :param y: segona columna.
    :param kx: tipus de `x`.
    :param ky: tipus de `y`.
    :return: un valor entre -1 i 1 (o entre 0 i 1), o `None` si no es pot calcular amb fiabilitat.
    """
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
    """
    V de Cramér (relació entre dues categòriques) amb correcció per a mostres
    petites. No es calcula si hi ha massa caselles amb pocs casos esperats.

    :param table: taula de freqüències creuades de les dues columnes.
    :return: un valor entre 0 i 1, o `None` si no és fiable.
    """
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
    """
    Agrupa en una sola categoria `other` les categories amb molt poques files,
    que farien inestables les mesures de relació.

    :param s: la columna.
    :param min_count: files mínimes perquè una categoria es mantingui sola.
    :return: la columna amb les categories rares agrupades.
    """
    counts = s.value_counts()
    rare = counts.index[counts < min_count]
    return s.where(~s.isin(rare), "\x00other") if len(rare) else s


def detect_distribution(ctx: Context) -> list[Change]:
    """
    Canvis de distribució d'una columna (C530 `distribution`): prova de
    Kolmogorov-Smirnov per a numèriques, variació total per a categòriques.
    Amb files aparellades, es comparen els seus valors antics i nous, només a
    les cel·les que tenen valor a totes dues versions; sense, tota la columna,
    si no ha canviat la proporció de buits. No es miren els identificadors, el
    text lliure ni les columnes que ja explica una fórmula.

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :return: els canvis trobats.
    """
    cfg = ctx.config
    paired = len(ctx.rows.pairs) > 0
    out = []
    for m in ctx.cols.matches:
        ko, kn = ctx.old.columns[m.old], ctx.new.columns[m.new]
        if m.old in ctx.identifiers or m.old in ctx.kind_changed or OPAQUE in (ko.kind, kn.kind) \
                or TEXT in (ko.kind, kn.kind):
            continue
        # Si una fórmula o un soroll (C322) ja explica com han canviat els valors, el canvi
        # de distribució n'és la conseqüència: no s'hi afegeix C530.
        if cfg.transformation_suppresses_c530 and m.old in ctx.explained:
            continue
        if paired:
            a, b = ctx.paired(m)
            both = (a.notna() & b.notna()).to_numpy()
            a, b = a[both], b[both]
        elif m.old in ctx.missing_changed:
            continue
        else:
            a, b = ctx.old.values[m.old].dropna(), ctx.new.values[m.new].dropna()
        if len(a) < 20 or len(b) < 20:
            continue
        if ko.kind != NUMERIC:
            # Es compara després de desfer el reetiquetatge o el canvi de format (ja són C312).
            if m.old in ctx.relabeled:
                a = a.map(lambda v: ctx.relabeled[m.old].get(v, v))
            if m.old in ctx.representation:
                a, b = a.map(normalize_value), b.map(normalize_value)
        distance, pval, _ = distribution_distance(a, b, ko.kind == NUMERIC)
        if distance >= cfg.c530_min_distance and pval < cfg.alpha:
            out.append(change("C530", m, subtype="distribution"))
    return out
