"""
Tests unitaris per a `src/run_pipeline.py`.

Cobreixen `eligibility_scan.new_run_dir` (numeració de carpetes `run_<id>`)
i `run_full_pipeline`: l'ordre de crides, que el `csv_path` de la Fase 0-1
arriba a la Fase 1b i el `versions.csv` de la Fase 1b a la Fase 2, que TOTS els outputs d'una execució es
redirigeixen a la mateixa carpeta `run_<id>/`, i els flags `--input-csv`/`--skip-*`. Cada fase
individual (`eligibility_scan.run_sampling`, `version_extractor.
run_extraction`, `eligibility_scan.run_classification`) ja té els seus
propis tests -- aquí es pegen amb `monkeypatch` per no tornar-les a
exercir.
"""

import os

import pandas as pd
import pytest

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
        return eligibility_csv, "funnel_summary.json", {"eligible": eligible_total}, {"org/ds": ["c1"]}

    monkeypatch.setattr(es, "run_sampling", fake_run_sampling)


def _patch_run_extraction(monkeypatch, calls):
    def fake_run_extraction(input_csv, output_csv, hf_token, retry_config, compute_size=True, tabular_commits=None):
        calls.append(("run_extraction", input_csv, output_csv, compute_size, tabular_commits))
        return {"n_eligible": 1, "n_rows_written": 1}

    monkeypatch.setattr(ve, "run_extraction", fake_run_extraction)


def _patch_run_classification(monkeypatch, calls, output_csv="change_classification.csv"):
    def fake_run_classification(versions_csv):
        calls.append(("run_classification", versions_csv))
        return output_csv

    monkeypatch.setattr(es, "run_classification", fake_run_classification)


class TestRunFullPipeline:
    def test_each_phase_reads_the_output_of_the_previous_one(self, monkeypatch, tmp_path):
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
        assert calls[1][4] == {"org/ds": ["c1"]}  # i rep en memòria els commits tabulars de la Fase 0-1
        assert calls[2][1] == calls[1][2]  # Fase 2 llegeix el versions.csv que escriu la Fase 1b
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
        assert files["Fase 0-1 (mostreig+elegibilitat)"] == [eligibility_csv, "funnel_summary.json"]
        assert files["Fase 1b (versions)"] == [str(tmp_path / "run_1" / "versions.csv")]
        assert files["Fase 2 (classificació de canvis)"] == [str(tmp_path / "run_1" / "change_classification.csv"),
                                                              str(tmp_path / "run_1" / "comparison_status.csv")]

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
        assert calls[0][4] is None  # sense Fase 0-1, la Fase 1b torna a buscar els commits
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

    def test_skip_version_extraction_also_skips_classification(self, monkeypatch, tmp_path):
        _patch_base_output_dir(monkeypatch, tmp_path)
        calls = []
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)

        result = rp.run_full_pipeline(
            sample_size=1, max_scanned=None, num_threads=1, tags_only=False,
            input_csv=None, skip_version_extraction=True, skip_classification=False, skip_size=False,
        )

        # La Fase 2 compara les versions de la Fase 1b: sense elles, no hi ha res a comparar.
        assert [c[0] for c in calls] == ["run_sampling"]
        assert result["versions_csv"] is None
        assert result["change_classification_csv"] is None

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


# ---------------------------------------------------------------------------
# Fase 3: el magatzem (dbt build se simula; no s'executa mai a aquests tests)
# ---------------------------------------------------------------------------

def _patch_build_warehouse(monkeypatch, calls, complete_folder=True, fail=False):
    import subprocess

    import build_warehouse as bw

    def fake_build_warehouse(run_dir):
        calls.append(("build_warehouse", run_dir))
        if fail:
            raise subprocess.CalledProcessError(1, ["dbt", "build"])
        return os.path.join("data", "warehouse", f"{os.path.basename(run_dir)}.duckdb")

    if complete_folder:
        monkeypatch.setattr(bw, "missing_files", lambda run_dir: [])
    monkeypatch.setattr(bw, "build_warehouse", fake_build_warehouse)


