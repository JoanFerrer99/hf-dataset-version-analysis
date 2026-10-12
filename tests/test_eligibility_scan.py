"""
Tests unitaris per a `src/eligibility_scan.py`.

Cobreixen:
  1. `reservoir_sample_dataset_ids` només conserva identificadors (strings),
     mai els objectes originals -- aquest era el bug de memòria reportat.
  2. `compute_funnel_stats`: denominadors correctes de l'embut
     d'elegibilitat (separant accés restringit i errors dels no elegibles).
"""

import os
import random
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import eligibility_scan as es


class _FakeSibling:
    def __init__(self, rfilename):
        self.rfilename = rfilename


class _FakeRepoInfo:
    """Resposta simulada de `dataset_info`: només la llista de fitxers (`siblings`)."""

    def __init__(self, files):
        self.siblings = [_FakeSibling(f) for f in files]


def _current_files(monkeypatch, files):
    """Simula els fitxers de la versió actual que retorna l'API (`list_current_files`)."""
    calls = []
    monkeypatch.setattr(es, "dataset_info", lambda **kw: calls.append(kw["repo_id"]) or _FakeRepoInfo(files))
    return calls


@pytest.fixture(autouse=True)
def _repo_with_a_table(monkeypatch):
    # Per defecte, la versió actual té una taula: cap test fa crides reals a l'API.
    _current_files(monkeypatch, ["README.md", "data/train.csv"])


@contextmanager
def _no_git_clone(dataset_id):
    # Sense clon (yield None): cap commit no compta, perquè no se sap quins
    # fitxers toca. Evita una crida de xarxa real a cada test.
    yield None


def _files_by_title(monkeypatch):
    """
    Clon fals on cada commit toca fitxers segons el títol: "README"/"typo" →
    `README.md` (no compta); qualsevol altre → `data/train.csv` (dades tabulars).
    `_FakeCommit` usa el títol com a `commit_id`, que és el que rep `get_changed_files`.
    """
    def changed(clone_dir, sha):
        return ["README.md"] if any(w in sha.lower() for w in ("readme", "typo")) else ["data/train.csv"]

    monkeypatch.setattr(es, "bare_clone", _fake_git_clone)
    monkeypatch.setattr(es, "get_changed_files", changed)


