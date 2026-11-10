"""
Tests de les figures de la memòria (`src/figures/`), amb el magatzem de la
fixture sintètica: cada figura es dibuixa, es desa a 300 ppp i diu quina
pregunta respon i de quin mart surt.
"""

import inspect

import pytest
from PIL import Image

from figures import common, make_all


@pytest.fixture
def con(warehouse):
    connection = common.connect(warehouse)
    yield connection
    connection.close()


@pytest.mark.parametrize("module", make_all.FIGURES, ids=lambda m: m.NAME)
def test_every_figure_is_drawn_and_saved_at_300_dpi(module, con, tmp_path):
    path = common.save(module.draw(con), module.NAME, str(tmp_path))

    with Image.open(path) as image:
        assert image.format == "PNG"
        assert [round(d) for d in image.info["dpi"]] == [common.DPI, common.DPI]
        assert image.width > 1000


@pytest.mark.parametrize("module", make_all.FIGURES, ids=lambda m: m.NAME)
def test_every_figure_says_its_question_and_source_mart(module):
    header = inspect.getdoc(module)
    assert "Pregunta:" in header and ("Mart:" in header)


def test_figure_names_are_unique():
    names = [module.NAME for module in make_all.FIGURES]
    assert len(names) == len(set(names))


def test_make_all_writes_every_figure(warehouse, tmp_path):
    paths = make_all.make(warehouse=warehouse, out_dir=str(tmp_path))

    assert sorted(p.split("/")[-1] for p in paths) == sorted(f"{m.NAME}.png" for m in make_all.FIGURES)


def test_make_all_refuses_unknown_names_and_a_missing_warehouse(warehouse, tmp_path):
    with pytest.raises(ValueError, match="nope"):
        make_all.make(["nope"], warehouse=warehouse, out_dir=str(tmp_path))
    assert make_all.main(["--warehouse", str(tmp_path / "missing.duckdb")]) == 1
    assert make_all.main(["nope", "--warehouse", warehouse, "--out", str(tmp_path)]) == 1
