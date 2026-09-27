"""
Tests unitaris per a `notebooks/extension_report.py` (feedback del
director: estadístiques agregades per extensió dels fitxers dels
datasets elegibles, previ a l'exclusió dels binaris de la classificació
de canvis).

Cobreixen `build_extension_report`: filtre `eligible==True`, agregació
PER EXTENSIÓ (no per dataset -- `file_count`/`pct_of_total`/`is_tabular`,
sumats sobre TOTS els elegibles), tolerància a una fallada de dataset
sencer, i el resum (`n_eligible_with_tabular_files`, `tabular_files_
per_dataset`). Cap crida real a l'API de Hugging Face.
"""

import httpx
import pandas as pd
from huggingface_hub.utils import HfHubHTTPError

import extension_report as er
import version_extractor as ve


def make_http_error(status_code: int, message: str = "boom") -> HfHubHTTPError:
    request = httpx.Request("GET", "https://huggingface.co/api/datasets/foo/tree/main")
    response = httpx.Response(status_code, request=request)
    return HfHubHTTPError(message, response=response)


NO_RETRY_CONFIG = {
    "max_retries": 2,
    "base_wait_s": 0.0,
    "max_wait_s": 0.0,
    "sleep_fn": lambda seconds: None,
    "jitter_fn": lambda: 0.0,
}


class TestBuildExtensionReport:
    def test_filters_to_eligible_only(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([
            {"dataset_id": "org/eligible", "eligible": True},
            {"dataset_id": "org/not-eligible", "eligible": False},
        ]).to_csv(input_csv, index=False)

        seen_dataset_ids = []

        def fake_fetch(dataset_id, hf_token, retry_config):
            seen_dataset_ids.append(dataset_id)
            return ["data/train.csv"]

        monkeypatch.setattr(ve, "fetch_tree_paths", fake_fetch)

        report_df, summary = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        assert seen_dataset_ids == ["org/eligible"]
        assert summary["n_eligible"] == 1

    def test_aggregates_file_counts_by_extension_across_datasets(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([
            {"dataset_id": "org/a", "eligible": True},
            {"dataset_id": "org/b", "eligible": True},
        ]).to_csv(input_csv, index=False)

        files_by_dataset = {
            "org/a": ["data/train.csv", "data/test.csv"],
            "org/b": ["data/train.csv", "audio/sample.wav"],
        }
        monkeypatch.setattr(ve, "fetch_tree_paths", lambda dataset_id, hf_token, retry_config: files_by_dataset[dataset_id])

        report_df, summary = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        # Agregat per extensio -- cap columna dataset_id, cap taula per dataset.
        assert set(report_df.columns) == {"extension", "file_count", "pct_of_total", "is_tabular"}

        csv_row = report_df[report_df["extension"] == ".csv"].iloc[0]
        assert csv_row["file_count"] == 3
        assert csv_row["is_tabular"] == True  # noqa: E712
        assert csv_row["pct_of_total"] == 75.0

        wav_row = report_df[report_df["extension"] == ".wav"].iloc[0]
        assert wav_row["file_count"] == 1
        assert wav_row["is_tabular"] == False  # noqa: E712
        assert wav_row["pct_of_total"] == 25.0

        assert summary["total_files"] == 4
        assert summary["total_tabular_files"] == 3
        assert summary["pct_tabular"] == 75.0

    def test_compound_tar_gz_extension_not_split(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([{"dataset_id": "org/ds", "eligible": True}]).to_csv(input_csv, index=False)
        monkeypatch.setattr(ve, "fetch_tree_paths", lambda *a, **kw: ["archive/data.tar.gz"])

        report_df, _ = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        assert report_df.iloc[0]["extension"] == ".tar.gz"

    def test_one_dataset_failure_does_not_stop_the_others(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([
            {"dataset_id": "org/broken", "eligible": True},
            {"dataset_id": "org/ok", "eligible": True},
        ]).to_csv(input_csv, index=False)

        def fake_fetch(dataset_id, hf_token, retry_config):
            if dataset_id == "org/broken":
                raise make_http_error(403)
            return ["data/train.csv"]

        monkeypatch.setattr(ve, "fetch_tree_paths", fake_fetch)
        monkeypatch.setattr(ve, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        report_df, summary = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        assert summary["n_dataset_level_failures"] == 1
        assert summary["total_files"] == 1
        assert report_df.iloc[0]["file_count"] == 1

        failures_df = pd.read_csv(tmp_path / "failures.csv")
        assert failures_df.iloc[0]["source"] == "extension_report"
        assert failures_df.iloc[0]["dataset_id"] == "org/broken"

    def test_tabular_files_per_dataset_in_summary(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([{"dataset_id": "org/ds", "eligible": True}]).to_csv(input_csv, index=False)
        monkeypatch.setattr(
            ve, "fetch_tree_paths",
            lambda *a, **kw: ["data/train.csv", "data/test.parquet", "audio/sample.wav"],
        )

        _, summary = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        assert summary["tabular_files_per_dataset"] == {"org/ds": 2}

    def test_n_eligible_with_tabular_files_counts_datasets_not_files(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([
            {"dataset_id": "org/has-tabular", "eligible": True},
            {"dataset_id": "org/no-tabular", "eligible": True},
        ]).to_csv(input_csv, index=False)

        files_by_dataset = {
            "org/has-tabular": ["data/train.csv", "data/test.csv"],
            "org/no-tabular": ["audio/sample.wav"],
        }
        monkeypatch.setattr(ve, "fetch_tree_paths", lambda dataset_id, hf_token, retry_config: files_by_dataset[dataset_id])

        _, summary = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        # 2 fitxers tabulars pero d'UN sol dataset -- el numero demanat compta
        # datasets, no fitxers.
        assert summary["n_eligible_with_tabular_files"] == 1

    def test_empty_eligible_population(self, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([{"dataset_id": "org/not-eligible", "eligible": False}]).to_csv(input_csv, index=False)

        report_df, summary = er.build_extension_report(str(input_csv), "tok", NO_RETRY_CONFIG)

        assert report_df.empty
        assert summary["n_eligible"] == 0
        assert summary["pct_tabular"] == 0.0
        assert summary["n_eligible_with_tabular_files"] == 0