@contextmanager
def _fake_git_clone(dataset_id):
    # Com _no_git_clone, però amb un directori (fals): així `is_tabular_commit`
    # consulta `get_changed_files`, que cada test substitueix.
    yield "/fake/clone"


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

    def test_commits_beyond_the_minimum_gap_are_dispersed(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base - timedelta(hours=1, seconds=1)]
        assert es.has_time_dispersed_substantive_commits(times, min_gap_hours=1.0) is True

    def test_commits_exactly_at_the_gap_are_still_one_session(self):
        # cluster_commit_times exigeix MES DE gap_hours per obrir una
        # sessio nova ("mes de", no "com a minim") -- exactament al
        # llindar es queda a la MATEIXA sessio. Abans aquesta funcio
        # comprovava `span >= gap_hours` (inclusiu), inconsistent amb
        # cluster_commit_times -- ara delega a la mateixa funcio i
        # hereta el mateix criteri estricte arreu del pipeline.
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base - timedelta(hours=1)]
        assert es.has_time_dispersed_substantive_commits(times, min_gap_hours=1.0) is False

    def test_dense_commits_spanning_a_wide_interval_are_still_one_session(self):
        # Regressio real: abans, una UNICA sessio densa (cap buit intern
        # per sobre del llindar) amb un interval TOTAL ampli (per sobre
        # del llindar) es comptava incorrectament com "dispersa" --
        # nomes mirava l'interval entre extrems, no si real ment hi havia
        # >=2 sessions. 20 commits cada 5h (gaps sempre <6h) sumen 95h
        # d'interval total, per sobre del llindar de 6h, PERO segueix
        # sent UNA sola sessio real (cap buit intern supera les 6h).
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base - timedelta(hours=5 * i) for i in range(20)]
        assert es.has_time_dispersed_substantive_commits(times, min_gap_hours=6.0) is False

    def test_two_real_sessions_are_dispersed(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        session_a = [base - timedelta(minutes=m) for m in range(0, 30, 10)]
        session_b = [base - timedelta(hours=10, minutes=m) for m in range(0, 30, 10)]
        assert es.has_time_dispersed_substantive_commits(session_a + session_b, min_gap_hours=6.0) is True


# ---------------------------------------------------------------------------
# is_substantive_path / get_changed_files / is_tabular_commit /
# bare_clone — US-302: detecció real de fitxers modificats per commit
# ---------------------------------------------------------------------------

class TestIsSubstantivePath:
    def test_metadata_files_are_not_substantive(self):
        assert es.is_substantive_path("README.md") is False
        assert es.is_substantive_path(".gitattributes") is False
        assert es.is_substantive_path("dataset_infos.json") is False
        assert es.is_substantive_path("changelog.json") is False

    def test_nested_metadata_files_are_not_substantive(self):
        assert es.is_substantive_path("some/dir/README.md") is False

    def test_github_folder_is_not_substantive(self):
        assert es.is_substantive_path(".github") is False
        assert es.is_substantive_path(".github/workflows/ci.yml") is False

    def test_data_files_are_substantive(self):
        assert es.is_substantive_path("data/chunk-000/file-000.parquet") is True
        assert es.is_substantive_path("videos/observation.images.top/chunk-000/file-000.mp4") is True

    def test_unknown_extensions_default_to_substantive(self):
        # Extensió genuïnament no prevista (ni allowlist ni denylist):
        # fail-open, però registrat (log.debug) per revisió futura.
        assert es.is_substantive_path("some/dir/notes.xyz") is True

    def test_meta_prefix_files_are_not_substantive_regardless_of_extension(self):
        # Trobat empíricament (calibratge agost 2026): tot el que penja de
        # meta/ és metadada a LeRobot, encara que l'extensió normalment
        # indiqui dades reals (.parquet, .jsonl).
        assert es.is_substantive_path("meta/info.json") is False
        assert es.is_substantive_path("meta/stats.json") is False
        assert es.is_substantive_path("meta/episodes.jsonl") is False
        assert es.is_substantive_path("meta/episodes_stats.jsonl") is False
        assert es.is_substantive_path("meta/tasks.parquet") is False
        assert es.is_substantive_path("meta/episodes/chunk-000/file-000.parquet") is False
        assert es.is_substantive_path("meta_data/info.json") is False

    def test_parquet_outside_meta_is_still_substantive(self):
        # Contrast directe amb el cas anterior: el mateix format
        # (.parquet) SÍ és substantiu fora del prefix meta/.
        assert es.is_substantive_path("data/chunk-000/episode_000015.parquet") is True

    def test_generalized_documentation_and_config_extensions_are_not_substantive(self):
        # Generalitza més enllà de README.md/setup.cfg (noms exactes):
        # qualsevol fitxer amb aquestes extensions és documentació/config,
        # no dades, independentment del nom.
        assert es.is_substantive_path("CARD.md") is False
        assert es.is_substantive_path("docs/CONTRIBUTING.md") is False
        assert es.is_substantive_path("pyproject.toml") is False
        assert es.is_substantive_path(".pre-commit-config.yaml") is False
        assert es.is_substantive_path("poetry.lock") is False


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


class TestIsTabularCommit:
    """Un commit compta si toca algun fitxer de dades tabular; sense clon, no compta."""

    def test_without_clone_the_commit_does_not_count(self):
        assert es.is_tabular_commit(_FakeCommit("Add new records"), None) is False

    def test_uses_real_files_when_clone_available(self, monkeypatch):
        commit = _FakeCommit("Merge pull request #3")
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: ["data/file.parquet", "README.md"])
        assert es.is_tabular_commit(commit, "/fake/clone") is True

    def test_metadata_only_files_do_not_count(self, monkeypatch):
        commit = _FakeCommit("Update stuff")
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: ["README.md", ".gitattributes"])
        assert es.is_tabular_commit(commit, "/fake/clone") is False

    def test_non_tabular_data_files_do_not_count(self, monkeypatch):
        # Àudio, vídeo, imatges, tensors o arxius són dades, però el motor no
        # les compara: no fan elegible el dataset ni arriben mai a la Fase 2.
        binary_paths = [
            "audio/sample.wav", "audio/sample.mp3", "audio/sample.flac",
            "video/clip.mp4", "video/clip.avi", "video/clip.mov",
            "images/frame.png", "images/frame.jpg", "images/frame.webp",
            "tensors/weights.safetensors", "tensors/array.npy", "tensors/array.npz",
            "archive/data.tar.gz", "archive/data.zip",
        ]
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: binary_paths)
        assert es.is_tabular_commit(_FakeCommit("Add episodes"), "/fake/clone") is False

    def test_lerobot_meta_tables_do_not_count(self, monkeypatch):
        commit = _FakeCommit("Update meta")
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: ["meta/episodes.jsonl"])
        assert es.is_tabular_commit(commit, "/fake/clone") is False

    def test_when_git_show_fails_the_commit_does_not_count(self, monkeypatch):
        monkeypatch.setattr(es, "get_changed_files", lambda clone_dir, sha: None)
        assert es.is_tabular_commit(_FakeCommit("Add new records"), "/fake/clone") is False


