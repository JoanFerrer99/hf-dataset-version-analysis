"""
Pas 3a i 3c: aparellar les columnes de dues versions (quina columna nova és quina antiga).

1. Pel **nom**: exacte, i després normalitzat (`marital-status` =
   `marital.status`).
2. Les que queden sense parella, pel **contingut** sobre les files ja
   aparellades: valors idèntics, una correspondència u a u entre categories
   (`Male` → `True`), una transformació numèrica (×1000, logaritme…) o una
   codificació one-hot. Si la versió nova és una altra mostra de files, també
   val compartir la majoria de valors amb la mateixa distribució. Totes les
   parelles es trien alhora amb l'algorisme hongarès; el nom només desempata.
3. El que encara queda: columnes afegides (C221, `derived` si es poden
   calcular a partir d'una que ja hi era) i eliminades (C222).
"""

import difflib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from diffengine.config import EngineConfig
from diffengine.load import NUMERIC, OPAQUE, Table
from diffengine.rows import RowAlignment, cell_tokens, paired_values, value_overlap
from diffengine.transforms import distribution_distance, fit_numeric, is_bijection


@dataclass
class ColumnMatch:
    """
    :ivar method: `exact`, `normalized`, `identical`, `bijection`,
        `transform` (només els tres últims són renoms trobats per contingut).
    """

    old: str
    new: str
    method: str
    validity: float = 1.0
    detail: dict = field(default_factory=dict)


@dataclass
class ColumnAlignment:
    matches: list[ColumnMatch]
    removed: list[str]
    added: list[str]
    one_hot: list[dict] = field(default_factory=list)
    derived: dict[str, str] = field(default_factory=dict)
    removed_subtypes: dict[str, str] = field(default_factory=dict)

    def pairs(self) -> list[tuple[str, str]]:
        """
        :return: les parelles de columnes com a `(nom antic, nom nou)`.
        """
        return [(m.old, m.new) for m in self.matches]


def normalize_name(name) -> str:
    """
    Nom de columna en minúscules i sense separadors, per reconèixer el mateix nom
    escrit diferent (`marital-status` i `Marital.Status`).

    :param name: nom de la columna.
    :return: el nom normalitzat.
    """
    out = str(name).lower()
    for sep in ("-", "_", ".", " "):
        out = out.replace(sep, "")
    return out


def align_by_name(old: Table, new: Table) -> ColumnAlignment:
    """
    Aparella les columnes pel nom: primer el nom exacte, després el nom normalitzat.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :return: les parelles i les columnes que han quedat sense parella a cada versió.
    """
    old_cols, new_cols = list(old.values.columns), list(new.values.columns)
    matches = [ColumnMatch(c, c, "exact") for c in old_cols if c in set(new_cols)]
    removed = [c for c in old_cols if c not in set(new_cols)]
    added = [c for c in new_cols if c not in set(old_cols)]
    by_norm: dict[str, list[str]] = {}
    for c in added:
        by_norm.setdefault(normalize_name(c), []).append(c)
    for c in list(removed):
        candidates = by_norm.get(normalize_name(c), [])
        if candidates:
            target = candidates.pop(0)
            matches.append(ColumnMatch(c, target, "normalized"))
            removed.remove(c)
            added.remove(target)
    return ColumnAlignment(matches, removed, added)


def _score(old: Table, new: Table, o: str, n: str, rows: RowAlignment, config: EngineConfig) -> tuple[float, str, dict]:
    """
    Puntua si una columna eliminada i una d'afegida són la mateixa. Prova, en
    ordre: si tenen exactament els mateixos valors; si es corresponen fila a fila
    (mateixos valors, una transformació o una correspondència u a u); i si són
    una altra mostra de files amb els mateixos valors i distribució.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :param o: nom de la columna antiga.
    :param n: nom de la columna nova.
    :param rows: aparellament de files.
    :param config: llindars del motor.
    :return: `(puntuació, mètode, detall)`; puntuació 0 si no són la mateixa columna.
    """
    if old.columns[o].kind == OPAQUE or new.columns[n].kind == OPAQUE:
        return 0.0, "", {}
    ta_all, tb_all = cell_tokens(old, o), cell_tokens(new, n)
    many_values = min(ta_all.nunique(), tb_all.nunique()) >= 20
    if many_values:
        # Molts valors distints i el mateix multiconjunt: és la mateixa columna,
        # encara que les files no s'hagin pogut aparellar bé.
        overlap = value_overlap(ta_all, tb_all)
        if overlap >= config.column_match_min_validity:
            return overlap, "identical", {"by": "value_multiset"}
    found = _score_on_pairs(old, new, o, n, rows, config, ta_all, tb_all)
    if found[0] or not many_values:
        return found
    # Una altra mostra de files (p.e. Census D3): la majoria de valors distints
    # nous ja hi eren i la distribució no canvia segons el criteri de C530.
    shared = len(set(ta_all) & set(tb_all)) / tb_all.nunique()
    same_kind = (old.columns[o].kind == NUMERIC) == (new.columns[n].kind == NUMERIC)
    if same_kind and shared >= config.same_column_min_shared_values:
        distance, _, measure = distribution_distance(old.values[o].dropna(), new.values[n].dropna(),
                                                     old.columns[o].kind == NUMERIC)
        if distance < config.c530_min_distance:
            return shared, "same_distribution", {"shared_values": shared, measure: distance}
    return 0.0, "", {}


