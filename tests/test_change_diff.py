"""
Tests unitaris per a `notebooks/change_diff.py`.

Cobreixen el motor de diffing (funcions pures `diff_*`/`compute_all_
diffs`) i la capa de classificació (`classify_diffs`/`classify_file_
change`, fusionada des de l'antic `change_classifier.py`, setembre 2026),
amb `DataFrame` sintètics petits -- mai crides de xarxa
(`download_tabular_file_at_revision` no es testeja aquí, és un
embolcall prim de `hf_hub_download`/`errors.with_retry`, ja cobertes per
la resta del projecte).
"""

import pandas as pd

import change_diff as cd


class TestDiffColumns:
    def test_no_changes(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = cd.diff_columns(df, df.copy())
        assert result == {"added": [], "removed": [], "renamed": [], "order_changed": False}

    def test_added_column(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = cd.diff_columns(before, after)
        assert result["added"] == ["b"]
        assert result["removed"] == []
        assert result["renamed"] == []

    def test_removed_column(self):
        before = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        after = pd.DataFrame({"a": [1, 2]})
        result = cd.diff_columns(before, after)
        assert result["removed"] == ["b"]
        assert result["added"] == []

    def test_renamed_same_position_compatible_dtype(self):
        before = pd.DataFrame({"a": [1, 2], "old_name": [3, 4]})
        after = pd.DataFrame({"a": [1, 2], "new_name": [3, 4]})
        result = cd.diff_columns(before, after)
        assert result["renamed"] == [("old_name", "new_name")]
        assert result["added"] == []
        assert result["removed"] == []

    def test_remove_and_add_different_position_is_not_a_rename(self):
        before = pd.DataFrame({"a": [1], "old_name": [2], "c": [3]})
        after = pd.DataFrame({"a": [1], "c": [3], "new_name": [2]})
        result = cd.diff_columns(before, after)
        assert result["renamed"] == []
        assert result["removed"] == ["old_name"]
        assert result["added"] == ["new_name"]

    def test_remove_and_add_incompatible_dtype_is_not_a_rename(self):
        before = pd.DataFrame({"old_name": [1, 2]})
        after = pd.DataFrame({"new_name": ["x", "y"]})
        result = cd.diff_columns(before, after)
        assert result["renamed"] == []
        assert result["removed"] == ["old_name"]
        assert result["added"] == ["new_name"]

    def test_order_changed(self):
        before = pd.DataFrame({"a": [1], "b": [2]})
        after = pd.DataFrame({"b": [2], "a": [1]})
        result = cd.diff_columns(before, after)
        assert result["order_changed"] is True
        assert result["added"] == [] and result["removed"] == []


class TestDiffColumnTypes:
    def test_no_type_change(self):
        df = pd.DataFrame({"a": [1, 2]})
        assert cd.diff_column_types(df, df.copy()) == {}

    def test_numerical_type_change(self):
        before = pd.DataFrame({"a": pd.array([1, 2], dtype="int64")})
        after = pd.DataFrame({"a": pd.array([1.0, 2.0], dtype="float64")})
        result = cd.diff_column_types(before, after)
        assert result["a"]["kind"] == "numerical"
        assert result["a"]["before"] == "int64"
        assert result["a"]["after"] == "float64"

    def test_categorical_type_change(self):
        before = pd.DataFrame({"a": pd.Series(["x", "y"], dtype="object")})
        after = pd.DataFrame({"a": pd.Series(["x", "y"], dtype="category")})
        result = cd.diff_column_types(before, after)
        assert result["a"]["kind"] == "categorical"


class TestDiffCategoricalValues:
    def test_no_changes(self):
        df = pd.DataFrame({"a": ["x", "y"]})
        assert cd.diff_categorical_values(df, df.copy()) == {}

    def test_added_and_removed_categories(self):
        before = pd.DataFrame({"a": ["x", "y"]})
        after = pd.DataFrame({"a": ["x", "z"]})
        result = cd.diff_categorical_values(before, after)
        assert result["a"]["added"] == ["z"]
        assert result["a"]["removed"] == ["y"]

    def test_numeric_columns_are_ignored(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 3]})
        assert cd.diff_categorical_values(before, after) == {}

    def test_unhashable_values_are_skipped_not_crashed(self):
        # Columnes d'àudio/imatge llegides amb pandas.read_parquet sense
        # la decodificació de `datasets` arriben com a dict -- .unique()
        # hi llença TypeError: unhashable type: 'dict'. Confirmat en una
        # execució real sobre adalat-ai/fleurs-ro i theayos/libero_
        # spatial_image (ambdós datasets d'àudio/robòtica).
        before = pd.DataFrame({"audio": [{"bytes": b"a", "path": None}, {"bytes": b"b", "path": None}]})
        after = pd.DataFrame({"audio": [{"bytes": b"c", "path": None}, {"bytes": b"d", "path": None}]})
        assert cd.diff_categorical_values(before, after) == {}

    def test_unhashable_column_does_not_block_other_columns(self):
        before = pd.DataFrame({
            "audio": [{"bytes": b"a"}, {"bytes": b"b"}],
            "label": ["x", "y"],
        })
        after = pd.DataFrame({
            "audio": [{"bytes": b"c"}, {"bytes": b"d"}],
            "label": ["x", "z"],
        })
        result = cd.diff_categorical_values(before, after)
        assert "audio" not in result
        assert result["label"] == {"added": ["z"], "removed": ["y"]}


