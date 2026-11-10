"""
La fixture `tests/fixtures/run_sample/` és el que escriu el pipeline: si un
format de sortida canvia, aquest test falla fins que es torna a generar
(`python tests/fixtures/make_run_sample.py`).
"""

import filecmp
import os
import sys

import pandas as pd
import pytest

import eligibility_scan as es

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RUN_SAMPLE = os.path.join(FIXTURES, "run_sample")
FILES = ["eligibility_report.csv", "funnel_summary.json", "versions.csv", "change_classification.csv",
         "comparison_status.csv", "failures.csv"]


@pytest.fixture
def make_run_sample(monkeypatch):
    monkeypatch.syspath_prepend(FIXTURES)
    monkeypatch.setattr(es, "OUTPUT_DIR", es.OUTPUT_DIR)  # el generador el canvia: es restaura en acabar
    import make_run_sample as module
    yield module
    sys.modules.pop("make_run_sample", None)


def test_committed_fixture_is_what_the_pipeline_writes(make_run_sample, tmp_path):
    make_run_sample.main(str(tmp_path))

    assert sorted(os.listdir(tmp_path)) == sorted(FILES)
    mismatch = [f for f in FILES if not filecmp.cmp(tmp_path / f, os.path.join(RUN_SAMPLE, f), shallow=False)]
    assert mismatch == [], "fixture desactualitzada: python tests/fixtures/make_run_sample.py"


def test_n_codes_matches_the_classification_rows():
    status = pd.read_csv(os.path.join(RUN_SAMPLE, "comparison_status.csv"))
    changes = pd.read_csv(os.path.join(RUN_SAMPLE, "change_classification.csv"))
    per_table = changes.groupby(["dataset_id", "version_from", "version_to", "table"]).size()
    keys = zip(status["dataset_id"], status["version_from"], status["version_to"], status["table"])
    assert [per_table.get(k, 0) for k in keys] == status["n_codes"].tolist()


def test_every_compared_version_is_in_versions_and_every_dataset_is_eligible():
    versions = pd.read_csv(os.path.join(RUN_SAMPLE, "versions.csv"))
    status = pd.read_csv(os.path.join(RUN_SAMPLE, "comparison_status.csv"))
    report = pd.read_csv(os.path.join(RUN_SAMPLE, "eligibility_report.csv"))
    assert set(status["version_from"]) | set(status["version_to"]) <= set(versions["commit_sha"])
    assert set(status["dataset_id"]) <= set(report.loc[report["eligible"], "dataset_id"])