class TestFindTabularCommits:
    def test_returns_positions_of_tabular_commits(self, monkeypatch):
        _files_by_title(monkeypatch)
        commits = [_FakeCommit("Add rows"), _FakeCommit("Update README"), _FakeCommit("Fix labels")]
        assert es.find_tabular_commits(commits, "/fake/clone") == [0, 2]


class TestEligibilityCriterion:
    def test_criterion_a_needs_two_tags_and_two_tabular_commits(self):
        assert es.eligibility_criterion(2, 1, [_FakeCommit("a"), _FakeCommit("b")]) == "A"
        assert es.eligibility_criterion(2, 1, [_FakeCommit("a")]) is None

    def test_criterion_b_needs_two_sessions(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        gap = timedelta(hours=es.MIN_SUBSTANTIVE_GAP_HOURS + 1)
        two_sessions = [_FakeCommit("a", created_at=base), _FakeCommit("b", created_at=base - gap)]
        one_session = [_FakeCommit("a", created_at=base), _FakeCommit("b", created_at=base - timedelta(minutes=5))]
        assert es.eligibility_criterion(0, 2, two_sessions) == "B"
        assert es.eligibility_criterion(0, 2, one_session) is None
        assert es.eligibility_criterion(0, 2, two_sessions, tags_only=True) is None


class TestTabularFileShare:
    def test_share_of_data_files_that_are_tabular(self):
        paths = ["README.md", "data/train.parquet", "videos/a.mp4", "videos/b.mp4", "meta/info.json"]
        assert es.tabular_file_share(paths) == (3, round(1 / 3, 4))

    def test_no_data_files(self):
        assert es.tabular_file_share(["README.md", ".gitattributes"]) == (0, None)


class TestBareClone:
    def test_clones_without_content_and_only_the_recent_history(self, monkeypatch):
        captured = []
        monkeypatch.setattr(es.subprocess, "run", lambda args, **kw: captured.append(args) or _FakeCompletedProcess())

        with es.bare_clone("org/ds"):
            pass

        assert "--bare" in captured[0] and "--filter=blob:none" in captured[0]
        assert f"--depth={es.MAX_COMMITS + 1}" in captured[0]

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

    def test_estimate_and_sample_planning_use_all_attempts(self):
        # Xifres de run_6: 11 elegibles en 2.000 intents (87 inaccessibles, 8 errors).
        counts = es.FunnelCounts(
            total_scanned=1_068_504, eligible=11, ineligible=1894, access_restricted=87, errors=8
        )
        stats = es.compute_funnel_stats(counts)
        assert stats["estimated_eligible_in_scanned_population"] == round(11 / 2000 * 1_068_504)
        assert stats["attempts_per_eligible"] == round(2000 / 11, 1)

    def test_handles_zero_classified_without_dividing_by_zero(self):
        counts = es.FunnelCounts(
            total_scanned=50, eligible=0, ineligible=0, access_restricted=10, errors=40
        )
        stats = es.compute_funnel_stats(counts)
        assert stats["eligible_proportion"] == 0.0
        assert stats["eligible_proportion_of_attempts"] == 0.0
        assert stats["estimated_eligible_in_scanned_population"] == 0
        assert stats["attempts_per_eligible"] is None


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
    def __init__(self, title, created_at=None, commit_id=None):
        self.title = title
        self.created_at = created_at
        self.commit_id = commit_id or title


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class TestClassifyDatasetFilters:
    """Els tres filtres de `classify_dataset`, del més barat al més car."""

    def test_without_two_tags_or_branches_nothing_else_is_queried(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1"], branches=["main"]))
        files_calls = _current_files(monkeypatch, ["data/train.csv"])
        monkeypatch.setattr(es, "list_repo_commits", lambda **kw: (_ for _ in ()).throw(AssertionError("no")))
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["eligible"] is False
        assert result["eligibility_reason"] == es.ELIGIBILITY_REASONS["no_version_marks"]
        assert files_calls == []

    def test_without_tabular_files_there_is_no_commit_listing_nor_clone(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        _current_files(monkeypatch, ["README.md", "videos/ep_0.mp4", "videos/ep_1.mp4"])
        monkeypatch.setattr(es, "list_repo_commits", lambda **kw: (_ for _ in ()).throw(AssertionError("no")))
        monkeypatch.setattr(es, "bare_clone", lambda ds: (_ for _ in ()).throw(AssertionError("no")))
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["eligible"] is False
        assert result["eligibility_reason"] == es.ELIGIBILITY_REASONS["no_tabular_files"]
        assert (result["num_data_files"], result["tabular_file_share"]) == (2, 0.0)

    def test_tabular_share_is_reported_for_candidates(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        _current_files(monkeypatch, ["README.md", "data/train.csv", "videos/ep_0.mp4", "videos/ep_1.mp4"])
        monkeypatch.setattr(es, "list_repo_commits", lambda **kw: iter([_FakeCommit("Update README")]))
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert (result["num_data_files"], result["tabular_file_share"]) == (3, round(1 / 3, 4))
        assert result["eligibility_reason"] == es.ELIGIBILITY_REASONS["no_tabular_commits"]


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
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is True
        assert result["eligibility_reason"] == "Criteri A: tags>=2 i >=2 commits amb dades tabulars"

    def test_tags_with_only_one_substantive_commit_are_not_eligible(self, monkeypatch, tmp_path):
        # >=2 tags però només 1 commit substantiu (per sota del llindar de
        # 2) -> NO elegible via Criteri A.
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([_FakeCommit("Update README"), _FakeCommit("Add new records")]),
        )
        _files_by_title(monkeypatch)
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
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
        assert result["eligible"] is False

    def test_tags_only_still_verifies_substantive_commits_for_criteria_a(self, monkeypatch, tmp_path):
        # tags_only=True NO evita list_repo_commits: el Criteri A es
        # verifica amb el mateix rigor que en mode normal.
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([_FakeCommit("Add new records"), _FakeCommit("Fix labeling errors")]),
        )
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds", tags_only=True)

        assert result["eligible"] is True
        assert result["eligibility_reason"] == "Criteri A: tags>=2 i >=2 commits amb dades tabulars"

    def test_tags_only_with_insufficient_substantive_commits_is_not_eligible(self, monkeypatch, tmp_path):
        # >=2 tags per si sols ja NO n'hi ha prou (a diferència del
        # comportament antic de "camí ràpid").
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: iter([_FakeCommit("Update README"), _FakeCommit("Add new records")]),
        )
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds", tags_only=True)

        assert result["eligible"] is False

    def test_tags_only_never_eligible_via_criteria_b(self, monkeypatch, tmp_path):
        # tags<2 amb tags_only=True: el Criteri B mai pot aplicar-se en
        # aquest mode, així que ni s'ha d'entrar al bucle de commits
        # (list_repo_commits no s'hauria de cridar).
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(branches=["main", "dev"]))
        monkeypatch.setattr(
            es, "list_repo_commits",
            lambda **kw: (_ for _ in ()).throw(AssertionError("no s'hauria de cridar")),
        )
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds", tags_only=True)

        assert result["eligible"] is False

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
        _files_by_title(monkeypatch)
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
        _files_by_title(monkeypatch)
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


