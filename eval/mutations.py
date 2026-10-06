"""
Generador de casos d'avaluació amb etiqueta: parells de fitxers (versió
antiga, versió nova) on se sap exactament quins codis de la taxonomia han
de sortir.

Cada mutació transforma una còpia d'una taula llavor i retorna les seves
etiquetes:
  - `required`: codis que el motor ha de detectar.
  - `allowed`: efectes secundaris legítims (no compten com a fals positiu,
    però tampoc són obligatoris). P.e. eliminar totes les files d'una
    categoria també la treu del domini (C312).

Els casos es materialitzen com a bytes de fitxer (CSV o parquet) perquè
cada motor els llegeixi amb el seu propi carregador.
"""

import io
import os
import string
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

ADULT_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
ADULT_COLUMNS = [
    "age", "workclass", "fnlwgt", "education", "education-num", "marital-status", "occupation",
    "relationship", "race", "sex", "capital-gain", "capital-loss", "hours-per-week", "native-country", "income",
]
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


# ---------------------------------------------------------------------------
# Taules llavor
# ---------------------------------------------------------------------------


@dataclass
class Seed:
    """
    Taula llavor amb els rols de les seves columnes (només per al generador;
    el motor no els rep mai).
    """

    name: str
    df: pd.DataFrame
    id_col: str | None
    numeric: list[str]
    categorical: list[str]
    label: str
    missing_token: str = ""


def synthetic_seed(rng: np.random.Generator, n: int = 600) -> Seed:
    age = rng.integers(18, 80, n)
    df = pd.DataFrame({
        "id": np.arange(n) + int(rng.integers(0, 10_000)),
        "age": age,
        "income": np.round(rng.lognormal(10, 0.5, n), 2),
        "score": np.round(age * 0.8 + rng.normal(0, 8, n), 3),
        "hours": rng.integers(10, 60, n),
        "sex": rng.choice(["Male", "Female"], n),
        "workclass": rng.choice(["Private", "Gov", "Self", "Never", "Unknown"], n, p=[.5, .2, .15, .05, .1]),
        "city": rng.choice([f"city_{i:02d}" for i in range(19)], n),
        "label": rng.choice(["no", "yes"], n, p=[.8, .2]),
    })
    return Seed("synthetic", df, "id", ["age", "income", "score", "hours"], ["sex", "workclass", "city", "label"],
                "label")


def adult_seed(rng: np.random.Generator, n: int = 3000) -> Seed:
    """UCI Adult en brut: conserva `" ?"` com a valor absent i els espais inicials."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "adult.data")
    if not os.path.exists(path):
        urllib.request.urlretrieve(ADULT_URL, path)
    full = pd.read_csv(path, header=None, names=ADULT_COLUMNS, keep_default_na=False, na_values=[" ?"])
    df = full.sample(n=n, random_state=int(rng.integers(0, 2**31))).reset_index(drop=True)
    numeric = ["age", "fnlwgt", "education-num", "capital-gain", "capital-loss", "hours-per-week"]
    categorical = [c for c in ADULT_COLUMNS if c not in numeric]
    return Seed("adult", df, None, numeric, categorical, "income", missing_token=" ?")


# ---------------------------------------------------------------------------
# Cas d'avaluació
# ---------------------------------------------------------------------------


@dataclass
class Version:
    """Una versió en construcció: la taula i com s'escriu a disc."""

    df: pd.DataFrame
    fmt: str = "csv"
    csv: dict = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        if self.fmt == "parquet":
            buf = io.BytesIO()
            self.df.to_parquet(buf, index=False)
            return buf.getvalue()
        return self.df.to_csv(index=False, **self.csv).encode("utf-8")


@dataclass
class Case:
    case_id: str
    seed: str
    mutations: tuple[str, ...]
    old: bytes
    new: bytes
    old_ext: str
    new_ext: str
    required: frozenset[tuple[str, str | None]]
    allowed: frozenset[str]

    @property
    def required_codes(self) -> frozenset[str]:
        return frozenset(code for code, _ in self.required)


class NotApplicable(Exception):
    """La mutació no té sentit sobre aquesta llavor."""


