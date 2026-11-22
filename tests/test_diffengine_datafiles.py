"""Tests de `diffengine.datafiles`: quins fitxers formen el dataset en una revisió, sense xarxa."""

from diffengine import datafiles
from diffengine.datafiles import dataset_files


class TestDatasetFiles:
    def test_every_data_file_of_the_repository_is_part_of_the_dataset(self):
        data = dataset_files(["README.md", "data/train-00000-of-00002.parquet", "data/train-00001-of-00002.parquet",
                              "data/test-00000-of-00001.parquet", "notes.parquet"])
        assert data.files == ("data/test-00000-of-00001.parquet", "data/train-00000-of-00002.parquet",
                              "data/train-00001-of-00002.parquet", "notes.parquet")
        assert data.fmt == "parquet"

    def test_one_file_per_year_or_per_document_is_one_dataset(self):
        assert dataset_files(["data/sales_2020.csv", "data/sales_2019.csv"]).files == (
            "data/sales_2019.csv", "data/sales_2020.csv")
        # `pulsia/fr-bench-pdf2md` (run_9): una carpeta per document.
        files = ["pdfs/charts/thesis_page3/tests_graphics.jsonl", "pdfs/forms/Scan_12_page0/tests.jsonl"]
        assert dataset_files(files).files == tuple(sorted(files))

    def test_files_are_in_natural_order(self):
        data = dataset_files(["data/part_10.csv", "data/part_2.csv", "data/part_1.csv"])
        assert data.files == ("data/part_1.csv", "data/part_2.csv", "data/part_10.csv")

    def test_metadata_is_not_part_of_the_dataset(self):
        """LeRobot: les dades són a `data/`; `meta/` són índexs d'episodis i estadístiques."""
        files = ["data/chunk-000/episode_000000.parquet", "meta/episodes/chunk-000/file-000.parquet",
                 "meta/tasks.parquet", "meta/info.json", "dataset_infos.json", "videos/chunk-000/a.mp4"]
        assert dataset_files(files).files == ("data/chunk-000/episode_000000.parquet",)

    def test_every_listed_format_is_part_of_the_dataset(self):
        """Decisió T-44: el format ja no importa; tots els fitxers de dades es llegeixen."""
        data = dataset_files(["b.parquet", "a.parquet", "c.csv", "README.md"])
        assert data.files == ("a.parquet", "b.parquet", "c.csv")
        assert (data.formats, data.fmt) == (("csv", "parquet"), "csv+parquet")

    def test_formats_follow_the_order_of_the_list(self):
        assert dataset_files(["data.csv", "data.parquet"], formats=("parquet", "csv")).fmt == "parquet+csv"

    def test_a_format_left_out_of_the_list_is_not_data(self):
        assert dataset_files(["a.json", "b.parquet"], formats=("json",)).files == ("a.json",)
        assert dataset_files(["b.parquet"], formats=("json",)) == datafiles.DatasetFiles((), ())
        assert dataset_files(["b.parquet"], formats=("json",)).fmt is None


class TestFormats:
    def test_a_file_is_tabular_only_in_a_listed_format_and_outside_metadata(self):
        assert datafiles.is_tabular_path("data/train.CSV")
        assert datafiles.is_tabular_path("data/train.csv", ("csv",))
        assert not datafiles.is_tabular_path("data/train.parquet", ("csv",))
        assert not datafiles.is_tabular_path("meta/info.json", ("json",))
        assert not datafiles.is_tabular_path("meta/episodes.jsonl")
        assert not datafiles.is_tabular_path("changelog.json")
