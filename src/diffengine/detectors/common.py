"""El que comparteixen tots els detectors: el context de la comparació i com es crea un canvi."""

from dataclasses import dataclass, field

import pandas as pd

from diffengine.columns import ColumnAlignment, ColumnMatch
from diffengine.config import EngineConfig
from diffengine.load import NUMERIC, OPAQUE, Table
from diffengine.output import Change
from diffengine.rows import RowAlignment, is_identifier_like, is_row_number, is_sequence, paired_values


@dataclass
class Context:
    """
    Les dues taules ja aparellades, més anotacions que uns detectors deixen per als següents.

    :ivar identifiers: columnes que identifiquen files (no són variables: fora de C520/C530).
    :ivar row_numbers: columnes que són la posició de la fila (fora també de C322).
    :ivar explained: columnes que una transformació explica (C322) → P8, sense C530.
    :ivar relabeled: mapatge de les columnes reetiquetades, per comparar-ne la distribució.
    :ivar representation: columnes que només canvien de format (espais, majúscules).
    :ivar kind_changed: columnes que canvien de tipus: no se'n comparen els valors.
    :ivar c510_columns: columnes amb cel·les que passen de nul a valor o al revés.
    """

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
        """Valors de la columna a les files aparellades (vell, nou), alineats."""
        pairs = self.rows.pairs
        return paired_values(self.old, m.old, pairs[:, 0]), paired_values(self.new, m.new, pairs[:, 1])

    def comparable(self, m: ColumnMatch) -> bool:
        """Es poden comparar cel·la a cel·la: mateix tipus, ni opaca ni número de fila."""
        ko, kn = self.old.columns[m.old], self.new.columns[m.new]
        return (m.old not in self.kind_changed and m.old not in self.row_numbers
                and OPAQUE not in (ko.kind, kn.kind) and family(ko.kind) == family(kn.kind))


def family(kind: str) -> str:
    """`numeric`, `categorical` (inclou text) o `opaque`."""
    return "numeric" if kind == NUMERIC else ("opaque" if kind == OPAQUE else "categorical")


def change(code: str, m: ColumnMatch | None = None, **kw) -> Change:
    """Crea un `Change`; amb `m`, hi posa la columna nova i l'antiga si s'ha reanomenat."""
    if m is not None:
        kw.setdefault("column", m.new)
        kw.setdefault("old_column", m.old if m.old != m.new else None)
    return Change(code, **kw)


def find_identifiers(ctx: Context) -> None:
    """
    Marca les columnes que identifiquen files i no són variables: la clau, les
    que tenen nom d'identificador i valors únics, els números de fila i les
    seqüències (p.e. `episode_index`).
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