@dataclass
class Effect:
    required: set[tuple[str, str | None]] = field(default_factory=set)
    allowed: set[str] = field(default_factory=set)
    touched: set[str] = field(default_factory=set)


Mutation = Callable[[Version, Version, Seed, np.random.Generator, float], Effect]
MUTATIONS: dict[str, tuple[Mutation, str]] = {}


def mutation(name: str, kind: str):
    """Registra una mutació. `kind`: `column`, `row`, `order` o `negative`."""
    def register(fn: Mutation) -> Mutation:
        MUTATIONS[name] = (fn, kind)
        return fn
    return register


def _pick(rng, cols: list[str], exclude: set[str] = frozenset()) -> str:
    options = [c for c in cols if c not in exclude]
    if not options:
        raise NotApplicable
    return options[int(rng.integers(len(options)))]


def _low_card(seed: Seed, df: pd.DataFrame, max_card: int = 10) -> list[str]:
    return [c for c in seed.categorical if df[c].nunique(dropna=True) <= max_card]


def _rows(rng, n: int, share: float) -> np.ndarray:
    k = max(1, int(round(n * share)))
    return rng.choice(n, size=min(k, n), replace=False)


# ---------------------------------------------------------------------------
# Conjunt de columnes (C210, C221, C222, C223)
# ---------------------------------------------------------------------------


@mutation("swap_columns", "order")
def swap_columns(old, new, seed, rng, mag):
    cols = list(new.df.columns)
    i, j = sorted(rng.choice(len(cols), 2, replace=False))
    cols[i], cols[j] = cols[j], cols[i]
    new.df = new.df[cols]
    return Effect({("C210", None)})


@mutation("add_column_unexplained", "column")
def add_column_unexplained(old, new, seed, rng, mag):
    pos = int(rng.integers(len(new.df.columns) + 1))
    new.df.insert(pos, "extra_feature", np.round(rng.normal(0, 1, len(new.df)), 4))
    return Effect({("C221", "unexplained")}, touched={"extra_feature"})


@mutation("add_column_derived", "column")
def add_column_derived(old, new, seed, rng, mag):
    col = _pick(rng, seed.numeric)
    new.df[f"{col}_bin"] = pd.cut(new.df[col], bins=4, labels=["q1", "q2", "q3", "q4"]).astype(str)
    return Effect({("C221", "derived")}, touched={col, f"{col}_bin"})


@mutation("remove_column", "column")
def remove_column(old, new, seed, rng, mag):
    col = _pick(rng, seed.numeric + seed.categorical, {seed.label})
    new.df = new.df.drop(columns=[col])
    return Effect({("C222", "unexplained")}, allowed={"C520"}, touched={col})


@mutation("remove_column_mostly_null", "column")
def remove_column_mostly_null(old, new, seed, rng, mag):
    values = pd.Series(np.round(rng.normal(0, 1, len(old.df)), 3))
    values[rng.random(len(values)) < 0.95] = np.nan
    old.df["sparse_col"] = values.values
    return Effect({("C222", "mostly_null")}, touched={"sparse_col"})


@mutation("rename_identical", "column")
def rename_identical(old, new, seed, rng, mag):
    col = _pick(rng, seed.numeric + seed.categorical, {seed.label})
    new.df = new.df.rename(columns={col: f"renamed_{len(col)}x"})
    return Effect({("C223", None)}, touched={col})


@mutation("rename_recode", "column")
def rename_recode(old, new, seed, rng, mag):
    col = _pick(rng, _low_card(seed, new.df), {seed.label})
    values = sorted(new.df[col].dropna().unique())
    mapping = {v: f"code_{i}" for i, v in enumerate(values)}
    new.df[col] = new.df[col].map(mapping)
    new.df = new.df.rename(columns={col: f"{col}_recoded_as"})
    return Effect({("C223", None), ("C312", "relabel")}, touched={col})


@mutation("one_hot", "column")
def one_hot(old, new, seed, rng, mag):
    col = _pick(rng, [c for c in _low_card(seed, new.df, 5)], {seed.label})
    dummies = pd.get_dummies(new.df[col], prefix=f"{col}_is", dtype=int)
    new.df = pd.concat([new.df.drop(columns=[col]), dummies], axis=1)
    return Effect({("C311", "one_hot")}, touched={col})


