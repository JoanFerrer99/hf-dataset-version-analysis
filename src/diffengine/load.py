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

Un dataset repartit en diversos fitxers es llegeix sencer amb `load_files`:
les files de cada fitxer a continuació de les de l'anterior, amb les
columnes de tots (decisió T-37), també si són de formats diferents (T-44).
"""

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass, field, replace

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
    :ivar dropped_files: fitxers que no s'han llegit perquè no són taules o repetien files d'un altre més gran
        (`load_files`).
    """

    fmt: str
    values: pd.DataFrame
    columns: dict[str, Column]
    raw: pd.DataFrame | None = None
    dialect: dict = field(default_factory=dict)
    dropped_files: tuple[str, ...] = ()

    @property
    def n_rows(self) -> int:
        """
        :return: nombre de files de la taula.
        """
        return len(self.values)


class ParseError(Exception):
    pass


class MixedColumns(Exception):
    """Els fitxers d'una versió no tenen totes les mateixes columnes: no es comparen (decisió T-44)."""


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


def _read_csv(data: bytes, ext: str) -> tuple[pd.DataFrame, dict]:
    """
    Llegeix un CSV o TSV com a text, sense decidir-ne encara els tipus.

    :param data: contingut del fitxer, en bytes.
    :param ext: `.csv` o `.tsv`.
    :return: `(cel·les com a text, dialecte)`.
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
    return raw, dialect


def _from_csv(raw: pd.DataFrame, dialect: dict, config: EngineConfig) -> Table:
    """
    Decideix el tipus de cada columna d'un CSV o TSV pels valors. Els tokens
    de valor absent (`?`, `NA`, buit...) es converteixen en buits.

    :param raw: cel·les com a text (`_read_csv`).
    :param dialect: dialecte del fitxer (`_read_csv`).
    :param config: llindars del motor.
    :return: la taula preparada per comparar.
    """
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


def _read(data: bytes, ext: str) -> tuple[pd.DataFrame, dict]:
    """
    Llegeix un fitxer tabular, sense decidir-ne encara els tipus.

    :param data: contingut del fitxer, en bytes.
    :param ext: extensió, en minúscules.
    :return: `(taula, dialecte)`: text per als CSV, i els tipus del fitxer per a parquet i JSON (sense dialecte).
    :raises ParseError: si no es pot llegir o el format no és compatible.
    """
    try:
        if ext in (".csv", ".tsv"):
            return _read_csv(data, ext)
        if ext == ".parquet":
            return pd.read_parquet(io.BytesIO(data)), {}
        if ext in (".json", ".jsonl"):
            return pd.read_json(io.BytesIO(data), lines=(ext == ".jsonl")), {}
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"{type(exc).__name__}: {exc}") from exc
    raise ParseError(f"format no suportat: {ext}")


def _prepare(df: pd.DataFrame, ext: str, dialect: dict, config: EngineConfig) -> Table:
    """
    Decideix el tipus de cada columna d'una taula llegida amb `_read`.

    :return: la taula preparada per comparar.
    :raises ParseError: si no es pot preparar.
    """
    try:
        if ext in (".csv", ".tsv"):
            return _from_csv(df, dialect, config)
        return _from_typed(df, "parquet" if ext == ".parquet" else "json", config)
    except Exception as exc:
        raise ParseError(f"{type(exc).__name__}: {exc}") from exc


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
    df, dialect = _read(data, ext)
    return _prepare(df, ext, dialect, config)


def cell_tokens(table: Table, column: str) -> pd.Series:
    """
    Converteix els valors d'una columna en text normalitzat, per poder-los
    comparar i fer-ne hash. Els nombres es formaten igual a totes dues versions
    (`3` i `3.0` donen el mateix text) i els buits, amb una marca especial.

    :param table: la taula.
    :param column: nom de la columna.
    :return: un text per fila.
    """
    s = table.values[column]
    if table.columns[column].kind == NUMERIC:
        return s.map(lambda v: NULL_TOKEN if pd.isna(v) else format(float(v), ".10g"))
    return s.map(lambda v: NULL_TOKEN if is_missing(v) else str(v))



def _as_text(values: pd.Series, kind: str) -> pd.Series:
    """
    Converteix una columna en text, per unir-la amb una altra d'un tipus diferent.

    :param values: valors de la columna.
    :param kind: tipus de la columna.
    :return: els valors com a text (`None` = buit); els nombres enters, sense `.0`.
    """
    if kind == NUMERIC:
        return values.map(lambda v: None if pd.isna(v) else format(float(v), ".15g")).astype(object)
    return values.map(lambda v: None if is_missing(v) else str(v)).astype(object)


def _all_numbers(values: pd.Series) -> pd.Series | None:
    """
    :param values: una columna com a text (`None` = buit).
    :return: la columna en float64 si tots els valors no buits són números (la regla dels CSV,
        `_from_csv`), o `None` si no.
    """
    present = values.dropna()
    parsed = pd.to_numeric(present, errors="coerce")
    if present.empty or parsed.isna().any():
        return None
    out = pd.Series(np.nan, index=values.index, dtype="float64")
    out[present.index] = parsed.astype("float64")
    return out


def _merge_tables(tables: list[Table], config: EngineConfig) -> Table:
    """
    Uneix taules de formats diferents, ja preparades, en una sola (decisió T-44).

    Les columnes són les de totes, en l'ordre en què surten. Si una columna té
    el mateix tipus a totes, es manté. Si és numèrica en algun format i tots
    els seus valors, de tots els formats, són números (p.e. `"1"` en un JSON),
    és numèrica; si no, passa a text (o a `opaque`, si alguna ho és). Entre
    text i categòrica es torna a decidir amb tots els valors.

    :param tables: taules preparades, cadascuna d'un format.
    :param config: llindars del motor.
    :return: la taula unida, amb les files en l'ordre de `tables`.
    """
    names = list(dict.fromkeys(name for t in tables for name in t.values.columns))
    sizes = [t.n_rows for t in tables]
    values, columns = {}, {}
    for name in names:
        present = [t.columns[name] for t in tables if name in t.columns]
        kinds = {c.kind for c in present}
        if kinds == {NUMERIC}:
            parts = [t.values[name] if name in t.columns else pd.Series(np.nan, index=range(n), dtype="float64")
                     for t, n in zip(tables, sizes)]
            merged = pd.concat(parts, ignore_index=True).astype("float64")
            csv_column = next((c for c in present if c.raw_dtype == "str"), present[0])
            columns[name] = replace(csv_column, integer=_integral(merged))
        else:
            kind = OPAQUE if OPAQUE in kinds else None
            parts = [_as_text(t.values[name], t.columns[name].kind) if name in t.columns
                     else pd.Series([None] * n, dtype=object) for t, n in zip(tables, sizes)]
            merged = pd.concat(parts, ignore_index=True).astype(object)
            raw_dtypes = "|".join(sorted({c.raw_dtype for c in present}))
            numbers = _all_numbers(merged) if kind is None and NUMERIC in kinds else None
            if numbers is not None:
                merged = numbers
                columns[name] = Column(name, NUMERIC, integer=_integral(merged), raw_dtype=raw_dtypes)
            else:
                columns[name] = Column(name, kind or _text_or_categorical(merged, config), raw_dtype=raw_dtypes)
        values[name] = merged
    return Table("+".join(dict.fromkeys(t.fmt for t in tables)), pd.DataFrame(values, columns=names), columns)


def _load_same_format(parts: list[pd.DataFrame], ext: str, dialect: dict, config: EngineConfig) -> Table:
    """
    Uneix fitxers del mateix format i en decideix els tipus amb tots els valors.

    :param parts: els fitxers llegits (`_read`), en ordre.
    :param ext: extensió comuna.
    :param dialect: dialecte del primer fitxer (CSV).
    :param config: llindars del motor.
    :return: la taula preparada.
    """
    if len(parts) == 1:
        return _prepare(parts[0], ext, dialect, config)
    df = pd.concat(parts, ignore_index=True, sort=False)
    if ext in (".csv", ".tsv"):
        df = df.fillna("")  # cel·la d'una columna que el seu fitxer no té: buida, com un camp buit
    return _prepare(df, ext, dialect, config)


def _row_hashes(table: Table) -> set[int]:
    """
    Hash de cada fila amb els valors normalitzats (`cell_tokens`): el mateix
    valor dona el mateix hash en qualsevol format. Les columnes van per nom.

    :param table: la taula d'un fitxer.
    :return: el conjunt de hashos de les seves files.
    """
    names = sorted(table.values.columns)
    tokens = pd.DataFrame({i: cell_tokens(table, name) for i, name in enumerate(names)}, index=table.values.index)
    return set(pd.util.hash_pandas_object(tokens, index=False).tolist())


def files_to_keep(tables: list[Table]) -> list[int]:
    """
    Quins fitxers es llegeixen quan n'hi ha que repeteixen files d'altres
    (decisió T-44). Es recorren del que té més files al que en té menys (en
    cas d'empat, en ordre natural) i es conserva cada fitxer que no comparteix
    cap fila amb els ja conservats. Les files repetides dins d'un mateix
    fitxer no compten.

    :param tables: la taula de cada fitxer, en ordre natural.
    :return: les posicions dels fitxers que es conserven, en ordre natural.
    """
    kept, seen = [], set()
    for i in sorted(range(len(tables)), key=lambda i: (-tables[i].n_rows, i)):
        rows = _row_hashes(tables[i])
        if rows.isdisjoint(seen):
            kept.append(i)
            seen |= rows
    return sorted(kept)


def load_files(paths: list[str], config: EngineConfig = DEFAULT_CONFIG) -> Table:
    """
    Llegeix els fitxers d'un dataset (`datafiles.dataset_files`) com una sola
    taula, amb les regles de la decisió T-44:

    - Un fitxer `.json` que no es pot llegir com a taula (és un document, p.e.
      `croissant.json` o `metadata.json`, i no una llista de registres) no és
      dades i no es llegeix. Si és l'únic fitxer, la versió no es pot llegir.
    - Tots els fitxers han de tenir les mateixes columnes (el mateix conjunt de
      noms, en qualsevol ordre); si no, no es comparen (`MixedColumns`).
    - Si un fitxer repeteix files d'un altre de més gran, no es llegeix
      (`files_to_keep`): així un fitxer que agrega els altres (p.e. `overall`)
      no duplica les files.
    - Les files de cada fitxer van a continuació de les de l'anterior, en
      ordre. El tipus de cada columna es decideix amb tots els valors del
      mateix format, com si fos un sol fitxer. Si hi ha fitxers de més d'un
      format, cada format es prepara pel seu compte i després s'uneixen
      (`_merge_tables`).

    :param paths: fitxers locals, en ordre natural.
    :param config: llindars del motor.
    :return: la taula preparada per comparar; `dropped_files`, els fitxers que no s'han llegit (no són
        taules o repeteixen files d'un altre).
    :raises ParseError: si algun fitxer que no és un `.json` no es pot llegir, o cap és una taula.
    :raises MixedColumns: si els fitxers no tenen totes les mateixes columnes.
    """
    kept, exts, read, dialects, not_tables = [], [], [], [], []
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        try:
            df, dialect = _read(data, ext)
        except ParseError:
            if ext != ".json" or len(paths) == 1:
                raise
            not_tables.append(path)  # un document JSON (p.e. `croissant.json`), no una taula
            continue
        kept.append(path)
        exts.append(ext)
        read.append(df)
        dialects.append(dialect)
    if not read:
        raise ParseError("cap fitxer de dades és una taula")
    repeated: list[str] = []
    if len(read) > 1:
        if len({frozenset(map(str, df.columns)) for df in read}) > 1:
            raise MixedColumns(f"{len(read)} fitxers amb columnes diferents")
        tables = [_prepare(df, ext, dialect, config) for df, ext, dialect in zip(read, exts, dialects)]
        keep = files_to_keep(tables)
        repeated = [kept[i] for i in range(len(kept)) if i not in keep]
        exts, read, dialects = [exts[i] for i in keep], [read[i] for i in keep], [dialects[i] for i in keep]
    dropped = tuple(p for p in paths if p in set(not_tables) | set(repeated))
    groups: dict[str, list[int]] = {}
    for i, ext in enumerate(exts):
        groups.setdefault(ext, []).append(i)
    first = {ext: dialects[idx[0]] for ext, idx in groups.items()}  # el dialecte del primer fitxer de cada format
    if len(groups) == 1:
        ext = next(iter(groups))
        table = _load_same_format(read, ext, first[ext], config)
    else:
        tables = [_load_same_format([read[i] for i in idx], ext, first[ext], config) for ext, idx in groups.items()]
        table = _merge_tables(tables, config)
        # les files, en l'ordre dels fitxers i no agrupades per format
        starts = np.cumsum([0] + [len(df) for df in read])
        order = np.concatenate([np.arange(starts[i], starts[i + 1]) for idx in groups.values() for i in idx])
        table.values = table.values.iloc[np.argsort(order, kind="stable")].reset_index(drop=True)
    table.dropped_files = dropped
    return table
