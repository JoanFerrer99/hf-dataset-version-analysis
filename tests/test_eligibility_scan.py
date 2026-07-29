"""
Tests unitaris per a `notebooks/eligibility_scan.py`.

Cobreixen:
  1. `reservoir_sample_dataset_ids` només conserva identificadors (strings),
     mai els objectes originals -- aquest era el bug de memòria reportat.
  2. `compute_funnel_stats`: denominadors correctes de l'embut
     d'elegibilitat (separant accés restringit i errors dels no elegibles).
"""

import os
import random
from contextlib import contextmanager
from datetime import datetime, timedelta

import eligibility_scan as es


@contextmanager
def _no_git_clone(dataset_id):
    # Substitueix es.bare_clone als tests de classify_dataset() que no
    # exerceixen explícitament US-302: sense clonatge real (yield None),
    # classify_dataset recorre a l'heurística de títol (is_substantive_commit),
    # evitant una crida de xarxa real (i lenta/inestable) a cada test.
    yield None


class _FakeDatasetInfo:
    """
    Simula un huggingface_hub.hf_api.DatasetInfo "pesant": porta un atribut
    `.id` (l'únic que hauria de sobreviure al reservori) més un blob gran
    que no hauria de quedar-se enlloc un cop consumit l'iterador.
    """

    def __init__(self, dataset_id: str):
        self.id = dataset_id
        self.cardData = {"heavy": "x" * 10_000}
        self.siblings = list(range(1000))


# ---------------------------------------------------------------------------
# reservoir_sample_dataset_ids — el fix de memòria
# ---------------------------------------------------------------------------

class TestReservoirSampleDatasetIds:
    def test_reservoir_contains_only_string_ids_never_the_objects(self):
        items = [_FakeDatasetInfo(f"org/ds-{i}") for i in range(50)]
        reservoir, n_seen = es.reservoir_sample_dataset_ids(
            iter(items), sample_size=10, rng=random.Random(42), show_progress=False
        )

        assert n_seen == 50
        assert len(reservoir) == 10
        for entry in reservoir:
            assert isinstance(entry, str)
            assert not isinstance(entry, _FakeDatasetInfo)

    def test_population_smaller_than_sample_size_returns_everything(self):
        items = [_FakeDatasetInfo(f"org/ds-{i}") for i in range(3)]
        reservoir, n_seen = es.reservoir_sample_dataset_ids(
            iter(items), sample_size=10, rng=random.Random(1), show_progress=False
        )

        assert n_seen == 3
        assert sorted(reservoir) == ["org/ds-0", "org/ds-1", "org/ds-2"]

    def test_population_equal_to_sample_size(self):
        items = [_FakeDatasetInfo(f"org/ds-{i}") for i in range(10)]
        reservoir, n_seen = es.reservoir_sample_dataset_ids(
            iter(items), sample_size=10, rng=random.Random(7), show_progress=False
        )

        assert n_seen == 10
        assert len(reservoir) == 10
        assert sorted(reservoir) == sorted(f"org/ds-{i}" for i in range(10))

    def test_max_scanned_stops_iteration_early(self):
        items = [_FakeDatasetInfo(f"org/ds-{i}") for i in range(1000)]
        reservoir, n_seen = es.reservoir_sample_dataset_ids(
            iter(items), sample_size=5, max_scanned=20, rng=random.Random(3), show_progress=False
        )

        assert n_seen == 20
        assert len(reservoir) == 5

    def test_deterministic_with_seeded_rng(self):
        def make_items():
            return [_FakeDatasetInfo(f"org/ds-{i}") for i in range(200)]

        reservoir_a, _ = es.reservoir_sample_dataset_ids(
            iter(make_items()), sample_size=10, rng=random.Random(123), show_progress=False
        )
        reservoir_b, _ = es.reservoir_sample_dataset_ids(
            iter(make_items()), sample_size=10, rng=random.Random(123), show_progress=False
        )

        assert reservoir_a == reservoir_b

    def test_accepts_plain_strings_without_id_attribute(self):
        # iter_all_dataset_ids() ja produeix strings directament (no
        # DatasetInfo objects), així que el reservori ha de funcionar igual.
        reservoir, n_seen = es.reservoir_sample_dataset_ids(
            iter(["a", "b", "c"]), sample_size=2, rng=random.Random(5), show_progress=False
        )

        assert n_seen == 3
        assert len(reservoir) == 2
        assert all(isinstance(x, str) for x in reservoir)


# ---------------------------------------------------------------------------
# has_time_dispersed_substantive_commits — PROPOSTA revisió Criteri B (US-108)
# ---------------------------------------------------------------------------