# ---------------------------------------------------------------------------
# Tipus de columna (C311, C321)
# ---------------------------------------------------------------------------


@mutation("categorical_to_codes", "column")
def categorical_to_codes(old, new, seed, rng, mag):
    col = _pick(rng, _low_card(seed, new.df), {seed.label})
    new.df[col] = new.df[col].astype("category").cat.codes.replace(-1, np.nan)
    return Effect({("C311", "to_numeric")}, allowed={"C312"}, touched={col})


@mutation("real_to_integer", "column")
def real_to_integer(old, new, seed, rng, mag):
    cols = [c for c in seed.numeric if pd.api.types.is_float_dtype(new.df[c]) and new.df[c].notna().all()]
    col = _pick(rng, cols)
    new.df[col] = new.df[col].round().astype("int64")
    return Effect({("C321", "real_to_integer")}, allowed={"C322"}, touched={col})


@mutation("numeric_to_bins", "column")
def numeric_to_bins(old, new, seed, rng, mag):
    col = _pick(rng, seed.numeric, {seed.id_col})
    new.df[col] = pd.cut(new.df[col], bins=5).astype(str)
    return Effect({("C321", "to_categorical")}, touched={col})


# ---------------------------------------------------------------------------
# Valors categòrics (C312)
# ---------------------------------------------------------------------------


@mutation("cat_relabel", "column")
def cat_relabel(old, new, seed, rng, mag):
    col = _pick(rng, _low_card(seed, new.df))
    values = sorted(new.df[col].dropna().unique())
    new.df[col] = new.df[col].map({v: f"{v}_v2" for v in values})
    return Effect({("C312", "relabel")}, touched={col})


@mutation("cat_merge", "column")
def cat_merge(old, new, seed, rng, mag):
    col = _pick(rng, [c for c in _low_card(seed, new.df) if new.df[c].nunique() >= 3])
    counts = new.df[col].value_counts()
    a, b = counts.index[-1], counts.index[-2]
    new.df[col] = new.df[col].replace({a: b})
    return Effect({("C312", "merge")}, allowed={"C530", "C520"}, touched={col})


@mutation("cat_split", "column")
def cat_split(old, new, seed, rng, mag):
    col = _pick(rng, _low_card(seed, new.df))
    top = new.df[col].value_counts().index[0]
    mask = (new.df[col] == top) & (rng.random(len(new.df)) < 0.5)
    new.df.loc[mask, col] = f"{top}_b"
    return Effect({("C312", "split")}, allowed={"C530", "C520"}, touched={col})


@mutation("cat_anonymize", "column")
def cat_anonymize(old, new, seed, rng, mag):
    col = _pick(rng, seed.categorical, {seed.label})
    values = new.df[col].dropna().unique()
    tokens = {v: "".join(rng.choice(list(string.hexdigits.lower()), 10)) for v in values}
    new.df[col] = new.df[col].map(tokens)
    return Effect({("C312", "anonymization")}, touched={col})


@mutation("cat_cell_edits", "column")
def cat_cell_edits(old, new, seed, rng, mag):
    col = _pick(rng, _low_card(seed, new.df))
    present = np.flatnonzero(new.df[col].notna().to_numpy())
    rows = rng.choice(present, size=min(len(present), max(1, int(len(new.df) * 0.02 * mag))), replace=False)
    domain = new.df[col].dropna().unique()
    for r in rows:
        current = new.df.at[r, col]
        new.df.at[r, col] = rng.choice([d for d in domain if d != current])
    return Effect({("C312", "cell_edits")}, allowed={"C530", "C520"}, touched={col})


@mutation("cat_whitespace", "column")
def cat_whitespace(old, new, seed, rng, mag):
    col = _pick(rng, [c for c in seed.categorical if (new.df[c].dropna() != new.df[c].dropna().str.upper()).any()])
    new.df[col] = new.df[col].str.upper()
    return Effect({("C312", "representation")}, touched={col})