# ---------------------------------------------------------------------------
# compare_change_units -- Fase 2: cada parella de revisions passa pel motor
# ---------------------------------------------------------------------------

class TestCompareChangeUnits:
    """Fase 2 amb el motor: es compara taula a taula amb `diffengine.pairs`."""

    @staticmethod
    def _fake_pair(status="ok", result=None):
        from diffengine.pairs import UnitPair

        return UnitPair("default/train", ("data/train.csv",), ("data/train.csv",), status=status, result=result)

    def test_returns_one_row_per_change(self, monkeypatch):
        from diffengine.output import Change, DiffResult

        result = DiffResult("ok", [Change("C221", column="b", subtype="unexplained")])
        monkeypatch.setattr(es.pairs, "compare_revisions", lambda *a, **kw: [self._fake_pair(result=result)])

        changes = es.compare_change_units("org/ds", [("sha1", "sha2")], "tok", es.RETRY_CONFIG)

        assert changes == [{"dataset_id": "org/ds", "version_from": "sha1", "version_to": "sha2",
                            "file_path": "data/train.csv", "code": "C221"}]

    def test_download_failure_gives_no_changes(self, monkeypatch):
        monkeypatch.setattr(es.pairs, "compare_revisions", lambda *a, **kw: [self._fake_pair("download_failed")])

        assert es.compare_change_units("org/ds", [("sha1", "sha2")], "tok", es.RETRY_CONFIG) == []

    def test_no_units_means_no_hub_calls(self, monkeypatch):
        def must_not_be_called(*a, **kw):
            raise AssertionError("no s'havia de consultar el Hub")

        monkeypatch.setattr(es.pairs, "compare_revisions", must_not_be_called)
        assert es.compare_change_units("org/ds", [], "tok", es.RETRY_CONFIG) == []


