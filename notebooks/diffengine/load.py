"""
L1: llegir un fitxer tabular i normalitzar-lo.

- CSV/TSV es llegeixen com a text cru (es conserva per detectar canvis de
  representació) i després es converteixen.
- El tipus lògic de cada columna surt dels VALORS, no del dtype de pandas:
  una columna entera que guanya un NaN continua sent entera.
- Les cel·les no hashables (dict, list, bytes: imatge/àudio de HF) es
  serialitzen de manera determinista: participen en la identitat i l'ordre
  de les files, però no en les comparacions de valors.
"""

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from diffengine.config import DEFAULT_CONFIG, EngineConfig

NUMERIC = "numeric"
CATEGORICAL = "categorical"
TEXT = "text"
OPAQUE = "opaque"


@dataclass
class Column:
    """
    :ivar kind: `numeric`, `categorical`, `text` o `opaque`.
    :ivar integer: per a numèriques, si tots els valors no nuls són enters.
    :ivar raw_dtype: dtype físic (pandas/arrow) o `str` per a CSV.
    :ivar missing_tokens: tokens d'absent trobats al text cru (CSV).
    :ivar exponent_share: proporció de valors escrits en notació científica (CSV).
    :ivar decimal_comma: el separador decimal és la coma (CSV).
    """

    name: str
    kind: str
    integer: bool = False
    raw_dtype: str = ""
    missing_tokens: frozenset[str] = frozenset()
    exponent_share: float = 0.0
    decimal_comma: bool = False


@dataclass
class Table:
    """
    Una versió d'un fitxer, llesta per comparar.

    :ivar values: valors normalitzats; numèriques en float64 (NaN = nul),
        la resta en text exacte (None = nul).
    :ivar raw: text cru de cada cel·la (només CSV/TSV).
    """

    fmt: str
    values: pd.DataFrame
    columns: dict[str, Column]
    raw: pd.DataFrame | None = None
    dialect: dict = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        return len(self.values)


class ParseError(Exception):
    pass


def _serialize(value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (bytes, bytearray)):
        return "sha1:" + hashlib.sha1(bytes(value)).hexdigest()
    if isinstance(value, np.ndarray):
        value = value.tolist()
    return json.dumps(value, sort_keys=True, default=_json_default)


def _json_default(value):
    if isinstance(value, (bytes, bytearray)):
        return "sha1:" + hashlib.sha1(bytes(value)).hexdigest()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return repr(value)


def _is_missing(value) -> bool:
    try:
        return value is None or bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_opaque(series: pd.Series) -> bool:
    sample = series.dropna()
    if sample.empty:
        return False
    first = sample.iloc[0]
    return isinstance(first, (dict, list, tuple, bytes, bytearray, np.ndarray))


def _text_or_categorical(values: pd.Series, config: EngineConfig) -> str:
    present = values.dropna()
    if present.empty:
        return CATEGORICAL
    distinct_share = present.nunique() / len(present)
    mean_len = present.str.len().mean()
    if distinct_share >= config.text_min_distinct_share and mean_len >= config.text_min_mean_length:
        return TEXT
    return CATEGORICAL


def _integral(values: pd.Series) -> bool:
    present = values.dropna()
    return bool(len(present)) and bool(np.all(np.isclose(present, np.round(present))))


def _from_typed(df: pd.DataFrame, fmt: str, config: EngineConfig) -> Table:
    """Parquet/JSON: el tipus físic ja ve donat."""
    values, columns = {}, {}
    for name in df.columns:
        s = df[name]
        raw_dtype = str(s.dtype)
        if _is_opaque(s):
            values[name] = s.map(_serialize).astype(object)
            columns[name] = Column(name, OPAQUE, raw_dtype=raw_dtype)
        elif pd.api.types.is_bool_dtype(s):
            values[name] = s.astype(object).map(lambda v: None if _is_missing(v) else str(bool(v))).astype(object)
            columns[name] = Column(name, CATEGORICAL, raw_dtype=raw_dtype)
        elif pd.api.types.is_numeric_dtype(s):
            values[name] = pd.to_numeric(s, errors="coerce").astype("float64")
            columns[name] = Column(name, NUMERIC, integer=_integral(values[name]), raw_dtype=raw_dtype)
        else:
            v = s.astype(object).map(lambda x: None if _is_missing(x) else str(x)).astype(object)
            tokens = set(config.missing_tokens)
            is_token = v.map(lambda x: not _is_missing(x) and x.strip() in tokens).astype(bool)
            found = frozenset(x.strip() for x in v[is_token]) if is_token.any() else frozenset()
            v = v.where(~is_token, None).astype(object)
            values[name] = v
            columns[name] = Column(name, _text_or_categorical(v, config), raw_dtype=raw_dtype, missing_tokens=found)
    return Table(fmt, pd.DataFrame(values, columns=list(df.columns)), columns)


