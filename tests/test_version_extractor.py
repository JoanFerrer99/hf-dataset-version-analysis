"""
Tests unitaris per a `notebooks/version_extractor.py` (US-201 + US-202).

Cobreixen:
  1. Funcions pures: ordenació cronològica, suma de mides, format d'autors.
  2. `build_sessions_from_commits`: agrupació de commits substantius en
     sessions (Criteri B), reutilitzant `determine_commit_substantive` i
     `cluster_commit_times` reals.
  3. `extract_versions_for_dataset`: bifurcació tag/sessió segons
     `eligibility_reason`, tolerància a errors parcials.
  4. `fetch_tree_size_bytes`: `list_repo_tree` (generador lazy) es consumeix
     DINS de la crida reintentada -- no abans (Finding B).
  5. `run_extraction`: una fallada de dataset sencer no atura els altres.

Cap d'aquests tests fa crides reals a l'API de Hugging Face ni espera temps
real (s'injecten `sleep_fn`/`jitter_fn` fake quan cal exercir `with_retry`).
"""

from datetime import datetime, timedelta

import httpx
import pandas as pd
import pytest
from huggingface_hub.utils import HfHubHTTPError

import version_extractor as ve
from eligibility_scan import MIN_SUBSTANTIVE_GAP_HOURS


def make_http_error(status_code: int, message: str = "boom") -> HfHubHTTPError:
    request = httpx.Request("GET", "https://huggingface.co/api/datasets/foo/tree/main")
    response = httpx.Response(status_code, request=request)
    return HfHubHTTPError(message, response=response)


class _FakeCommit:
    def __init__(self, title, created_at=None, commit_id="abc123", authors=None):
        self.title = title
        self.created_at = created_at
        self.commit_id = commit_id
        self.authors = authors or []


class _FakeTag:
    def __init__(self, name, target_commit="sha-tag"):
        self.name = name
        self.target_commit = target_commit


class _FakeRefs:
    def __init__(self, tags=None, branches=None):
        self.tags = tags or []
        self.branches = branches or []


class _FakeRepoFile:
    def __init__(self, size):
        self.size = size


class _FakeRepoFolder:
    pass


NO_RETRY_CONFIG = {
    "max_retries": 2,
    "base_wait_s": 0.0,
    "max_wait_s": 0.0,
    "sleep_fn": lambda seconds: None,
    "jitter_fn": lambda: 0.0,
}


# ---------------------------------------------------------------------------
# Funcions pures
# ---------------------------------------------------------------------------


class TestOrderVersionsByDate:
    def test_orders_chronologically_oldest_first(self):
        versions = [
            {"commit_date": "2024-03-01T00:00:00"},
            {"commit_date": "2024-01-01T00:00:00"},
            {"commit_date": "2024-02-01T00:00:00"},
        ]
        ordered = ve.order_versions_by_date(versions)
        assert [v["commit_date"] for v in ordered] == [
            "2024-01-01T00:00:00", "2024-02-01T00:00:00", "2024-03-01T00:00:00",
        ]
        assert [v["version_order"] for v in ordered] == [1, 2, 3]

    def test_none_dates_sort_last_but_are_kept(self):
        versions = [{"commit_date": None}, {"commit_date": "2024-01-01T00:00:00"}]
        ordered = ve.order_versions_by_date(versions)
        assert len(ordered) == 2
        assert ordered[0]["commit_date"] == "2024-01-01T00:00:00"
        assert ordered[1]["commit_date"] is None
        assert ordered[1]["version_order"] == 2

    def test_empty_list(self):
        assert ve.order_versions_by_date([]) == []


class TestSumTreeSize:
    def test_sums_file_sizes_and_ignores_folders(self):
        entries = [_FakeRepoFile(100), _FakeRepoFolder(), _FakeRepoFile(50)]
        assert ve.sum_tree_size(entries) == 150

    def test_empty_is_zero(self):
        assert ve.sum_tree_size([]) == 0