# ---------------------------------------------------------------------------
# Commits tabulars: la Fase 0 els desa i les Fases 1 i 2 els reaprofiten
# ---------------------------------------------------------------------------

def _record_units(monkeypatch):
    """Substitueix la comparació per una que només apunta les parelles rebudes."""
    calls = []

    def fake(dataset_id, units_to_compare, hf_token, retry_config):
        calls.extend(units_to_compare)
        return [{"dataset_id": dataset_id, "version_from": o, "version_to": n, "file_path": "train.csv",
                 "code": "C421"} for o, n in units_to_compare]

    monkeypatch.setattr(es, "compare_change_units", fake)
    return calls


def _write_phase0(tmp_path, reports, commits_by_dataset):
    """Escriu un `eligibility_report.csv` i el `tabular_commits.csv` que la Fase 0 hi desa al costat."""
    import pandas as pd

    report = tmp_path / "eligibility_report.csv"
    pd.DataFrame(reports).to_csv(report, index=False)
    rows = [{"dataset_id": ds, "tabular_commits": commits} for ds, commits in commits_by_dataset.items()]
    es.save_tabular_commits(rows, str(tmp_path / es.TABULAR_COMMITS_FILE))
    return str(report)


class TestTabularCommitsFromPhase0:
    def test_eligible_dataset_keeps_its_tabular_commits_and_their_parents(self, monkeypatch, tmp_path):
        commits = [_FakeCommit(f"Add batch {i}", commit_id=f"c{i}") for i in (4, 3, 2, 1)]
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(es, "list_repo_commits", lambda **kw: commits)
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["eligible"] is True
        assert result["num_tabular_commits"] == 4
        # El pare és el commit següent de la llista; el més vell no en té de conegut.
        assert [(c.commit_id, c.parent_id) for c in result["tabular_commits"]] == [
            ("c4", "c3"), ("c3", "c2"), ("c2", "c1"), ("c1", None)]

    def test_ineligible_dataset_keeps_no_commits(self, monkeypatch, tmp_path):
        # Commits amb dades, però tots en una sola sessió i sense tags: no és elegible.
        now = datetime(2026, 1, 1, 12, 0, 0)
        commits = [_FakeCommit(f"Add episode {i}", created_at=now - timedelta(minutes=i)) for i in range(5)]
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(branches=["main", "dev"]))
        monkeypatch.setattr(es, "list_repo_commits", lambda **kw: commits)
        _files_by_title(monkeypatch)
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["eligible"] is False
        assert result["tabular_commits"] == []

    def test_saved_commits_are_read_back_unchanged(self, tmp_path):
        commits = [
            es.TabularCommit("c2", "c1", datetime(2026, 1, 2, tzinfo=timezone.utc), ("ana", "bob")),
            es.TabularCommit("c1", None, datetime(2026, 1, 1, tzinfo=timezone.utc), ()),
        ]
        report = _write_phase0(tmp_path, [{"dataset_id": "org/ds", "eligible": True}], {"org/ds": commits})

        assert es.load_tabular_commits(report) == {"org/ds": commits}

    def test_report_without_the_file_gives_nothing(self, tmp_path):
        assert es.load_tabular_commits(str(tmp_path / "eligibility_report.csv")) == {}

    def test_report_has_no_internal_fields_and_commits_go_to_their_own_file(self, monkeypatch, tmp_path):
        import pandas as pd

        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
        row = {
            "dataset_id": "org/ds", "num_tags": 2, "num_branches": 1, "num_tabular_commits": 1,
            "eligible": True, "eligibility_reason": es.ELIGIBILITY_REASONS["A"], "status": "classified",
            "error_category": "", "error": "", "num_data_files": 3, "tabular_file_share": 0.5,
            "tabular_commits": [es.TabularCommit("c2", "c1", datetime(2026, 1, 2), ())],
        }

        csv_path, _, summary = es.write_results([row], total_scanned=1)

        report = pd.read_csv(csv_path)
        assert not set(es.INTERNAL_FIELDS) & set(report.columns)
        saved = pd.read_csv(tmp_path / es.TABULAR_COMMITS_FILE)
        assert saved[["dataset_id", "commit_id", "parent_id"]].values.tolist() == [["org/ds", "c2", "c1"]]
        assert {"eligible", "ineligible", "access_restricted", "errors"} <= set(summary)
        assert not any(k.startswith("with_") for k in summary)


