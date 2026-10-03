"""
Motor de diffing i classificador de canvis entre dues revisions d'un
fitxer tabular (taxonomia: `docs/taiga/taxonomy.md`).

  - Diffing (`diff_*`, `compute_all_diffs`): funcions pures que reben dos
    `DataFrame` i retornen fets estructurals.
  - Classificació (`classify_diffs`, `classify_file_change`): tradueix
    aquests fets a etiquetes `ChangeLabel` (codi + `is_breaking`).

Cobreix els 14 codis tabulars; C100 (metadada) queda fora d'abast.
L'únic cridant és `eligibility_scan.classify_dataset`.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

import errors

log = logging.getLogger(__name__)

# Codis que trenquen l'EXECUCIÓ d'un pipeline que llegeix per nom/posició/
# tipus/ordre; no mesura l'impacte en la qualitat del model.
BREAKING_CODES = frozenset({"C210", "C222", "C223", "C311", "C321", "C410"})

TABULAR_CODES = (
    "C210", "C221", "C222", "C223", "C311", "C312", "C321", "C322",
    "C410", "C421", "C422", "C510", "C520", "C530",
)

CODE_DESCRIPTIONS: dict[str, str] = {
    "C210": "Ordre de columnes",
    "C221": "Afegir columna",
    "C222": "Eliminar columna",
    "C223": "Renombrar columna",
    "C311": "Tipus de columna categòrica",
    "C312": "Valors d'una columna categòrica",
    "C321": "Tipus de columna numèrica",
    "C322": "Valors d'una columna numèrica",
    "C410": "Ordre de files",
    "C421": "Afegir fila",
    "C422": "Eliminar fila",
    "C510": "Missings",
    "C520": "Correlacions",
    "C530": "Distribució de les dades",
}

TABULAR_EXTENSIONS = (".parquet", ".csv", ".tsv")


def is_tabular_path(path: str) -> bool:
    """
    :param path: ruta relativa dins del repositori.
    :return: `True` si és `.parquet`/`.csv`/`.tsv`, l'únic tipus que es compara.
    """
    return path.lower().endswith(TABULAR_EXTENSIONS)


def download_tabular_file_at_revision(
    repo_id: str, path: str, revision: str, hf_token: str | None, retry_config: dict,
) -> pd.DataFrame | None:
    """
    Descarrega un fitxer tabular a una revisió concreta i el carrega
    sencer amb pandas.

    :param repo_id: dataset (`owner/name`).
    :param path: ruta del fitxer dins del repositori.
    :param revision: SHA del commit.
    :param hf_token: token HF.
    :param retry_config: configuració de reintent del cridant.
    :return: el `DataFrame`, o `None` si el fitxer no existeix en aquesta
        revisió o no es pot descarregar/llegir (no es propaga l'error).
    """
    try:
        local_path = errors.with_retry(
            hf_hub_download, repo_id=repo_id, repo_type="dataset", filename=path, revision=revision,
            token=hf_token, **retry_config,
        )
    except Exception as exc:
        log.debug(f"download_tabular_file_at_revision: no disponible {repo_id}@{revision}:{path}: {exc}")
        return None
    try:
        if local_path.endswith(".parquet"):
            return pd.read_parquet(local_path)
        return pd.read_csv(local_path, sep="\t" if local_path.endswith(".tsv") else ",")
    except Exception as exc:
        log.debug(f"download_tabular_file_at_revision: lectura fallida {repo_id}@{revision}:{path}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Motor de diffing -- funcions pures
# ---------------------------------------------------------------------------


def _dtypes_compatible(dtype_a, dtype_b) -> bool:
    """Mateixa família de tipus (numèric amb numèric, no-numèric amb no-numèric)."""
    return pd.api.types.is_numeric_dtype(dtype_a) == pd.api.types.is_numeric_dtype(dtype_b)


def _normalize_column_name(name: str) -> str:
    """
    Minúscules i sense `-`/`_`/`.`/espai. Només absorbeix diferències de
    separador (`capital-gain` == `capital_gain`), sense similitud de text.
    """
    normalized = str(name).lower()
    for sep in ("-", "_", ".", " "):
        normalized = normalized.replace(sep, "")
    return normalized


def diff_columns(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Compara el conjunt i l'ordre de columnes (C210, C221, C222, C223).

    Una columna eliminada i una afegida compten com a renom només si tenen
    el mateix nom normalitzat i dtype de la mateixa família. Els renoms
    semàntics (`sex` -> `is_male`) surten com a eliminada + afegida.

    :return: `added`, `removed` (sense els renoms), `renamed` (llista de
        `(nom_abans, nom_després)`) i `order_changed` (ordre de les
        columnes que es mantenen).
    """
    cols_before = list(before.columns)
    cols_after = list(after.columns)
    set_before, set_after = set(cols_before), set(cols_after)

    added = [c for c in cols_after if c not in set_before]
    removed = [c for c in cols_before if c not in set_after]

    added_by_normalized: dict[str, list[str]] = {}
    for col in added:
        added_by_normalized.setdefault(_normalize_column_name(col), []).append(col)

    renamed: list[tuple[str, str]] = []
    matched_added: set[str] = set()
    for col in removed:
        for candidate in added_by_normalized.get(_normalize_column_name(col), []):
            if candidate in matched_added:
                continue
            if _dtypes_compatible(before[col].dtype, after[candidate].dtype):
                renamed.append((col, candidate))
                matched_added.add(candidate)
                break

    renamed_before = {r[0] for r in renamed}
    renamed_after = {r[1] for r in renamed}
    added = [c for c in added if c not in renamed_after]
    removed = [c for c in removed if c not in renamed_before]

    common_before = [c for c in cols_before if c in set_after and c not in renamed_before]
    common_after = [c for c in cols_after if c in set_before and c not in renamed_after]
    order_changed = common_before != common_after

    return {"added": added, "removed": removed, "renamed": renamed, "order_changed": order_changed}


def diff_column_types(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Dtype canviat a les columnes comunes (C311, C321).

    :return: per columna canviada: `before`, `after` (`str(dtype)`) i
        `kind` (`"categorical"`/`"numerical"`, segons el dtype d'abans).
    """
    common = [c for c in before.columns if c in after.columns]
    changes = {}
    for col in common:
        dtype_before, dtype_after = before[col].dtype, after[col].dtype
        if str(dtype_before) != str(dtype_after):
            kind = "numerical" if pd.api.types.is_numeric_dtype(dtype_before) else "categorical"
            changes[col] = {"before": str(dtype_before), "after": str(dtype_after), "kind": kind}
    return changes


def _is_hashable_series(series: pd.Series) -> bool:
    """
    `True` si els valors de la columna són hashables (necessari per a
    `.unique()`/`.value_counts()`). Les columnes d'àudio/imatge arriben com
    a `dict` i no ho són. Només mira el primer valor no nul.
    """
    sample = series.dropna()
    if sample.empty:
        return True
    try:
        hash(sample.iloc[0])
        return True
    except TypeError:
        return False


def diff_categorical_values(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Categories noves o desaparegudes a les columnes no numèriques comunes
    (C312). Salta les columnes no hashables.

    :return: per columna canviada: `added`, `removed` (ordenades).
    """
    common = [c for c in before.columns if c in after.columns]
    changes = {}
    for col in common:
        if pd.api.types.is_numeric_dtype(before[col]) or pd.api.types.is_numeric_dtype(after[col]):
            continue
        if not (_is_hashable_series(before[col]) and _is_hashable_series(after[col])):
            log.debug(f"diff_categorical_values: columna '{col}' amb valors no hashables, ignorada")
            continue
        values_before = set(before[col].dropna().unique())
        values_after = set(after[col].dropna().unique())
        added = values_after - values_before
        removed = values_before - values_after
        if added or removed:
            changes[col] = {"added": sorted(map(str, added)), "removed": sorted(map(str, removed))}
    return changes


def diff_numeric_values(before: pd.DataFrame, after: pd.DataFrame, threshold: float = 0.05) -> dict:
    """
    Canvi de `mean`/`std`/`min`/`max` a les columnes numèriques comunes
    (C322), amb tolerància relativa i absoluta `threshold`.

    :param threshold: tolerància; per sota es considera soroll de coma flotant.
    :return: per columna canviada: mitjana, mínim i màxim abans/després.
    """
    common = [c for c in before.columns if c in after.columns]
    changes = {}
    for col in common:
        if not (pd.api.types.is_numeric_dtype(before[col]) and pd.api.types.is_numeric_dtype(after[col])):
            continue
        stats_before = before[col].agg(["mean", "std", "min", "max"])
        stats_after = after[col].agg(["mean", "std", "min", "max"])
        if not np.allclose(stats_before.to_numpy(dtype=float), stats_after.to_numpy(dtype=float),
                            rtol=threshold, atol=threshold, equal_nan=True):
            changes[col] = {
                "mean_before": float(stats_before["mean"]), "mean_after": float(stats_after["mean"]),
                "min_before": float(stats_before["min"]), "min_after": float(stats_after["min"]),
                "max_before": float(stats_before["max"]), "max_after": float(stats_after["max"]),
            }
    return changes


def diff_row_count(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Nombre de files (C421 si creix, C422 si decreix). Sense un ID de fila
    estable només se'n pot saber el signe del canvi, no quines files.

    :return: `before`, `after`, `delta`.
    """
    n_before, n_after = len(before), len(after)
    return {"before": n_before, "after": n_after, "delta": n_after - n_before}


def diff_row_order(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Reordenació pura de files (C410): mateix multiset de hashes per fila
    (`hash_pandas_object` sobre les columnes hashables comunes) però en un
    altre ordre.

    Només detecta reordenació PURA: si a més hi ha qualsevol altre canvi de
    contingut, o el nombre de files difereix, retorna `False`.

    :return: `reordered` (`bool`).
    """
    if len(before) != len(after):
        return {"reordered": False}

    common = [c for c in before.columns if c in after.columns]
    hashable = [c for c in common if _is_hashable_series(before[c]) and _is_hashable_series(after[c])]
    if not hashable:
        return {"reordered": False}

    hashes_before = pd.util.hash_pandas_object(before[hashable].reset_index(drop=True), index=False).to_numpy()
    hashes_after = pd.util.hash_pandas_object(after[hashable].reset_index(drop=True), index=False).to_numpy()

    if np.array_equal(hashes_before, hashes_after):
        return {"reordered": False}
    return {"reordered": bool(np.array_equal(np.sort(hashes_before), np.sort(hashes_after)))}


def diff_missingness(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Proporció de nuls canviada a les columnes comunes (C510).

    :return: per columna canviada: `before`, `after` (proporció [0, 1]).
    """
    common = [c for c in before.columns if c in after.columns]
    changes = {}
    for col in common:
        rate_before = float(before[col].isna().mean())
        rate_after = float(after[col].isna().mean())
        if abs(rate_before - rate_after) > 1e-9:
            changes[col] = {"before": rate_before, "after": rate_after}
    return changes


def diff_correlation(before: pd.DataFrame, after: pd.DataFrame, threshold: float = 0.05) -> dict:
    """
    Canvi a la matriu de correlació de Pearson de les columnes numèriques
    comunes (C520).

    :param threshold: diferència absoluta mínima entre algun parell de columnes.
    :return: `changed` i `max_abs_diff` (`0.0` si hi ha menys de 2 columnes
        numèriques o la correlació no està definida).
    """
    common_numeric = [
        c for c in before.columns
        if c in after.columns and pd.api.types.is_numeric_dtype(before[c]) and pd.api.types.is_numeric_dtype(after[c])
    ]
    if len(common_numeric) < 2:
        return {"changed": False, "max_abs_diff": 0.0}

    corr_before = before[common_numeric].corr()
    corr_after = after[common_numeric].corr()
    diff = (corr_before - corr_after).abs()
    valid_diffs = diff.to_numpy()
    valid_diffs = valid_diffs[~np.isnan(valid_diffs)]
    max_diff = float(valid_diffs.max()) if valid_diffs.size else 0.0
    return {"changed": max_diff > threshold, "max_abs_diff": max_diff}


def diff_distribution(before: pd.DataFrame, after: pd.DataFrame, threshold: float = 0.05) -> dict:
    """
    Canvi de distribució a les columnes comunes (C530): quartils per a les
    numèriques, freqüència relativa per categoria per a la resta.

    :param threshold: tolerància relativa (numèriques) o desplaçament
        absolut de freqüència (categòriques).
    :return: per columna canviada, els quartils o el desplaçament màxim.
    """
    common = [c for c in before.columns if c in after.columns]
    changes = {}
    for col in common:
        if pd.api.types.is_numeric_dtype(before[col]) and pd.api.types.is_numeric_dtype(after[col]):
            q_before = before[col].quantile([0.25, 0.5, 0.75]).to_numpy(dtype=float)
            q_after = after[col].quantile([0.25, 0.5, 0.75]).to_numpy(dtype=float)
            if not np.allclose(q_before, q_after, rtol=threshold, atol=threshold, equal_nan=True):
                changes[col] = {"quantiles_before": q_before.tolist(), "quantiles_after": q_after.tolist()}
        elif _is_hashable_series(before[col]) and _is_hashable_series(after[col]):
            freq_before = before[col].value_counts(normalize=True)
            freq_after = after[col].value_counts(normalize=True)
            common_categories = freq_before.index.intersection(freq_after.index)
            if len(common_categories) == 0:
                continue
            max_shift = float((freq_before[common_categories] - freq_after[common_categories]).abs().max())
            if max_shift > threshold:
                changes[col] = {"max_frequency_shift": max_shift}
        else:
            log.debug(f"diff_distribution: columna '{col}' amb valors no hashables, ignorada")
    return changes


def compute_all_diffs(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Executa totes les funcions `diff_*` i en tradueix el resultat a un
    booleà per codi.

    :return: una clau per codi (`"C210"`...`"C530"`) amb valor `bool`, més
        `"_details"` amb la sortida completa de cada `diff_*`.
    """
    columns = diff_columns(before, after)
    types = diff_column_types(before, after)
    categorical_values = diff_categorical_values(before, after)
    numeric_values = diff_numeric_values(before, after)
    rows = diff_row_count(before, after)
    rows_order = diff_row_order(before, after)
    missingness = diff_missingness(before, after)
    correlation = diff_correlation(before, after)
    distribution = diff_distribution(before, after)

    categorical_types = {c: d for c, d in types.items() if d["kind"] == "categorical"}
    numerical_types = {c: d for c, d in types.items() if d["kind"] == "numerical"}

    return {
        "C210": columns["order_changed"],
        "C221": bool(columns["added"]),
        "C222": bool(columns["removed"]),
        "C223": bool(columns["renamed"]),
        "C311": bool(categorical_types),
        "C312": bool(categorical_values),
        "C321": bool(numerical_types),
        "C322": bool(numeric_values),
        "C410": rows_order["reordered"],
        "C421": rows["delta"] > 0,
        "C422": rows["delta"] < 0,
        "C510": bool(missingness),
        "C520": correlation["changed"],
        "C530": bool(distribution),
        "_details": {
            "columns": columns, "types": types, "categorical_values": categorical_values,
            "numeric_values": numeric_values, "rows": rows, "rows_order": rows_order,
            "missingness": missingness, "correlation": correlation, "distribution": distribution,
        },
    }


# ---------------------------------------------------------------------------
# Classificació. Regla de la taxonomia: mai es fa servir quina columna és
# el target del pipeline.
# ---------------------------------------------------------------------------


@dataclass
class ChangeLabel:
    """
    Un codi de la taxonomia detectat entre dues revisions d'un dataset.

    :ivar dataset_id: dataset.
    :ivar version_from: SHA de la revisió anterior.
    :ivar version_to: SHA de la revisió posterior.
    :ivar code: codi (`"C210"`...`"C530"`).
    :ivar is_breaking: `True` si el codi és a `BREAKING_CODES`.
    """

    dataset_id: str
    version_from: str
    version_to: str
    code: str
    is_breaking: bool


def classify_diffs(diffs: dict, dataset_id: str, version_from: str, version_to: str) -> list[ChangeLabel]:
    """
    Converteix cada codi amb senyal de `compute_all_diffs` en un `ChangeLabel`.

    :param diffs: sortida de `compute_all_diffs`.
    :return: un `ChangeLabel` per codi detectat.
    """
    return [
        ChangeLabel(dataset_id, version_from, version_to, code, is_breaking=code in BREAKING_CODES)
        for code in TABULAR_CODES
        if diffs.get(code)
    ]


def classify_file_change(
    dataset_id: str,
    before_df: pd.DataFrame | None,
    after_df: pd.DataFrame | None,
    version_from: str,
    version_to: str,
) -> list[ChangeLabel]:
    """
    Classifica el canvi d'un fitxer tabular entre dues revisions.

    :param before_df: contingut abans, o `None` si el fitxer no existia.
    :param after_df: contingut després, o `None` si s'ha eliminat.
    :return: `[]` si tots dos són `None`; `C421` si el fitxer és nou;
        `C422` si s'ha eliminat; si no, el resultat de
        `classify_diffs(compute_all_diffs(...))`.
    """
    if before_df is None and after_df is None:
        return []
    if before_df is None:
        return [ChangeLabel(dataset_id, version_from, version_to, "C421", is_breaking=False)]
    if after_df is None:
        return [ChangeLabel(dataset_id, version_from, version_to, "C422", is_breaking=False)]

    diffs = compute_all_diffs(before_df, after_df)
    return classify_diffs(diffs, dataset_id, version_from, version_to)