def _score_on_pairs(old: Table, new: Table, o: str, n: str, rows: RowAlignment, config: EngineConfig,
                    ta_all: pd.Series, tb_all: pd.Series) -> tuple[float, str, dict]:
    """
    Puntua dues columnes comparant-les fila a fila sobre les files aparellades.
    Si no hi ha prou files aparellades, compara les freqüències dels valors.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :param o: nom de la columna antiga.
    :param n: nom de la columna nova.
    :param rows: aparellament de files.
    :param config: llindars del motor.
    :param ta_all: valors de la columna antiga, com a text.
    :param tb_all: valors de la columna nova, com a text.
    :return: `(puntuació, mètode, detall)`; puntuació 0 si no ho semblen.
    """
    reliable = rows.reliable_pairs
    if len(reliable) >= 10:
        a_idx, b_idx = reliable[:, 0], reliable[:, 1]
        same = float(np.mean(ta_all.iloc[a_idx].to_numpy() == tb_all.iloc[b_idx].to_numpy()))
        if same >= config.column_match_min_validity:
            return same, "identical", {}
        x, y = paired_values(old, o, a_idx), paired_values(new, n, b_idx)
        if old.columns[o].kind == NUMERIC and new.columns[n].kind == NUMERIC:
            fit = fit_numeric(x.to_numpy(float), y.to_numpy(float), config.column_match_min_validity)
            if fit is not None:
                return fit.validity, "transform", {"fit": fit.kind, **fit.params}
        ok, validity = is_bijection(x, y, config.column_match_min_validity)
        if ok and x.nunique() > 1:
            return validity, "bijection", {}
        return 0.0, "", {}
    # Sense files aparellades: perfil de freqüències sense etiquetes + cardinalitat.
    fa = old.values[o].value_counts(normalize=True, dropna=False).sort_values().to_numpy()
    fb = new.values[n].value_counts(normalize=True, dropna=False).sort_values().to_numpy()
    if len(fa) == len(fb) and len(fa) > 1 and np.allclose(fa, fb, atol=0.01):
        return 0.9, "bijection", {"label_free": True}
    return 0.0, "", {}


def _binary_tokens(table: Table, column: str) -> pd.Series | None:
    """
    Si una columna només té valors 0/1 o vertader/fals, els converteix en 0 i 1.

    :param table: la taula.
    :param column: nom de la columna.
    :return: la columna amb 0 i 1, o `None` si no és binària.
    """
    t = cell_tokens(table, column)
    mapping = {"0": 0, "1": 1, "False": 0, "True": 1, "false": 0, "true": 1}
    if not t.isin(list(mapping)).all():
        return None
    return t.map(mapping)


def _find_one_hot(old: Table, new: Table, ca: ColumnAlignment, rows: RowAlignment, config: EngineConfig) -> None:
    """
    Busca columnes categòriques que s'han convertit en diverses columnes 0/1, una
    per categoria (one-hot). Les que troba es treuen de les pendents i es
    registren a `ca.one_hot`.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :param ca: aparellament de columnes (es modifica).
    :param rows: aparellament de files.
    :param config: llindars del motor.
    """
    reliable = rows.reliable_pairs
    if len(reliable) < 10:
        return
    a_idx, b_idx = reliable[:, 0], reliable[:, 1]
    dummies = {n: _binary_tokens(new, n) for n in ca.added}
    dummies = {n: d.iloc[b_idx].to_numpy() for n, d in dummies.items() if d is not None}
    for o in list(ca.removed):
        if old.columns[o].kind == NUMERIC or old.columns[o].kind == OPAQUE:
            continue
        values = paired_values(old, o, a_idx)
        categories = values.dropna().unique()
        if not 2 <= len(categories) <= 50:
            continue
        used = {}
        for v in categories:
            indicator = (values == v).to_numpy().astype(int)
            for n, d in dummies.items():
                if n not in used.values() and np.mean(d == indicator) >= config.column_match_min_validity:
                    used[v] = n
                    break
        if len(used) >= max(2, len(categories) - 1):
            ca.one_hot.append({"old": o, "new": list(used.values()), "categories": [str(k) for k in used]})
            ca.removed.remove(o)
            for n in used.values():
                ca.added.remove(n)
                dummies.pop(n)


