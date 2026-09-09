"""
Motor de diffing de canvis estructurals/de contingut entre dues revisions
d'un dataset (US-305, `docs/taiga/taxonomy.md`).

Funcions pures reutilitzades pel classificador (`change_classifier.py`):
totes les `diff_*` prenen dos `pandas.DataFrame` i retornen fets
estructurals, sense saber res de codis C1XX-C5XX ni de com s'han adquirit
els `DataFrame` -- aquesta separació és la que permet cridar-les des de
`eligibility_scan.classify_dataset` (població real, `classify_changes=
True`) sense cap acoblament amb l'origen de les dades.

Aquest mòdul NO tracta C100 (metadada) -- és fora de l'abast d'una
comparació tabular, i el projecte ha decidit no classificar-lo (vegeu
`docs/decisions_tfg.txt`).

Nota històrica: el motor es va validar contra el ground truth Census
Income del paper del director (US-304) abans d'integrar-se a la
població real -- aquella validació (adquisició D0-D7, comparació amb la
Taula 1 del paper) va ser un exercici puntual, ja fet i documentat a
`docs/architecture.md`/`docs/decisions_tfg.txt` (T-07/T-08/T-09), i no es
manté com a codi viu aquí.
"""

import logging

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

import errors

log = logging.getLogger(__name__)

RETRY_CONFIG: dict = {
    "max_retries": errors.DEFAULT_MAX_RETRIES,
    "base_wait_s": errors.DEFAULT_BASE_WAIT_S,
    "max_wait_s": errors.DEFAULT_MAX_WAIT_S,
}

TABULAR_CODES = (
    "C210", "C221", "C222", "C223", "C311", "C312", "C321", "C322",
    "C410", "C421", "C422", "C510", "C520", "C530",
)

TABULAR_EXTENSIONS = (".parquet", ".csv", ".tsv")


def is_tabular_path(path: str) -> bool:
    """
    :param path: ruta relativa dins del repositori.
    :return: `True` si l'extensió és a `TABULAR_EXTENSIONS` -- NOMÉS
        aquests formats es diferencien a nivell de contingut (columnes,
        files, valors); la resta (àudio/vídeo/tensors) no té concepte de
        "columna" i queda fora de l'abast d'aquest motor.
    """
    return path.lower().endswith(TABULAR_EXTENSIONS)


