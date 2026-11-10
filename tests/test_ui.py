"""
Test de fum de la interfície (`ui/`): un magatzem construït amb dbt a partir de
la fixture sintètica (`tests/fixtures/run_sample/`), i cada pàgina renderitzada
amb `streamlit.testing.v1.AppTest`, sense navegador ni xarxa.
"""

import os

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import build_warehouse as bw

APP = os.path.join(bw.REPO_ROOT, "ui", "app.py")
PAGES = ["pages/home.py", "pages/sampling.py", "pages/versions.py", "pages/changes.py", "pages/explorer.py"]


@pytest.fixture
def app(warehouse, monkeypatch):
    """L'aplicació, apuntant al magatzem de la fixture; la connexió en memòria cau es buida a cada test."""
    monkeypatch.setenv("WAREHOUSE_PATH", warehouse)
    st.cache_resource.clear()
    yield AppTest.from_file(APP, default_timeout=30)
    st.cache_resource.clear()


def _components(app) -> dict:
    """Els components HTML (CCv2) dibuixats al cos de la pàgina: nom -> les dades que han rebut."""
    import json

    return {element.proto.component_name: json.loads(element.proto.json)
            for element in app.main.children.values() if getattr(element, "type", None) == "bidi_component"}


def test_home_shows_the_key_figures_of_the_run(app):
    app.run()

    assert not app.exception
    cards = {card["label"]: card["value"] for card in _components(app)["hf_cards"]["cards"]}
    assert cards == {"Datasets de la mostra": "12", "Elegibles": "3", "Comparacions fetes": "3 de 4",
                     "Canvis detectats": "7"}
    assert app.dataframe[0].value.shape[0] == 14  # la taxonomia


def test_the_shell_draws_the_navigation_and_the_page_header(app):
    # Una execució normal (no `switch_page`) passa per app.py: navegació, capçalera i filtres.
    app.run()

    components = _components(app)
    nav, header = components["hf_nav"], components["hf_header"]
    assert [page["title"] for page in nav["pages"]] == ["Inici", "Mostreig i elegibilitat", "Versions", "Canvis",
                                                        "Explorador"]
    assert nav["active"] == "Inici"
    assert "run_sample" in nav["badge"]
    assert header["title"] == "Inici"
    assert not app.sidebar.children  # sense barra lateral: la navegació nativa està amagada


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_errors(app, page):
    app.run()
    app.switch_page(page).run()

    assert not app.exception
    assert app.markdown


def test_a_missing_warehouse_shows_how_to_build_it(monkeypatch, tmp_path):
    monkeypatch.setenv("WAREHOUSE_PATH", str(tmp_path / "missing.duckdb"))
    st.cache_resource.clear()

    app = AppTest.from_file(APP, default_timeout=30).run()

    assert not app.exception
    assert "build_warehouse.py" in app.error[0].value


# ---------------------------------------------------------------------------
# Contingut de cada pàgina, amb el magatzem de la fixture (12 datasets, 3 elegibles:
# org/tags-a i org/tags-c pel Criteri A, org/sessions-b pel B; 4 comparacions, 7 canvis)
# ---------------------------------------------------------------------------

def _page(app, page, **state):
    """Obre una pàgina amb els filtres (o altres valors de `st.session_state`) ja triats."""
    for key, value in state.items():
        app.session_state[key] = value
    app.switch_page(page).run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_sampling_page_shows_the_funnel_and_both_criteria(app):
    _page(app, "pages/sampling.py")

    assert app.dataframe[0].value["Hi arriben"].tolist() == [12, 10, 6, 4, 3]
    assert {m.label: m.value for m in app.metric} == {"Criteri A: tags": "2", "Criteri B: sessions de commits": "1"}


def test_versions_page_lists_every_version_with_its_commit_link(app):
    _page(app, "pages/versions.py")

    versions = app.dataframe[0].value
    assert len(versions) == 7
    assert versions["commit_url"].str.startswith("https://huggingface.co/datasets/").all()


def test_filters_restrict_the_data_and_are_kept_across_pages(app):
    _page(app, "pages/versions.py", filter_criteria=["B"])
    assert set(app.dataframe[0].value["dataset_id"]) == {"org/sessions-b"}

    _page(app, "pages/home.py")
    _page(app, "pages/versions.py")
    assert set(app.dataframe[0].value["dataset_id"]) == {"org/sessions-b"}


def test_changes_page_applies_perspective_and_breaking_filters(app):
    _page(app, "pages/changes.py", filter_perspectives=["Rows Set"], filter_breaking="Només no trencadors")

    frequency = app.dataframe[0].value
    assert frequency["code"].tolist() == ["C421", "C422"]
    assert frequency["n_changes"].tolist() == [1, 0]


def test_explorer_drills_down_from_a_dataset_to_its_codes(app):
    _page(app, "pages/explorer.py", explorer_dataset="org/tags-a", explorer_unit=1)

    units, changes = app.dataframe[0].value, app.dataframe[1].value
    assert units["label_to"].tolist() == ["v1.1", "v2.0"]
    assert changes["code"].tolist() == ["C222", "C223", "C510"]
    assert set(changes["table_path"]) == {"default/train"}