class TestHasTimeDispersedSubstantiveCommits:
    def test_less_than_two_valid_times_is_false(self):
        assert es.has_time_dispersed_substantive_commits([]) is False
        assert es.has_time_dispersed_substantive_commits([datetime(2026, 1, 1)]) is False

    def test_none_values_are_ignored_when_counting(self):
        assert es.has_time_dispersed_substantive_commits([None, datetime(2026, 1, 1), None]) is False

    def test_commits_within_the_minimum_gap_are_not_dispersed(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base - timedelta(minutes=59)]
        assert es.has_time_dispersed_substantive_commits(times, min_gap_hours=1.0) is False

    def test_commits_at_or_beyond_the_minimum_gap_are_dispersed(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base - timedelta(hours=1)]
        assert es.has_time_dispersed_substantive_commits(times, min_gap_hours=1.0) is True

    def test_only_the_span_between_extremes_matters_not_the_count(self):
        # Molts commits intermedis dins de la mateixa finestra no haurien
        # de fer variar el resultat: només importa el rang (max - min).
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base - timedelta(minutes=m) for m in range(0, 30, 2)]
        assert es.has_time_dispersed_substantive_commits(times, min_gap_hours=1.0) is False


# ---------------------------------------------------------------------------
# is_substantive_path / get_changed_files / determine_commit_substantive /
# bare_clone — US-302: detecció real de fitxers modificats per commit
# ---------------------------------------------------------------------------

class TestIsSubstantivePath:
    def test_metadata_files_are_not_substantive(self):
        assert es.is_substantive_path("README.md") is False
        assert es.is_substantive_path(".gitattributes") is False
        assert es.is_substantive_path("dataset_infos.json") is False

    def test_nested_metadata_files_are_not_substantive(self):
        assert es.is_substantive_path("some/dir/README.md") is False

    def test_github_folder_is_not_substantive(self):
        assert es.is_substantive_path(".github") is False
        assert es.is_substantive_path(".github/workflows/ci.yml") is False

    def test_data_files_are_substantive(self):
        assert es.is_substantive_path("data/chunk-000/file-000.parquet") is True
        assert es.is_substantive_path("videos/observation.images.top/chunk-000/file-000.mp4") is True

    def test_unknown_files_default_to_substantive(self):
        assert es.is_substantive_path("meta/info.json") is True


class TestGetChangedFiles:
    def test_parses_added_modified_deleted_lines(self, monkeypatch):
        fake_output = "A\tdata/new_file.parquet\nM\tmeta/info.json\nD\tdata/old_file.parquet\n"
        monkeypatch.setattr(
            es.subprocess, "run",
            lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout=fake_output),
        )
        result = es.get_changed_files("/fake/clone", "abc123")
        assert result == ["data/new_file.parquet", "meta/info.json", "data/old_file.parquet"]

    def test_parses_rename_lines_keeping_new_path(self, monkeypatch):
        fake_output = "R100\told_name.csv\tnew_name.csv\n"
        monkeypatch.setattr(
            es.subprocess, "run",
            lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout=fake_output),
        )
        result = es.get_changed_files("/fake/clone", "abc123")
        assert result == ["new_name.csv"]

    def test_returns_none_on_nonzero_returncode(self, monkeypatch):
        monkeypatch.setattr(
            es.subprocess, "run",
            lambda *a, **kw: _FakeCompletedProcess(returncode=128, stdout=""),
        )
        assert es.get_changed_files("/fake/clone", "abc123") is None

    def test_returns_none_on_timeout(self, monkeypatch):
        def boom(*a, **kw):
            raise es.subprocess.TimeoutExpired(cmd="git show", timeout=10)

        monkeypatch.setattr(es.subprocess, "run", boom)
        assert es.get_changed_files("/fake/clone", "abc123") is None

    def test_empty_output_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            es.subprocess, "run",
            lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout=""),
        )
        assert es.get_changed_files("/fake/clone", "abc123") == []


class TestDetermineCommitSubstantive:
    def test_falls_back_to_title_heuristic_when_no_clone_dir(self):
        assert es.determine_commit_substantive(_FakeCommit("Add new records"), None) is True
        assert es.determine_commit_substantive(_FakeCommit("Update README"), None) is False

    def test_uses_real_files_when_clone_available(self, monkeypatch):
        # Títol genèric (no substantiu segons l'heurística) però toca
        # dades reals -> substantiu segons la inspecció de fitxers.
        commit = _FakeCommit("Merge pull request #3")
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: ["data/file.parquet"])
        assert es.determine_commit_substantive(commit, "/fake/clone") is True

    def test_metadata_only_files_are_not_substantive_even_with_generic_title(self, monkeypatch):
        commit = _FakeCommit("Update stuff")
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: ["README.md", ".gitattributes"])
        assert es.determine_commit_substantive(commit, "/fake/clone") is False

    def test_falls_back_to_title_heuristic_when_get_changed_files_fails(self, monkeypatch):
        commit = _FakeCommit("Add new records")
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: None)
        assert es.determine_commit_substantive(commit, "/fake/clone") is True


