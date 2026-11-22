"""Tests del pas 2 del motor: llegir una taula (`diffengine.load`)."""

import io
import os

import numpy as np
import pandas as pd
import pytest

from diffengine.load import CATEGORICAL, NUMERIC, OPAQUE, MixedColumns, ParseError, load_files, load_table


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


def _files(tmp_path, contents: dict[str, bytes]) -> list[str]:
    paths = []
    for name, data in contents.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
        paths.append(str(tmp_path / name))
    return paths


def test_files_of_a_dataset_are_read_in_order(tmp_path):
    table = load_files(_files(tmp_path, {"a_1.csv": b"x\n1\n2\n", "a_2.csv": b"x\n3\n"}))
    assert table.values["x"].tolist() == [1.0, 2.0, 3.0]
    assert table.columns["x"].integer


def test_files_with_different_columns_are_not_compared(tmp_path):
    """Decisió T-44: un CSV per any que afegeix una columna, o JSON amb camps opcionals (`pulsia/fr-bench-pdf2md`)."""
    with pytest.raises(MixedColumns):
        load_files(_files(tmp_path, {"y_2019.csv": b"id,a\n1,x\n", "y_2020.csv": b"id,a,b\n2,y,7\n"}))
    parts = {"t_0.parquet": parquet(pd.DataFrame({"a": [1, 2]})),
             "t_1.parquet": parquet(pd.DataFrame({"a": [3], "c": ["z"]}))}
    with pytest.raises(MixedColumns):
        load_files(_files(tmp_path, parts))


def test_the_same_columns_in_another_order_are_the_same_columns(tmp_path):
    table = load_files(_files(tmp_path, {"p_1.csv": b"id,a\n1,x\n", "p_2.csv": b"a,id\ny,2\n"}))
    assert table.values["id"].tolist() == [1.0, 2.0] and table.values["a"].tolist() == ["x", "y"]


def test_the_type_of_a_column_is_decided_with_every_file(tmp_path):
    # Al primer fitxer, `v` sembla numèrica; amb el segon, és de categories.
    table = load_files(_files(tmp_path, {"p_1.jsonl": b'{"v": 1}\n', "p_2.jsonl": b'{"v": "alt"}\n{"v": null}\n'}))
    assert table.columns["v"].kind == CATEGORICAL
    assert table.values["v"].tolist()[:2] == ["1", "alt"] and table.values["v"].isna().tolist() == [False, False, True]


def _questions(ids):
    return pd.DataFrame({"ID": [f"Q{i}" for i in ids], "PROMPT": [f"question {i}" for i in ids]})


def test_a_file_that_repeats_rows_of_a_bigger_one_is_not_read(tmp_path):
    """PDL-Bench v1: un fitxer per categoria (algunes preguntes en diverses) i `overall`, amb una pregunta pròpia."""
    parts = {"algebra.parquet": parquet(_questions([1, 2, 3])), "geometry.parquet": parquet(_questions([3, 4])),
             "overall.parquet": parquet(_questions([1, 2, 3, 4, 5]))}
    table = load_files(_files(tmp_path, parts))
    assert table.values["ID"].tolist() == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert [os.path.basename(p) for p in table.dropped_files] == ["algebra.parquet", "geometry.parquet"]


def test_of_two_identical_files_the_first_is_kept(tmp_path):
    table = load_files(_files(tmp_path, {"a/dev.jsonl": b'{"x": 1}\n{"x": 2}\n', "b/dev.jsonl": b'{"x": 1}\n{"x": 2}\n'}))
    assert table.n_rows == 2 and [os.path.basename(os.path.dirname(p)) for p in table.dropped_files] == ["b"]


def test_the_same_table_in_csv_and_parquet_is_read_once(tmp_path):
    df = pd.DataFrame({"id": [1, 2], "score": [0.5, 1.25], "name": ["ann", None]})
    table = load_files(_files(tmp_path, {"data.csv": b"id,score,name\n1,0.5,ann\n2,1.25,\n", "data.parquet": parquet(df)}))
    assert table.n_rows == 2 and [os.path.basename(p) for p in table.dropped_files] == ["data.parquet"]


def test_files_without_shared_rows_are_all_read(tmp_path):
    table = load_files(_files(tmp_path, {"p_1.csv": b"x\n1\n1\n", "p_2.csv": b"x\n2\n"}))
    assert table.values["x"].tolist() == [1.0, 1.0, 2.0]  # la repetició dins d'un fitxer es conserva
    assert table.dropped_files == ()


def test_files_of_different_formats_are_one_dataset(tmp_path):
    """Decisió T-44: cada format es prepara pel seu compte; les files segueixen l'ordre dels fitxers."""
    parts = {"p_1.csv": b"id,name\n1,ann\n", "p_2.parquet": parquet(pd.DataFrame({"id": [2], "name": ["bob"]})),
             "p_3.csv": b"id,name\n3,cat\n"}
    table = load_files(_files(tmp_path, parts))
    assert table.values["id"].tolist() == [1.0, 2.0, 3.0]
    assert table.values["name"].tolist() == ["ann", "bob", "cat"]
    assert table.columns["id"].kind == NUMERIC and table.columns["id"].integer
    assert table.fmt == "csv+parquet"


def test_a_column_with_different_types_in_two_formats_becomes_text(tmp_path):
    parts = {"a.csv": b"v\n1\n2\n", "b.jsonl": b'{"v": "x"}\n'}
    table = load_files(_files(tmp_path, parts))
    assert table.columns["v"].kind == CATEGORICAL
    assert table.values["v"].tolist() == ["1", "2", "x"]


def test_numbers_written_as_text_in_another_format_are_numbers(tmp_path):
    """Un CSV numèric i un JSON amb `"3"`: tots els valors són números, i la columna és numèrica."""
    table = load_files(_files(tmp_path, {"a.csv": b"v\n1\n2\n", "b.jsonl": b'{"v": "3"}\n{"v": null}\n'}))
    assert table.columns["v"].kind == NUMERIC and table.columns["v"].integer
    assert table.values["v"].iloc[:3].tolist() == [1.0, 2.0, 3.0] and np.isnan(table.values["v"].iloc[3])


def test_a_json_document_next_to_the_data_is_not_read(tmp_path):
    """run_11: `metadata.json`, `croissant.json` o `subtasks.json` al costat dels parquet no són taules."""
    parts = {"data/train.parquet": parquet(pd.DataFrame({"id": [1, 2]})),
             "metadata.json": b'{"name": "opera", "splits": ["train", "test"], "files": ["a", "b", "c"]}'}
    table = load_files(_files(tmp_path, parts))
    assert table.values["id"].tolist() == [1.0, 2.0]
    assert [os.path.basename(p) for p in table.dropped_files] == ["metadata.json"]


def test_a_json_document_alone_cannot_be_read(tmp_path):
    with pytest.raises(ParseError):
        load_files(_files(tmp_path, {"metadata.json": b'{"name": "opera", "splits": ["train", "test"], "files": ["a", "b", "c"]}'}))


def test_a_broken_data_file_is_still_a_parse_error(tmp_path):
    """Només es deixen de banda els documents JSON: un fitxer de dades que no es pot llegir no s'amaga."""
    parts = {"a.parquet": parquet(pd.DataFrame({"id": [1]})), "b.jsonl": b'{"id": 2\n'}
    with pytest.raises(ParseError):
        load_files(_files(tmp_path, parts))
