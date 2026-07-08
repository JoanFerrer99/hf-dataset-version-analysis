"""
Tests unitaris per a `notebooks/eligibility_scan.py`.

Cobreixen:
  1. `reservoir_sample_dataset_ids` només conserva identificadors (strings),
     mai els objectes originals -- aquest era el bug de memòria reportat.
  2. `compute_funnel_stats`: denominadors correctes de l'embut
     d'elegibilitat (separant accés restringit i errors dels no elegibles).
"""

import random

import eligibility_scan as es


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


class TestClassifyDatasetResultShape:
    def test_status_is_classified_when_eligible_via_tags(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "list_repo_refs", lambda **kw: _FakeRefs(tags=["v1", "v2"]))
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        result = es.classify_dataset("org/ds")

        assert result["status"] == "classified"
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

    def test_result_has_status_key_regardless_of_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(es, "FAILURES_LOG_PATH", str(tmp_path / "failures.csv"))

        for fake_refs_fn in (
            lambda **kw: _FakeRefs(tags=["v1", "v2"]),
            lambda **kw: _FakeRefs(),
            lambda **kw: (_ for _ in ()).throw(ValueError("boom")),
        ):
            monkeypatch.setattr(es, "list_repo_refs", fake_refs_fn)
            result = es.classify_dataset("org/ds")
            assert "status" in result
            assert result["status"] in ("classified", "access_restricted", "error")
