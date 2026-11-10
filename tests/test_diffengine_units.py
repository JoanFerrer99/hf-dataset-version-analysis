"""Tests de `diffengine.units`: resolució de taules (subset, split) sense xarxa."""

from diffengine import units
from diffengine.units import classify_naming, resolve_units


def _tables(layout):
    return {(u.subset, u.split): list(u.files) for u in layout.units}


class TestResolveUnits:
    def test_hf_shards_take_priority_over_loose_files(self):
        layout = resolve_units([
            "data/train-00000-of-00002.parquet", "data/train-00001-of-00002.parquet",
            "data/test-00000-of-00001.parquet", "notes.parquet",
        ])
        assert _tables(layout) == {
            ("default", "train"): ["data/train-00000-of-00002.parquet", "data/train-00001-of-00002.parquet"],
            ("default", "test"): ["data/test-00000-of-00001.parquet"],
        }
        assert layout.excluded == {"notes.parquet": "outside_any_split"}

    def test_split_names_without_shards(self):
        layout = resolve_units(["train.csv", "test.csv", "extra.csv"])
        assert _tables(layout) == {("default", "train"): ["train.csv"], ("default", "test"): ["test.csv"]}
        assert layout.excluded == {"extra.csv": "outside_any_split"}

    def test_without_any_pattern_everything_is_one_train_split(self):
        layout = resolve_units(["adult.csv", "census_2020.csv"])
        assert _tables(layout) == {("default", "train"): ["adult.csv", "census_2020.csv"]}
        assert layout.units[0].naming == "distinct"

    def test_the_first_format_of_the_list_wins_not_the_most_common(self):
        layout = resolve_units(["a.parquet", "b.parquet", "c.csv"])  # per defecte, CSV primer
        assert _tables(layout) == {("default", "train"): ["c.csv"]}
        assert layout.excluded == {"a.parquet": "other_format", "b.parquet": "other_format"}

    def test_the_order_is_the_one_given(self):
        layout = resolve_units(["data.csv", "data.parquet"], formats=("parquet", "csv"))
        assert _tables(layout) == {("default", "train"): ["data.parquet"]}
        assert layout.excluded == {"data.csv": "other_format"}

    def test_a_format_left_out_of_the_list_is_not_a_table(self):
        layout = resolve_units(["a.json", "b.parquet"], formats=("parquet",))
        assert _tables(layout) == {("default", "train"): ["b.parquet"]}
        assert layout.excluded == {}  # no és tabular: ni es compara ni es registra

    def test_without_the_preferred_format_the_next_one_is_used(self):
        layout = resolve_units(["a.jsonl", "b.json"], formats=("csv", "jsonl", "json"))
        assert _tables(layout) == {("default", "train"): ["a.jsonl"]}
        assert layout.excluded == {"b.json": "other_format"}

    def test_media_metadata_is_not_a_table(self):
        layout = resolve_units(["train/metadata.csv", "train/a.png", "train/b.png"])
        assert layout.units == []
        assert layout.excluded == {"train/metadata.csv": "media_metadata"}

    def test_yaml_configs_are_resolved_as_separate_subsets(self):
        readme = (
            "---\nconfigs:\n- config_name: leaderboard\n  data_files: lb.csv\n"
            "- config_name: ablation\n  data_files: abl.csv\n---\n# Title\n"
        )
        layout = resolve_units(["lb.csv", "abl.csv", "MANIFEST_SHA256.csv"], readme)
        assert _tables(layout) == {("leaderboard", "train"): ["lb.csv"], ("ablation", "train"): ["abl.csv"]}

    def test_lerobot_glob_config_becomes_one_numbered_table(self):
        readme = "---\nconfigs:\n- config_name: default\n  data_files: data/*/*.parquet\n---\n"
        episodes = [f"data/chunk-000/episode_{i:06d}.parquet" for i in range(3)]
        layout = resolve_units(episodes + ["meta/info.json", "videos/chunk-000/a.mp4"], readme)
        assert _tables(layout) == {("default", "train"): episodes}
        assert layout.units[0].naming == "numbered"

    def test_unknown_feature_type_in_card_does_not_break_resolution(self):
        readme = (
            "---\nconfigs:\n- config_name: default\n  data_files: data/*.parquet\n"
            "dataset_info:\n  features:\n  - name: frame\n    dtype: VideoFrame\n---\n"
        )
        layout = resolve_units(["data/a.parquet"], readme)
        assert layout.error is None
        assert _tables(layout) == {("default", "train"): ["data/a.parquet"]}


    def test_tables_of_a_media_repo_are_resolved_on_their_own(self):
        """LeRobot: més vídeos que parquet; `datasets` el veu com a `videofolder`."""
        layout = resolve_units(
            [f"videos/chunk-000/cam/episode_{i:06d}.mp4" for i in range(6)]
            + [f"data/chunk-000/episode_{i:06d}.parquet" for i in range(3)]
            + ["meta/info.json", "meta/tasks.jsonl"]
        )
        assert layout.builder == "videofolder"
        assert _tables(layout) == {("default", "train"): [f"data/chunk-000/episode_{i:06d}.parquet" for i in range(3)]}
        assert layout.units[0].naming == "numbered"
        assert layout.excluded == {"meta/tasks.jsonl": "other_format"}

    def test_hub_metadata_json_is_not_a_table(self):
        layout = resolve_units(["data.csv", "dataset_infos.json"])
        assert _tables(layout) == {("default", "train"): ["data.csv"]}
        assert layout.excluded == {}

    def test_unresolvable_repo_falls_back_to_one_table_per_file(self, monkeypatch):
        import datasets.load

        def fail(self):
            raise ValueError("no es pot resoldre")

        monkeypatch.setattr(datasets.load.LocalDatasetModuleFactory, "get_module", fail)
        layout = units.resolve_units(["a.csv", "b/c.csv", "d.parquet", "README.md"])
        assert layout.error.startswith("ValueError")
        assert _tables(layout) == {("default", "a.csv"): ["a.csv"], ("default", "b/c.csv"): ["b/c.csv"]}
        assert layout.excluded == {"d.parquet": "other_format"}  # també aquí, només el primer format


class TestFormats:
    def test_preferred_format_is_the_first_present(self):
        paths = ["a.json", "b.parquet", "README.md", "dataset_infos.json"]
        assert units.preferred_format(paths, ("csv", "parquet", "json")) == "parquet"
        assert units.preferred_format(paths, ("json", "parquet")) == "json"
        assert units.preferred_format(["README.md", "dataset_infos.json"], ("json",)) is None

    def test_a_file_is_tabular_only_in_a_listed_format(self):
        assert units.is_tabular_path("data/train.CSV")
        assert units.is_tabular_path("data/train.csv", ("csv",))
        assert not units.is_tabular_path("data/train.parquet", ("csv",))
        assert not units.is_tabular_path("meta/info.json", ("json",))


class TestClassifyNaming:
    def test_patterns(self):
        assert classify_naming(["a.csv"]) == "single"
        assert classify_naming(["train-00000-of-00002.parquet", "train-00001-of-00002.parquet"]) == "hf_shards"
        assert classify_naming(["ep_000001.parquet", "ep_000002.parquet"]) == "numbered"
        assert classify_naming(["leaderboard.csv", "ablation.csv"]) == "distinct"
