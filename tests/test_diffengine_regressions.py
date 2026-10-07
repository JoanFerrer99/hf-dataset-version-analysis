"""
Casos FP/FN coneguts del motor antic (prompt del motor v2), un test per cas.
Les decisions que en canvien l'expectativa són a `docs/open_decisions.md`
(C100 fora d'abast: cas 8; P8: cas 15; C530 sense target: casos 16 i 17).
Els casos 11 i 13 (fallada de descàrrega, dos fitxers) són de L0:
`tests/test_diffengine_pairs.py`.
"""

import io

import numpy as np
import pandas as pd
import pytest

from diffengine.engine import diff_bytes


def csv_bytes(df: pd.DataFrame, **kw) -> bytes:
    return df.to_csv(index=False, **kw).encode()


def parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def labels(old: bytes, new: bytes, old_ext=".csv", new_ext=".csv") -> set[tuple[str, str | None]]:
    """Etiquetes detectades. Comprova de pas que cap codi surt sense evidència ni confiança."""
    result = diff_bytes(old, old_ext, new, new_ext)
    for c in result.changes:
        assert c.evidence, f"{c.code} sense evidència"
        assert 0 < c.confidence <= 1, f"{c.code} amb confiança {c.confidence}"
    return {(c.code, c.subtype.split(":")[0] if c.subtype else None) for c in result.changes}


def codes(old: bytes, new: bytes, old_ext=".csv", new_ext=".csv") -> set[str]:
    return {code for code, _ in labels(old, new, old_ext, new_ext)}


@pytest.fixture
def base() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 400
    age = rng.integers(18, 80, n)
    return pd.DataFrame({
        "id": np.arange(n),
        "age": age,
        "score": np.round(age * 0.8 + rng.normal(0, 8, n), 3),
        "sex": rng.choice(["Male", "Female"], n),
        "workclass": rng.choice(["Private", "Gov", "Self", "Unknown"], n),
        "label": rng.choice(["no", "yes"], n, p=[0.8, 0.2]),
    })


def test_01_rename_with_recode_is_rename_plus_relabel(base):
    new = base.rename(columns={"sex": "is_male"})
    new["is_male"] = new["is_male"].map({"Male": "yes", "Female": "no"})
    got = labels(csv_bytes(base), csv_bytes(new))
    assert ("C223", None) in got and ("C312", "relabel") in got
    assert not {"C221", "C222"} & {c for c, _ in got}


def test_02_rename_with_identical_content_is_only_c223(base):
    assert codes(csv_bytes(base), csv_bytes(base.rename(columns={"workclass": "employment"}))) == {"C223"}


def test_03_shuffled_and_added_rows(base):
    extra = base.head(5).assign(id=lambda d: d["id"] + 10_000, age=33)
    new = pd.concat([base.sample(frac=1, random_state=1), extra])
    assert {"C410", "C421"} <= codes(csv_bytes(base), csv_bytes(new))


def test_04_same_count_removed_and_added_rows(base):
    extra = base.head(10).assign(id=lambda d: d["id"] + 5_000, score=1.0)
    new = pd.concat([base.iloc[10:], extra])
    got = codes(csv_bytes(base), csv_bytes(new))
    assert {"C421", "C422"} <= got


def test_05_edited_cells_are_column_changes_not_row_changes(base):
    new = base.copy()
    new.loc[:4, "age"] = new.loc[:4, "age"] + 1
    got = labels(csv_bytes(base), csv_bytes(new))
    assert ("C322", "cell_edits") in got
    assert not {"C421", "C422"} & {c for c, _ in got}


def test_06_int_column_gaining_nans_is_only_c510(base):
    new = base.copy()
    new["age"] = new["age"].astype(float)
    new.loc[:2, "age"] = np.nan
    assert codes(csv_bytes(base), csv_bytes(new)) == {"C510"}


def test_07_resaved_with_other_quoting_and_line_endings_is_nothing(base):
    assert codes(csv_bytes(base), csv_bytes(base, quoting=1, lineterminator="\r\n")) == set()


def test_08_csv_to_parquet_is_nothing_because_c100_is_out_of_scope(base):
    assert codes(csv_bytes(base), parquet_bytes(base), ".csv", ".parquet") == set()


