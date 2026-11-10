"""Tests del pas 1 del motor (`diffengine.pairs`): el dataset de dues revisions i l'estat de la comparació, sense xarxa."""

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd

from diffengine import pairs
from diffengine.config import DEFAULT_CONFIG
from diffengine.datafiles import dataset_files
from diffengine.load import ParseError, load_table


def revision(name: str, files: dict[str, str]) -> pairs.Revision:
    """`files`: ruta -> identificador de contingut. Cada fitxer fa 100 bytes."""
    return pairs.Revision(name, {p: 100 for p in files}, dict(files), dataset_files(list(files)))


def _csv(df):
    return df.to_csv(index=False).encode()


class TestPairDatasets:
    def test_all_the_files_are_one_comparison_even_if_their_count_changes(self):
        old = revision("a", {"data/train-00000-of-00001.parquet": "x"})
        new = revision("b", {"data/train-00000-of-00002.parquet": "y", "data/train-00001-of-00002.parquet": "z"})
        comparison = pairs.pair_datasets(old, new)
        assert (comparison.status, len(comparison.old.files), len(comparison.new.files)) == ("pending", 1, 2)

    def test_identical_content_is_not_compared(self):
        files = {"train.csv": "t", "test.csv": "s", "README.md": "r1"}
        assert pairs.pair_datasets(revision("a", files), revision("b", {**files, "README.md": "r2"})).status == \
            "identical_content"

    def test_the_same_content_in_other_files_is_compared(self):
        # Les files poden ser les mateixes, però el dataset s'ha reorganitzat: ho diu la comparació.
        assert pairs.pair_datasets(revision("a", {"data.csv": "h"}), revision("b", {"data_v2.csv": "h"})).status == \
            "pending"

    def test_a_version_without_data_files(self):
        with_data, without = revision("a", {"train.csv": "h"}), revision("b", {"README.md": "r"})
        assert pairs.pair_datasets(without, with_data).status == "absent_old"
        assert pairs.pair_datasets(with_data, without).status == "absent_new"
        assert pairs.pair_datasets(without, without).status == "no_data"

    def test_the_size_is_every_file_of_both_versions(self):
        old = revision("a", {"a.csv": "1", "b.csv": "2", "README.md": "r"})
        new = revision("b", {"a.csv": "1", "b.csv": "3", "c.csv": "4"})
        assert pairs.pair_datasets(old, new).size_bytes == 500


class TestCompareDatasets:
    @staticmethod
    def _load(monkeypatch, contents: dict[str, bytes]):
        """Cada revisió es llegeix del CSV de `contents`, sense descarregar res."""
        monkeypatch.setattr(pairs, "_load_files",
                            lambda repo_id, revision, files, token, call, config: load_table(contents[revision], ".csv"))

    def test_changes_between_two_versions(self, monkeypatch):
        base = pd.DataFrame({"a": range(50), "b": ["x", "y"] * 25})
        self._load(monkeypatch, {"a": _csv(base), "b": _csv(base.rename(columns={"b": "c"}))})
        old, new = revision("a", {"train.csv": "1"}), revision("b", {"train.csv": "2"})

        comparison = pairs.compare_datasets("org/ds", pairs.pair_datasets(old, new), old, new, None)

        assert (comparison.status, comparison.result.codes) == ("ok", {"C223"})

    def test_download_failure_gives_status_and_no_codes(self):
        """Cas 11."""
        def failing_call(fn, *args, **kwargs):
            raise OSError("connection reset")
        old, new = revision("a", {"train.csv": "h1"}), revision("b", {"train.csv": "h2"})

        comparison = pairs.compare_datasets("org/ds", pairs.pair_datasets(old, new), old, new, None, failing_call)

        assert (comparison.status, comparison.result) == ("download_failed", None)

    def test_a_file_that_cannot_be_read_gives_parse_failed(self, monkeypatch):
        def unreadable(*a):
            raise ParseError("no és un CSV")
        monkeypatch.setattr(pairs, "_load_files", unreadable)
        old, new = revision("a", {"train.csv": "h1"}), revision("b", {"train.csv": "h2"})

        comparison = pairs.compare_datasets("org/ds", pairs.pair_datasets(old, new), old, new, None)

        assert (comparison.status, comparison.result) == ("parse_failed", None)

    def test_a_dataset_over_the_size_limit_is_not_downloaded(self, monkeypatch):
        def must_not_download(*a):
            raise AssertionError("no s'havia de descarregar")
        monkeypatch.setattr(pairs, "_load_files", must_not_download)
        old = revision("a", {"train.csv": "h1"})  # 100 bytes per fitxer: 200 entre les dues versions
        new = revision("b", {"train.csv": "h2"})

        comparison = pairs.compare_datasets("org/ds", pairs.pair_datasets(old, new), old, new, None,
                                            config=replace(DEFAULT_CONFIG, max_dataset_bytes=199))

        assert (comparison.status, comparison.result) == ("too_large", None)

    def test_a_dataset_at_the_size_limit_is_compared(self, monkeypatch):
        base = pd.DataFrame({"a": range(50)})
        self._load(monkeypatch, {"a": _csv(base), "b": _csv(base.iloc[:40])})
        old, new = revision("a", {"train.csv": "h1"}), revision("b", {"train.csv": "h2"})

        comparison = pairs.compare_datasets("org/ds", pairs.pair_datasets(old, new), old, new, None,
                                            config=replace(DEFAULT_CONFIG, max_dataset_bytes=200))

        assert comparison.status == "ok"