@mutation("cat_new_categories", "column")
def cat_new_categories(old, new, seed, rng, mag):
    """Cas 20: 19 → 21 valors distints; no hi ha canvi de tipus."""
    col = "city" if "city" in new.df.columns else _pick(rng, seed.categorical, {seed.label})
    rows = _rows(rng, len(new.df), 0.004)
    for i, r in enumerate(rows[:2]):
        new.df.at[r, col] = f"new_value_{i}"
    return Effect({("C312", "cell_edits")}, touched={col})


# ---------------------------------------------------------------------------
# Valors numèrics (C322)
# ---------------------------------------------------------------------------


def _numeric_feature(seed, df, rng, positive=False):
    cols = [c for c in seed.numeric if c != seed.id_col and df[c].notna().all()]
    if positive:
        cols = [c for c in cols if (df[c] > 0).all()]
    return _pick(rng, cols)


@mutation("num_factor", "column")
def num_factor(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng)
    new.df[col] = new.df[col].astype(float) * 1000.0
    return Effect({("C322", "factor")}, touched={col})


@mutation("num_log", "column")
def num_log(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng, positive=True)
    new.df[col] = np.round(np.log(new.df[col].astype(float)), 6)
    return Effect({("C322", "log")}, touched={col})


@mutation("num_minmax", "column")
def num_minmax(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng)
    x = new.df[col].astype(float)
    new.df[col] = np.round((x - x.min()) / (x.max() - x.min()), 6)
    return Effect({("C322", "minmax")}, touched={col})


@mutation("num_standardize", "column")
def num_standardize(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng)
    x = new.df[col].astype(float)
    new.df[col] = np.round((x - x.mean()) / x.std(), 6)
    return Effect({("C322", "standardization")}, touched={col})


@mutation("num_perturb", "column")
def num_perturb(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng)
    x = new.df[col].astype(float)
    new.df[col] = np.round(x + rng.normal(0, 0.05 * mag * x.std(), len(x)), 6)
    return Effect({("C322", "perturbation")}, allowed={"C520"}, touched={col})


@mutation("num_cell_edits", "column")
def num_cell_edits(old, new, seed, rng, mag):
    """Cas 5: unes poques cel·les editades dins del rang existent."""
    col = _numeric_feature(seed, new.df, rng)
    rows = _rows(rng, len(new.df), 0.01 * mag)
    pool = new.df[col].dropna().to_numpy()
    for r in rows:
        options = pool[pool != new.df.at[r, col]]
        if len(options):
            new.df.at[r, col] = rng.choice(options)
    return Effect({("C322", "cell_edits")}, allowed={"C520"}, touched={col})


@mutation("num_scientific_notation", "column")
def num_scientific_notation(old, new, seed, rng, mag):
    cols = [c for c in seed.numeric if pd.api.types.is_float_dtype(new.df[c])]
    if not cols or new.fmt != "csv":
        raise NotApplicable
    new.csv["float_format"] = "%.6e"
    return Effect({("C322", "representation")}, touched=set(cols))


@mutation("permute_column", "column")
def permute_column(old, new, seed, rng, mag):
    """Trenca la correlació mantenint la distribució marginal."""
    cols = [c for c in seed.numeric if c != seed.id_col]
    col = "score" if "score" in cols else _pick(rng, cols)
    new.df[col] = rng.permutation(new.df[col].values)
    return Effect({("C520", None), ("C322", "cell_edits")}, touched={col})


# ---------------------------------------------------------------------------
# Files (C410, C421, C422)
# ---------------------------------------------------------------------------


@mutation("shuffle_rows", "order")
def shuffle_rows(old, new, seed, rng, mag):
    new.df = new.df.sample(frac=1, random_state=int(rng.integers(0, 2**31))).reset_index(drop=True)
    return Effect({("C410", None)})


@mutation("sort_rows", "order")
def sort_rows(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng)
    new.df = new.df.sort_values(col, kind="stable").reset_index(drop=True)
    return Effect({("C410", "sorted_by")})


def _new_rows(df: pd.DataFrame, k: int, rng, seed: Seed) -> pd.DataFrame:
    rows = df.sample(n=k, replace=True, random_state=int(rng.integers(0, 2**31))).reset_index(drop=True)
    for c in df.columns:
        rows[c] = df[c].sample(n=k, replace=True, random_state=int(rng.integers(0, 2**31))).values
    if seed.id_col in df.columns:
        rows[seed.id_col] = np.arange(k) + int(df[seed.id_col].max()) + 1
    return rows


