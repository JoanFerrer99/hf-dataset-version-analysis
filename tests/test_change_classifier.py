"""
Tests unitaris per a `notebooks/change_classifier.py`.

Cobreixen NOMÉS la capa d'etiquetatge (`classify_diffs`, `classify_file_
change`), amb fets sintètics -- mai crides de xarxa.
"""

import pandas as pd

import change_classifier as cc
import change_diff as cd


def _no_signals() -> dict:
    """Diccionari de `compute_all_diffs` amb tots els codis sense senyal."""
    return {code: (None if code == "C410" else False) for code in cd.TABULAR_CODES}


class TestClassifyDiffs:
    def test_no_signals_produces_no_labels(self):
        labels = cc.classify_diffs(_no_signals(), "ds", "v1", "v2")
        assert labels == []

    def test_single_signal_produces_one_label(self):
        diffs = _no_signals()
        diffs["C221"] = True
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C221"
        assert labels[0].dataset_id == "ds"
        assert labels[0].version_from == "v1"
        assert labels[0].version_to == "v2"

    def test_breaking_code_flagged(self):
        diffs = _no_signals()
        diffs["C223"] = True  # renom -- a BREAKING_CODES
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2")
        assert labels[0].is_breaking is True

    def test_non_breaking_code_not_flagged(self):
        diffs = _no_signals()
        diffs["C421"] = True  # afegir fila -- NO a BREAKING_CODES
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2")
        assert labels[0].is_breaking is False

    def test_c410_none_never_produces_a_label(self):
        diffs = _no_signals()
        assert diffs["C410"] is None
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2")
        assert all(label.code != "C410" for label in labels)

    def test_multiple_signals_produce_multiple_labels(self):
        diffs = _no_signals()
        diffs["C221"] = True
        diffs["C510"] = True
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2")
        codes = {label.code for label in labels}
        assert codes == {"C221", "C510"}

    def test_never_produces_c100(self):
        # C100 (metadada) esta deliberadament fora d'abast del
        # classificador -- no hi ha cap via per generar-lo.
        diffs = _no_signals()
        for code in diffs:
            diffs[code] = True if code != "C410" else None
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2")
        assert all(label.code != "C100" for label in labels)

    def test_classifier_never_receives_a_target_column_parameter(self):
        # Regla de disseny obligatòria de la taxonomia: el classificador
        # no ha de saber quina columna és el target -- verificat aquí
        # amb introspecció de la signatura, no només documentació.
        import inspect

        params = inspect.signature(cc.classify_diffs).parameters
        assert "target" not in params
        assert "target_column" not in params


class TestClassifyFileChange:
    def test_both_none_produces_no_labels(self):
        assert cc.classify_file_change("ds", None, None, "v1", "v2") == []

    def test_added_file_produces_c421(self):
        after = pd.DataFrame({"a": [1, 2]})
        labels = cc.classify_file_change("ds", None, after, "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C421"
        assert labels[0].is_breaking is False

    def test_removed_file_produces_c422(self):
        before = pd.DataFrame({"a": [1, 2]})
        labels = cc.classify_file_change("ds", before, None, "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C422"
        assert labels[0].is_breaking is False

    def test_both_present_delegates_to_compute_all_diffs_and_classify_diffs(self):
        before = pd.DataFrame({"a": [1, 2]})
        after = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        labels = cc.classify_file_change("ds", before, after, "v1", "v2")
        assert len(labels) == 1
        assert labels[0].code == "C221"
