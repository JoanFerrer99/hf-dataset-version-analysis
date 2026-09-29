"""
Tests unitaris per a `notebooks/run_pipeline.py`.

Cobreixen `next_pipeline_run_dir` (numeració de carpetes `run_<id>`) i
`run_full_pipeline`: l'ordre de crides, que el MATEIX `csv_path` flueix de
la Fase 0-1 a la Fase 1b/2, que TOTS els outputs d'una execució es
redirigeixen a la mateixa carpeta `run_<id>/` (`es.OUTPUT_DIR`/`ve.
OUTPUT_DIR` reassignats), i els flags `--input-csv`/`--skip-*`. Cada fase
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


class TestNextPipelineRunDir:
    def test_no_existing_runs_starts_at_1(self, tmp_path):
        assert rp.next_pipeline_run_dir(str(tmp_path)) == str(tmp_path / "run_1")

    def test_picks_max_plus_one(self, tmp_path):
        (tmp_path / "run_1").mkdir()
        (tmp_path / "run_3").mkdir()
        assert rp.next_pipeline_run_dir(str(tmp_path)) == str(tmp_path / "run_4")

    def test_ignores_files_named_like_a_run_dir(self, tmp_path):
        (tmp_path / "run_5").write_text("not a directory")
        assert rp.next_pipeline_run_dir(str(tmp_path)) == str(tmp_path / "run_1")

    def test_missing_data_dir_starts_at_1(self, tmp_path):
        assert rp.next_pipeline_run_dir(str(tmp_path / "does-not-exist")) == str(tmp_path / "does-not-exist" / "run_1")


def _patch_base_output_dir(monkeypatch, tmp_path):
    # run_full_pipeline calcula run_<id>/ a partir de rp.DATA_DIR (base
    # ESTABLE, no es.OUTPUT_DIR -- vegeu el comentari a run_pipeline.py:
    # es.OUTPUT_DIR es reassigna internament cap a la carpeta run_<id>
    # triada, així que fer-lo servir com a base produiria niament
    # recursiu en crides repetides) i reassigna es/ve.OUTPUT_DIR
    # internament -- els tests només cal que fixin el DIRECTORI ARREL
    # (tmp_path), no la carpeta run_<id> final.
    monkeypatch.setattr(rp, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))


def _patch_run_sampling(monkeypatch, calls, eligibility_csv, eligible_total):
    def fake_run_sampling(**kwargs):
        calls.append(("run_sampling", kwargs))
        return eligibility_csv, "funnel_summary.json", {"eligible_total": eligible_total}

    monkeypatch.setattr(es, "run_sampling", fake_run_sampling)


def _patch_run_extraction(monkeypatch, calls):
    monkeypatch.setattr(ve, "get_next_run_id", lambda output_dir: 1)

    def fake_run_extraction(input_csv, output_csv, hf_token, retry_config, compute_size=True):
        calls.append(("run_extraction", input_csv, output_csv, compute_size))
        return {"n_eligible": 1, "n_rows_written": 1}

    monkeypatch.setattr(ve, "run_extraction", fake_run_extraction)


def _patch_run_classification(monkeypatch, calls, output_csv="change_classification_1.csv"):
    def fake_run_classification(input_csv):
        calls.append(("run_classification", input_csv))
        return output_csv

    monkeypatch.setattr(es, "run_classification", fake_run_classification)


class TestRunFullPipeline:
    def test_full_chain_uses_same_csv_across_all_phases(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        eligibility_csv = str(tmp_path / "run_1" / "eligibility_report_1_1.csv")
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
        assert result["eligible_total"] == 1
        assert result["versions_csv"] == str(tmp_path / "run_1" / "versions_1.csv")
        assert result["change_classification_csv"] == "change_classification_1.csv"

    def test_all_phase_outputs_redirected_to_the_same_run_dir(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report_1_1.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        expected_run_dir = str(tmp_path / "run_1")
        assert es.OUTPUT_DIR == expected_run_dir
        assert ve.OUTPUT_DIR == expected_run_dir
        assert es.FAILURES_LOG_PATH == ve.FAILURES_LOG_PATH == os.path.join(expected_run_dir, "failures.csv")
        assert os.path.isdir(expected_run_dir)

    def test_calling_twice_in_the_same_process_does_not_nest_run_dirs(self, monkeypatch, tmp_path):
        # Regressio: next_pipeline_run_dir es calculava a partir d'es.
        # OUTPUT_DIR, que run_full_pipeline tambe reassignava -- una
        # segona crida al mateix proces (p. ex. un notebook/REPL) llegia
        # la carpeta run_1 ja reassignada com si fos l'arrel de dades i
        # generava run_1/run_1, run_1/run_1/run_1, etc. Es va trobar un
        # arbre buit de 6 nivells (data/run_1/run_1/.../run_1) que nomes
        # s'explica per aquest patro de crides repetides.
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report_1_1.csv"), eligible_total=1)
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
        eligibility_csv = str(tmp_path / "run_1" / "eligibility_report_1_1.csv")
        _patch_run_sampling(monkeypatch, calls, eligibility_csv, eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls, output_csv=str(tmp_path / "run_1" / "change_classification_1.csv"))

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=False,
        )

        files = result["generated_files"]
        assert files["Fase 0-1 (mostreig+elegibilitat)"] == [eligibility_csv, "funnel_summary.json"]
        assert files["Fase 1b (versions)"] == [str(tmp_path / "run_1" / "versions_1.csv")]
        assert files["Fase 2 (classificació de canvis)"] == [str(tmp_path / "run_1" / "change_classification_1.csv")]

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
        assert result["eligible_total"] == 1
        # Fase 0-1 saltada -- no hi ha res a llistar per a aquesta fase.
        assert result["generated_files"]["Fase 0-1 (mostreig+elegibilitat)"] == []

    def test_zero_eligible_skips_extraction_and_classification(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report_1_1.csv"), eligible_total=0)
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
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report_1_1.csv"), eligible_total=1)
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
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report_1_1.csv"), eligible_total=1)
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
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report_1_1.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=False, skip_classification=False, skip_size=True,
        )

        compute_size = next(c[3] for c in calls if c[0] == "run_extraction")
        assert compute_size is False
