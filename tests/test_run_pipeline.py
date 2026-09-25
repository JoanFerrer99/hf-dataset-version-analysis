"""
Tests unitaris per a `notebooks/run_pipeline.py`.

Cobreixen NOMÉS l'orquestració (`run_full_pipeline`): l'ordre de crides,
que el MATEIX `csv_path` flueix de la Fase 0-1 a la Fase 1b/2, i els flags
`--input-csv`/`--skip-*`. Cada fase individual (`eligibility_scan.
run_sampling`, `version_extractor.run_extraction`, `eligibility_scan.
run_classification`) ja té els seus propis tests -- aquí es pegen amb
`monkeypatch` per no tornar-les a exercir.
"""

import os

import pandas as pd

import eligibility_scan as es
import run_pipeline as rp
import version_extractor as ve


def _patch_run_sampling(monkeypatch, calls, eligibility_csv, eligible_total):
    def fake_run_sampling(**kwargs):
        calls.append(("run_sampling", kwargs))
        return eligibility_csv, "funnel_summary.json", {"eligible_total": eligible_total}

    monkeypatch.setattr(es, "run_sampling", fake_run_sampling)


def _patch_run_extraction(monkeypatch, calls, tmp_path):
    monkeypatch.setattr(ve, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(ve, "get_next_run_id", lambda output_dir: 1)

    def fake_run_extraction(input_csv, output_csv, hf_token, retry_config, compute_size=True):
        calls.append(("run_extraction", input_csv, output_csv, compute_size))
        return {"n_eligible": 1, "n_rows_written": 1}

    monkeypatch.setattr(ve, "run_extraction", fake_run_extraction)


def _patch_run_classification(monkeypatch, calls):
    def fake_run_classification(input_csv):
        calls.append(("run_classification", input_csv))

    monkeypatch.setattr(es, "run_classification", fake_run_classification)


class TestRunFullPipeline:
    def test_full_chain_uses_same_csv_across_all_phases(self, monkeypatch, tmp_path):
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "eligibility_report_1_1.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls, tmp_path)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        eligibility_csv = str(tmp_path / "eligibility_report_1_1.csv")
        assert [c[0] for c in calls] == ["run_sampling", "run_extraction", "run_classification"]
        assert calls[1][1] == eligibility_csv  # Fase 1b llegeix el CSV de la Fase 0-1
        assert calls[2][1] == eligibility_csv  # Fase 2 llegeix el MATEIX CSV, no un altre
        assert result["eligibility_csv"] == eligibility_csv
        assert result["eligible_total"] == 1
        assert result["versions_csv"] == os.path.join(str(tmp_path), "versions_1.csv")

    def test_input_csv_skips_run_sampling(self, monkeypatch, tmp_path):
        calls = []
        _patch_run_sampling(monkeypatch, calls, "SHOULD_NOT_BE_USED.csv", eligible_total=99)
        _patch_run_extraction(monkeypatch, calls, tmp_path)
        _patch_run_classification(monkeypatch, calls)

        input_csv = tmp_path / "existing_eligibility_report.csv"
        pd.DataFrame({"dataset_id": ["org/ds"], "eligible": [True]}).to_csv(input_csv, index=False)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=str(input_csv), skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_extraction", "run_classification"]
        assert result["eligibility_csv"] == str(input_csv)
        assert result["eligible_total"] == 1

    def test_zero_eligible_skips_extraction_and_classification(self, monkeypatch, tmp_path):
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "eligibility_report_1_1.csv"), eligible_total=0)
        _patch_run_extraction(monkeypatch, calls, tmp_path)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        assert calls == [("run_sampling", {"sample_size": 1, "max_scanned": None, "num_threads": 1, "tags_only": False})]
        assert result["versions_csv"] is None

    def test_skip_version_extraction_flag(self, monkeypatch, tmp_path):
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "eligibility_report_1_1.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls, tmp_path)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=True, skip_classification=False, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_sampling", "run_classification"]
        assert result["versions_csv"] is None

    def test_skip_classification_flag(self, monkeypatch, tmp_path):
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "eligibility_report_1_1.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls, tmp_path)
        _patch_run_classification(monkeypatch, calls)

        rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=True, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_sampling", "run_extraction"]

    def test_skip_size_passed_through_to_run_extraction(self, monkeypatch, tmp_path):
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "eligibility_report_1_1.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls, tmp_path)
        _patch_run_classification(monkeypatch, calls)

        rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=True,
        )

        compute_size = next(c[3] for c in calls if c[0] == "run_extraction")
        assert compute_size is False
