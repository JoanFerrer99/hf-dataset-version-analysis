"""
Tests unitaris per a `src/run_pipeline.py`.

Cobreixen `eligibility_scan.new_run_dir` (numeració de carpetes `run_<id>`)
i `run_full_pipeline`: l'ordre de crides, que el MATEIX `csv_path` flueix de
la Fase 0-1 a la Fase 1b/2, que TOTS els outputs d'una execució es
redirigeixen a la mateixa carpeta `run_<id>/`, i els flags `--input-csv`/`--skip-*`. Cada fase
individual (`eligibility_scan.run_sampling`, `version_extractor.
run_extraction`, `eligibility_scan.run_classification`) ja té els seus
propis tests -- aquí es pegen amb `monkeypatch` per no tornar-les a
exercir.
"""

import os

import pandas as pd

import eligibility_scan as es
import run_pipeline as rp
import version_extractor as ve


class TestNewRunDir:
    def test_no_existing_runs_starts_at_1(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "DATA_DIR", str(tmp_path))
        assert es.new_run_dir() == str(tmp_path / "run_1")
        assert os.path.isdir(tmp_path / "run_1")

    def test_picks_max_plus_one(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "DATA_DIR", str(tmp_path))
        (tmp_path / "run_1").mkdir()
        (tmp_path / "run_3").mkdir()
        assert es.new_run_dir() == str(tmp_path / "run_4")

    def test_missing_parent_is_created(self, tmp_path):
        assert es.new_run_dir(str(tmp_path / "census_income")) == str(tmp_path / "census_income" / "run_1")

    def test_redirects_the_outputs_of_the_module(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "DATA_DIR", str(tmp_path))
        run_dir = es.new_run_dir()
        assert es.OUTPUT_DIR == run_dir
        assert es.FAILURES_LOG_PATH == os.path.join(run_dir, "failures.csv")


def _patch_base_output_dir(monkeypatch, tmp_path):
    # Les carpetes run_<id> es creen dins de tmp_path; es restaura la sortida en acabar.
    monkeypatch.setattr(es, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))
    monkeypatch.setattr(ve, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))


def _patch_run_sampling(monkeypatch, calls, eligibility_csv, eligible_total):
    def fake_run_sampling(**kwargs):
        calls.append(("run_sampling", kwargs))
        return eligibility_csv, "funnel_summary.json", {"eligible": eligible_total}

    monkeypatch.setattr(es, "run_sampling", fake_run_sampling)


def _patch_run_extraction(monkeypatch, calls):
    def fake_run_extraction(input_csv, output_csv, hf_token, retry_config, compute_size=True):
        calls.append(("run_extraction", input_csv, output_csv, compute_size))
        return {"n_eligible": 1, "n_rows_written": 1}

    monkeypatch.setattr(ve, "run_extraction", fake_run_extraction)


def _patch_run_classification(monkeypatch, calls, output_csv="change_classification.csv"):
    def fake_run_classification(input_csv):
        calls.append(("run_classification", input_csv))
        return output_csv

    monkeypatch.setattr(es, "run_classification", fake_run_classification)


class TestRunFullPipeline:
    def test_full_chain_uses_same_csv_across_all_phases(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        eligibility_csv = str(tmp_path / "run_1" / "eligibility_report.csv")
        _patch_run_sampling(monkeypatch, calls, eligibility_csv, eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_sampling", "run_extraction", "run_classification"]
        assert calls[1][1] == eligibility_csv  # Fase 1b llegeix el CSV de la Fase 0-1
        assert calls[2][1] == eligibility_csv  # Fase 2 llegeix el MATEIX CSV, no un altre
        assert result["run_dir"] == str(tmp_path / "run_1")
        assert result["eligibility_csv"] == eligibility_csv
        assert result["eligible"] == 1
        assert result["versions_csv"] == str(tmp_path / "run_1" / "versions.csv")
        assert result["change_classification_csv"] == "change_classification.csv"

    def test_all_phase_outputs_redirected_to_the_same_run_dir(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        expected_run_dir = str(tmp_path / "run_1")
        assert es.OUTPUT_DIR == expected_run_dir
        assert es.FAILURES_LOG_PATH == ve.FAILURES_LOG_PATH == os.path.join(expected_run_dir, "failures.csv")
        assert os.path.isdir(expected_run_dir)

    def test_calling_twice_in_the_same_process_does_not_nest_run_dirs(self, monkeypatch, tmp_path):
        # Regressió: la carpeta nova es calculava a partir de la sortida de
        # l'execució anterior, i una segona crida al mateix procés generava
        # run_1/run_1/... Ara sempre es parteix de `es.DATA_DIR`.
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        first = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )
        second = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        assert first["run_dir"] == str(tmp_path / "run_1")
        assert second["run_dir"] == str(tmp_path / "run_2")

    def test_generated_files_grouped_by_phase(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        eligibility_csv = str(tmp_path / "run_1" / "eligibility_report.csv")
        _patch_run_sampling(monkeypatch, calls, eligibility_csv, eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls, output_csv=str(tmp_path / "run_1" / "change_classification.csv"))

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        files = result["generated_files"]
        assert files["Fase 0-1 (mostreig+elegibilitat)"] == [
            eligibility_csv, "funnel_summary.json", str(tmp_path / "run_1" / "tabular_commits.csv")]
        assert files["Fase 1b (versions)"] == [str(tmp_path / "run_1" / "versions.csv")]
        assert files["Fase 2 (classificació de canvis)"] == [str(tmp_path / "run_1" / "change_classification.csv")]

    def test_input_csv_skips_run_sampling(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, "SHOULD_NOT_BE_USED.csv", eligible_total=99)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        input_csv = tmp_path / "existing_eligibility_report.csv"
        pd.DataFrame({"dataset_id": ["org/ds"], "eligible": [True]}).to_csv(input_csv, index=False)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=str(input_csv), skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_extraction", "run_classification"]
        assert result["eligibility_csv"] == str(input_csv)
        assert result["eligible"] == 1
        # Fase 0-1 saltada -- no hi ha res a llistar per a aquesta fase.
        assert result["generated_files"]["Fase 0-1 (mostreig+elegibilitat)"] == []

    def test_zero_eligible_skips_extraction_and_classification(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=0)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        assert calls == [("run_sampling", {"sample_size": 1, "max_scanned": None, "num_threads": 1, "tags_only": False})]
        assert result["versions_csv"] is None
        assert result["change_classification_csv"] is None

    def test_skip_version_extraction_flag(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=True, skip_classification=False, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_sampling", "run_classification"]
        assert result["versions_csv"] is None

    def test_skip_classification_flag(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=True, skip_size=False,
        )

        assert [c[0] for c in calls] == ["run_sampling", "run_extraction"]
        assert result["change_classification_csv"] is None

    def test_skip_size_passed_through_to_run_extraction(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=True,
        )

        compute_size = next(c[3] for c in calls if c[0] == "run_extraction")
        assert compute_size is False