class TestBareClone:
    def test_yields_directory_on_success_and_cleans_up_after(self, monkeypatch):
        monkeypatch.setattr(es.subprocess, "run", lambda *a, **kw: _FakeCompletedProcess(returncode=0))

        with es.bare_clone("org/ds") as clone_dir:
            assert clone_dir is not None
            assert os.path.isdir(clone_dir)
            captured_dir = clone_dir

        assert not os.path.exists(captured_dir)

    def test_yields_none_on_nonzero_returncode(self, monkeypatch):
        monkeypatch.setattr(es.subprocess, "run", lambda *a, **kw: _FakeCompletedProcess(returncode=128))

        with es.bare_clone("org/ds") as clone_dir:
            assert clone_dir is None

    def test_yields_none_on_timeout_and_still_cleans_up(self, monkeypatch):
        def boom(*a, **kw):
            raise es.subprocess.TimeoutExpired(cmd="git clone", timeout=30)

        monkeypatch.setattr(es.subprocess, "run", boom)

        with es.bare_clone("org/ds") as clone_dir:
            assert clone_dir is None

    def test_yields_none_when_git_binary_is_missing(self, monkeypatch):
        # Regressió: sense 'git' al PATH (p.e. una imatge Docker on s'ha
        # oblidat instal·lar-lo), bare_clone ha de recórrer al fallback
        # de títol per a TOTS els datasets -- no ha de petar el pipeline.
        def boom(*a, **kw):
            raise FileNotFoundError("git no trobat")

        monkeypatch.setattr(es.subprocess, "run", boom)

        with es.bare_clone("org/ds") as clone_dir:
            assert clone_dir is None


# ---------------------------------------------------------------------------
# compute_funnel_stats — correcció dels bugs de denominador
# ---------------------------------------------------------------------------

class TestComputeFunnelStats:
    def test_eligible_proportion_excludes_errors_and_access_restricted(self):
        # Reproduint el cas real observat: 1000 mostrats, 591 errors,
        # 22 dels quals eren en realitat 403 (access_restricted).
        counts = es.FunnelCounts(
            total_scanned=1000,
            eligible=6,
            ineligible=1000 - 6 - 22 - 569,
            access_restricted=22,
            errors=569,
        )
        stats = es.compute_funnel_stats(counts)

        # El denominador vàlid exclou errors i access_restricted.
        assert stats["eligible_proportion"] == round(6 / (6 + counts.ineligible), 4)
        # Molt més alt que 6/1000 = 0.006 (l'estimació esbiaixada d'abans).
        assert stats["eligible_proportion"] > 6 / 1000

    def test_ineligible_is_not_always_zero(self):
        counts = es.FunnelCounts(
            total_scanned=100, eligible=3, ineligible=90, access_restricted=2, errors=5
        )
        stats = es.compute_funnel_stats(counts)
        assert stats["ineligible"] == 90

    def test_eligible_proportion_of_attempts_includes_everything(self):
        counts = es.FunnelCounts(
            total_scanned=100, eligible=10, ineligible=70, access_restricted=10, errors=10
        )
        stats = es.compute_funnel_stats(counts)
        assert stats["eligible_proportion_of_attempts"] == round(10 / 100, 4)

    def test_handles_zero_classified_without_dividing_by_zero(self):
        counts = es.FunnelCounts(
            total_scanned=50, eligible=0, ineligible=0, access_restricted=10, errors=40
        )
        stats = es.compute_funnel_stats(counts)
        assert stats["eligible_proportion"] == 0.0
        assert stats["eligible_proportion_of_attempts"] == 0.0
        assert stats["estimated_eligible_in_population"] == 0


# ---------------------------------------------------------------------------
# classify_dataset — el "status" ha d'estar sempre present
# ---------------------------------------------------------------------------
#
# write_results() fa df["status"] == "error"/"access_restricted" sobre TOTES
# les files. Si una fila d'èxit no tingués la clau "status", pd.DataFrame
# podria acabar sense aquesta columna quan cap fila del lot ha fallat mai,
# provocant un KeyError. Aquests tests exerceixen classify_dataset() de
# veritat (amb list_repo_refs/list_repo_commits substituïts per fakes, sense
# cap crida real a l'API) per comprovar que "status" hi és sempre.

class _FakeRefs:
    def __init__(self, tags=None, branches=None):
        self.tags = tags or []
        self.branches = branches or []


