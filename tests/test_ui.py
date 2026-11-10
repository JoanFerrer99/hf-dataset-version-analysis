"""
Test de fum de la interfície (`ui/`): un magatzem construït amb dbt a partir de
la fixture sintètica (`tests/fixtures/run_sample/`), i cada pàgina renderitzada
amb `streamlit.testing.v1.AppTest`, sense navegador ni xarxa.
"""

import json
import os
import subprocess

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import build_warehouse as bw

APP = os.path.join(bw.REPO_ROOT, "ui", "app.py")
RUN_SAMPLE = os.path.join(bw.REPO_ROOT, "tests", "fixtures", "run_sample")
PAGES = ["pages/home.py", "pages/sampling.py", "pages/versions.py", "pages/changes.py", "pages/explorer.py",
         "pages/validation.py"]


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory):
    """El magatzem de la fixture, construït un sol cop per a tots els tests."""
    path = str(tmp_path_factory.mktemp("warehouse") / "run_sample.duckdb")
    command = [bw.dbt_executable(), "build", "--project-dir", bw.PROJECT_DIR, "--profiles-dir", bw.PROJECT_DIR,
               "--vars", json.dumps({"run_dir": RUN_SAMPLE})]
    subprocess.run(command, cwd=bw.REPO_ROOT, env={**os.environ, "WAREHOUSE_PATH": path}, check=True,
                   capture_output=True)
    return path


@pytest.fixture
def app(warehouse, monkeypatch):
    """L'aplicació, apuntant al magatzem de la fixture; la connexió en memòria cau es buida a cada test."""
    monkeypatch.setenv("WAREHOUSE_PATH", warehouse)
    st.cache_resource.clear()
    yield AppTest.from_file(APP, default_timeout=30)
    st.cache_resource.clear()


def test_home_shows_the_key_figures_of_the_run(app):
    app.run()

    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Datasets de la mostra"] == "12"
    assert metrics["Elegibles (≥2 versions amb dades tabulars)"] == "3"
    assert metrics["Comparacions fetes"] == "3 de 4"
    assert metrics["Canvis detectats"] == "7"
    assert "run_sample" in app.caption[0].value
    assert app.dataframe[0].value.shape[0] == 14  # la taxonomia


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_errors(app, page):
    app.run()
    app.switch_page(page).run()

    assert not app.exception
    assert app.title


def test_a_missing_warehouse_shows_how_to_build_it(monkeypatch, tmp_path):
    monkeypatch.setenv("WAREHOUSE_PATH", str(tmp_path / "missing.duckdb"))
    st.cache_resource.clear()

    app = AppTest.from_file(APP, default_timeout=30).run()

    assert not app.exception
    assert "build_warehouse.py" in app.error[0].value
