"""
L4: aparellar les files de dues versions (quina fila nova és quina antiga).

Per passos (`align_rows`):
1. **Clau**: si una columna té valors únics a les dues versions i en
   comparteixen la majoria (un identificador), s'uneix per ella. Un número
   de fila (0, 1, 2…) no compta: es renumera quan s'insereixen files.
2. **Files idèntiques**: cada fila es resumeix en un número (hash) a partir
   dels valors de les columnes que conserven la majoria dels seus valors.
   El hash d'una fila és la suma dels hashes de les seves cel·les, i per
   això "la fila sense una columna" és una simple resta.
3. **Files editades en una columna**, i després en dues: es tornen a
   comparar sense aquelles columnes. Només s'accepta si no pot ser
   casualitat.
4. **Parelles dubtoses**: si diverses files són idèntiques, quina va amb
   quina és ambigu; es marquen i no s'usen per comparar valors ni ordre.

Els comptadors de posició (`index`, `episode_index`) no entren al hash: una
inserció al mig els renumera tots (P10). La classe `_HashMatcher` té un
mètode per cada pas.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from diffengine.config import EngineConfig
from diffengine.load import NULL_TOKEN, NUMERIC, OPAQUE, Table, is_missing

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
    :ivar partial: per a cada parella, si s'ha fet sense totes les columnes
        (fila editada): la identitat és probable, no segura.
    """

    pairs: np.ndarray
    unmatched_old: np.ndarray
    unmatched_new: np.ndarray
    method: str
    key_columns: list[str] = field(default_factory=list)
    stable_columns: list[str] = field(default_factory=list)
    ambiguous_share: float = 0.0
    ambiguous: np.ndarray | None = None
    partial: np.ndarray | None = None

    @property
    def reliable_pairs(self) -> np.ndarray:
        """Parelles que no depenen de l'ordre d'ocurrència (per comparar valors)."""
        if self.ambiguous is None:
            return self.pairs
        return self.pairs[~self.ambiguous]

    @property
    def certain_pairs(self) -> np.ndarray:
        """Parelles no ambigües i fetes amb totes les columnes (per jutjar l'ordre)."""
        if self.partial is None:
            return self.reliable_pairs
        return self.pairs[~self.ambiguous & ~self.partial]

    @property
    def matched_share(self) -> float:
        total = len(self.pairs) + max(len(self.unmatched_old), len(self.unmatched_new))
        return len(self.pairs) / total if total else 1.0


def cell_tokens(table: Table, column: str) -> pd.Series:
    """Valor normalitzat d'una columna com a text, per comparar i fer hash."""
    s = table.values[column]
    if table.columns[column].kind == NUMERIC:
        return s.map(lambda v: NULL_TOKEN if pd.isna(v) else format(float(v), ".10g"))
    return s.map(lambda v: NULL_TOKEN if is_missing(v) else str(v))


def paired_values(table: Table, column: str, rows: np.ndarray) -> pd.Series:
    """Valors d'una columna a les files `rows`, reindexats 0..n (per comparar files aparellades)."""
    return table.values[column].iloc[rows].reset_index(drop=True)


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


def is_row_number(table: Table, column: str) -> bool:
    """La columna és la posició de la fila (0..n-1 o 1..n, en ordre), p.e. `index` de LeRobot."""
    if table.columns[column].kind != NUMERIC or not table.n_rows:
        return False
    x = table.values[column].to_numpy(float)
    return x[0] in (0.0, 1.0) and bool(np.array_equal(x, x[0] + np.arange(len(x))))


def is_sequence(table: Table, column: str) -> bool:
    """
    Enter no decreixent al llarg de les files (`index`, `episode_index`...):
    diu on és la fila, no quina és, i es renumera quan s'insereixen files.
    """
    if table.columns[column].kind != NUMERIC or table.n_rows < 2:
        return False
    x = table.values[column].to_numpy(float)
    return bool(not np.isnan(x).any() and table.columns[column].integer and np.all(np.diff(x) >= 0) and x[0] != x[-1])


def infer_key(old: Table, new: Table, matches: list[tuple[str, str]], config: EngineConfig) -> tuple[str, str] | None:
    """
    Una columna aparellada única, no nul·la i compartida a les dues versions.
    Un número de fila a totes dues no és una clau: només diu la posició, i es
    renumera quan s'afegeixen o s'eliminen files.
    """
    candidates = []
    for o, n in matches:
        if old.columns[o].kind == OPAQUE or (is_row_number(old, o) and is_row_number(new, n)):
            continue
        a, b = cell_tokens(old, o), cell_tokens(new, n)
        if (a == NULL_TOKEN).any() or (b == NULL_TOKEN).any():
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