class _FakeCommit:
    def __init__(self, title, created_at=None, commit_id="abc123"):
        self.title = title
        self.created_at = created_at
        self.commit_id = commit_id


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class TestClassifyDatasetResultShape:
    def test_eligible_via_tags_requires_two_substantive_commits(self, monkeypatch, tmp_path):
        # >=2 tags amb >=2 commits substantius (mateix llindar que el
        # Criteri B) -> elegible via Criteri A.
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([
                _FakeCommit("Update README"),
                _FakeCommit("Add new records"),
                _FakeCommit("Fix labeling errors"),
            ]),
        )
        monkeypatch.setattr(es, "bare_clone", _no_git_clone)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is True
        assert result["eligibility_reason"] == "Criteri A: tags>=2 amb commits substantius"

    def test_tags_with_only_one_substantive_commit_are_not_eligible(self, monkeypatch, tmp_path):
        # >=2 tags però només 1 commit substantiu (per sota del llindar de
        # 2) -> NO elegible via Criteri A.
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([_FakeCommit("Update README"), _FakeCommit("Add new records")]),
        )
        monkeypatch.setattr(es, "bare_clone", _no_git_clone)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is False

    def test_tags_without_any_substantive_commit_are_not_eligible(self, monkeypatch, tmp_path):
        # >=2 tags però TOTS els commits són purament de metadades/documentació
        # (el cas improbable que motiva aquest guard) -> NO elegible via Criteri A.
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([_FakeCommit("Update README"), _FakeCommit("fix typo")]),
        )
        monkeypatch.setattr(es, "bare_clone", _no_git_clone)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is False

    def test_tags_only_mode_skips_the_substantive_commit_check(self, monkeypatch, tmp_path):
        # tags_only=True: >=2 tags n'hi ha prou, sense consultar commits.
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: (_ for _ in ()).throw(AssertionError("no s'hauria de cridar")),
        )
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds", tags_only=True)

        assert result["eligible"] is True
        assert result["eligibility_reason"] == "Criteri A: tags>=2"

    def test_status_is_classified_when_ineligible(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs())
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is False
        assert result["eligibility_reason"] != ""

    def test_status_is_access_restricted_on_403(self, monkeypatch, tmp_path):
        import httpx
        from huggingface_hub.utils import HfHubHTTPError

        def gated(**kw):
            request = httpx.Request("GET", "https://huggingface.co/api/datasets/org/ds/refs")
            response = httpx.Response(403, request=request)
            raise HfHubHTTPError("gated", response=response)

        monkeypatch.setattr(es, "list_repo_refs", gated)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "access_restricted"
        assert result["eligible"] is False

    def test_status_is_error_on_unexpected_exception(self, monkeypatch, tmp_path):
        def boom(**kw):
            raise ValueError("something unexpected")

        monkeypatch.setattr(es, "list_repo_refs", boom)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "error"
        assert result["eligible"] is False

    def test_eligible_via_branches_requires_time_dispersed_substantive_commits(
        self, monkeypatch, tmp_path
    ):
        # >=2 branches amb >=2 commits substantius separats per >=24h (llindar
        # per defecte, vegeu MIN_SUBSTANTIVE_GAP_HOURS) -> elegible via Criteri B.
        now = datetime(2026, 1, 1, 12, 0, 0)
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(branches=["main", "dev"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([
                _FakeCommit("Add new records", created_at=now),
                _FakeCommit("Update README", created_at=now - timedelta(minutes=30)),
                _FakeCommit("Fix labeling errors", created_at=now - timedelta(days=2)),
            ]),
        )
        monkeypatch.setattr(es, "bare_clone", _no_git_clone)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is True
        assert result["eligibility_reason"].startswith("Criteri B")

    def test_branches_with_substantive_commits_clustered_in_time_are_not_eligible(
        self, monkeypatch, tmp_path
    ):
        # Patró LeRobot: desenes de commits substantius (segons la
        # heurística de títol) però tots dins d'una única sessió de pujada
        # de pocs minuts -> NO elegible via Criteri B (US-108).
        now = datetime(2026, 1, 1, 12, 0, 0)
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(branches=["main", "dev"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([
                _FakeCommit("Add new episode", created_at=now),
                _FakeCommit("Add new episode", created_at=now - timedelta(minutes=2)),
                _FakeCommit("Add new episode", created_at=now - timedelta(minutes=5)),
            ]),
        )
        monkeypatch.setattr(es, "bare_clone", _no_git_clone)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is False

    def test_result_has_status_key_regardless_of_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))
        monkeypatch.setattr(
            es, "list_repo_commits", lambda **kw: iter([_FakeCommit("Add new records")])
        )
        monkeypatch.setattr(es, "bare_clone", _no_git_clone)

        for fake_refs_fn in (
            lambda **kw: _FakeRefs(tags=["v1", "v2"]),
            lambda **kw: _FakeRefs(),
            lambda **kw: (_ for _ in ()).throw(ValueError("boom")),
        ):
            monkeypatch.setattr(es, "list_repo_refs", fake_refs_fn)
            result = es.classify_dataset("org/ds")
            assert "status" in result
            assert result["status"] in ("classified", "access_restricted", "error")