class TestPhase3:
    def _run(self, monkeypatch, tmp_path, calls, **flags):
        _patch_base_output_dir(monkeypatch, tmp_path)
        _patch_run_sampling(monkeypatch, calls, str(tmp_path / "run_1" / "eligibility_report.csv"), eligible_total=1)
        _patch_run_extraction(monkeypatch, calls)
        _patch_run_classification(monkeypatch, calls)
        args = dict(sample_size=1, max_scanned=None, num_threads=1, tags_only=False, input_csv=None,
                    skip_version_extraction=False, skip_classification=False, skip_size=False)
        return rp.run_full_pipeline(**{**args, **flags})

    def test_builds_the_warehouse_of_the_run_folder_after_classification(self, monkeypatch, tmp_path):
        calls = []
        _patch_build_warehouse(monkeypatch, calls)

        result = self._run(monkeypatch, tmp_path, calls)

        assert [c[0] for c in calls] == ["run_sampling", "run_extraction", "run_classification", "build_warehouse"]
        assert calls[-1][1] == str(tmp_path / "run_1")
        assert result["warehouse_path"] == os.path.join("data", "warehouse", "run_1.duckdb")
        assert result["generated_files"]["Fase 3 (magatzem)"] == [result["warehouse_path"]]

    def test_skip_warehouse_flag(self, monkeypatch, tmp_path):
        calls = []
        _patch_build_warehouse(monkeypatch, calls)

        result = self._run(monkeypatch, tmp_path, calls, skip_warehouse=True)

        assert "build_warehouse" not in [c[0] for c in calls]
        assert result["warehouse_path"] is None

    def test_a_folder_without_every_phase_has_no_warehouse(self, monkeypatch, tmp_path):
        # Les fases simulades no escriuen res: a la carpeta hi falten tots els fitxers (com amb --input-csv).
        calls = []
        _patch_build_warehouse(monkeypatch, calls, complete_folder=False)

        result = self._run(monkeypatch, tmp_path, calls)

        assert "build_warehouse" not in [c[0] for c in calls]
        assert result["warehouse_path"] is None

    def test_a_dbt_failure_keeps_the_rest_of_the_run(self, monkeypatch, tmp_path):
        calls = []
        _patch_build_warehouse(monkeypatch, calls, fail=True)

        result = self._run(monkeypatch, tmp_path, calls)

        assert calls[-1][0] == "build_warehouse"
        assert result["warehouse_path"] is None
        assert result["change_classification_csv"] == "change_classification.csv"


class TestBuildWarehouse:
    @pytest.fixture
    def run_dir(self, tmp_path):
        import build_warehouse as bw

        run = tmp_path / "data" / "run_7"
        run.mkdir(parents=True)
        for name in bw.REQUIRED_FILES:
            (run / name).write_text("x\n", encoding="utf-8")
        return run

    def test_runs_dbt_build_on_the_run_folder_and_writes_outside_it(self, monkeypatch, tmp_path, run_dir):
        import json

        import build_warehouse as bw

        monkeypatch.setattr(bw, "WAREHOUSE_DIR", str(tmp_path / "data" / "warehouse"))
        seen = {}
        monkeypatch.setattr(bw.subprocess, "run", lambda command, cwd, env, check: seen.update(
            command=command, cwd=cwd, env=env, check=check))

        path = bw.build_warehouse(str(run_dir))

        assert path == str(tmp_path / "data" / "warehouse" / "run_7.duckdb")
        assert not path.startswith(str(run_dir))
        assert seen["command"][1:6] == ["build", "--project-dir", bw.PROJECT_DIR, "--profiles-dir", bw.PROJECT_DIR]
        assert json.loads(seen["command"][-1]) == {"run_dir": str(run_dir)}
        assert seen["env"]["WAREHOUSE_PATH"] == path
        assert (seen["cwd"], seen["check"]) == (bw.REPO_ROOT, True)
        assert os.path.isdir(tmp_path / "data" / "warehouse")

    def test_refuses_a_folder_without_every_phase(self, monkeypatch, run_dir):
        import build_warehouse as bw

        (run_dir / "comparison_status.csv").unlink()
        monkeypatch.setattr(bw.subprocess, "run", lambda *a, **kw: pytest.fail("no s'havia de cridar dbt"))

        with pytest.raises(FileNotFoundError, match="comparison_status.csv"):
            bw.build_warehouse(str(run_dir))
        assert bw.main(["--run-dir", str(run_dir)]) == 1

    def test_failures_csv_is_optional(self, run_dir):
        import build_warehouse as bw

        assert bw.missing_files(str(run_dir)) == []

    def test_no_arguments_prints_help_and_exits(self, capsys):
        import build_warehouse as bw

        with pytest.raises(SystemExit) as exc:
            bw.main([])
        assert exc.value.code == 0
        assert "--run-dir" in capsys.readouterr().out