def _sniff(text: str) -> dict:
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return {"delimiter": dialect.delimiter, "skipinitialspace": bool(dialect.skipinitialspace)}
    except csv.Error:
        return {"delimiter": ",", "skipinitialspace": False}


def _from_csv(data: bytes, ext: str, config: EngineConfig) -> Table:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    # Un espai després de cada separador (p.e. UCI Adult, ", ") és part del
    # dialecte, no de les dades: es treu igual que fa el lector de CSV.
    dialect = {"delimiter": "\t", "skipinitialspace": False} if ext == ".tsv" else _sniff(text)
    dialect["encoding"] = encoding
    try:
        raw = pd.read_csv(io.StringIO(text), sep=dialect["delimiter"], dtype=str, keep_default_na=False,
                          na_filter=False, skipinitialspace=dialect["skipinitialspace"])
    except Exception as exc:
        raise ParseError(str(exc)) from exc

    tokens = set(config.missing_tokens)
    values, columns = {}, {}
    for name in raw.columns:
        cells = raw[name].astype(object)
        stripped = cells.str.strip()
        is_null = stripped.isin(tokens)
        found_tokens = frozenset(stripped[is_null].unique())
        present = stripped[~is_null]

        decimal_comma = dialect["delimiter"] != "," and present.str.match(r"^-?\d+,\d+$").mean() > 0.5 \
            if len(present) else False
        candidate = present.str.replace(",", ".", regex=False) if decimal_comma else present
        parsed = pd.to_numeric(candidate, errors="coerce")
        if len(present) and parsed.notna().all():
            col = pd.Series(np.nan, index=cells.index, dtype="float64")
            col[~is_null] = parsed.astype("float64")
            values[name] = col
            exponent = present.str.contains(r"\d[eE][+-]?\d", regex=True).mean()
            columns[name] = Column(name, NUMERIC, integer=_integral(col), raw_dtype="str",
                                   missing_tokens=found_tokens, exponent_share=float(exponent),
                                   decimal_comma=bool(decimal_comma))
        else:
            v = cells.where(~is_null, None).astype(object)
            values[name] = v
            columns[name] = Column(name, _text_or_categorical(v, config), raw_dtype="str",
                                   missing_tokens=found_tokens)
    raw_view = raw.astype(object)
    return Table("csv", pd.DataFrame(values, columns=list(raw.columns)), columns, raw=raw_view, dialect=dialect)


def load_table(data: bytes, ext: str, config: EngineConfig = DEFAULT_CONFIG) -> Table:
    """
    Llegeix un fitxer tabular.

    :param data: contingut del fitxer.
    :param ext: extensió (`.csv`, `.tsv`, `.parquet`, `.json`, `.jsonl`).
    :raises ParseError: si no es pot llegir.
    """
    ext = ext.lower()
    try:
        if ext in (".csv", ".tsv"):
            return _from_csv(data, ext, config)
        if ext == ".parquet":
            return _from_typed(pd.read_parquet(io.BytesIO(data)), "parquet", config)
        if ext in (".json", ".jsonl"):
            df = pd.read_json(io.BytesIO(data), lines=(ext == ".jsonl"))
            return _from_typed(df, "json", config)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"{type(exc).__name__}: {exc}") from exc
    raise ParseError(f"format no suportat: {ext}")
