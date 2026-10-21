"""
Pas 2: llegir un fitxer tabular i saber el tipus de cada columna.

El tipus que dona pandas no és el tipus de la dada: una columna d'enters amb
un sol nul passa a `float`, un CSV porta espais després de les comes, i `?`
vol dir "absent". Per això `load_table`:

- Llegeix els CSV com a text i en detecta el separador i el dialecte.
- Converteix els tokens d'absent (`?`, `NA`, buit…) en nuls. Tots són el
  mateix buit: si una versió nova escriu els absents amb un altre símbol, no
  surt cap canvi.
- Dedueix el **tipus lògic** pels valors: `numeric`, `categorical`, `text`
  (text lliure) o `opaque` (imatges, àudio, vectors). Les cel·les opaques es
  converteixen en text determinista: serveixen per reconèixer files, però no
  es comparen.
- Llegeix com a nombre una columna d'arrays d'un sol element (LeRobot desa
  així els escalars).
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

NULL_TOKEN = "\x00null"
"""Representació d'un nul quan una columna es compara o es fa hash com a text."""


@dataclass
class Column:
    """
    :ivar name: nom de la columna.
    :ivar kind: `numeric`, `categorical`, `text` o `opaque`.
    :ivar integer: per a numèriques, si tots els valors no nuls són enters.
    :ivar raw_dtype: dtype físic (pandas/arrow) o `str` per a CSV.
    :ivar exponent_share: proporció de valors escrits en notació científica (CSV).
    :ivar decimal_comma: el separador decimal és la coma (CSV).
    """

    name: str
    kind: str
    integer: bool = False
    raw_dtype: str = ""
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
        """
        :return: nombre de files de la taula.
        """
        return len(self.values)


class ParseError(Exception):
    pass


def _json_default(value):
    """
    Converteix a text els valors que el mòdul `json` no sap escriure.

    :param value: el valor.
    :return: un valor que `json` pot escriure (bytes → resum SHA-1, array → llista...).
    """
    if isinstance(value, (bytes, bytearray)):
        return "sha1:" + hashlib.sha1(bytes(value)).hexdigest()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return repr(value)


def _serialize(value) -> str | None:
    """
    Converteix una cel·la complexa (imatge, àudio, llista) en un text
    determinista, perquè es pugui comparar i fer-ne hash.

    :param value: el contingut de la cel·la.
    :return: el text, o `None` si la cel·la és buida.
    """
    if is_missing(value):
        return None
    if isinstance(value, (bytes, bytearray)):
        return _json_default(value)
    return json.dumps(value, sort_keys=True, default=_json_default)


def is_missing(value) -> bool:
    """
    Diu si un valor és buit (`None`, `NaN`). Una llista o un array no ho és mai.

    :param value: qualsevol valor.
    :return: `True` si és buit.
    """
    try:
        return value is None or bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _unwrap_singletons(series: pd.Series) -> pd.Series | None:
    """
    Si totes les cel·les d'una columna són llistes d'un sol element (`[0.04]`),
    les converteix en valors simples.

    :param series: la columna.
    :return: la columna amb valors simples, o `None` si no és d'aquest tipus.
    """
    present = series[series.map(lambda v: v is not None)]  # `[nan]` també compta: és un escalar absent
    if present.empty or not present.map(lambda v: isinstance(v, (list, tuple, np.ndarray)) and len(v) == 1).all():
        return None
    return series.map(lambda v: None if v is None else (v[0].item() if isinstance(v[0], np.generic) else v[0]))


def _is_opaque(series: pd.Series) -> bool:
    """
    Diu si una columna conté valors complexos (diccionaris, llistes, bytes) que no
    es poden comparar com a nombres o text.

    :param series: la columna.
    :return: `True` si el primer valor no buit és complex.
    """
    sample = series.dropna()
    if sample.empty:
        return False
    first = sample.iloc[0]
    return isinstance(first, (dict, list, tuple, bytes, bytearray, np.ndarray))


def _text_or_categorical(values: pd.Series, config: EngineConfig) -> str:
    """
    Decideix si una columna de text és text lliure (molts valors diferents i
    llargs) o categòrica (pocs valors que es repeteixen).

    :param values: la columna, com a text.
    :param config: llindars del motor.
    :return: `text` o `categorical`.
    """
    present = values.dropna()
    if present.empty:
        return CATEGORICAL
    distinct_share = present.nunique() / len(present)
    mean_len = present.str.len().mean()
    if distinct_share >= config.text_min_distinct_share and mean_len >= config.text_min_mean_length:
        return TEXT
    return CATEGORICAL


