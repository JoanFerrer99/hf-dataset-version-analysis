"""
Tests unitaris per a `notebooks/validate_eligible.py` (US-108).

Cobreix les funcions pures sense crides a l'API/xarxa:
`cluster_commit_times`, `summarize_commits`, `classify_dataset_evidence`
i `generate_markdown_report`. `gather_evidence_for_dataset` es deixa fora
de l'abast (embolcall prim de crides a l'API + `bare_clone`, ja cobertes
per `tests/test_eligibility_scan.py`).
"""

from datetime import datetime, timedelta

import eligibility_scan as es
import validate_eligible as ve


class _FakeCommit:
    def __init__(self, title, commit_id="abc123", created_at=None):
        self.title = title
        self.commit_id = commit_id
        self.created_at = created_at


class TestClusterCommitTimes:
    def test_empty_list_returns_no_clusters(self):
        assert ve.cluster_commit_times([]) == []

    def test_none_values_are_ignored(self):
        assert ve.cluster_commit_times([None, None]) == []

    def test_single_time_is_one_cluster(self):
        t = datetime(2026, 1, 1, 12, 0, 0)
        assert ve.cluster_commit_times([t]) == [[t]]

    def test_times_within_gap_form_one_cluster(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base + timedelta(minutes=5), base + timedelta(minutes=10)]
        clusters = ve.cluster_commit_times(times, gap_hours=1.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_times_beyond_gap_form_separate_clusters(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base + timedelta(minutes=5), base + timedelta(days=2)]
        clusters = ve.cluster_commit_times(times, gap_hours=1.0)
        assert len(clusters) == 2
        assert len(clusters[0]) == 2
        assert len(clusters[1]) == 1

    def test_clusters_are_chronologically_ordered_regardless_of_input_order(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        unordered = [base + timedelta(days=2), base, base + timedelta(minutes=5)]
        clusters = ve.cluster_commit_times(unordered, gap_hours=1.0)
        assert clusters == [[base, base + timedelta(minutes=5)], [base + timedelta(days=2)]]


class TestSummarizeCommits:
    def test_counts_substantive_and_non_substantive_commits(self):
        commits = [
            _FakeCommit("Add new training episode"),
            _FakeCommit("Update README"),
            _FakeCommit("Fix labeling errors"),
            _FakeCommit("fix typo"),
        ]

        result = ve.summarize_commits(commits)

        assert result["num_substantive"] == 2
        assert len(result["commits"]) == 4

    def test_each_entry_has_the_expected_shape(self):
        commits = [_FakeCommit("Add new records", commit_id="deadbeef")]

        result = ve.summarize_commits(commits)
        entry = result["commits"][0]

        assert entry["sha"] == "deadbeef"
        assert entry["title"] == "Add new records"
        assert entry["is_substantive"] is True

    def test_empty_commit_list(self):
        result = ve.summarize_commits([])

        assert result["commits"] == []
        assert result["num_substantive"] == 0
        assert result["num_sessions"] == 0

    def test_all_non_substantive_commits(self):
        commits = [
            _FakeCommit("Update README"),
            _FakeCommit("Update dataset_infos"),
            _FakeCommit("fix typo"),
        ]

        result = ve.summarize_commits(commits)

        assert result["num_substantive"] == 0
        assert result["num_sessions"] == 0

    def test_matches_is_substantive_commit_heuristic_when_no_clone_dir(self):
        # Sense clone_dir, determine_commit_substantive recorre a
        # l'heurística de títol -- garanteix que summarize_commits no
        # n'és una còpia que es pugui desincronitzar amb el temps.
        titles = ["Add new records", "readme update", "Fix bug in labels", "license change"]
        commits = [_FakeCommit(t) for t in titles]

        result = ve.summarize_commits(commits, clone_dir=None)

        expected = sum(1 for t in titles if es.is_substantive_commit(t))
        assert result["num_substantive"] == expected

    def test_uses_real_file_detection_when_clone_dir_given(self, monkeypatch):
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: clone_dir is not None)
        commits = [_FakeCommit("irrelevant title")]

        result = ve.summarize_commits(commits, clone_dir="/fake/clone")

        assert result["num_substantive"] == 1

    def test_num_sessions_counts_distinct_clusters_of_substantive_commits(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        commits = [
            _FakeCommit("Add new records", created_at=base),
            _FakeCommit("Update README", created_at=base - timedelta(minutes=10)),  # no substantiu
            _FakeCommit("Fix labeling errors", created_at=base - timedelta(days=2)),
        ]

        result = ve.summarize_commits(commits)

        assert result["num_substantive"] == 2
        assert result["num_sessions"] == 2


class TestClassifyDatasetEvidence:
    def test_error_takes_precedence(self):
        evidence = {"error": "[access_restricted] gated", "num_sessions": 5}
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "ERROR"

    def test_error_takes_precedence_even_for_criteri_a(self):
        evidence = {"error": "[access_restricted] gated", "eligibility_reason": "Criteri A: tags>=2", "num_sessions": 0}
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "ERROR"

    def test_criteri_a_is_always_tp_regardless_of_sessions(self):
        # El Criteri A (tags explícits) mai ha exigit dispersió temporal a
        # classify_dataset -- l'informe no hauria d'inventar-ne un de nou.
        evidence = {
            "eligibility_reason": "Criteri A: tags>=2 amb commits substantius",
            "num_sessions": 1,
            "error": "",
        }
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "TP"

    def test_criteri_a_is_tp_even_with_zero_sessions(self):
        evidence = {
            "eligibility_reason": "Criteri A: tags>=2 amb commits substantius",
            "num_sessions": 0,
            "error": "",
        }
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "TP"

    def test_criteri_b_two_or_more_sessions_is_tp(self):
        evidence = {
            "eligibility_reason": "Criteri B: substantive_commits>=2 dispersos >=24.0h",
            "num_sessions": 2,
            "error": "",
        }
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "TP"

    def test_criteri_b_one_session_is_review(self):
        evidence = {
            "eligibility_reason": "Criteri B: substantive_commits>=2 dispersos >=24.0h",
            "num_sessions": 1,
            "error": "",
        }
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "REVIEW"

    def test_criteri_b_zero_sessions_is_review(self):
        evidence = {
            "eligibility_reason": "Criteri B: substantive_commits>=2 dispersos >=24.0h",
            "num_sessions": 0,
            "error": "",
        }
        result = ve.classify_dataset_evidence(evidence)
        assert result["verdict"] == "REVIEW"


class TestGenerateMarkdownReport:
    def _sample_output(self):
        return {
            "generated_at": "2026-07-29T18:00:00",
            "source_csv": "/app/data/eligibility_report_2000_2.csv",
            "n_datasets": 3,
            "datasets": [
                {
                    "dataset_id": "org/tp-dataset",
                    "url": "https://huggingface.co/datasets/org/tp-dataset",
                    "eligibility_reason": "Criteri A: tags>=2 amb commits substantius",
                    "num_substantive": 3,
                    "num_sessions": 2,
                    "error": "",
                },
                {
                    "dataset_id": "org/review-dataset",
                    "url": "https://huggingface.co/datasets/org/review-dataset",
                    "eligibility_reason": "Criteri B: substantive_commits>=2 dispersos >=24.0h",
                    "num_substantive": 5,
                    "num_sessions": 1,
                    "error": "",
                },
                {
                    "dataset_id": "org/error-dataset",
                    "url": "https://huggingface.co/datasets/org/error-dataset",
                    "eligibility_reason": "Criteri B: substantive_commits>=2 dispersos >=24.0h",
                    "num_substantive": 0,
                    "num_sessions": 0,
                    "error": "[access_restricted] gated",
                },
            ],
        }

    def test_report_contains_one_row_per_dataset(self):
        report = ve.generate_markdown_report(self._sample_output())

        assert "org/tp-dataset" in report
        assert "org/review-dataset" in report
        assert "org/error-dataset" in report

    def test_report_aggregate_counts_are_correct(self):
        report = ve.generate_markdown_report(self._sample_output())

        assert "| Total elegibles | 3 |" in report
        assert "| Criteri A | 1 |" in report
        assert "| Criteri B | 2 |" in report
        assert "| **TP** (Criteri A, o Criteri B amb >=2 sessions) | 1 |" in report
        assert "| **REVIEW** (Criteri B amb 1 sessió, cal revisió humana) | 1 |" in report
        assert "| ERROR | 1 |" in report

    def test_report_handles_zero_datasets_without_dividing_by_zero(self):
        empty_output = {
            "generated_at": "2026-07-29T18:00:00",
            "source_csv": "/app/data/eligibility_report_2000_2.csv",
            "n_datasets": 0,
            "datasets": [],
        }
        report = ve.generate_markdown_report(empty_output)

        assert "N/A" in report