@mutation("add_rows_new", "row")
def add_rows_new(old, new, seed, rng, mag):
    k = max(1, int(len(new.df) * 0.02 * mag))
    new.df = pd.concat([new.df, _new_rows(new.df, k, rng, seed)], ignore_index=True)
    return Effect({("C421", "new")}, allowed={"C312"})


@mutation("add_rows_duplicate", "row")
def add_rows_duplicate(old, new, seed, rng, mag):
    rows = new.df.iloc[_rows(rng, len(new.df), 0.02 * mag)]
    new.df = pd.concat([new.df, rows], ignore_index=True)
    return Effect({("C421", "duplicate_of_existing")})


@mutation("remove_rows_random", "row")
def remove_rows_random(old, new, seed, rng, mag):
    new.df = new.df.drop(index=_rows(rng, len(new.df), 0.03 * mag)).reset_index(drop=True)
    return Effect({("C422", None)}, allowed={"C312"})


@mutation("replace_rows", "row")
def replace_rows(old, new, seed, rng, mag):
    """Cas 4: k files fora i k de noves; el recompte no canvia."""
    k = max(1, int(len(new.df) * 0.02 * mag))
    kept = new.df.drop(index=_rows(rng, len(new.df), k / len(new.df))).reset_index(drop=True)
    new.df = pd.concat([kept, _new_rows(kept, k, rng, seed)], ignore_index=True)
    return Effect({("C421", "new"), ("C422", None)}, allowed={"C312"})


@mutation("remove_rows_with_nulls", "row")
def remove_rows_with_nulls(old, new, seed, rng, mag):
    col = _numeric_feature(seed, old.df, rng)
    nulls = _rows(rng, len(old.df), 0.03)
    old.df[col] = old.df[col].astype(float)
    old.df.loc[nulls, col] = np.nan
    new.df = old.df.dropna(subset=[col]).reset_index(drop=True)
    # P12: la proporció de nuls baixa només perquè s'eliminen files; C510 es permet però no s'exigeix.
    return Effect({("C422", "had_nulls")}, allowed={"C312", "C510"}, touched={col})


@mutation("remove_outliers", "row")
def remove_outliers(old, new, seed, rng, mag):
    col = _numeric_feature(seed, new.df, rng)
    x = new.df[col].astype(float)
    z = (x - x.mean()) / x.std()
    keep = z.abs() <= 2.5
    if keep.all():
        raise NotApplicable
    new.df = new.df[keep].reset_index(drop=True)
    return Effect({("C422", "outlier")}, allowed={"C530", "C322", "C520", "C312"})


@mutation("remove_by_predicate", "row")
def remove_by_predicate(old, new, seed, rng, mag):
    col = _pick(rng, [c for c in _low_card(seed, new.df) if new.df[c].nunique() >= 3], {seed.label})
    value = new.df[col].value_counts().index[-1]
    new.df = new.df[new.df[col] != value].reset_index(drop=True)
    return Effect({("C422", "predicate")}, allowed={"C312", "C530", "C520", "C322"})


@mutation("remove_one_duplicate", "row")
def remove_one_duplicate(old, new, seed, rng, mag):
    """Cas 19: l'antiga té una fila duplicada; la nova en treu una còpia."""
    r = int(rng.integers(len(old.df)))
    old.df = pd.concat([old.df, old.df.iloc[[r]]], ignore_index=True)
    new.df = old.df.iloc[:-1].copy()
    return Effect({("C422", "duplicate_removed")})


# ---------------------------------------------------------------------------
# Valors absents (C510)
# ---------------------------------------------------------------------------


@mutation("inject_nulls", "column")
def inject_nulls(old, new, seed, rng, mag):
    col = _pick(rng, [c for c in seed.numeric + seed.categorical if c not in (seed.id_col, seed.label)])
    rows = _rows(rng, len(new.df), 0.05 * mag)
    if pd.api.types.is_integer_dtype(new.df[col]):
        new.df[col] = new.df[col].astype(float)
    new.df.loc[rows, col] = np.nan
    return Effect({("C510", "masking")}, allowed={"C530"}, touched={col})