def test_explorer_says_why_a_comparison_has_no_codes(app):
    _page(app, "pages/explorer.py", explorer_dataset="org/tags-c")

    assert "no s'ha pogut fer" in app.info[0].value


# ---------------------------------------------------------------------------
# ui/data.py: sense filtres, el mateix que els marts
# ---------------------------------------------------------------------------

@pytest.fixture
def ui_data(warehouse, monkeypatch):
    monkeypatch.setenv("WAREHOUSE_PATH", warehouse)
    monkeypatch.syspath_prepend(os.path.join(bw.REPO_ROOT, "ui"))
    st.cache_resource.clear()
    import data
    yield data
    st.cache_resource.clear()


def test_code_frequency_without_filters_is_the_mart(ui_data):
    computed = ui_data.code_frequency().set_index("code")
    mart = ui_data._query("select * from mart_code_frequency").set_index("code")

    for column in ("n_changes", "n_units", "n_datasets", "share_of_compared_units"):
        assert computed[column].fillna(-1).tolist() == mart[column].fillna(-1).tolist(), column


def test_changes_by_quarter_without_filters_is_the_mart(ui_data):
    keys = ["year_quarter", "perspective"]
    computed = ui_data.changes_by_quarter().sort_values(keys).reset_index(drop=True)
    mart = ui_data._query("select * from mart_changes_by_quarter").sort_values(keys).reset_index(drop=True)

    assert computed[keys + ["n_changes", "n_units"]].values.tolist() == mart[keys + ["n_changes", "n_units"]].values.tolist()


def test_conditions_only_use_the_filters_that_apply(ui_data):
    import filters

    selected = filters.Filters(datasets=("org/a",), criteria=("A", "B"), breaking=False)

    assert ui_data._conditions(None, dataset="d") == ("true", [])
    assert ui_data._conditions(selected, criterion="c") == ("c in (?, ?)", ["A", "B"])
    assert ui_data._conditions(selected, dataset="d", perspective="p", breaking="b") == (
        "d in (?) and b = ?", ["org/a", False])


def test_the_filter_bar_says_how_many_filters_are_active(app):
    app.session_state["filter_criteria"] = ["B"]
    app.session_state["filter_breaking"] = "Només trencadors"
    app.run()

    assert not app.exception
    labels = [element.label for element in app.main.children.values() if getattr(element, "type", None) == "expander"]
    assert labels == ["Filtres (2 actius)"]


# ---------------------------------------------------------------------------
# ui/shell.py: les dades dels components, sense navegador
# ---------------------------------------------------------------------------

@pytest.fixture
def shell(monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(bw.REPO_ROOT, "ui"))
    import shell
    return shell


def test_every_page_of_the_navigation_exists_once(shell):
    titles = [entry["title"] for entry in shell.PAGES]
    assert len(titles) == len(set(titles))
    for entry in shell.PAGES:
        assert os.path.exists(os.path.join(bw.REPO_ROOT, "ui", entry["path"])), entry["path"]
    with pytest.raises(KeyError):
        shell.page("No existeix")


def test_nav_data_marks_the_open_page(shell):
    data = shell.nav_data(shell.PAGES, "Canvis", "Execució run_9")

    assert data["active"] == "Canvis"
    assert {page["id"] for page in data["pages"]} == {entry["title"] for entry in shell.PAGES}


def test_every_card_opens_an_existing_page(shell):
    figures = {"sample_size": 2000, "classified": 1903, "eligible": 8, "eligible_a": 4, "eligible_b": 4,
               "n_units": 52, "n_compared_units": 49, "n_changes": 1868, "n_codes": 10}

    cards = shell.figure_cards_data(figures, lambda n: f"{n:,}".replace(",", "."))

    assert [card["value"] for card in cards] == ["2.000", "8", "49 de 52", "1.868"]
    assert all(shell.page(card["target"]) for card in cards)


def test_compiled_tailwind_has_every_class_the_components_use():
    """Si es canvia una classe a ui/components/*.js sense tornar a compilar (ui/styles), aquest test falla."""
    import glob
    import re

    css = open(os.path.join(bw.REPO_ROOT, "ui", "static", "tailwind.css"), encoding="utf-8").read()
    missing = set()
    for path in glob.glob(os.path.join(bw.REPO_ROOT, "ui", "components", "*.js")):
        source = open(path, encoding="utf-8").read()
        for classes in re.findall(r'className\s*=\s*(?:[^"]*\?\s*)?"([^"]+)"', source) + re.findall(r'^\s*: "([^"]+)"', source, re.M):
            for name in classes.split():
                selector = "." + re.sub(r"([:.\[\]/%])", r"\\\1", name)
                if selector not in css:
                    missing.add(name)
    assert not missing, f"classes sense compilar (cal npm run build a ui/styles): {sorted(missing)}"