def test_09_missing_token_change_is_c510_representation_only(base):
    old = base.copy()
    old.loc[:5, "workclass"] = np.nan
    got = labels(csv_bytes(old, na_rep="?"), csv_bytes(old, na_rep=""))
    assert got == {("C510", "representation")}


def test_10_stripped_whitespace_is_c312_representation(base):
    old = base.copy()
    old["workclass"] = " " + old["workclass"]
    assert labels(csv_bytes(old), csv_bytes(base)) == {("C312", "representation")}


def test_12_reorder_with_an_image_column_is_detected(base):
    old = base.copy()
    old["image"] = [{"bytes": bytes([i % 256, i // 256])} for i in range(len(old))]
    new = old.sample(frac=1, random_state=3).reset_index(drop=True)
    assert "C410" in codes(parquet_bytes(old), parquet_bytes(new), ".parquet", ".parquet")


def test_14_column_inserted_in_the_middle_is_c221_without_c210(base):
    new = base.copy()
    new.insert(2, "extra", np.random.default_rng(1).normal(size=len(base)).round(4))
    assert codes(csv_bytes(base), csv_bytes(new)) == {"C221"}


def test_14_swapped_columns_is_c210(base):
    new = base[["id", "sex", "age", "score", "workclass", "label"]]
    assert codes(csv_bytes(base), csv_bytes(new)) == {"C210"}


def test_15_standardized_feature_is_c322_without_c530(base):
    new = base.copy()
    new["score"] = ((new["score"] - new["score"].mean()) / new["score"].std()).round(6)
    got = labels(csv_bytes(base), csv_bytes(new))
    assert ("C322", "standardization") in got
    assert not {"C530", "C321"} & {c for c, _ in got}


def test_16_oversampled_minority_is_c421_duplicate_plus_c530(base):
    new = pd.concat([base, base[base["label"] == "yes"]], ignore_index=True)
    got = labels(csv_bytes(base), csv_bytes(new))
    assert ("C421", "duplicate_of_existing") in got
    assert "C530" in {c for c, _ in got}


def test_17_flipped_labels_for_a_subgroup(base):
    new = base.copy()
    mask = new["workclass"] == "Gov"
    new.loc[mask, "label"] = new.loc[mask, "label"].map({"yes": "no", "no": "yes"})
    got = codes(csv_bytes(base), csv_bytes(new))
    assert "C312" in got


def test_18_identical_content_has_status_and_no_codes(base):
    result = diff_bytes(csv_bytes(base), ".csv", csv_bytes(base), ".csv")
    assert result.status == "identical_content" and result.changes == []


def test_19_one_copy_of_a_duplicated_row_removed(base):
    old = pd.concat([base, base.iloc[[7]]], ignore_index=True)
    result = diff_bytes(csv_bytes(old), ".csv", csv_bytes(base), ".csv")
    c422 = [c for c in result.changes if c.code == "C422"]
    assert {c.code for c in result.changes} == {"C422"}
    assert sum(c.n_affected for c in c422) == 1


def test_20_new_categories_around_cardinality_threshold_is_not_a_type_change(base):
    rng = np.random.default_rng(2)
    old = base.copy()
    old["city"] = rng.choice([f"city_{i:02d}" for i in range(19)], len(old))
    new = old.copy()
    new.loc[[3, 9], "city"] = ["new_city_a", "new_city_b"]
    got = codes(csv_bytes(old), csv_bytes(new))
    assert not {"C311", "C321"} & got
    assert "C312" in got


def test_21_renumbered_row_index_is_not_a_key_nor_a_value_change():
    """LeRobot: `index` és la posició global del frame; inserir un episodi al mig el renumera."""
    rng = np.random.default_rng(1)

    def episode(ep):
        return pd.DataFrame({"episode_index": ep, "frame_index": np.arange(30),
                             "state": np.round(rng.normal(size=30), 4)})

    old = pd.concat([episode(e) for e in range(4)], ignore_index=True)
    new = pd.concat([old.iloc[:60], episode(9), old.iloc[60:]], ignore_index=True)
    old.insert(0, "index", np.arange(len(old)))
    new.insert(0, "index", np.arange(len(new)))
    got = labels(parquet_bytes(old), parquet_bytes(new), ".parquet", ".parquet")
    assert ("C421", "new") in got
    # Sense C322 (index renumerat), C410 ni C422 (files mal aparellades). C530 a
    # `episode_index` sí que hi és: apareix un episodi nou.
    assert {c for c, _ in got} <= {"C421", "C530"}


def _lerobot(episodes: list[int], lengths: list[int], seed: int) -> pd.DataFrame:
    """Taula tipus LeRobot: vectors opacs (`state`) i comptadors de posició."""
    rng = np.random.default_rng(seed)
    parts = []
    for ep, n in zip(episodes, lengths):
        parts.append(pd.DataFrame({
            "state": [rng.normal(size=3).round(4) for _ in range(n)],
            "timestamp": np.arange(n) / 10, "frame_index": np.arange(n), "episode_index": ep,
        }))
    df = pd.concat(parts, ignore_index=True)
    df["index"] = np.arange(len(df))
    return df


def test_22_episode_inserted_in_the_middle_renumbers_counters_but_rows_are_paired():
    """Cas real `stlee601/cube_pick1`: s'insereix un episodi i es renumeren `index` i `episode_index`."""
    old = _lerobot([0, 1, 2, 3], [40, 40, 40, 40], seed=0)
    inserted = _lerobot([0], [25], seed=9)
    new = pd.concat([old.iloc[:80], inserted, old.iloc[80:]], ignore_index=True)
    new["episode_index"] = np.repeat([0, 1, 2, 3, 4], [40, 40, 25, 40, 40])
    new["index"] = np.arange(len(new))
    got = labels(parquet_bytes(old), parquet_bytes(new), ".parquet", ".parquet")
    assert got == {("C421", "new"), ("C322", "renumbered")}


def test_23_re_recorded_table_is_not_paired_by_repeated_counters():
    """Cas real `nuoyihan/eval_lerobot-pick-red-pen`: mateixos comptadors, vectors nous."""
    old = _lerobot(list(range(6)), [50] * 6, seed=0)
    new = _lerobot(list(range(4)), [45] * 4, seed=1)
    got = labels(parquet_bytes(old), parquet_bytes(new), ".parquet", ".parquet")
    assert ("C422", "all_rows") in got and ("C421", "new") in got
    assert not {"C322", "C410"} & {c for c, _ in got}


def test_24_rename_on_another_sample_of_rows_is_c223():
    """Census D3: `fnlwgt` → `final_weight` en una altra mostra de files (part noves)."""
    rng = np.random.default_rng(3)

    def people(n):
        return pd.DataFrame({"age": rng.integers(18, 80, n), "sex": rng.choice(["Male", "Female"], n),
                             "fnlwgt": rng.integers(10_000, 30_000, n)})

    old = people(3000)
    new = pd.concat([old.sample(1500, random_state=1), people(700)], ignore_index=True)
    new = new.rename(columns={"fnlwgt": "final_weight"})
    got = labels(csv_bytes(old), csv_bytes(new))
    assert ("C223", None) in got
    assert not {"C221", "C222"} & {c for c, _ in got}


def test_25_null_rate_change_caused_only_by_removed_rows_is_still_c510(base):
    """Paper §4: C510 "can be a consequence of the addition/removal of rows. However, we consider them separately"."""
    old = base.copy()
    old.loc[old.index[::10], "workclass"] = None
    new = old.dropna(subset=["workclass"]).reset_index(drop=True)
    got = labels(csv_bytes(old), csv_bytes(new))
    assert ("C422", "had_nulls") in got
    assert ("C510", "rate") in got


def test_26_label_encoding_is_a_type_change_and_a_recoding(base):
    """Paper §4 i Taula 1 (D3/D4): categòriques codificades com a enters → C311 + C312."""
    new = base.copy()
    new["workclass"] = new["workclass"].map({"Private": 0, "Gov": 1, "Self": 2, "Unknown": 3})
    got = labels(csv_bytes(base), csv_bytes(new))
    assert ("C311", "to_numeric") in got and ("C312", "recoded") in got


def test_27_numbers_written_as_text_are_not_a_recoding(base):
    """Un canvi de format ("1" → 1) no canvia els valors del domini: sense C312."""
    old = base.assign(level=(base["age"] % 4).astype(str))  # parquet: text "0".."3"
    new = old.assign(level=old["level"].astype(int))
    got = labels(parquet_bytes(old), parquet_bytes(new), ".parquet", ".parquet")
    assert ("C311", "to_numeric") in got
    assert "C312" not in {c for c, _ in got}