@mutation("int_gains_nan", "column")
def int_gains_nan(old, new, seed, rng, mag):
    """Cas 6: una columna entera guanya NaN; pandas la passa a float."""
    cols = [c for c in seed.numeric if c != seed.id_col and pd.api.types.is_integer_dtype(new.df[c])]
    col = _pick(rng, cols)
    new.df[col] = new.df[col].astype(float)
    new.df.loc[_rows(rng, len(new.df), 0.01), col] = np.nan
    return Effect({("C510", "masking")}, touched={col})


@mutation("impute_constant", "column")
def impute_constant(old, new, seed, rng, mag):
    col = _numeric_feature(seed, old.df, rng)
    nulls = _rows(rng, len(old.df), 0.05)
    old.df[col] = old.df[col].astype(float)
    old.df.loc[nulls, col] = np.nan
    new.df = old.df.copy()
    new.df[col] = new.df[col].fillna(round(float(old.df[col].mean()), 3))
    return Effect({("C510", "imputed_constant")}, allowed={"C530", "C520"}, touched={col})


@mutation("missing_token_change", "column")
def missing_token_change(old, new, seed, rng, mag):
    """Cas 9: el token d'absent canvia (`?` → buit) sense canviar cap dada."""
    if old.fmt != "csv" or new.fmt != "csv":
        raise NotApplicable
    col = _pick(rng, [c for c in seed.categorical if c != seed.label])
    rows = _rows(rng, len(old.df), 0.03)
    old.df.loc[rows, col] = np.nan
    new.df = old.df.copy()
    old.csv["na_rep"] = seed.missing_token or "?"
    new.csv["na_rep"] = ""
    return Effect({("C510", "representation")}, touched={col})


# ---------------------------------------------------------------------------
# Distribució (C530)
# ---------------------------------------------------------------------------


@mutation("undersample_majority", "row")
def undersample_majority(old, new, seed, rng, mag):
    major = new.df[seed.label].value_counts().index[0]
    idx = new.df.index[new.df[seed.label] == major]
    drop = rng.choice(idx, size=int(len(idx) * 0.5), replace=False)
    new.df = new.df.drop(index=drop).reset_index(drop=True)
    return Effect({("C422", None), ("C530", None)}, allowed={"C520", "C322", "C312"})


@mutation("oversample_minority", "row")
def oversample_minority(old, new, seed, rng, mag):
    """Cas 16."""
    minor = new.df[seed.label].value_counts().index[-1]
    rows = new.df[new.df[seed.label] == minor]
    new.df = pd.concat([new.df, rows], ignore_index=True)
    return Effect({("C421", "duplicate_of_existing"), ("C530", None)}, allowed={"C520", "C322"})


@mutation("flip_labels_subgroup", "column")
def flip_labels_subgroup(old, new, seed, rng, mag):
    """Cas 17."""
    group_col = _pick(rng, _low_card(seed, new.df), {seed.label})
    group = new.df[group_col].value_counts().index[0]
    values = list(new.df[seed.label].dropna().unique())
    if len(values) != 2:
        raise NotApplicable
    mask = new.df[group_col] == group
    new.df.loc[mask, seed.label] = new.df.loc[mask, seed.label].map({values[0]: values[1], values[1]: values[0]})
    return Effect({("C312", "cell_edits")}, allowed={"C520", "C530"}, touched={seed.label})


# ---------------------------------------------------------------------------
# Negatius cosmètics (no ha de sortir cap codi)
# ---------------------------------------------------------------------------


@mutation("identical", "negative")
def identical(old, new, seed, rng, mag):
    return Effect()


@mutation("resave_quoting_crlf", "negative")
def resave_quoting_crlf(old, new, seed, rng, mag):
    """Cas 7."""
    if new.fmt != "csv":
        raise NotApplicable
    new.csv.update(quoting=1, lineterminator="\r\n")
    return Effect()


@mutation("csv_to_parquet", "negative")
def csv_to_parquet(old, new, seed, rng, mag):
    """Cas 8: canvi de format (C100, fora d'abast)."""
    new.fmt = "parquet"
    return Effect()


