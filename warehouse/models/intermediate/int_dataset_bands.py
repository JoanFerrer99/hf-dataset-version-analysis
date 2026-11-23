"""
Intervals de les mesures dels datasets, per discretització amb k-means (un
model Python de dbt).

Cada mesura es divideix en 3 clústers (`KMeans` de scikit-learn sobre
`log1p` del valor, perquè les distribucions són molt asimètriques) i cada
clúster rep una etiqueta per l'ordre del seu centre: `Few/Medium/Many` per a
les descàrregues i `Low/Medium/High` per a la resta. Si hi ha menys de 3
valors diferents, hi ha menys clústers (`Low/High`, o `Medium` si n'hi ha
un). Els valors buits no tenen interval.

- Descàrregues: sobre tota la mostra.
- La resta (mida inicial, files i columnes inicials, versions i commits
  tabulars): sobre els elegibles, els únics que tenen versions.
"""

import numpy as np
import pandas as pd

DOWNLOADS = ("Few", "Medium", "Many")
LEVELS = ("Low", "Medium", "High")

# columna d'origen -> (columna de l'interval, etiquetes, només els elegibles)
BANDS = {
    "downloads": ("downloads_band", DOWNLOADS, False),
    "initial_size_bytes": ("initial_size_band", LEVELS, True),
    "initial_n_rows": ("initial_rows_band", LEVELS, True),
    "initial_n_columns": ("initial_columns_band", LEVELS, True),
    "n_versions": ("n_versions_band", LEVELS, True),
    "num_tabular_commits": ("n_tabular_commits_band", LEVELS, True),
}


def kmeans_bands(values: pd.Series, labels: tuple[str, str, str]) -> pd.Series:
    """
    Discretitza una mesura amb k-means.

    :param values: la mesura (pot tenir buits).
    :param labels: les etiquetes dels 3 clústers, de menys a més.
    :return: l'etiqueta de cada valor, o `None` si és buit.
    """
    from sklearn.cluster import KMeans

    out = pd.Series([None] * len(values), index=values.index, dtype=object)
    present = values.dropna().astype(float)
    k = min(3, present.nunique())
    if k == 0:
        return out
    if k == 1:
        out[present.index] = labels[1]
        return out
    x = np.log1p(present.clip(lower=0)).to_numpy().reshape(-1, 1)
    model = KMeans(n_clusters=k, n_init=10, random_state=0).fit(x)
    rank = np.argsort(np.argsort(model.cluster_centers_.ravel()))
    names = labels if k == 3 else (labels[0], labels[2])
    out[present.index] = [names[rank[c]] for c in model.labels_]
    return out


def model(dbt, session):
    dbt.config(materialized="table")
    measures = dbt.ref("int_dataset_measures").df()
    eligible = measures["eligibility"] == "Si"
    bands = measures[["dataset_id"]].copy()
    for column, (band, labels, only_eligible) in BANDS.items():
        values = measures[column].where(eligible) if only_eligible else measures[column]
        bands[band] = kmeans_bands(values, labels).astype("string")  # text també si tot és buit
    return bands