class TestFormatAuthors:
    def test_joins_unique_authors_preserving_order(self):
        assert ve.format_authors(["alice", "bob", "alice"]) == "alice,bob"

    def test_none_or_empty_is_empty_string(self):
        assert ve.format_authors(None) == ""
        assert ve.format_authors([]) == ""


# ---------------------------------------------------------------------------
# build_sessions_from_commits — Criteri B: sessió = versió
# ---------------------------------------------------------------------------


class TestBuildSessionsFromCommits:
    def test_commits_within_gap_form_one_session(self, monkeypatch):
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: True)
        base = datetime(2026, 1, 1, 12, 0, 0)
        commits = [
            _FakeCommit("Add records", created_at=base, commit_id="c1", authors=["alice"]),
            _FakeCommit("Add more records", created_at=base + timedelta(hours=1), commit_id="c2", authors=["bob"]),
        ]
        sessions = ve.build_sessions_from_commits(commits, clone_dir=None)
        assert len(sessions) == 1
        assert sessions[0]["commit_sha"] == "c2"
        assert sessions[0]["session_commit_count"] == 2
        assert sessions[0]["authors"] == ["alice", "bob"]

    def test_commits_beyond_gap_form_separate_sessions(self, monkeypatch):
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: True)
        base = datetime(2026, 1, 1, 0, 0, 0)
        commits = [
            _FakeCommit("Session 1", created_at=base, commit_id="c1"),
            _FakeCommit(
                "Session 2", created_at=base + timedelta(hours=MIN_SUBSTANTIVE_GAP_HOURS + 1), commit_id="c2"
            ),
        ]
        sessions = ve.build_sessions_from_commits(commits, clone_dir=None)
        assert len(sessions) == 2
        assert [s["commit_sha"] for s in sessions] == ["c1", "c2"]

    def test_non_substantive_commits_are_excluded(self, monkeypatch):
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: False)
        commits = [_FakeCommit("Update README", created_at=datetime(2026, 1, 1))]
        assert ve.build_sessions_from_commits(commits, clone_dir=None) == []

    def test_commits_without_created_at_are_ignored(self, monkeypatch):
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: True)
        commits = [_FakeCommit("Add records", created_at=None)]
        assert ve.build_sessions_from_commits(commits, clone_dir=None) == []

    def test_sessions_are_returned_in_chronological_order(self, monkeypatch):
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: True)
        base = datetime(2026, 1, 1)
        gap = timedelta(hours=MIN_SUBSTANTIVE_GAP_HOURS + 1)
        commits = [
            _FakeCommit("Later", created_at=base + 2 * gap, commit_id="late"),
            _FakeCommit("Earlier", created_at=base, commit_id="early"),
        ]
        sessions = ve.build_sessions_from_commits(commits, clone_dir=None)
        assert [s["commit_sha"] for s in sessions] == ["early", "late"]


# ---------------------------------------------------------------------------
# extract_versions_for_dataset — bifurcació tag vs sessió
# ---------------------------------------------------------------------------


