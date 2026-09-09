"""
Tests unitaris per a `notebooks/change_classifier.py` (US-305).

Cobreixen NOMÉS la capa d'etiquetatge (`diff_metadata`, `classify_diffs`,
`build_classification_table`, `summarize_agreement`), amb fets sintètics
-- mai crides de xarxa (`run_census_income_classification` no es
testeja aquí, mateix criteri que `gather_evidence_for_dataset` a
`test_validate_eligible.py`).
"""

import change_classifier as cc
import change_diff as cd


def _no_signals() -> dict:
    """Diccionari de `compute_all_diffs` amb tots els codis sense senyal."""
    return {code: (None if code == "C410" else False) for code in cd.TABULAR_CODES}


class TestDiffMetadata:
    def test_no_changes(self):
        card = {"license": "mit", "tags": ["tabular"]}
        assert cc.diff_metadata(card, dict(card)) == {}

    def test_license_changed(self):
        before = {"license": "mit"}
        after = {"license": "apache-2.0"}
        result = cc.diff_metadata(before, after)
        assert result == {"license": {"before": "mit", "after": "apache-2.0"}}

    def test_tags_changed(self):
        before = {"tags": ["a"]}
        after = {"tags": ["a", "b"]}
        result = cc.diff_metadata(before, after)
        assert result["tags"] == {"before": ["a"], "after": ["a", "b"]}

    def test_missing_keys_default_to_none(self):
        result = cc.diff_metadata({}, {"license": "mit"})
        assert result == {"license": {"before": None, "after": "mit"}}


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

    def test_metadata_changed_adds_c100_never_breaking(self):
        labels = cc.classify_diffs(_no_signals(), "ds", "v1", "v2", metadata_changed=True)
        assert len(labels) == 1
        assert labels[0].code == "C100"
        assert labels[0].is_breaking is False

    def test_metadata_not_changed_does_not_add_c100(self):
        labels = cc.classify_diffs(_no_signals(), "ds", "v1", "v2", metadata_changed=False)
        assert all(label.code != "C100" for label in labels)

    def test_multiple_signals_produce_multiple_labels(self):
        diffs = _no_signals()
        diffs["C221"] = True
        diffs["C510"] = True
        labels = cc.classify_diffs(diffs, "ds", "v1", "v2", metadata_changed=True)
        codes = {label.code for label in labels}
        assert codes == {"C100", "C221", "C510"}

    def test_classifier_never_receives_a_target_column_parameter(self):
        # Regla de disseny obligatòria de la taxonomia: el classificador
        # no ha de saber quina columna és el target -- verificat aquí
        # amb introspecció de la signatura, no només documentació.
        import inspect

        params = inspect.signature(cc.classify_diffs).parameters
        assert "target" not in params
        assert "target_column" not in params


class TestBuildClassificationTable:
    def test_empty_labels_gives_empty_dataframe_with_correct_columns(self):
        table = cc.build_classification_table([])
        assert list(table.columns) == ["dataset_id", "version_from", "version_to", "code", "is_breaking"]
        assert len(table) == 0

    def test_one_row_per_label(self):
        labels = [
            cc.ChangeLabel("ds", "v1", "v2", "C221", False),
            cc.ChangeLabel("ds", "v1", "v2", "C223", True),
        ]
        table = cc.build_classification_table(labels)
        assert len(table) == 2
        assert list(table["code"]) == ["C221", "C223"]
        assert list(table["is_breaking"]) == [False, True]


class TestSummarizeAgreement:
    def test_counts_labels_per_version(self):
        labels = [
            cc.ChangeLabel("D1", "D0", "D1", "C223", True),
            cc.ChangeLabel("D3", "D0", "D3", "C221", False),
            cc.ChangeLabel("D3", "D0", "D3", "C222", False),
        ]
        table = cc.build_classification_table(labels)
        summary = cc.summarize_agreement(table)

        by_version = summary.set_index("version")
        assert by_version.loc["D1", "codes_labeled"] == 1
        assert by_version.loc["D3", "codes_labeled"] == 2
        assert by_version.loc["D2", "codes_labeled"] == 0

    def test_paper_row_total_column_matches_change_diff_constant(self):
        summary = cc.summarize_agreement(cc.build_classification_table([]))
        by_version = summary.set_index("version")
        for version, total in cd.PAPER_ROW_TOTALS.items():
            assert by_version.loc[version, "paper_row_total"] == total

    def test_covers_all_seven_census_income_versions(self):
        summary = cc.summarize_agreement(cc.build_classification_table([]))
        assert set(summary["version"]) == set(cd.CENSUS_INCOME_SOURCES.keys())
