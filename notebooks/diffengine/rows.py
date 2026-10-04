"""
L4: aparellar les files de dues versions.

1. Clau: si una columna aparellada és única i no nul·la a les dues versions
   i en comparteix els valors, s'uneix per ella.
2. Si no, hash additiu de fila sobre les columnes ESTABLES (les que
   conserven el seu multiconjunt de valors). Les columnes transformades
   senceres (factor, reetiquetatge...) es deixen fora: si no, cap fila
   coincidiria. El hash d'una fila és la suma (mod 2^64) dels hashes de les
   seves cel·les, així que "la fila sense la columna j" és una resta.
   Les files repetides porten un índex d'ocurrència.
3. Les files que queden soles s'aparellen si difereixen en una sola
   columna estable (hash sense aquella columna), sempre que coincideixin
   en prou columnes (P2).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from diffengine.config import EngineConfig
from diffengine.load import NUMERIC, OPAQUE, Table

_ID_NAMES = ("id", "_id", "uuid", "key", "index", "idx")


@dataclass
class RowAlignment:
    """
    :ivar pairs: `(fila antiga, fila nova)` aparellades.
    :ivar unmatched_old: files antigues sense parella (candidates a C422).
    :ivar unmatched_new: files noves sense parella (candidates a C421).
    :ivar method: `key`, `hash` o `none`.
    :ivar key_columns: columnes clau (noms antics) si `method == "key"`.
    :ivar stable_columns: columnes (noms antics) usades per al hash.
    :ivar ambiguous_share: proporció de files aparellades per ordre d'ocurrència.
    :ivar ambiguous: per a cada parella de `pairs`, si s'ha fet per ordre
        d'ocurrència dins d'un grup de files iguals (pot ser incorrecta).
    """

    pairs: np.ndarray
    unmatched_old: np.ndarray
    unmatched_new: np.ndarray
    method: str
    key_columns: list[str] = field(default_factory=list)
    stable_columns: list[str] = field(default_factory=list)
    ambiguous_share: float = 0.0
    ambiguous: np.ndarray | None = None

    @property
    def reliable_pairs(self) -> np.ndarray:
        """Parelles que no depenen de l'ordre d'ocurrència."""
        if self.ambiguous is None:
            return self.pairs
        return self.pairs[~self.ambiguous]

    @property
    def matched_share(self) -> float:
        total = len(self.pairs) + max(len(self.unmatched_old), len(self.unmatched_new))
        return len(self.pairs) / total if total else 1.0


def cell_tokens(table: Table, column: str) -> pd.Series:
    """Valor normalitzat d'una columna com a text, per comparar i fer hash."""
    s = table.values[column]
    if table.columns[column].kind == NUMERIC:
        return s.map(lambda v: "\x00null" if pd.isna(v) else format(float(v), ".10g"))
    return s.map(lambda v: "\x00null" if v is None or (isinstance(v, float) and v != v) else str(v))


def _column_hash(tokens: pd.Series, column_id: int) -> np.ndarray:
    h = pd.util.hash_array(tokens.to_numpy(dtype=object), categorize=True)
    salt = np.uint64((0x9E3779B97F4A7C15 * (column_id + 1)) & 0xFFFFFFFFFFFFFFFF)
    with np.errstate(over="ignore"):
        return (h ^ salt) * np.uint64(0xBF58476D1CE4E5B9)


def value_overlap(old_tokens: pd.Series, new_tokens: pd.Series) -> float:
    """
    Proporció de valors (multiconjunt) compartits, sobre la versió més petita:
    una columna que conserva els valors en un subconjunt de files és estable.
    """
    a, b = old_tokens.value_counts(), new_tokens.value_counts()
    shared = a.align(b, fill_value=0)
    common = np.minimum(shared[0], shared[1]).sum()
    return float(common / max(min(len(old_tokens), len(new_tokens)), 1))


def _collision_rate(h: np.ndarray) -> float:
    """Probabilitat que dues files diferents de la mateixa taula comparteixin la clau `h`."""
    n = len(h)
    if n < 2:
        return 0.0
    counts = pd.Series(h).value_counts().to_numpy(dtype=float)
    return float(np.sum(counts * (counts - 1)) / (n * (n - 1)))


def is_identifier_like(name: str) -> bool:
    lower = str(name).lower()
    return lower in _ID_NAMES or lower.endswith(("_id", "-id", " id", "id_"))


def infer_key(old: Table, new: Table, matches: list[tuple[str, str]], config: EngineConfig) -> tuple[str, str] | None:
    """Una columna aparellada única, no nul·la i compartida a les dues versions."""
    candidates = []
    for o, n in matches:
        if old.columns[o].kind == OPAQUE:
            continue
        a, b = cell_tokens(old, o), cell_tokens(new, n)
        if a.str.startswith("\x00null").any() or b.str.startswith("\x00null").any():
            continue
        if not (a.is_unique and b.is_unique):
            continue
        overlap = len(set(a) & set(b)) / max(min(len(a), len(b)), 1)
        if overlap >= config.key_min_overlap:
            candidates.append((not is_identifier_like(o), -overlap, o, n))
    if not candidates:
        return None
    _, _, o, n = sorted(candidates)[0]
    return o, n


