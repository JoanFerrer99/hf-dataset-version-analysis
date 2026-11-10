"""
La seed de la taxonomia del magatzem (`warehouse/seeds/taxonomy.csv`) ha de
dir el mateix que el motor (`diffengine.output`): els mateixos 14 codis i els
mateixos codis trencadors.
"""

import os

import pandas as pd

from diffengine.output import BREAKING_CODES, CODE_DESCRIPTIONS, TABULAR_CODES

SEED = os.path.join(os.path.dirname(__file__), "..", "warehouse", "seeds", "taxonomy.csv")


def _seed() -> pd.DataFrame:
    return pd.read_csv(SEED)


def test_seed_has_the_14_tabular_codes_in_order():
    assert tuple(_seed()["code"]) == TABULAR_CODES
    assert "C100" not in set(_seed()["code"])


def test_breaking_codes_match_the_engine():
    seed = _seed()
    assert set(seed.loc[seed["is_breaking"], "code"]) == BREAKING_CODES


def test_levels_follow_the_digits_of_the_code():
    seed = _seed()
    # Mateixa primera xifra -> mateix level_1; mateixes dues xifres -> mateix level_2.
    assert (seed.groupby(seed["code"].str[:2])["level_1"].nunique() == 1).all()
    assert (seed.groupby(seed["code"].str[:3])["level_2"].nunique() == 1).all()
    assert seed["level_1"].nunique() == 4


def test_every_code_of_the_engine_has_a_name_in_the_seed():
    assert set(_seed()["code"]) == set(CODE_DESCRIPTIONS)
