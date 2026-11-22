"""Tests dels intervals k-means del magatzem (`warehouse/models/intermediate/int_dataset_bands.py`)."""

import importlib.util
import os

import pandas as pd

PATH = os.path.join(os.path.dirname(__file__), "..", "warehouse", "models", "intermediate", "int_dataset_bands.py")
spec = importlib.util.spec_from_file_location("int_dataset_bands", PATH)
bands = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bands)


def test_three_clusters_are_named_by_the_order_of_their_centres():
    values = pd.Series([1, 2, 3, 1000, 1200, 1100, 10**6, 2 * 10**6])
    out = bands.kmeans_bands(values, bands.DOWNLOADS)
    assert out.tolist() == ["Few"] * 3 + ["Medium"] * 3 + ["Many"] * 2


def test_empty_values_have_no_band():
    out = bands.kmeans_bands(pd.Series([None, 5, None, 500, 50_000]), bands.LEVELS)
    assert out.isna().tolist() == [True, False, True, False, False]
    assert out.dropna().tolist() == ["Low", "Medium", "High"]


def test_fewer_distinct_values_give_fewer_clusters():
    assert bands.kmeans_bands(pd.Series([3, 3, 3]), bands.LEVELS).tolist() == ["Medium"] * 3
    assert bands.kmeans_bands(pd.Series([1, 1, 900]), bands.LEVELS).tolist() == ["Low", "Low", "High"]
    assert bands.kmeans_bands(pd.Series([None, None], dtype=float), bands.LEVELS).isna().all()
