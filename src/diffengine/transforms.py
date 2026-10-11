"""
Eines per explicar com ha canviat una columna, comparant els seus valors a les
files aparellades. Les fan servir el pas 3c (reconèixer una columna
reanomenada) i el pas 4 (dir quin canvi ha patit).

- `fit_numeric`: quina transformació porta els valors vells als nous
  (identitat, factor, lineal, min-max, estandardització, logaritme…). Es
  proven de la més simple a la més complexa, i se n'accepta una si reprodueix
  gairebé totes les files, també les que han canviat.
- `analyze_mapping`: com es corresponen les categories velles i noves
  (reetiquetatge, anonimització, fusió, divisió, només format, o edicions
  soltes).
- `distribution_distance`: quant ha canviat la distribució d'una columna
  (prova KS o variació total), compartida per C530 i per l'aparellament de
  columnes.
"""

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from diffengine.load import NULL_TOKEN


@dataclass
class Fit:
    """
    :ivar kind: `identity`, `factor`, `linear`, `minmax`, `standardization`,
        `normalization`, `log`, `sqrt`, `reciprocal`, `exp`, `round`.
    :ivar validity: proporció de files no nul·les reproduïdes.
    """

    kind: str
    validity: float
    params: dict = field(default_factory=dict)


def _close(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Compara dues llistes de nombres amb una petita tolerància (relativa a la
    mida dels valors).

    :param a: primera llista.
    :param b: segona llista.
    :return: per a cada posició, `True` si els dos valors són pràcticament iguals.
    """
    scale = max(float(np.nanmax(np.abs(b))) if len(b) else 1.0, 1e-12)
    return np.isclose(a, b, rtol=1e-5, atol=1e-6 * scale)


def fit_numeric(x: np.ndarray, y: np.ndarray, min_validity: float, explain_changed: bool = False) -> Fit | None:
    """
    Busca una fórmula que porti els valors antics als nous (multiplicar per un
    factor, escalar entre 0 i 1, estandarditzar, logaritme...). Prova de la més
    simple a la més complexa i accepta la primera que reprodueix gairebé totes
    les files.

    :param x: valors antics.
    :param y: valors nous, alineats amb `x`.
    :param min_validity: proporció mínima de files que la fórmula ha de reproduir.
    :param explain_changed: si és `True`, la fórmula també ha de reproduir les
        files que han canviat (no n'hi ha prou amb les que no) i "no canviar" no compta.
    :return: la fórmula trobada (tipus, paràmetres i proporció de files que
        reprodueix), o `None` si cap no funciona.
    """
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask].astype(float), y[mask].astype(float)
    if len(x) < 3:
        return None
    changed = ~_close(x, y) if explain_changed else None

    def check(kind: str, pred: np.ndarray, **params) -> Fit | None:
        with np.errstate(all="ignore"):
            ok = _close(pred, y)
        validity = float(np.mean(ok))
        if changed is not None and changed.any() and np.mean(ok[changed]) < min_validity:
            return None
        return Fit(kind, validity, params) if validity >= min_validity else None

    candidates = []
    if not explain_changed:
        candidates.append(lambda: check("identity", x))
    mn, mx, mean = x.min(), x.max(), x.mean()
    std0, std1, total = x.std(ddof=0), x.std(ddof=1), x.sum()
    if mx > mn:
        candidates.append(lambda: check("minmax", (x - mn) / (mx - mn)))
    for ddof, s in ((1, std1), (0, std0)):
        if s > 0:
            candidates.append(lambda s=s, ddof=ddof: check("standardization", (x - mean) / s, ddof=ddof))
    if total != 0:
        candidates.append(lambda: check("normalization", x / total))
    candidates.append(lambda: check("round", np.round(x)))
    if (x > 0).all():
        for base, fn in (("e", np.log), ("10", np.log10), ("2", np.log2)):
            candidates.append(lambda fn=fn, base=base: check("log", fn(x), base=base))
        candidates.append(lambda: check("sqrt", np.sqrt(x)))
    if (x > -1).all():
        candidates.append(lambda: check("log", np.log1p(x), base="1p"))
    if (x != 0).all():
        candidates.append(lambda: check("reciprocal", 1.0 / x))
    if np.abs(x).max() < 50:
        candidates.append(lambda: check("exp", np.exp(x)))

    for make in candidates:
        fit = make()
        if fit:
            return fit

    if np.ptp(x) > 0:
        a, b = np.polyfit(x, y, 1)
        kind = "factor" if abs(b) <= 1e-9 * max(abs(a) * np.abs(x).max(), 1.0) else "linear"
        fit = check(kind, a * x + b, a=float(a), b=float(b))
        if fit:
            return fit
    return None


def distribution_distance(a: pd.Series, b: pd.Series, numeric: bool) -> tuple[float, float, str]:
    """
    Mesura quant ha canviat la distribució d'una columna. Per a nombres, la
    prova de Kolmogorov-Smirnov; per a categories, la variació total (amb una
    prova de khi quadrat).

    :param a: valors antics, sense buits.
    :param b: valors nous, sense buits.
    :param numeric: `True` si la columna és numèrica.
    :return: `(distància, p-valor, nom de la mesura)`.
    """
    if numeric:
        res = stats.ks_2samp(a.to_numpy(float), b.to_numpy(float), method="asymp")
        return float(res.statistic), float(res.pvalue), "ks"
    fa, fb = a.value_counts(normalize=True).align(b.value_counts(normalize=True), fill_value=0)
    counts = pd.concat([a.value_counts(), b.value_counts()], axis=1).fillna(0)
    pval = float(stats.chi2_contingency(counts.to_numpy())[1]) if counts.shape[0] > 1 else 1.0
    return float(0.5 * np.abs(fa - fb).sum()), pval, "total_variation"


def is_perturbation(x: np.ndarray, y: np.ndarray, max_rel_noise: float = 0.25, min_changed: float = 0.5) -> bool:
    """
    Diu si els valors nous són els antics amb soroll: molts valors canviats,
    però poc i sense una tendència.

    :param x: valors antics.
    :param y: valors nous, alineats amb `x`.
    :param max_rel_noise: soroll màxim, com a fracció de la desviació dels valors.
    :param min_changed: proporció mínima de valors canviats.
    :return: `True` si és soroll.
    """
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if len(x) < 10 or np.std(x) == 0:
        return False
    changed = ~_close(x, y)
    if changed.mean() < min_changed:
        return False
    residual = y - x
    return bool(np.std(residual) <= max_rel_noise * np.std(x) and abs(np.mean(residual)) <= max_rel_noise * np.std(x))


_OPAQUE_TOKEN = re.compile(r"^[0-9a-fA-F]{8,}$|^[A-Za-z0-9_\-]{16,}$")


@dataclass
class Mapping:
    """
    :ivar kind: `identity`, `relabel`, `anonymization`, `merge`, `split`,
        `representation` o `cell_edits`.
    :ivar changed: nombre de files aparellades amb el valor canviat.
    """

    kind: str
    validity: float
    changed: int
    mapping: dict = field(default_factory=dict)


def normalize_value(v) -> str:
    """
    Forma canònica d'una categoria, per detectar canvis només de format: sense
    espais de més i en minúscules.

    :param v: el valor.
    :return: el valor normalitzat.
    """
    return re.sub(r"\s+", " ", str(v).strip()).lower()


def _dominant_maps(a: np.ndarray, b: np.ndarray) -> tuple[pd.Series, pd.Series, np.ndarray, np.ndarray]:
    """
    Per a cada valor antic, el valor nou més freqüent (i al revés), i quines
    files segueixen aquesta correspondència.

    :param a: valors antics.
    :param b: valors nous, alineats amb `a`.
    :return: `(antic → nou, nou → antic, files que segueixen antic → nou, files que segueixen nou → antic)`.
    """
    df = pd.DataFrame({"a": a, "b": b})
    fwd = df.groupby("a")["b"].agg(lambda s: s.value_counts().index[0])
    bwd = df.groupby("b")["a"].agg(lambda s: s.value_counts().index[0])
    return fwd, bwd, df["a"].map(fwd).to_numpy() == b, df["b"].map(bwd).to_numpy() == a


def analyze_mapping(old: pd.Series, new: pd.Series, min_validity: float, min_group_rows: int) -> Mapping:
    """
    Explica com han canviat els valors d'una columna de categories, comparant
    les files aparellades on els dos valors no són buits.

    :param old: valors antics, com a text.
    :param new: valors nous, alineats amb `old`.
    :param min_validity: proporció mínima de files que la correspondència ha d'explicar.
    :param min_group_rows: files mínimes perquè una categoria nova compti com a divisió.
    :return: el tipus de canvi (`identity`, `representation`, `relabel`,
        `anonymization`, `merge`, `split` o `cell_edits`), la correspondència i
        quantes files han canviat.
    """
    mask = old.notna().to_numpy() & new.notna().to_numpy()
    a = old[mask].astype(str).to_numpy()
    b = new[mask].astype(str).to_numpy()
    n = len(a)
    diff = a != b
    changed = int(diff.sum())
    if n == 0 or changed == 0:
        return Mapping("identity", 1.0, 0)

    if all(normalize_value(x) == normalize_value(y) for x, y in zip(a[diff], b[diff])):
        return Mapping("representation", 1.0, changed)

    fwd, bwd, fwd_hit, bwd_hit = _dominant_maps(a, b)
    fwd_ok = fwd_hit.mean() >= min_validity and fwd_hit[diff].mean() >= min_validity
    bwd_ok = bwd_hit.mean() >= min_validity and bwd_hit[diff].mean() >= min_validity

    if fwd_ok and bwd_ok and fwd.nunique() == len(fwd):
        new_values = set(fwd.values)
        opaque = all(_OPAQUE_TOKEN.match(v) for v in new_values) and not (set(fwd.index) & new_values)
        validity = float(min(fwd_hit.mean(), bwd_hit.mean()))
        return Mapping("anonymization" if opaque else "relabel", validity, changed, fwd.to_dict())
    if fwd_ok:
        return Mapping("merge", float(fwd_hit.mean()), changed, fwd[fwd.index != fwd.values].to_dict())
    if bwd_ok and pd.Series(b[diff]).value_counts().min() >= min_group_rows:
        return Mapping("split", float(bwd_hit.mean()), changed, bwd[bwd.index != bwd.values].to_dict())
    return Mapping("cell_edits", 1.0 - changed / n, changed)


def is_bijection(old: pd.Series, new: pd.Series, min_validity: float) -> tuple[bool, float]:
    """
    Diu si dues columnes es corresponen u a u: cada valor antic dona sempre el
    mateix valor nou, i al revés.

    :param old: valors antics.
    :param new: valors nous, alineats amb `old`.
    :param min_validity: proporció mínima de files que han de seguir la correspondència.
    :return: `(es corresponen, proporció de files que la segueixen)`.
    """
    a = old.astype(object).where(old.notna(), NULL_TOKEN).astype(str).to_numpy()
    b = new.astype(object).where(new.notna(), NULL_TOKEN).astype(str).to_numpy()
    if not len(a):
        return False, 0.0
    fwd, _, fwd_hit, bwd_hit = _dominant_maps(a, b)
    validity = float(min(fwd_hit.mean(), bwd_hit.mean()))
    return validity >= min_validity and fwd.nunique() == len(fwd), validity