@mutation("int_to_float_same_values", "negative")
def int_to_float_same_values(old, new, seed, rng, mag):
    """Artefacte de tipus: els valors són els mateixos (1 → 1.0)."""
    if new.fmt != "parquet":
        old.fmt = new.fmt = "parquet"
    cols = [c for c in seed.numeric if c != seed.id_col and pd.api.types.is_integer_dtype(new.df[c])]
    col = _pick(rng, cols)
    new.df[col] = new.df[col].astype(float)
    return Effect()


# ---------------------------------------------------------------------------
# Construcció dels casos
# ---------------------------------------------------------------------------


# Mutacions que reconstrueixen la versió nova a partir de l'antiga: s'han
# d'aplicar primer perquè no esborrin l'efecte de les altres.
SETUP_FIRST = ("remove_rows_with_nulls", "impute_constant", "missing_token_change", "remove_one_duplicate")


def _apply(names: list[str], seed: Seed, rng, mag: float, fmt: str) -> tuple[Version, Version, Effect]:
    names = sorted(names, key=lambda n: n not in SETUP_FIRST)
    old = Version(seed.df.copy(), fmt=fmt)
    new = Version(seed.df.copy(), fmt=fmt)
    total = Effect()
    for name in names:
        fn, _ = MUTATIONS[name]
        free = lambda cols: [c for c in cols if c in old.df.columns and c in new.df.columns  # noqa: E731
                             and c not in total.touched]
        view = Seed(seed.name, seed.df, seed.id_col, free(seed.numeric), free(seed.categorical),
                    seed.label, seed.missing_token)
        eff = fn(old, new, view, rng, mag)
        if eff.touched & total.touched:
            raise NotApplicable
        total.required |= eff.required
        total.allowed |= eff.allowed
        total.touched |= eff.touched
    total.allowed -= {code for code, _ in total.required}
    return old, new, total


def _compatible(names: list[str]) -> bool:
    kinds = [MUTATIONS[n][1] for n in names]
    if "negative" in kinds:
        return len(names) == 1
    if sum(n in SETUP_FIRST for n in names) > 1:
        return False  # totes dues reconstruirien la versió nova: la segona esborraria la primera
    return kinds.count("order") <= 1 and len(set(names)) == len(names)


def build_cases(split: str, n_single: int = 3, n_composite: int = 60) -> list[Case]:
    """
    Genera els casos d'un conjunt.

    :param split: `"calibration"` o `"heldout"`; fan servir llavors aleatòries disjuntes.
    :param n_single: instàncies de cada mutació sola, per llavor.
    :param n_composite: composicions aleatòries de 2-3 mutacions, per llavor.
    """
    base = 0 if split == "calibration" else 1_000_000
    cases: list[Case] = []
    names = sorted(MUTATIONS)
    composable = [n for n in names if MUTATIONS[n][1] != "negative"]
    for seed_fn in (synthetic_seed, adult_seed):
        seed_rng = np.random.default_rng(base + (0 if seed_fn is synthetic_seed else 7))
        seed = seed_fn(seed_rng)
        plans = [[n] for n in names for _ in range(n_single)]
        plan_rng = np.random.default_rng(base + 99)
        while len(plans) < len(names) * n_single + n_composite:
            k = int(plan_rng.integers(2, 4))
            combo = list(plan_rng.choice(composable, size=k, replace=False))
            if _compatible(combo):
                plans.append(combo)
        for i, plan in enumerate(plans):
            rng = np.random.default_rng(base + 10_000 + i + (0 if seed.name == "synthetic" else 500_000))
            mag = float(rng.choice([1.0, 2.0, 4.0]))
            fmt = "csv" if rng.random() < 0.7 else "parquet"
            try:
                old, new, eff = _apply(plan, seed, rng, mag, fmt)
            except (NotApplicable, KeyError):
                continue
            cases.append(Case(
                case_id=f"{split}-{seed.name}-{i:04d}", seed=seed.name, mutations=tuple(plan),
                old=old.to_bytes(), new=new.to_bytes(), old_ext="." + old.fmt, new_ext="." + new.fmt,
                required=frozenset(eff.required), allowed=frozenset(eff.allowed),
            ))
    return cases