class TestRunClassification:
    def test_uses_the_commits_saved_by_phase0_without_looking_them_up_again(self, monkeypatch, tmp_path):
        commits = [es.TabularCommit("c2", "c1", datetime(2026, 1, 2), ()),
                   es.TabularCommit("c1", None, datetime(2026, 1, 1), ())]
        report = _write_phase0(
            tmp_path, [{"dataset_id": "org/ds", "eligible": True, "eligibility_reason": es.ELIGIBILITY_REASONS["A"]}],
            {"org/ds": commits})
        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(es, "classify_dataset", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no")))
        calls = _record_units(monkeypatch)

        es.run_classification(report)

        # Criteri A: c2 es compara amb el seu pare c1; c1 no té pare conegut.
        assert calls == [("c1", "c2")]

    def test_criterion_b_compares_session_boundaries(self, monkeypatch, tmp_path):
        base = datetime(2026, 1, 1, 12, 0, 0)
        gap = timedelta(hours=es.MIN_SUBSTANTIVE_GAP_HOURS + 1)
        commits = [es.TabularCommit("c1", "c2", base, ()),
                   es.TabularCommit("c2", "c3", base - timedelta(minutes=10), ()),
                   es.TabularCommit("c3", "c4", base - gap, ()),
                   es.TabularCommit("c4", None, base - gap - timedelta(minutes=10), ())]
        report = _write_phase0(
            tmp_path, [{"dataset_id": "org/ds", "eligible": True, "eligibility_reason": es.ELIGIBILITY_REASONS["B"]}],
            {"org/ds": commits})
        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
        calls = _record_units(monkeypatch)

        es.run_classification(report)

        # 2 sessions: només l'últim commit de cada una (mai c1-c2, c2-c3 ni c3-c4).
        assert calls == [("c3", "c1")]

    def test_old_report_without_saved_commits_looks_them_up_again(self, monkeypatch, tmp_path):
        import pandas as pd

        report = tmp_path / "eligibility_report.csv"
        pd.DataFrame([{"dataset_id": "org/ds", "eligible": True,
                       "eligibility_reason": es.ELIGIBILITY_REASONS["A"]}]).to_csv(report, index=False)
        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
        looked_up = []
        monkeypatch.setattr(es, "find_tabular_commits_again", lambda ds: looked_up.append(ds) or [
            es.TabularCommit("c2", "c1", datetime(2026, 1, 2), ())])
        calls = _record_units(monkeypatch)

        es.run_classification(str(report))

        assert looked_up == ["org/ds"]
        assert calls == [("c1", "c2")]

    def test_a_failing_dataset_is_logged_and_the_rest_continue(self, monkeypatch, tmp_path):
        import pandas as pd

        commits = {ds: [es.TabularCommit("c2", "c1", datetime(2026, 1, 2), ())] for ds in ("org/bad", "org/ok")}
        report = _write_phase0(
            tmp_path, [{"dataset_id": ds, "eligible": True, "eligibility_reason": es.ELIGIBILITY_REASONS["A"]}
                       for ds in commits], commits)
        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        def compare(dataset_id, units_to_compare, hf_token, retry_config):
            if dataset_id == "org/bad":
                raise ValueError("boom")
            return [{"dataset_id": dataset_id, "version_from": "c1", "version_to": "c2", "file_path": "t.csv",
                     "code": "C421"}]

        monkeypatch.setattr(es, "compare_change_units", compare)

        output_csv = es.run_classification(report)

        assert pd.read_csv(output_csv)["dataset_id"].tolist() == ["org/ok"]
        failures = pd.read_csv(tmp_path / "failures.csv")
        assert failures[["dataset_id", "source"]].values.tolist() == [["org/bad", "classification"]]

    def test_writes_one_row_per_table_versions_and_code(self, monkeypatch, tmp_path):
        import pandas as pd

        report = _write_phase0(
            tmp_path, [{"dataset_id": "org/ds", "eligible": True, "eligibility_reason": es.ELIGIBILITY_REASONS["A"]}],
            {"org/ds": [es.TabularCommit("sha2", "sha1", datetime(2026, 1, 2), ())]})

        def row(code, column):
            return {"dataset_id": "org/ds", "version_from": "sha1", "version_to": "sha2",
                    "file_path": "train.csv", "code": code, "column": column}

        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))
        # El mateix codi en dues columnes de la mateixa taula surt un sol cop.
        monkeypatch.setattr(es, "compare_change_units", lambda *a: [row("C421", None), row("C223", "a"),
                                                                     row("C223", "b")])

        output_csv = es.run_classification(report)

        out = pd.read_csv(output_csv)
        assert output_csv == str(tmp_path / "change_classification.csv")
        assert list(out.columns) == [
            "dataset_id", "version_from", "version_to", "file_path", "code", "description", "is_breaking",
        ]
        assert out["code"].tolist() == ["C421", "C223"]
        assert out.iloc[0]["description"] == "Afegir fila"
        assert bool(out.iloc[1]["is_breaking"]) is True

    def test_never_produces_c100(self, monkeypatch, tmp_path):
        # Un canvi de format (CSV -> parquet) seria C100, que és fora d'abast.
        import io

        import pandas as pd

        from diffengine.engine import diff_bytes
        from diffengine.pairs import UnitPair

        df = pd.DataFrame({"a": range(30), "b": ["x", "y", "z"] * 10})
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        result = diff_bytes(df.to_csv(index=False).encode(), ".csv", buf.getvalue(), ".parquet")
        pair = UnitPair("default/train", ("data.csv",), ("data.parquet",), status="ok", result=result)
        monkeypatch.setattr(es.pairs, "compare_revisions", lambda *a, **kw: [pair])

        labels = es.compare_change_units("org/ds", [("c1", "c2")], "tok", es.RETRY_CONFIG)

        assert all(label["code"] != "C100" for label in labels)

    def test_no_eligible_datasets_writes_an_empty_table(self, monkeypatch, tmp_path):
        import pandas as pd

        input_csv = tmp_path / "eligibility_report.csv"
        pd.DataFrame([{"dataset_id": "org/ds", "eligible": False}]).to_csv(input_csv, index=False)
        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))

        output_csv = es.run_classification(str(input_csv))

        assert pd.read_csv(output_csv).empty