def _with_occurrence(h: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({"h": h})
    df["occ"] = df.groupby("h").cumcount()
    df["dup"] = df.groupby("h")["h"].transform("size") > 1
    return df


def align_rows(old: Table, new: Table, matches: list[tuple[str, str]], config: EngineConfig,
               exclude: set[str] = frozenset()) -> RowAlignment:
    """
    Aparella les files de `old` i `new`.

    :param matches: columnes aparellades `(nom antic, nom nou)`.
    :param exclude: columnes (noms antics) que no han d'entrar al hash.
    """
    n_old, n_new = old.n_rows, new.n_rows
    key = infer_key(old, new, [m for m in matches if m[0] not in exclude], config)
    if key is not None:
        a = pd.Series(np.arange(n_old), index=cell_tokens(old, key[0]).values)
        b = pd.Series(np.arange(n_new), index=cell_tokens(new, key[1]).values)
        common = a.index.intersection(b.index)
        pairs = np.column_stack([a[common].values, b[common].values]) if len(common) else np.empty((0, 2), int)
        return RowAlignment(
            pairs=pairs, unmatched_old=np.setdiff1d(np.arange(n_old), pairs[:, 0]),
            unmatched_new=np.setdiff1d(np.arange(n_new), pairs[:, 1]), method="key", key_columns=[key[0]],
        )

    tokens = {o: (cell_tokens(old, o), cell_tokens(new, n)) for o, n in matches if o not in exclude}
    stable = [o for o, (a, b) in tokens.items() if value_overlap(a, b) >= 0.5]
    if not stable:
        return RowAlignment(np.empty((0, 2), int), np.arange(n_old), np.arange(n_new), "none")
    stable = stable[: config.max_pairing_columns]

    cell_old = {c: _column_hash(tokens[c][0], i) for i, c in enumerate(stable)}
    cell_new = {c: _column_hash(tokens[c][1], i) for i, c in enumerate(stable)}
    with np.errstate(over="ignore"):
        row_old = np.sum(np.vstack(list(cell_old.values())), axis=0, dtype=np.uint64)
        row_new = np.sum(np.vstack(list(cell_new.values())), axis=0, dtype=np.uint64)

    pairs: list[tuple[int, int, bool]] = []
    ambiguous = 0
    free_old, free_new = np.arange(n_old), np.arange(n_new)

    def match(h_old: np.ndarray, h_new: np.ndarray, require_agreement: bool) -> None:
        nonlocal free_old, free_new, ambiguous
        a = _with_occurrence(h_old[free_old]).assign(row=free_old)
        b = _with_occurrence(h_new[free_new]).assign(row=free_new)
        joined = a.merge(b, on=["h", "occ"], suffixes=("_o", "_n"))
        if require_agreement and len(joined):
            # Aparellament parcial només si és coherent a tota la taula: la clau
            # reduïda és única a les dues versions, o hi apareix el mateix nombre
            # de cops (una edició in situ no en canvia el recompte).
            count_old = pd.Series(h_old).value_counts()
            count_new = pd.Series(h_new).value_counts()
            co = joined["h"].map(count_old).to_numpy()
            cn = joined["h"].map(count_new).fillna(0).to_numpy()
            joined = joined[co == cn]
            # Hi ha d'haver molts més aparellaments que els esperats per atzar
            # entre les files lliures, donada la freqüència amb què dues files
            # de la taula ja comparteixen aquesta clau reduïda.
            expected = len(free_old) * len(free_new) * _collision_rate(h_old)
            if len(joined) < max(1, 5 * expected):
                return
            agree = np.zeros(len(joined))
            for c in stable:
                agree += cell_old[c][joined["row_o"].to_numpy()] == cell_new[c][joined["row_n"].to_numpy()]
            joined = joined[agree / len(stable) >= config.edited_row_min_agreement]
        if not len(joined):
            return
        dup = (joined["dup_o"] | joined["dup_n"]).to_numpy()
        ambiguous += int(dup.sum())
        pairs.extend(zip(joined["row_o"].tolist(), joined["row_n"].tolist(), dup.tolist()))
        free_old = np.setdiff1d(free_old, joined["row_o"].to_numpy())
        free_new = np.setdiff1d(free_new, joined["row_n"].to_numpy())

    match(row_old, row_new, require_agreement=False)
    if len(stable) >= 2:
        # Primer la columna amb més parelles candidates: la que ha canviat de
        # debò en dona centenars; una coincidència casual en una altra, una o dues.
        def candidates(c: str) -> int:
            with np.errstate(over="ignore"):
                a = pd.Index(row_old[free_old] - cell_old[c][free_old])
                b = pd.Index(row_new[free_new] - cell_new[c][free_new])
            return int(a.isin(b).sum())

        for c in sorted(stable, key=candidates, reverse=True):
            if not len(free_old) or not len(free_new):
                break
            with np.errstate(over="ignore"):
                match(row_old - cell_old[c], row_new - cell_new[c], require_agreement=True)

    if len(stable) >= 4 and len(free_old) and len(free_new):
        # Files que difereixen en dues columnes: només entre les columnes que més
        # canvien (menys solapament de valors), per mantenir el cost acotat.
        changed = sorted(stable, key=lambda c: value_overlap(*tokens[c]))[:6]
        for i, c1 in enumerate(changed):
            for c2 in changed[i + 1:]:
                if not len(free_old) or not len(free_new):
                    break
                with np.errstate(over="ignore"):
                    match(row_old - cell_old[c1] - cell_old[c2], row_new - cell_new[c1] - cell_new[c2],
                          require_agreement=True)

    pairs.sort()
    pairs_arr = np.array([(a, b) for a, b, _ in pairs], dtype=int) if pairs else np.empty((0, 2), int)
    return RowAlignment(
        pairs=pairs_arr, unmatched_old=np.sort(free_old), unmatched_new=np.sort(free_new), method="hash",
        stable_columns=stable, ambiguous_share=ambiguous / max(len(pairs), 1),
        ambiguous=np.array([d for _, _, d in pairs], dtype=bool),
    )
