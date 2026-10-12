"""
Etiquetes de la Taula 1 del paper (Census Income, D1-D7).

- La fixture i `validate_census_income.PAPER_GROUND_TRUTH` han de coincidir.
- Prova d'extrem a extrem (descarrega D0-D7): només amb `RUN_NETWORK_TESTS=1`.
  Comprova que el motor no empitjora la línia base registrada.
"""

import csv
import os
from collections import defaultdict
from pathlib import Path

import pytest

import validate_census_income as vci

FIXTURE = Path(__file__).parent / "fixtures" / "census_income_labels.csv"
BASELINE = {"precision": 0.645, "recall": 0.769}


def load_fixture() -> dict[str, frozenset[str]]:
    labels = defaultdict(set)
    with open(FIXTURE, newline="") as f:
        for row in csv.DictReader(f):
            labels[row["version"]].add(row["code"])
    return {v: frozenset(c) for v, c in labels.items()}


def test_fixture_matches_paper_ground_truth():
    assert load_fixture() == vci.PAPER_GROUND_TRUTH


@pytest.mark.skipif(not os.environ.get("RUN_NETWORK_TESTS"), reason="descarrega D0-D7 de la UCI i del Hub")
def test_engine_does_not_regress_on_census_income():
    detectability_df, _ = vci.run_validation(os.environ.get("HF_TOKEN"))
    metrics = vci.compute_agreement_metrics(vci.compare_detectability_with_paper(detectability_df))
    assert metrics["precision"] >= BASELINE["precision"] - 1e-3
    assert metrics["recall"] >= BASELINE["recall"] - 1e-3