# ---------------------------------------------------------------------------
# run_sampling -- retorna (csv_path, json_path, summary) perquè un cridant
# extern (src/run_pipeline.py) pugui encadenar altres fases amb el
# mateix CSV sense re-derivar-ne la ruta. NOMÉS fa mostreig/elegibilitat --
# encadenar la classificació de canvis és responsabilitat de l'orquestrador,
# no d'aquesta funció (vegeu tests/test_run_pipeline.py).
# ---------------------------------------------------------------------------

class TestRunSamplingReturnValue:
    def test_returns_csv_path_json_path_and_summary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "iter_all_dataset_ids", lambda: iter(["org/ds"]))
        monkeypatch.setattr(es, "reservoir_sample_dataset_ids", lambda ids, n, m: (["org/ds"], 1))
        monkeypatch.setattr(
            es, "classify_dataset_safe",
            lambda item: {
                "dataset_id": "org/ds", "num_tags": 0, "num_branches": 0,
                "num_tabular_commits": 0, "eligible": True,
                "eligibility_reason": "x", "status": "classified",
                "error_category": "", "error": "", "change_labels": [],
            },
        )
        monkeypatch.setattr(es, "OUTPUT_DIR", str(tmp_path))

        csv_path, json_path, summary = es.run_sampling(sample_size=1, max_scanned=None, num_threads=1)

        assert csv_path == os.path.join(str(tmp_path), "eligibility_report.csv")
        assert json_path == os.path.join(str(tmp_path), "funnel_summary.json")
        assert summary["eligible"] == 1
        assert "eligible_total" not in summary
        assert os.path.exists(csv_path)


