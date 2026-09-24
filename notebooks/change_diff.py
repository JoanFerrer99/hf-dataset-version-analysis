"""
Motor de diffing i classificació de canvis estructurals/de contingut
entre dues revisions d'un dataset (US-305, `docs/taiga/taxonomy.md`).

Dues capes en un mateix mòdul (fusionades des de l'antic `change_
classifier.py`, setembre 2026 -- eren dos fitxers separats sense cap
altre cridant que `eligibility_scan.py`, i la capa d'etiquetatge ja
llegia directament l'estructura interna d'aquest mòdul, així que la
"separació de responsabilitats" no aportava res un cop trimat el codi
mort):
  - **Diffing** (`diff_*`/`compute_all_diffs`): funcions pures, prenen
    dos `pandas.DataFrame` i retornen fets estructurals, sense saber res
    de codis C1XX-C5XX ni de com s'han adquirit els `DataFrame`.
  - **Classificació** (`classify_diffs`/`classify_file_change`): tradueix
    els fets estructurals a etiquetes `ChangeLabel` (codi + `is_breaking`).

Aquest mòdul NO tracta C100 (metadada) -- és fora de l'abast d'una
comparació tabular, i el projecte ha decidit no classificar-lo (vegeu
`docs/decisions_tfg.txt`).

Cridat per `eligibility_scan.classify_dataset` (`classify_changes=True`),
l'únic cridant real d'aquest mòdul.

Nota històrica: el motor es va validar contra el ground truth Census
Income del paper del director (US-304) abans d'integrar-se a la
població real -- aquella validació (adquisició D0-D7, comparació amb la
Taula 1 del paper) va ser un exercici puntual, ja fet i documentat a
`docs/architecture.md`/`docs/decisions_tfg.txt` (T-07/T-08/T-09), i no es
manté com a codi viu aquí.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

import errors

log = logging.getLogger(__name__)

BREAKING_CODES = frozenset({"C210", "C222", "C223", "C311", "C321", "C410"})

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
    repo_id: str, path: str, revision: str, hf_token: str | None, retry_config: dict,
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
    :param retry_config: mateix format que `errors.DEFAULT_RETRY_CONFIG`
        -- es rep com a paràmetre explícit (aquest mòdul no té CLI pròpia
        ni un `RETRY_CONFIG` propi) perquè el cridant (`eligibility_
        scan.py`) hi pugui propagar els seus propis `--retry-*`.
    :return: `DataFrame`, o `None` si el fitxer no existeix en aquesta
        revisió (afegit/eliminat entre les dues que es comparen, 404 --
        no reintentat per `errors.with_retry`, és una condició
        permanent) o si la descàrrega/lectura falla per qualsevol altre
        motiu després d'esgotar els reintents (429/transitori) -- es
        registra amb `log.debug`, no es repropaga: el cridant ho tracta
        com "sense contingut per diferenciar" (vegeu `classify_file_
        change`), no com un error fatal per a tot el dataset.
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
# Motor de diffing -- funcions pures, mai rutes/HTTP dins d'aquestes
# ---------------------------------------------------------------------------


def _dtypes_compatible(dtype_a, dtype_b) -> bool:
    """Mateixa família de tipus (numèric amb numèric, no-numèric amb no-numèric)."""
    return pd.api.types.is_numeric_dtype(dtype_a) == pd.api.types.is_numeric_dtype(dtype_b)


def _normalize_column_name(name: str) -> str:
    """
    Nom de columna normalitzat per a la detecció de renom (Decisió T-16):
    minúscules, sense `-`/`_`/`.`/espai. NOMÉS diferències de separador
    -- `"capital-gain"` i `"capital_gain"` normalitzen igual, però
    `"education-num"` i `"educational-num"` NO (calen 2 caràcters de
    diferència real, no només de separador) -- deliberadament NO es fa
    servir similitud de text aproximada (p.e. distància de Levenshtein),
    per evitar aparellar columnes NOMÉS semblants textualment però no
    relacionades.
    """
    normalized = str(name).lower()
    for sep in ("-", "_", ".", " "):
        normalized = normalized.replace(sep, "")
    return normalized


def diff_columns(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Compara el conjunt i l'ordre de columnes de dues instantànies.

    Detecció de renom (C223, Decisió T-16): NO hi ha cap tècnica
    purament estructural que distingeixi un renom d'un remove+add sense
    heurística -- aquí s'aplica una d'explícita i documentada: una
    columna eliminada i una afegida es tracten com a renom NOMÉS si el
    seu NOM NORMALITZAT (`_normalize_column_name`, insensible a `-`/`_`/
    `.`/espai) coincideix EXACTAMENT i tenen dtype de la mateixa família.

    NO es fa servir la posició ordinal (heurística anterior, substituïda
    a la Decisió T-16): afegir o eliminar una columna ABANS d'una
    columna renombrada desplaça la posició de TOTES les columnes
    següents, fent que una comparació per posició aparelli columnes NO
    relacionades amb el mateix dtype -- confirmat empíricament sobre
    Census Income (`docs/census_income_validation_report.md`): l'engine
    anterior aparellava `fnlwgt`->`capital_loss` i `education-num`->
    `final_weight` a D3 NOMÉS perquè compartien posició per casualitat
    després que altres columnes es reordenessin, no perquè hi hagués cap
    relació real entre elles.

    Qualsevol altre cas de columna eliminada+afegida (nom normalitzat
    diferent, p.e. `"sex"`->`"is_male"`, `"income"`->`"Y"`) es reporta
    per separat (`added`/`removed`), no com a renom -- limitació coneguda
    i irreductible sense informació semàntica externa, no un error.

    :param before: instantània anterior.
    :param after: instantània posterior.
    :return: `dict` amb `added`/`removed` (`list[str]`, després de
        descartar-ne les detectades com a renom), `renamed`
        (`list[tuple[str, str]]`, `(nom_abans, nom_després)`) i
        `order_changed` (`bool`, sobre les columnes que es mantenen a
        totes dues, ignorant les afegides/eliminades/renombrades).
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


def diff_row_order(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Detecta si les files s'han reordenat entre dues instantànies amb el
    MATEIX contingut exacte (mateix nombre de files, mateix multiset de
    valors) -- un canvi que pot passar desapercebut a la resta de
    `diff_*` (cap valor/columna/estadístic canvia) però que pot afectar
    pipelines d'ML que accedeixen a les dades per posició (p.e.
    `dataset[i]`), potencialment requerint adaptació als components
    d'ingesta o preprocessament.

    Tècnica: hash de contingut per fila (`pandas.util.hash_pandas_object`),
    calculat NOMÉS sobre el subconjunt de columnes hashables (columnes amb
    valors `dict`/`list` -- típic d'àudio/imatge, vegeu `_is_hashable_
    series` -- se salten, igual que a `diff_categorical_values`/`diff_
    distribution`). Si el MULTISET de hashes coincideix a totes dues
    bandes però la seqüència original difereix, és una reordenació PURA
    detectada amb certesa -- una comparació exacta, no una heurística.
    L'adquisició (`download_tabular_file_at_revision`, `pandas.
    read_parquet`/`read_csv` sense cap `sort`/`reindex` implícit) ja
    preserva l'ordre original del fitxer; el que calia resoldre no era
    l'adquisició, sinó distingir "reordenat" de "contingut diferent"
    sense un ID d'instància estable -- exactament el que fa aquesta
    comparació de multiset.

    :param before: instantània anterior.
    :param after: instantània posterior.
    :return: `dict` amb `reordered` (`bool`). Sempre `False` si el nombre
        de files difereix (ja cobert per `diff_row_count`/C421-C422 --
        barrejar-ho amb reordenació seria ambigu) o si totes les columnes
        comunes són no hashables (no hi ha res sobre què calcular el hash).
        LIMITACIÓ CONEGUDA (documentada, no amagada): només detecta
        reordenació PURA -- si també hi ha addicions/eliminacions/
        modificacions de contingut al mateix parell de versions, o si la
        reordenació només afecta columnes NO hashables (p.e. bytes
        d'àudio) mentre les columnes hashables es mantenen en la mateixa
        posició, `reordered` és `False` encara que hi hagi hagut un canvi
        d'ordre real.
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
        `bool`, més `"_details"` amb la sortida completa de cada `diff_*`.
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
# Classificació -- tradueix els fets estructurals de compute_all_diffs a
# etiquetes de codi (C210-C530). Regla de disseny de la taxonomia
# (obligatòria): NO usa informació de quina columna és el target del
# pipeline -- cap funció d'aquest bloc en rep cap paràmetre.
# ---------------------------------------------------------------------------


@dataclass
class ChangeLabel:
    """
    Una etiqueta de canvi: un codi de taxonomia detectat entre dues
    instantànies d'UN dataset.

    :ivar dataset_id: identificador del dataset.
    :ivar version_from: etiqueta de la versió anterior (SHA de commit).
    :ivar version_to: etiqueta de la versió posterior (SHA de commit).
    :ivar code: codi de la taxonomia (`"C210"`...`"C530"`).
    :ivar is_breaking: `True` si el codi és a `BREAKING_CODES`.
    """

    dataset_id: str
    version_from: str
    version_to: str
    code: str
    is_breaking: bool


def classify_diffs(diffs: dict, dataset_id: str, version_from: str, version_to: str) -> list[ChangeLabel]:
    """
    Tradueix els fets estructurals de `compute_all_diffs` a etiquetes de
    codi (C210-C530). NO recalcula res -- només llegeix els booleans ja
    calculats i hi afegeix `is_breaking`.

    `is_breaking` és una heurística PRÒPIA d'aquest estudi (el paper no
    en defineix cap de formal) -- "breaking" = un canvi que probablement
    trenca un pipeline que llegeix el dataset per nom/posició/tipus sense
    adaptar-se: C210 (ordre de columnes), C222 (eliminar columna), C223
    (renom), C311/C321 (canvi de tipus), C410 (ordre de files -- pot
    afectar pipelines que hi accedeixen per posició). La resta (afegir
    columna/fila, canvis de valors/distribució/correlació/missings) es
    marquen `is_breaking=False` -- poden afectar la qualitat del model,
    però no fan fallar un pipeline que simplement llegeix el dataset.

    :param diffs: sortida de `compute_all_diffs(before, after)`.
    :param dataset_id: identificador del dataset.
    :param version_from: SHA del commit anterior.
    :param version_to: SHA del commit posterior.
    :return: llista de `ChangeLabel`, una per codi amb senyal detectat
        (`diffs[code]` truthy).
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
    Classifica el canvi d'UN fitxer tabular concret entre dues revisions
    -- usada per `eligibility_scan.classify_dataset` (`classify_changes=
    True`) per a cada fitxer tabular (`is_tabular_path`) que canvia en
    un commit substantiu.

    :param dataset_id: identificador del dataset.
    :param before_df: contingut del fitxer a la revisió anterior, o
        `None` si el fitxer no hi existia (acabat d'afegir).
    :param after_df: contingut a la revisió posterior, o `None` si el
        fitxer ha estat eliminat.
    :param version_from: SHA del commit anterior.
    :param version_to: SHA del commit posterior.
    :return: si `before_df`/`after_df` són tots dos `None`, `[]`. Si
        NOMÉS un dels dos és `None` (fitxer afegit o eliminat sencer),
        UNA etiqueta aproximada (`C421` si afegit, `C422` si eliminat) --
        sense verificar-ho a nivell de fila (no hi ha ID d'instància
        estable entre fitxers/chunks, limitació ja documentada a
        `diff_row_count`). Si tots dos existeixen, el resultat de
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