def align_by_content(old: Table, new: Table, ca: ColumnAlignment, rows: RowAlignment,
                     config: EngineConfig) -> bool:
    """
    Aparella pel contingut les columnes eliminades i afegides que han quedat
    sense parella. Totes les parelles es trien alhora (algorisme hongarès) per
    maximitzar la puntuació total; la semblança del nom només desempata.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :param ca: aparellament de columnes (es modifica).
    :param rows: aparellament de files.
    :param config: llindars del motor.
    :return: `True` si ha trobat alguna parella nova.
    """
    found = False
    _find_one_hot(old, new, ca, rows, config)
    if ca.removed and ca.added:
        scores = np.zeros((len(ca.removed), len(ca.added)))
        details = {}
        for i, o in enumerate(ca.removed):
            for j, n in enumerate(ca.added):
                score, method, detail = _score(old, new, o, n, rows, config)
                if score:
                    name_sim = difflib.SequenceMatcher(None, str(o).lower(), str(n).lower()).ratio()
                    scores[i, j] = score + 1e-3 * name_sim
                    details[(i, j)] = (score, method, detail)
        if scores.any():
            ri, ci = linear_sum_assignment(-scores)
            accepted = [(i, j) for i, j in zip(ri, ci) if (i, j) in details]
            for i, j in accepted:
                score, method, detail = details[(i, j)]
                ca.matches.append(ColumnMatch(ca.removed[i], ca.added[j], method, score, detail))
            removed_i = {i for i, _ in accepted}
            added_j = {j for _, j in accepted}
            ca.removed = [c for i, c in enumerate(ca.removed) if i not in removed_i]
            ca.added = [c for j, c in enumerate(ca.added) if j not in added_j]
            found = bool(accepted)
    return found


def classify_leftovers(old: Table, new: Table, ca: ColumnAlignment, config: EngineConfig) -> None:
    """
    Explica les columnes que han quedat sense parella. Una afegida és `derived`
    si es pot calcular a partir d'una columna que ja hi era. Una eliminada és
    `mostly_null` (gairebé buida), `duplicate_of:<columna>` (repetia una altra) o
    `unexplained`. El resultat es desa a `ca.derived` i `ca.removed_subtypes`.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :param ca: aparellament de columnes (es modifica).
    :param config: llindars del motor.
    """
    kept_new = [m.new for m in ca.matches if new.columns[m.new].kind != OPAQUE]
    for n in ca.added:
        target = cell_tokens(new, n)
        if target.nunique() <= 1:
            continue
        for k in kept_new:
            source = cell_tokens(new, k)
            if source.nunique() <= 1:
                continue
            if source.nunique() < 0.5 * len(source):
                # Dependència funcional: cada valor de la font dona un sol valor nou.
                per_group = pd.DataFrame({"s": source, "t": target}).groupby("s")["t"].nunique()
                derived = (per_group <= 1).all() and target.nunique() <= source.nunique()
            elif new.columns[k].kind == NUMERIC:
                # Discretització d'una font contínua: cada valor nou ocupa un sol interval.
                t = target.to_numpy()[np.argsort(new.values[k].to_numpy(float), kind="stable")]
                derived = int(np.sum(t[1:] != t[:-1])) <= target.nunique() - 1
            else:
                derived = False
            if derived:
                ca.derived[n] = k
                break

    kept_old = [m.old for m in ca.matches]
    for o in ca.removed:
        if old.values[o].isna().mean() >= config.mostly_null_share:
            ca.removed_subtypes[o] = "mostly_null"
            continue
        tokens = cell_tokens(old, o)
        dup = next((k for k in kept_old if (cell_tokens(old, k) == tokens).all()), None)
        ca.removed_subtypes[o] = f"duplicate_of:{dup}" if dup is not None else "unexplained"


def order_changed(old: Table, new: Table, ca: ColumnAlignment) -> bool:
    """
    Diu si ha canviat l'ordre de les columnes que existeixen a totes dues versions.

    :param old: taula de la versió antiga.
    :param new: taula de la versió nova.
    :param ca: aparellament de columnes.
    :return: `True` si alguna columna ha canviat de posició respecte a les altres.
    """
    old_pos = {c: i for i, c in enumerate(old.values.columns)}
    new_pos = {c: i for i, c in enumerate(new.values.columns)}
    seq = [new_pos[m.new] for m in sorted(ca.matches, key=lambda m: old_pos[m.old])]
    return any(b < a for a, b in zip(seq, seq[1:]))