class TestDiffNumericValues:
    def test_no_changes(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        assert cd.diff_numeric_values(df, df.copy()) == {}

    def test_scale_change_detected(self):
        before = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        after = pd.DataFrame({"a": [10.0, 20.0, 30.0]})
        result = cd.diff_numeric_values(before, after)
        assert "a" in result
        assert result["a"]["mean_before"] == 2.0
        assert result["a"]["mean_after"] == 20.0

    def test_non_numeric_columns_are_ignored(self):
        before = pd.DataFrame({"a": ["x", "y"]})
        after = pd.DataFrame({"a": ["y", "x"]})
        assert cd.diff_numeric_values(before, after) == {}


class TestDiffRowCount:
    def test_same_count(self):
        before = pd.DataFrame({"a": [1, 2, 3]})
        after = pd.DataFrame({"a": [4, 5, 6]})
        result = cd.diff_row_count(before, after)
        assert result == {"before": 3, "after": 3, "delta": 0}

    def test_rows_added(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 2, 3]})
        result = cd.diff_row_count(before, after)
        assert result["delta"] == 1

    def test_rows_removed(self):
        before = pd.DataFrame({"a": [1, 2, 3]})
        after = pd.DataFrame({"a": [1]})
        result = cd.diff_row_count(before, after)
        assert result["delta"] == -2