class TestExtractVersionsForDataset:
    def test_criteria_a_uses_tags_as_versions(self, monkeypatch):
        monkeypatch.setattr(ve, "fetch_tags", lambda *a, **kw: [_FakeTag("v1", "sha1"), _FakeTag("v2", "sha2")])
        monkeypatch.setattr(
            ve, "fetch_commit_metadata",
            lambda dataset_id, revision, token, cfg: _FakeCommit(
                "tag commit", created_at=datetime(2026, 1, 1) if revision == "v1" else datetime(2026, 2, 1),
                authors=["alice"],
            ),
        )
        rows = ve.extract_versions_for_dataset(
            "org/ds", "Criteri A: tags>=2 amb commits substantius", "tok", ve.RETRY_CONFIG, compute_size=False
        )
        assert [r.version_label for r in rows] == ["v1", "v2"]
        assert all(r.version_source == "tag" for r in rows)
        assert all(r.status == "ok_no_size" for r in rows)
        assert rows[0].version_order == 1 and rows[1].version_order == 2

    def test_criteria_a_with_zero_tags_is_legitimately_empty(self, monkeypatch):
        monkeypatch.setattr(ve, "fetch_tags", lambda *a, **kw: [])
        rows = ve.extract_versions_for_dataset(
            "org/ds", "Criteri A: tags>=2 amb commits substantius", "tok", ve.RETRY_CONFIG, compute_size=False
        )
        assert rows == []

    def test_criteria_b_uses_commit_sessions_as_versions(self, monkeypatch):
        base = datetime(2026, 1, 1)
        monkeypatch.setattr(
            ve, "list_repo_commits",
            lambda **kw: [_FakeCommit("Add data", created_at=base, commit_id="c1", authors=["alice"])],
        )
        monkeypatch.setattr(ve, "bare_clone", lambda dataset_id: _NoGitClone())
        monkeypatch.setattr(ve, "determine_commit_substantive", lambda commit, clone_dir: True)

        rows = ve.extract_versions_for_dataset(
            "org/ds", "Criteri B: substantive_commits>=2 dispersos >=6.0h", "tok", ve.RETRY_CONFIG,
            compute_size=False,
        )
        assert len(rows) == 1
        assert rows[0].version_source == "commit_session"
        assert rows[0].version_label == "session-1"
        assert rows[0].commit_sha == "c1"

    def test_partial_tag_metadata_failure_keeps_other_versions(self, monkeypatch):
        monkeypatch.setattr(ve, "fetch_tags", lambda *a, **kw: [_FakeTag("v1", "sha1"), _FakeTag("v2", "sha2")])

        def flaky_metadata(dataset_id, revision, token, cfg):
            if revision == "v1":
                raise make_http_error(403)
            return _FakeCommit("ok", created_at=datetime(2026, 1, 1), authors=["alice"])

        monkeypatch.setattr(ve, "fetch_commit_metadata", flaky_metadata)
        rows = ve.extract_versions_for_dataset(
            "org/ds", "Criteri A: tags>=2 amb commits substantius", "tok", ve.RETRY_CONFIG, compute_size=False
        )
        assert len(rows) == 2
        by_label = {r.version_label: r for r in rows}
        assert by_label["v1"].status == "commit_error"
        assert by_label["v2"].status == "ok_no_size"

    def test_fetch_tags_failure_propagates(self, monkeypatch):
        def boom(*a, **kw):
            raise make_http_error(403)

        monkeypatch.setattr(ve, "fetch_tags", boom)
        with pytest.raises(HfHubHTTPError):
            ve.extract_versions_for_dataset(
                "org/ds", "Criteri A: tags>=2 amb commits substantius", "tok", ve.RETRY_CONFIG, compute_size=False
            )

    def test_size_error_does_not_drop_the_version(self, monkeypatch):
        monkeypatch.setattr(ve, "fetch_tags", lambda *a, **kw: [_FakeTag("v1", "sha1")])
        monkeypatch.setattr(
            ve, "fetch_commit_metadata",
            lambda *a, **kw: _FakeCommit("ok", created_at=datetime(2026, 1, 1), authors=["alice"]),
        )

        def boom_size(*a, **kw):
            raise make_http_error(500)

        monkeypatch.setattr(ve, "fetch_tree_size_bytes", boom_size)
        rows = ve.extract_versions_for_dataset(
            "org/ds", "Criteri A: tags>=2 amb commits substantius", "tok", ve.RETRY_CONFIG, compute_size=True
        )
        assert len(rows) == 1
        assert rows[0].status == "size_error"
        assert rows[0].approx_size_bytes is None


class _NoGitClone:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# fetch_tree_size_bytes — Finding B: list_repo_tree és un generador lazy
# ---------------------------------------------------------------------------


