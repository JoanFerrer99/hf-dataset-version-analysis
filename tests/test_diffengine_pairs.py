"""Tests de L0 (`diffengine.pairs`): aparellament de taules i estats, sense xarxa."""

import pandas as pd

from diffengine import pairs
from diffengine.units import resolve_units


def revision(name: str, files: dict[str, str], readme: str | None = None) -> pairs.Revision:
    """`files`: ruta -> identificador de contingut."""
    return pairs.Revision(name, {p: 100 for p in files}, dict(files), resolve_units(list(files), readme))


def by_key(result):
    return {p.key: p for p in result}


class TestPairUnits:
    def test_shards_of_a_split_are_one_unit_even_if_their_count_changes(self):
        old = revision("a", {"data/train-00000-of-00001.parquet": "x"})
        new = revision("b", {"data/train-00000-of-00002.parquet": "y", "data/train-00001-of-00002.parquet": "z"})
        result = by_key(pairs.pair_units(old, new))
        assert set(result) == {"default/train"}
        assert result["default/train"].status == "pending"
        assert len(result["default/train"].new_files) == 2

    def test_changed_file_outside_any_split_is_recorded_as_excluded(self):
        old = revision("a", {"train.csv": "t", "test.csv": "s", "notes.csv": "n1", "extra.csv": "e"})
        new = revision("b", {"train.csv": "t", "test.csv": "s", "notes.csv": "n2", "extra.csv": "e"})
        result = by_key(pairs.pair_units(old, new))
        assert result["notes.csv"].status == "excluded"
        assert result["notes.csv"].info == {"reason": "outside_any_split"}
        assert "extra.csv" not in result  # exclòs però sense canvis: no cal registrar-lo

    def test_identical_content_is_not_compared(self):
        files = {"train.csv": "same"}
        result = pairs.pair_units(revision("a", files), revision("b", files))
        assert [p.status for p in result] == ["identical_content"]

    def test_renamed_file_is_paired_by_content_hash(self):
        old = revision("a", {"leaderboard.csv": "h1", "ablation.csv": "h2"})
        new = revision("b", {"leaderboard_v2.csv": "h1", "ablation.csv": "h3"})
        result = by_key(pairs.pair_units(old, new))
        assert result["leaderboard_v2.csv"].info == {"renamed_from": "leaderboard.csv"}

    def test_format_change_pairs_by_stem(self):
        old = revision("a", {"data.csv": "h1"})
        new = revision("b", {"data.parquet": "h2"})
        result = pairs.pair_units(old, new)
        assert [(p.old_files, p.new_files, p.info) for p in result] == [(("data.csv",), ("data.parquet",),
                                                                         {"format_change": True})]

    def test_added_and_removed_files_get_absent_status(self):
        old = revision("a", {"a.csv": "h1", "b.csv": "h2"})
        new = revision("b", {"a.csv": "h1", "c.csv": "h3"})
        statuses = {p.key: p.status for p in pairs.pair_units(old, new)}
        assert statuses == {"a.csv": "identical_content", "b.csv": "absent_new", "c.csv": "absent_old"}

    def test_unrelated_files_merged_in_one_split_are_separate_units(self):
        old = revision("a", {"adult.csv": "h1", "census_2020.csv": "h2"})
        new = revision("b", {"adult.csv": "h1", "census_2020.csv": "h3"})
        statuses = {p.key: p.status for p in pairs.pair_units(old, new)}
        assert statuses == {"adult.csv": "identical_content", "census_2020.csv": "pending"}


def _csv(df):
    return df.to_csv(index=False).encode()


class TestComparePair:
    def _setup(self, monkeypatch, contents: dict[tuple[str, str], bytes]):
        def fake_load(repo_id, revision, files, token, call, config):
            from diffengine.load import load_table
            return load_table(contents[(revision, files[0])], ".csv", config)
        monkeypatch.setattr(pairs, "_load_files", fake_load)

    def test_download_failure_gives_status_and_no_codes(self, monkeypatch):
        """Cas 11."""
        def failing(*a, **kw):
            raise OSError("connection reset")
        monkeypatch.setattr("huggingface_hub.hf_hub_download", failing)
        old = revision("a", {"train.csv": "h1"})
        new = revision("b", {"train.csv": "h2"})
        pair = pairs.pair_units(old, new)[0]
        pairs.compare_pair("org/ds", pair, old, new, None, {"max_retries": 1, "base_wait_s": 0, "max_wait_s": 0})
        assert pair.status == "download_failed"
        assert pair.result is None

    def test_two_changed_files_give_separate_results(self, monkeypatch):
        """Cas 13."""
        base = pd.DataFrame({"a": range(50), "b": ["x", "y"] * 25})
        self._setup(monkeypatch, {
            ("a", "lb.csv"): _csv(base), ("b", "lb.csv"): _csv(base.rename(columns={"b": "c"})),
            ("a", "abl.csv"): _csv(base), ("b", "abl.csv"): _csv(base.drop(columns=["b"])),
        })
        readme = "---\nconfigs:\n- config_name: lb\n  data_files: lb.csv\n- config_name: abl\n  data_files: abl.csv\n---\n"
        old = revision("a", {"lb.csv": "1", "abl.csv": "2"}, readme)
        new = revision("b", {"lb.csv": "3", "abl.csv": "4"}, readme)
        result = {p.key: p for p in pairs.pair_units(old, new)}
        for p in result.values():
            pairs.compare_pair("org/ds", p, old, new, None, {})
        assert result["lb/train"].result.codes == {"C223"}
        assert result["abl/train"].result.codes == {"C222"}


def test_concat_rejects_shards_with_different_schemas():
    from diffengine.load import ParseError, load_table

    a = load_table(_csv(pd.DataFrame({"x": [1]})), ".csv")
    b = load_table(_csv(pd.DataFrame({"y": [1]})), ".csv")
    try:
        pairs._concat([a, b])
    except ParseError:
        return
    raise AssertionError("ParseError esperat")


def test_concat_keeps_rows_in_shard_order():
    from diffengine.load import load_table

    a = load_table(_csv(pd.DataFrame({"x": [1, 2]})), ".csv")
    b = load_table(_csv(pd.DataFrame({"x": [3]})), ".csv")
    assert pairs._concat([a, b]).values["x"].tolist() == [1.0, 2.0, 3.0]

