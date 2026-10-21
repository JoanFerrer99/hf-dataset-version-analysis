"""Tests del pas 2 del motor: llegir una taula (`diffengine.load`)."""

import io

import numpy as np
import pandas as pd

from diffengine.load import CATEGORICAL, NUMERIC, OPAQUE, load_table


def parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def test_csv_missing_tokens_and_integer_column_with_gaps():
    t = load_table(b"id,age,wc\n1,30,Private\n2,,?\n3,41,Gov\n", ".csv")
    assert t.columns["age"].kind == NUMERIC and t.columns["age"].integer
    assert t.values["wc"].isna().tolist() == [False, True, False]


def test_parquet_string_nulls_and_tokens_become_nulls():
    df = pd.DataFrame({"wc": pd.Series(["Private", None, "?"], dtype="str"), "n": [1.0, np.nan, 3.0]})
    t = load_table(parquet(df), ".parquet")
    assert t.columns["wc"].kind == CATEGORICAL
    assert t.values["wc"].isna().tolist() == [False, True, True]
    assert t.columns["n"].integer


def test_space_after_every_separator_is_dialect_not_data():
    t = load_table(b"age, wc\n39, State-gov\n50, Private\n", ".csv")
    assert t.dialect["skipinitialspace"] is True
    assert t.values["wc"].tolist() == ["State-gov", "Private"]


def test_space_in_one_column_is_kept():
    rows = "".join(f"{i}, Private,{30 + i}\n" for i in range(30))
    t = load_table(("id,wc,age\n" + rows).encode(), ".csv")
    assert t.values["wc"].iloc[0] == " Private"


def test_semicolon_and_decimal_comma():
    t = load_table(b"a;b\n1,5;x\n2,25;y\n", ".csv")
    assert t.dialect["delimiter"] == ";"
    assert t.values["a"].tolist() == [1.5, 2.25]
    assert t.columns["a"].decimal_comma


def test_image_cells_are_opaque_and_deterministic():
    df = pd.DataFrame({"img": [{"bytes": b"\x00", "path": "a"}, {"path": "b", "bytes": b"\x01"}]})
    first = load_table(parquet(df), ".parquet")
    second = load_table(parquet(df), ".parquet")
    assert first.columns["img"].kind == OPAQUE
    assert first.values["img"].tolist() == second.values["img"].tolist()


def test_single_element_arrays_are_read_as_scalars():
    """LeRobot desa escalars com a arrays d'un element (`gripper_width`)."""
    df = pd.DataFrame({"gripper_width": [np.array([0.5]), np.array([np.nan]), np.array([0.25])],
                       "state": [np.array([1.0, 2.0])] * 3})
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    table = load_table(buf.getvalue(), ".parquet")
    assert table.columns["gripper_width"].kind == NUMERIC
    assert table.values["gripper_width"].isna().tolist() == [False, True, False]
    assert table.columns["state"].kind == OPAQUE


def test_single_element_arrays_that_are_all_nan_are_a_numeric_null_column():
    """`stlee601/cube_pick1`: `gripper_width` és `[nan]` a totes les files de la versió antiga."""
    df = pd.DataFrame({"gripper_width": [np.array([np.nan])] * 3})
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    table = load_table(buf.getvalue(), ".parquet")
    assert table.columns["gripper_width"].kind == NUMERIC
    assert table.values["gripper_width"].isna().all()