class TestDiffRowOrder:
    def test_pure_reorder_detected(self):
        before = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        after = before.iloc[[2, 0, 1]].reset_index(drop=True)
        assert cd.diff_row_order(before, after) == {"reordered": True}

    def test_identical_order_is_not_reordered(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        assert cd.diff_row_order(df, df.copy()) == {"reordered": False}

    def test_different_row_count_is_never_reordered(self):
        # Ja el cobreixen C421/C422 -- barrejar-ho amb reordenació seria ambigu.
        before = pd.DataFrame({"a": [1, 2, 3]})
        after = pd.DataFrame({"a": [1, 2]})
        assert cd.diff_row_order(before, after) == {"reordered": False}

    def test_content_change_same_order_is_not_reordered(self):
        before = pd.DataFrame({"a": [1, 2, 3]})
        after = pd.DataFrame({"a": [1, 2, 99]})
        assert cd.diff_row_order(before, after) == {"reordered": False}

    def test_reorder_mixed_with_content_change_is_not_pure_reorder(self):
        # El multiset de contingut difereix -- no és una reordenació pura,
        # el canvi ja el reflecteixen els altres codis (p.e. C322).
        before = pd.DataFrame({"a": [1, 2, 3]})
        after = pd.DataFrame({"a": [3, 1, 99]})
        assert cd.diff_row_order(before, after) == {"reordered": False}

    def test_duplicate_rows_reordered_still_detected(self):
        before = pd.DataFrame({"a": [1, 1, 2]})
        after = pd.DataFrame({"a": [2, 1, 1]})
        assert cd.diff_row_order(before, after) == {"reordered": True}

    def test_reorder_confined_to_non_hashable_column_not_detected(self):
        # Limitació documentada: si les columnes hashables es mantenen en
        # la mateixa posició i la reordenació només afecta una columna no
        # hashable (p.e. bytes d'àudio), aquesta tècnica no ho detecta.
        before = pd.DataFrame({
            "id": [1, 2, 3],
            "audio": [{"bytes": b"a"}, {"bytes": b"b"}, {"bytes": b"c"}],
        })
        after = pd.DataFrame({
            "id": [1, 2, 3],
            "audio": [{"bytes": b"c"}, {"bytes": b"a"}, {"bytes": b"b"}],
        })
        assert cd.diff_row_order(before, after) == {"reordered": False}

    def test_all_columns_non_hashable_cannot_detect(self):
        before = pd.DataFrame({"audio": [{"bytes": b"a"}, {"bytes": b"b"}]})
        after = pd.DataFrame({"audio": [{"bytes": b"b"}, {"bytes": b"a"}]})
        assert cd.diff_row_order(before, after) == {"reordered": False}


class TestDiffMissingness:
    def test_no_change(self):
        df = pd.DataFrame({"a": [1, None, 3]})
        assert cd.diff_missingness(df, df.copy()) == {}

    def test_missingness_increased(self):
        before = pd.DataFrame({"a": [1, 2, 3, 4]})
        after = pd.DataFrame({"a": [1, None, None, 4]})
        result = cd.diff_missingness(before, after)
        assert result["a"]["before"] == 0.0
        assert result["a"]["after"] == 0.5


class TestDiffCorrelation:
    def test_fewer_than_two_numeric_columns(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = cd.diff_correlation(df, df.copy())
        assert result == {"changed": False, "max_abs_diff": 0.0}

    def test_correlation_change_detected(self):
        before = pd.DataFrame({"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]})
        after = pd.DataFrame({"a": [1, 2, 3, 4], "b": [4, 3, 2, 1]})
        result = cd.diff_correlation(before, after)
        assert result["changed"] is True
        assert result["max_abs_diff"] > 0.05

    def test_no_correlation_change(self):
        before = pd.DataFrame({"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]})
        after = pd.DataFrame({"a": [5, 6, 7, 8], "b": [5, 6, 7, 8]})
        result = cd.diff_correlation(before, after)
        assert result["changed"] is False

    def test_single_row_gives_undefined_correlation_without_warning(self, recwarn):
        # DataFrame.corr() amb una sola fila retorna NaN a tota la matriu
        # (correlació indefinida) -- no ha de llençar cap RuntimeWarning
        # (np.nanmax sobre una slice tota NaN) ni petar, i s'ha de tractar
        # com "sense canvi detectable".
        before = pd.DataFrame({"a": [1], "b": [2]})
        after = pd.DataFrame({"a": [1], "b": [2]})
        result = cd.diff_correlation(before, after)
        assert result == {"changed": False, "max_abs_diff": 0.0}
        assert len(recwarn) == 0


class TestDiffDistribution:
    def test_no_change(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
        assert cd.diff_distribution(df, df.copy()) == {}

    def test_numeric_distribution_shift_detected(self):
        before = pd.DataFrame({"a": list(range(1, 101))})
        after = pd.DataFrame({"a": list(range(500, 600))})
        result = cd.diff_distribution(before, after)
        assert "a" in result

    def test_categorical_frequency_shift_detected(self):
        before = pd.DataFrame({"a": ["x"] * 90 + ["y"] * 10})
        after = pd.DataFrame({"a": ["x"] * 10 + ["y"] * 90})
        result = cd.diff_distribution(before, after)
        assert "a" in result
        assert result["a"]["max_frequency_shift"] > 0.5

    def test_unhashable_values_are_skipped_not_crashed(self):
        before = pd.DataFrame({"audio": [{"bytes": b"a"}, {"bytes": b"b"}]})
        after = pd.DataFrame({"audio": [{"bytes": b"c"}, {"bytes": b"d"}]})
        assert cd.diff_distribution(before, after) == {}


class TestIsHashableSeries:
    def test_scalar_values_are_hashable(self):
        assert cd._is_hashable_series(pd.Series([1, "a", None])) is True

    def test_dict_values_are_not_hashable(self):
        assert cd._is_hashable_series(pd.Series([{"a": 1}, {"b": 2}])) is False

    def test_list_values_are_not_hashable(self):
        assert cd._is_hashable_series(pd.Series([[1, 2], [3, 4]])) is False

    def test_empty_series_is_hashable(self):
        assert cd._is_hashable_series(pd.Series([], dtype=object)) is True

    def test_all_null_series_is_hashable(self):
        assert cd._is_hashable_series(pd.Series([None, None])) is True


class TestComputeAllDiffs:
    def test_identical_dataframes_produce_no_signals(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result = cd.compute_all_diffs(df, df.copy())
        for code in cd.TABULAR_CODES:
            assert result[code] is False, f"{code} should be False"

    def test_reordered_rows_set_c410(self):
        before = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        after = before.iloc[[2, 0, 1]].reset_index(drop=True)
        result = cd.compute_all_diffs(before, after)
        assert result["C410"] is True
        assert result["C421"] is False and result["C422"] is False

    def test_added_row_sets_c421_not_c422(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 2, 3]})
        result = cd.compute_all_diffs(before, after)
        assert result["C421"] is True
        assert result["C422"] is False

    def test_removed_row_sets_c422_not_c421(self):
        before = pd.DataFrame({"a": [1, 2, 3]})
        after = pd.DataFrame({"a": [1]})
        result = cd.compute_all_diffs(before, after)
        assert result["C422"] is True
        assert result["C421"] is False

    def test_added_column_sets_c221(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = cd.compute_all_diffs(before, after)
        assert result["C221"] is True
        assert result["C222"] is False

    def test_details_key_present(self):
        df = pd.DataFrame({"a": [1, 2]})
        result = cd.compute_all_diffs(df, df.copy())
        assert "_details" in result
        assert set(result["_details"].keys()) == {
            "columns", "types", "categorical_values", "numeric_values",
            "rows", "rows_order", "missingness", "correlation", "distribution",
        }


def _no_signals() -> dict:
    """Diccionari de `compute_all_diffs` amb tots els codis sense senyal."""
    return {code: False for code in cd.TABULAR_CODES}


class TestClassifyDiffs:
    def test_no_signals_produces_no_labels(self):
        labels = cd.classify_diffs(_no_signals(), "ds", "v1", "v2")
        assert labels == []

    def test_single_signal_produces_one_label(self):
        diffs = _no_signals()
        diffs["C221"] = True
        labels = cd.classify_diffs(diffs, "ds", "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C221"
        assert labels[0].dataset_id == "ds"
        assert labels[0].version_from == "v1"
        assert labels[0].version_to == "v2"

    def test_breaking_code_flagged(self):
        diffs = _no_signals()
        diffs["C223"] = True  # renom -- a BREAKING_CODES
        labels = cd.classify_diffs(diffs, "ds", "v1", "v2")
        assert labels[0].is_breaking is True

    def test_non_breaking_code_not_flagged(self):
        diffs = _no_signals()
        diffs["C421"] = True  # afegir fila -- NO a BREAKING_CODES
        labels = cd.classify_diffs(diffs, "ds", "v1", "v2")
        assert labels[0].is_breaking is False

    def test_c410_signal_produces_a_breaking_label(self):
        diffs = _no_signals()
        diffs["C410"] = True
        labels = cd.classify_diffs(diffs, "ds", "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C410"
        assert labels[0].is_breaking is True

    def test_multiple_signals_produce_multiple_labels(self):
        diffs = _no_signals()
        diffs["C221"] = True
        diffs["C510"] = True
        labels = cd.classify_diffs(diffs, "ds", "v1", "v2")
        codes = {label.code for label in labels}
        assert codes == {"C221", "C510"}

    def test_never_produces_c100(self):
        # C100 (metadada) esta deliberadament fora d'abast del
        # classificador -- no hi ha cap via per generar-lo.
        diffs = _no_signals()
        for code in diffs:
            diffs[code] = True
        labels = cd.classify_diffs(diffs, "ds", "v1", "v2")
        assert all(label.code != "C100" for label in labels)

    def test_classifier_never_receives_a_target_column_parameter(self):
        # Regla de disseny obligatòria de la taxonomia: el classificador
        # no ha de saber quina columna és el target -- verificat aquí
        # amb introspecció de la signatura, no només documentació.
        import inspect

        params = inspect.signature(cd.classify_diffs).parameters
        assert "target" not in params
        assert "target_column" not in params


class TestClassifyFileChange:
    def test_both_none_produces_no_labels(self):
        assert cd.classify_file_change("ds", None, None, "v1", "v2") == []

    def test_added_file_produces_c421(self):
        after = pd.DataFrame({"a": [1, 2]})
        labels = cd.classify_file_change("ds", None, after, "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C421"
        assert labels[0].is_breaking is False

    def test_removed_file_produces_c422(self):
        before = pd.DataFrame({"a": [1, 2]})
        labels = cd.classify_file_change("ds", before, None, "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C422"
        assert labels[0].is_breaking is False

    def test_both_present_delegates_to_compute_all_diffs_and_classify_diffs(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        labels = cd.classify_file_change("ds", before, after, "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C221"