def align_rows(old: Table, new: Table, matches: list[tuple[str, str]], config: EngineConfig) -> RowAlignment:
    """
    Aparella les files de `old` i `new`, per passos:

    1. Clau: una columna única compartida → unió per aquesta columna.
    2. Files idèntiques en les columnes estables (hash de fila).
    3. Files que difereixen en una sola columna estable (fila editada).
    4. Files que difereixen en dues columnes, entre les 6 que més canvien.
    5. Es descarten les parelles dubtoses que una columna opaca desmenteix.

    :param matches: columnes aparellades `(nom antic, nom nou)`.
    """
    key = infer_key(old, new, matches, config)
    if key is not None:
        return _align_by_key(old, new, key)
    matcher = _HashMatcher(old, new, matches, config)
    if not matcher.stable:
        return RowAlignment(np.empty((0, 2), int), np.arange(old.n_rows), np.arange(new.n_rows), "none")
    matcher.match_identical()
    matcher.match_edited_in_one_column()
    matcher.match_edited_in_two_columns()
    matcher.reject_contested_pairs()
    return matcher.result()


def _align_by_key(old: Table, new: Table, key: tuple[str, str]) -> RowAlignment:
    a = pd.Series(np.arange(old.n_rows), index=cell_tokens(old, key[0]).values)
    b = pd.Series(np.arange(new.n_rows), index=cell_tokens(new, key[1]).values)
    common = a.index.intersection(b.index)
    pairs = np.column_stack([a[common].values, b[common].values]) if len(common) else np.empty((0, 2), int)
    return RowAlignment(
        pairs=pairs, unmatched_old=np.setdiff1d(np.arange(old.n_rows), pairs[:, 0]),
        unmatched_new=np.setdiff1d(np.arange(new.n_rows), pairs[:, 1]), method="key", key_columns=[key[0]],
    )


def _row_hash(cells: dict[str, np.ndarray], n_rows: int) -> np.ndarray:
    """Suma (mod 2^64) dels hashes de les cel·les de cada fila."""
    if not cells:
        return np.zeros(n_rows, dtype=np.uint64)
    with np.errstate(over="ignore"):
        return np.sum(np.vstack(list(cells.values())), axis=0, dtype=np.uint64)