# ---------------------------------------------------------------------------
# cluster_commit_times -- moguda de validate_eligible.py (US-108, ara
# eliminat) perquè és una funció pura reutilitzada per version_extractor.py
# ---------------------------------------------------------------------------

class TestClusterCommitTimes:
    def test_empty_list_returns_no_clusters(self):
        assert es.cluster_commit_times([]) == []

    def test_none_values_are_ignored(self):
        assert es.cluster_commit_times([None, None]) == []

    def test_single_time_is_one_cluster(self):
        t = datetime(2026, 1, 1, 12, 0, 0)
        assert es.cluster_commit_times([t]) == [[t]]

    def test_times_within_gap_form_one_cluster(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base + timedelta(minutes=5), base + timedelta(minutes=10)]
        clusters = es.cluster_commit_times(times, gap_hours=1.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_times_beyond_gap_form_separate_clusters(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        times = [base, base + timedelta(minutes=5), base + timedelta(days=2)]
        clusters = es.cluster_commit_times(times, gap_hours=1.0)
        assert len(clusters) == 2
        assert len(clusters[0]) == 2
        assert len(clusters[1]) == 1

    def test_clusters_are_chronologically_ordered_regardless_of_input_order(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        unordered = [base + timedelta(days=2), base, base + timedelta(minutes=5)]
        clusters = es.cluster_commit_times(unordered, gap_hours=1.0)
        assert clusters == [[base, base + timedelta(minutes=5)], [base + timedelta(days=2)]]


# ---------------------------------------------------------------------------
# group_commits_into_sessions / change_units -- quines revisions es comparen
# ---------------------------------------------------------------------------

class TestGroupCommitsIntoSessions:
    def test_empty_list(self):
        assert es.group_commits_into_sessions([]) == []

    def test_commits_without_created_at_are_ignored(self):
        assert es.group_commits_into_sessions([_FakeCommit("a", created_at=None)]) == []

    def test_commits_within_gap_form_one_session(self):
        # L'ordre dins d'una sessió no està garantit: només que hi siguin tots dos.
        base = datetime(2026, 1, 1, 12, 0, 0)
        newer = _FakeCommit("newer", created_at=base)
        older = _FakeCommit("older", created_at=base - timedelta(minutes=30))
        sessions = es.group_commits_into_sessions([newer, older])
        assert len(sessions) == 1
        assert newer in sessions[0] and older in sessions[0] and len(sessions[0]) == 2

    def test_sessions_are_newest_first(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        gap = timedelta(hours=es.MIN_SUBSTANTIVE_GAP_HOURS + 1)
        newest, middle, oldest = (_FakeCommit(c, created_at=base - k * gap) for k, c in enumerate(("c1", "c2", "c3")))
        assert es.group_commits_into_sessions([oldest, newest, middle]) == [[newest], [middle], [oldest]]


class TestChangeUnits:
    def test_criterion_a_pairs_each_tabular_commit_with_its_parent(self):
        # c3 no és tabular, però és el pare de c4; c1 és el més vell i no té pare conegut.
        commits = [es.TabularCommit("c4", "c3", None), es.TabularCommit("c2", "c1", None),
                   es.TabularCommit("c1", None, None)]
        assert es.change_units(commits, "A") == [("c3", "c4"), ("c1", "c2")]

    def test_criterion_b_single_session_produces_no_units(self):
        assert es.change_units([es.TabularCommit("c1", None, datetime(2026, 1, 1))], "B") == []

    def test_criterion_b_three_sessions_produce_two_boundaries(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        gap = timedelta(hours=es.MIN_SUBSTANTIVE_GAP_HOURS + 1)
        commits = [es.TabularCommit(c, None, base - k * gap) for k, c in enumerate(("c1", "c2", "c3"))]
        assert es.change_units(commits, "B") == [("c2", "c1"), ("c3", "c2")]

    def test_criterion_b_uses_latest_commit_of_each_session(self):
        base = datetime(2026, 1, 1, 12, 0, 0)
        gap = timedelta(hours=es.MIN_SUBSTANTIVE_GAP_HOURS + 1)
        commits = [
            es.TabularCommit("c1", "c2", base),
            es.TabularCommit("c2", "c3", base - timedelta(minutes=10)),
            es.TabularCommit("c3", None, base - gap),
        ]
        assert es.change_units(commits, "B") == [("c3", "c1")]