def _integral(values: pd.Series) -> bool:
    """
    Diu si tots els valors no buits d'una columna numèrica són enters.

    :param values: la columna.
    :return: `True` si són tots enters (i n'hi ha almenys un).
    """
    present = values.dropna()
    return bool(len(present)) and bool(np.all(np.isclose(present, np.round(present))))


def _from_typed(df: pd.DataFrame, fmt: str, config: EngineConfig) -> Table:
    """
    Converteix una taula que ja porta tipus (parquet, JSON) a la representació
    del motor: per a cada columna, els valors i el seu tipus.

    :param df: la taula llegida per pandas.
    :param fmt: format d'origen (`parquet` o `json`).
    :param config: llindars del motor (tokens de valor absent, llindars de text).
    :return: la taula preparada per comparar.
    """
    values, columns = {}, {}
    for name in df.columns:
        s = df[name]
        raw_dtype = str(s.dtype)
        if _is_opaque(s):
            unwrapped = _unwrap_singletons(s)
            if unwrapped is not None:
                s = unwrapped.infer_objects()
                raw_dtype = f"{raw_dtype}[1]"
        if _is_opaque(s):
            values[name] = s.map(_serialize).astype(object)
            columns[name] = Column(name, OPAQUE, raw_dtype=raw_dtype)
        elif pd.api.types.is_bool_dtype(s):
            values[name] = s.astype(object).map(lambda v: None if is_missing(v) else str(bool(v))).astype(object)
            columns[name] = Column(name, CATEGORICAL, raw_dtype=raw_dtype)
        elif pd.api.types.is_numeric_dtype(s):
            values[name] = pd.to_numeric(s, errors="coerce").astype("float64")
            columns[name] = Column(name, NUMERIC, integer=_integral(values[name]), raw_dtype=raw_dtype)
        else:
            v = s.astype(object).map(lambda x: None if is_missing(x) else str(x)).astype(object)
            tokens = set(config.missing_tokens)
            is_token = v.map(lambda x: not is_missing(x) and x.strip() in tokens).astype(bool)
            v = v.where(~is_token, None).astype(object)
            values[name] = v
            columns[name] = Column(name, _text_or_categorical(v, config), raw_dtype=raw_dtype)
    return Table(fmt, pd.DataFrame(values, columns=list(df.columns)), columns)


def _sniff(text: str) -> dict:
    """
    Endevina el separador d'un CSV (`,`, `;`, tabulador o `|`) i si hi ha un espai
    després de cada separador.

    :param text: contingut del fitxer.
    :return: diccionari amb `delimiter` i `skipinitialspace`.
    """
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return {"delimiter": dialect.delimiter, "skipinitialspace": bool(dialect.skipinitialspace)}
    except csv.Error:
        return {"delimiter": ",", "skipinitialspace": False}


def _from_csv(data: bytes, ext: str, config: EngineConfig) -> Table:
    """
    Llegeix un CSV o TSV com a text i decideix el tipus de cada columna pels
    valors. Els tokens de valor absent (`?`, `NA`, buit...) es converteixen en
    buits.

    :param data: contingut del fitxer, en bytes.
    :param ext: `.csv` o `.tsv`.
    :param config: llindars del motor.
    :return: la taula preparada per comparar.
    :raises ParseError: si pandas no el pot llegir.
    """
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
                                   exponent_share=float(exponent), decimal_comma=bool(decimal_comma))
        else:
            v = cells.where(~is_null, None).astype(object)
            values[name] = v
            columns[name] = Column(name, _text_or_categorical(v, config), raw_dtype="str")
    raw_view = raw.astype(object)
    return Table("csv", pd.DataFrame(values, columns=list(raw.columns)), columns, raw=raw_view, dialect=dialect)


def load_table(data: bytes, ext: str, config: EngineConfig = DEFAULT_CONFIG) -> Table:
    """
    Llegeix un fitxer tabular i el prepara per comparar: valors i tipus de cada
    columna.

    :param data: contingut del fitxer, en bytes.
    :param ext: extensió (`.csv`, `.tsv`, `.parquet`, `.json`, `.jsonl`).
    :param config: llindars del motor.
    :return: la taula preparada per comparar.
    :raises ParseError: si no es pot llegir o el format no és compatible.
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