class _HashMatcher:
    """
    Aparellament per hash de fila. El hash d'una fila és la suma (mod 2^64) dels
    hashes de les seves cel·les, així que "la fila sense la columna c" és una resta.
    """

    def __init__(self, old: Table, new: Table, matches: list[tuple[str, str]], config: EngineConfig):
        self.old, self.new, self.config = old, new, config
        # Les seqüències (`index`, `episode_index`) queden fora del hash si en queden prou d'altres:
        # una inserció al mig les renumera a totes les files següents.
        positional = {o for o, n in matches if is_sequence(old, o) and is_sequence(new, n)}
        if len(matches) - len(positional) < 2:
            positional = set()
        self.tokens = {o: (cell_tokens(old, o), cell_tokens(new, n)) for o, n in matches if o not in positional}
        # Estables: columnes que conserven almenys la meitat dels valors (les transformades senceres no).
        stable = [o for o, (a, b) in self.tokens.items() if value_overlap(a, b) >= 0.5]
        self.stable = stable[: config.max_pairing_columns]
        self.cell_old = {c: _column_hash(self.tokens[c][0], i) for i, c in enumerate(self.stable)}
        self.cell_new = {c: _column_hash(self.tokens[c][1], i) for i, c in enumerate(self.stable)}
        self.row_old = _row_hash(self.cell_old, old.n_rows)
        self.row_new = _row_hash(self.cell_new, new.n_rows)
        self.pairs: list[tuple[int, int, bool, bool]] = []  # (fila antiga, fila nova, ambigua, parcial)
        self.free_old, self.free_new = np.arange(old.n_rows), np.arange(new.n_rows)

    def _without(self, columns: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
        h_old, h_new = self.row_old.copy(), self.row_new.copy()
        with np.errstate(over="ignore"):
            for c in columns:
                h_old -= self.cell_old[c]
                h_new -= self.cell_new[c]
        return h_old, h_new

    def _done(self) -> bool:
        return not len(self.free_old) or not len(self.free_new)

    def match_identical(self) -> None:
        self._match(self.row_old, self.row_new, partial=False)

    def match_edited_in_one_column(self) -> None:
        if len(self.stable) < 2:
            return
        # Primer la columna amb més parelles candidates: la que ha canviat de debò
        # en dona centenars; una coincidència casual en una altra, una o dues.
        def candidates(c: str) -> int:
            h_old, h_new = self._without((c,))
            return int(pd.Index(h_old[self.free_old]).isin(pd.Index(h_new[self.free_new])).sum())

        for c in sorted(self.stable, key=candidates, reverse=True):
            if self._done():
                return
            self._match(*self._without((c,)), partial=True)

    def match_edited_in_two_columns(self) -> None:
        if len(self.stable) < 4 or self._done():
            return
        # Només entre les 6 columnes que més canvien, per mantenir el cost acotat.
        changed = sorted(self.stable, key=lambda c: value_overlap(*self.tokens[c]))[:6]
        for i, c1 in enumerate(changed):
            for c2 in changed[i + 1:]:
                if self._done():
                    return
                self._match(*self._without((c1, c2)), partial=True)

    def _match(self, h_old: np.ndarray, h_new: np.ndarray, partial: bool) -> None:
        """Aparella les files lliures amb el mateix hash (les repetides, per ordre d'aparició)."""
        a = _with_occurrence(h_old[self.free_old]).assign(row=self.free_old)
        b = _with_occurrence(h_new[self.free_new]).assign(row=self.free_new)
        joined = a.merge(b, on=["h", "occ"], suffixes=("_o", "_n"))
        if partial and len(joined):
            joined = self._plausible_edits(joined, h_old, h_new)
        if not len(joined):
            return
        ambiguous = (joined["dup_o"] | joined["dup_n"]).tolist()
        self.pairs.extend(zip(joined["row_o"].tolist(), joined["row_n"].tolist(), ambiguous, [partial] * len(joined)))
        self.free_old = np.setdiff1d(self.free_old, joined["row_o"].to_numpy())
        self.free_new = np.setdiff1d(self.free_new, joined["row_n"].to_numpy())

    def _plausible_edits(self, joined: pd.DataFrame, h_old: np.ndarray, h_new: np.ndarray) -> pd.DataFrame:
        """Un aparellament parcial només s'accepta si no pot ser casualitat."""
        # La clau reduïda apareix el mateix nombre de cops a les dues taules
        # (una edició in situ no en canvia el recompte).
        count_old, count_new = pd.Series(h_old).value_counts(), pd.Series(h_new).value_counts()
        same_count = joined["h"].map(count_old).to_numpy() == joined["h"].map(count_new).fillna(0).to_numpy()
        joined = joined[same_count]
        # Molts més aparellaments que els esperats per atzar entre les files lliures.
        expected = len(self.free_old) * len(self.free_new) * _collision_rate(h_old)
        if len(joined) < max(1, 5 * expected):
            return joined.iloc[0:0]
        # P2: les dues files coincideixen en prou columnes estables.
        agree = np.zeros(len(joined))
        for c in self.stable:
            agree += self.cell_old[c][joined["row_o"].to_numpy()] == self.cell_new[c][joined["row_n"].to_numpy()]
        return joined[agree / len(self.stable) >= self.config.edited_row_min_agreement]

    def reject_contested_pairs(self) -> None:
        """
        Una parella ambigua es descarta si no coincideix en una columna opaca fora
        del hash (vector, imatge): cap transformació no ho pot explicar, així que
        el hash no identificava la fila (p.e. només `timestamp` i `frame_index`,
        que es repeteixen a cada episodi). Una diferència en una columna escalar
        sí que pot ser una transformació, i es manté.
        """
        unstable = [c for c in self.tokens if c not in self.stable and self.old.columns[c].kind == OPAQUE]
        contested = [(a, b) for a, b, ambiguous, _ in self.pairs if ambiguous]
        if not unstable or not contested:
            return
        ia, ib = np.array(contested).T
        agree = np.ones(len(contested), dtype=bool)
        for c in unstable:
            agree &= self.tokens[c][0].to_numpy()[ia] == self.tokens[c][1].to_numpy()[ib]
        rejected = {p for p, ok in zip(contested, agree) if not ok}
        if rejected:
            self.pairs = [p for p in self.pairs if (p[0], p[1]) not in rejected]
            self.free_old = np.union1d(self.free_old, [a for a, _ in rejected]).astype(int)
            self.free_new = np.union1d(self.free_new, [b for _, b in rejected]).astype(int)

    def result(self) -> RowAlignment:
        pairs = sorted(self.pairs)
        flags = np.array([(ambiguous, partial) for _, _, ambiguous, partial in pairs], dtype=bool).reshape(-1, 2)
        return RowAlignment(
            pairs=np.array([(a, b) for a, b, _, _ in pairs], dtype=int).reshape(-1, 2),
            unmatched_old=np.sort(self.free_old), unmatched_new=np.sort(self.free_new), method="hash",
            stable_columns=self.stable, ambiguous_share=float(flags[:, 0].sum()) / max(len(pairs), 1),
            ambiguous=flags[:, 0], partial=flags[:, 1],
        )