class TestCompareRevisions:
    """De punta a punta, amb un Hub fals que escriu els fitxers de cada revisió en una carpeta temporal."""

    @staticmethod
    def _hub(monkeypatch, tmp_path, revisions: dict[str, dict[str, bytes]]):
        def list_repo_tree(repo_id, repo_type, revision, recursive, token):
            return [SimpleNamespace(path=p, size=len(data), lfs=None, blob_id=str(hash(data)))
                    for p, data in revisions[revision].items()]

        def hf_hub_download(repo_id, repo_type, filename, revision, token):
            local = tmp_path / revision / filename
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(revisions[revision][filename])
            return str(local)

        monkeypatch.setattr(pairs, "list_repo_tree", list_repo_tree)
        monkeypatch.setattr(pairs, "hf_hub_download", hf_hub_download)

    def test_a_csv_per_year_is_one_dataset(self, monkeypatch, tmp_path):
        years = {y: _csv(pd.DataFrame({"id": range(y * 100, y * 100 + 30), "sales": range(30)})) for y in (2019, 2020)}
        self._hub(monkeypatch, tmp_path, {
            "a": {"README.md": b"# v1", "data/sales_2019.csv": years[2019]},
            "b": {"README.md": b"# v2", "data/sales_2019.csv": years[2019], "data/sales_2020.csv": years[2020]},
        })

        comparison = pairs.compare_revisions("org/ds", "a", "b", None)

        assert (comparison.status, comparison.result.codes) == ("ok", {"C421"})
        assert pairs.status_row("org/ds", "a", "b", comparison) == {
            "dataset_id": "org/ds", "version_from": "a", "version_to": "b", "status": "ok", "n_codes": 1,
            "format_from": "csv", "format_to": "csv", "n_files_from": 1, "n_files_to": 2,
            "size_bytes": len(years[2019]) * 2 + len(years[2020])}
        assert pairs.revision_rows("org/ds", "a", "b", comparison) == [
            {"dataset_id": "org/ds", "version_from": "a", "version_to": "b", "code": "C421"}]

    def test_uses_the_formats_of_the_config(self, monkeypatch, tmp_path):
        self._hub(monkeypatch, tmp_path, {"a": {"data.csv": b"x\n1\n", "data.parquet": b"?"}})

        rev = pairs.list_revision("org/ds", "a", None, config=replace(DEFAULT_CONFIG, formats=("parquet", "csv")))

        assert (rev.data.files, rev.data.fmt) == (("data.parquet",), "parquet")


def test_status_row_of_a_comparison_that_was_not_made():
    comparison = pairs.pair_datasets(revision("a", {"README.md": "r"}), revision("b", {"t.csv": "1", "u.csv": "2"}))
    assert pairs.status_row("org/ds", "a", "b", comparison) == {
        "dataset_id": "org/ds", "version_from": "a", "version_to": "b", "status": "absent_old", "n_codes": 0,
        "format_from": None, "format_to": "csv", "n_files_from": 0, "n_files_to": 2, "size_bytes": 200}
    assert pairs.revision_rows("org/ds", "a", "b", comparison) == []
