"""
Tests unitaris per a `notebooks/validate_eligible.py` (US-108).

Només cobreix `summarize_commits`, l'única funció pura sense crides a
l'API. `gather_evidence_for_dataset` es deixa fora de l'abast dels tests
unitaris (és essencialment un embolcall prim de dues crides a l'API +
gestió d'errors ja coberta per `tests/test_errors.py`); validar-la
requeriria mockejar `list_repo_refs`/`list_repo_commits` de manera molt
similar als tests ja existents de `classify_dataset` a
`tests/test_eligibility_scan.py`, sense afegir cobertura nova rellevant.
"""

import validate_eligible as ve


class _FakeCommit:
    def __init__(self, title, commit_id="abc123", created_at=None):
        self.title = title
        self.commit_id = commit_id
        self.created_at = created_at


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

    def test_all_non_substantive_commits(self):
        commits = [
            _FakeCommit("Update README"),
            _FakeCommit("Update dataset_infos"),
            _FakeCommit("fix typo"),
        ]

        result = ve.summarize_commits(commits)

        assert result["num_substantive"] == 0

    def test_matches_is_substantive_commit_heuristic_exactly(self):
        # Garanteix que summarize_commits fa servir literalment la
        # mateixa heurística que classify_dataset (i no una còpia que es
        # pugui desincronitzar amb el temps).
        titles = ["Add new records", "readme update", "Fix bug in labels", "license change"]
        commits = [_FakeCommit(t) for t in titles]

        result = ve.summarize_commits(commits)

        expected = sum(1 for t in titles if ve.is_substantive_commit(t))
        assert result["num_substantive"] == expected