def download_tabular_file_at_revision(
    repo_id: str, path: str, revision: str, hf_token: str | None
) -> pd.DataFrame | None:
    """
    Baixa i carrega UN fitxer tabular concret d'un dataset a una revisió
    (SHA de commit) concreta. És la funció d'adquisició que fa servir
    `eligibility_scan.classify_dataset` (població real, intra-repositori)
    per obtenir el "abans"/"després" a comparar.

    :param repo_id: identificador del dataset (`owner/name`).
    :param path: ruta relativa del fitxer dins del repositori.
    :param revision: SHA del commit a llegir.
    :param hf_token: token HF.
    :return: `DataFrame`, o `None` si el fitxer no existeix en aquesta
        revisió (afegit/eliminat entre les dues que es comparen, 404 --
        no reintentat per `errors.with_retry`, és una condició
        permanent) o si la descàrrega/lectura falla per qualsevol altre
        motiu després d'esgotar els reintents (429/transitori) -- es
        registra amb `log.debug`, no es repropaga: el cridant ho tracta
        com "sense contingut per diferenciar" (vegeu `change_classifier.
        classify_file_change`), no com un error fatal per a tot el dataset.
    """
    try:
        local_path = errors.with_retry(
            hf_hub_download, repo_id=repo_id, repo_type="dataset", filename=path, revision=revision,
            token=hf_token, **RETRY_CONFIG,
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
# Motor de diffing -- funcions pures, mai rutes/HTTP dins d'aquestes
# ---------------------------------------------------------------------------


def _dtypes_compatible(dtype_a, dtype_b) -> bool:
    """Mateixa família de tipus (numèric amb numèric, no-numèric amb no-numèric)."""
    return pd.api.types.is_numeric_dtype(dtype_a) == pd.api.types.is_numeric_dtype(dtype_b)


def diff_columns(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Compara el conjunt i l'ordre de columnes de dues instantànies.

    Detecció de renom (C223): NO hi ha cap tècnica purament estructural
    que distingeixi un renom d'un remove+add sense heurística -- aquí
    s'aplica una d'explícita i documentada: una columna eliminada i una
    afegida es tracten com a renom NOMÉS si ocupen la MATEIXA posició
    ordinal a `before`/`after` i tenen dtype de la mateixa família
    (numèric amb numèric, no-numèric amb no-numèric). Qualsevol altre cas
    de columna eliminada+afegida es reporta per separat (`added`/
    `removed`), no com a renom -- limitació coneguda, no un error.

    :param before: instantània anterior.
    :param after: instantània posterior.
    :return: `dict` amb `added`/`removed` (`list[str]`, després de
        descartar-ne les detectades com a renom), `renamed`
        (`list[tuple[str, str]]`, `(nom_abans, nom_després)`) i
        `order_changed` (`bool`, sobre les columnes que es mantenen a
        totes dues, ignorant les afegides/eliminades).
    """
    cols_before = list(before.columns)
    cols_after = list(after.columns)
    set_before, set_after = set(cols_before), set(cols_after)

    added = [c for c in cols_after if c not in set_before]
    removed = [c for c in cols_before if c not in set_after]

    renamed: list[tuple[str, str]] = []
    for i, col in enumerate(cols_before):
        if col not in removed or i >= len(cols_after):
            continue
        candidate = cols_after[i]
        if candidate in added and _dtypes_compatible(before[col].dtype, after[candidate].dtype):
            renamed.append((col, candidate))

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
    Compara el dtype de cada columna present a totes dues instantànies.

    :return: `dict[str, dict]` una entrada per columna amb dtype canviat,
        amb `before`/`after` (`str(dtype)`) i `kind` (`"categorical"` o
        `"numerical"`, segons el dtype ABANS).
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
    Comprova si els valors d'una columna són hashables -- necessari per
    `.unique()`/`.value_counts()`. Columnes amb valors ESTRUCTURATS
    (`dict`/`list`, típic de columnes d'àudio/imatge llegides amb
    `pandas.read_parquet` sense la decodificació especial de la
    llibreria `datasets` -- p.e. `{"bytes": ..., "path": ...}`) no ho
    són. Es tracten com "opaques": excloses de la comparació de
    categories/distribució (`diff_categorical_values`/`diff_
    distribution`), però no de missingness/dtype/recompte de files, que
    no necessiten hashabilitat.

    :param series: columna a comprovar (es mira només el primer valor no
        nul, per eficiència -- assumeix tipus homogeni dins la columna,
        garantit per `pandas`/Arrow).
    :return: `True` si és buida (sense valors no nuls) o si el primer
        valor no nul és hashable; `False` si `hash()` hi llença
        `TypeError`.
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
    Compara el conjunt de categories (valors únics) de cada columna NO
    numèrica present a totes dues instantànies.

    :return: `dict[str, dict]` una entrada per columna amb categories
        afegides/eliminades, amb `added`/`removed` (`list[str]`, ordenats).
        Les columnes amb valors no hashables (`_is_hashable_series`) es
        salten -- registrat amb `log.debug`, no es tracten com un error.
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


def diff_numeric_values(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Compara estadístics bàsics (mitjana, desviació, mínim, màxim) de cada
    columna numèrica present a totes dues instantànies -- detecta canvis
    d'escala/rang (p.e. normalització), no substitueix `diff_distribution`.

    :return: `dict[str, dict]` una entrada per columna amb algun estadístic
        canviat, amb els 4 estadístics `before`/`after`.
    """
    common = [c for c in before.columns if c in after.columns]
    changes = {}
    for col in common:
        if not (pd.api.types.is_numeric_dtype(before[col]) and pd.api.types.is_numeric_dtype(after[col])):
            continue
        stats_before = before[col].agg(["mean", "std", "min", "max"])
        stats_after = after[col].agg(["mean", "std", "min", "max"])
        if not np.allclose(stats_before.to_numpy(dtype=float), stats_after.to_numpy(dtype=float),
                            rtol=1e-9, atol=1e-9, equal_nan=True):
            changes[col] = {
                "mean_before": float(stats_before["mean"]), "mean_after": float(stats_after["mean"]),
                "min_before": float(stats_before["min"]), "min_after": float(stats_after["min"]),
                "max_before": float(stats_before["max"]), "max_after": float(stats_after["max"]),
            }
    return changes


def diff_row_count(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Compara el nombre de files. Sense un identificador d'instància estable,
    NO es pot atribuir un canvi de recompte a "files afegides" vs "files
    eliminades" amb certesa -- només al signe del delta -- limitació
    coneguda, documentada aquí i no amagada.

    :return: `dict` amb `before`/`after` (`int`), `delta` (`after - before`).
    """
    n_before, n_after = len(before), len(after)
    return {"before": n_before, "after": n_after, "delta": n_after - n_before}


def diff_missingness(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Compara la proporció de valors absents de cada columna present a
    totes dues instantànies.

    :return: `dict[str, dict]` una entrada per columna amb la proporció
        canviada, amb `before`/`after` (`float`, [0, 1]).
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
    Compara la matriu de correlació de les columnes numèriques presents a
    totes dues instantànies (Pearson, `DataFrame.corr()`).

    :param threshold: diferència absoluta mínima, entre qualsevol parell
        de columnes, perquè es consideri un canvi de correlació.
    :return: `dict` amb `changed` (`bool`) i `max_abs_diff` (`float`,
        `0.0` si hi ha menys de 2 columnes numèriques comunes, o si la
        correlació és indefinida a totes dues bandes -- p.e. una sola
        fila, o columnes de variància zero -- `DataFrame.corr()` hi
        retorna NaN a tota la matriu; es tracta com "sense canvi
        detectable" en lloc de deixar que `np.nanmax` llenci un
        `RuntimeWarning` per una slice tota NaN).
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
    Compara la distribució de cada columna present a totes dues
    instantànies -- quartils (Q1/mediana/Q3) per a columnes numèriques,
    freqüència relativa per categoria per a columnes no numèriques. NO fa
    servir cap test estadístic (p.e. Kolmogorov-Smirnov, `scipy`) per no
    introduir una dependència nova només per a aquesta comprovació
    heurística.

    :param threshold: canvi relatiu mínim (numèriques) o absolut mínim
        (categòriques) perquè es consideri un canvi de distribució.
    :return: `dict[str, dict]` una entrada per columna amb distribució
        canviada.
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
    Combina totes les funcions `diff_*` i tradueix els fets estructurals a
    un senyal per codi de la taxonomia (14 codis tabulars -- C100 queda
    fora, és inspecció de dataset card/README, no una comparació tabular).

    :return: `dict` amb una clau per codi (`"C210"`, ..., `"C530"`) i valor
        `bool` (`None` per a `"C410"`, no detectable de forma fiable sense
        garantir que l'adquisició preserva l'ordre original de les files),
        més `"_details"` amb la sortida completa de cada `diff_*`.
    """
    columns = diff_columns(before, after)
    types = diff_column_types(before, after)
    categorical_values = diff_categorical_values(before, after)
    numeric_values = diff_numeric_values(before, after)
    rows = diff_row_count(before, after)
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
        "C410": None,
        "C421": rows["delta"] > 0,
        "C422": rows["delta"] < 0,
        "C510": bool(missingness),
        "C520": correlation["changed"],
        "C530": bool(distribution),
        "_details": {
            "columns": columns, "types": types, "categorical_values": categorical_values,
            "numeric_values": numeric_values, "rows": rows, "missingness": missingness,
            "correlation": correlation, "distribution": distribution,
        },
    }