class TestFetchTreeSizeBytes:
    def test_generator_result_is_fully_consumed_and_summed(self, monkeypatch):
        monkeypatch.setattr(
            ve, "list_repo_tree",
            lambda **kw: iter([_FakeRepoFile(10), _FakeRepoFolder(), _FakeRepoFile(5)]),
        )
        total = ve.fetch_tree_size_bytes("org/ds", "sha123", "tok", NO_RETRY_CONFIG)
        assert total == 15

    def test_lazy_failure_on_iteration_is_retried_not_missed(self, monkeypatch):
        # list_repo_tree és un generador: l'excepció real no surt en
        # CRIDAR-lo, sinó en ITERAR-lo. Aquest test simula exactament això
        # -- si fetch_tree_size_bytes passés la funció crua a with_retry
        # sense embolicar-la en un tancament que la consumeixi, aquest
        # 429 mai es capturaria i el test fallaria amb HfHubHTTPError sense
        # cap reintent.
        calls = {"n": 0}

        def flaky_list_repo_tree(**kwargs):
            calls["n"] += 1
            attempt = calls["n"]

            def gen():
                if attempt == 1:
                    raise make_http_error(429)
                yield _FakeRepoFile(42)

            return gen()

        monkeypatch.setattr(ve, "list_repo_tree", flaky_list_repo_tree)
        total = ve.fetch_tree_size_bytes("org/ds", "sha123", "tok", NO_RETRY_CONFIG)
        assert total == 42
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# run_extraction — una fallada de dataset no n'atura d'altres
# ---------------------------------------------------------------------------


class TestRunExtraction:
    def test_one_dataset_failure_does_not_stop_the_others(self, monkeypatch, tmp_path):
        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([
            {"dataset_id": "org/broken", "eligible": True, "eligibility_reason": "Criteri A: tags>=2 amb commits substantius"},
            {"dataset_id": "org/ok", "eligible": True, "eligibility_reason": "Criteri A: tags>=2 amb commits substantius"},
            {"dataset_id": "org/skip", "eligible": False, "eligibility_reason": "ineligible: ..."},
        ]).to_csv(input_csv, index=False)

        def fake_extract(dataset_id, eligibility_reason, token, cfg, compute_size=True):
            if dataset_id == "org/broken":
                raise make_http_error(403)
            return [
                ve.VersionRow(
                    dataset_id=dataset_id, version_label="v1", version_order=1, version_source="tag",
                    commit_sha="sha1", commit_date="2026-01-01T00:00:00", authors="alice",
                    approx_size_bytes=None, session_commit_count=1, status="ok_no_size",
                )
            ]

        monkeypatch.setattr(ve, "extract_versions_for_dataset", fake_extract)
        monkeypatch.setattr(ve, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        output_csv = tmp_path / "versions.csv"
        summary = ve.run_extraction(str(input_csv), str(output_csv), "tok", ve.RETRY_CONFIG, compute_size=False)

        assert summary["n_eligible"] == 2
        assert summary["n_dataset_level_failures"] == 1
        assert summary["n_rows_written"] == 1

        out_df = pd.read_csv(output_csv)
        assert list(out_df["dataset_id"]) == ["org/ok"]

        failures_df = pd.read_csv(tmp_path / "failures.csv")
        assert failures_df.iloc[0]["source"] == "version_extraction"
        assert failures_df.iloc[0]["dataset_id"] == "org/broken"


# ---------------------------------------------------------------------------
# get_next_run_id
# ---------------------------------------------------------------------------


class TestGetNextRunId:
    def test_no_existing_files_starts_at_one(self, tmp_path):
        assert ve.get_next_run_id(str(tmp_path)) == 1

    def test_picks_highest_existing_id_plus_one(self, tmp_path):
        (tmp_path / "versions_1.csv").write_text("")
        (tmp_path / "versions_3.csv").write_text("")
        (tmp_path / "versions_2.csv").write_text("")
        assert ve.get_next_run_id(str(tmp_path)) == 4

    def test_ignores_unrelated_files(self, tmp_path):
        (tmp_path / "versions_summary_5.json").write_text("")
        (tmp_path / "eligibility_report_2000_5.csv").write_text("")
        assert ve.get_next_run_id(str(tmp_path)) == 1
