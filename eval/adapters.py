"""
Adaptadors: cada motor rep un `Case` i retorna les etiquetes que detecta,
com a conjunt de `(codi, subtipus)` (subtipus `None` si el motor no en dona).
"""

import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notebooks"))
os.environ.setdefault("HF_TOKEN", "eval-dummy")  # eligibility_scan surt sense token; change_diff no el necessita

import change_diff  # noqa: E402

from eval.mutations import Case  # noqa: E402


def _read_like_pipeline(data: bytes, ext: str) -> pd.DataFrame | None:
    """Mateixa lectura que `change_diff.download_tabular_file_at_revision`."""
    try:
        if ext == ".parquet":
            return pd.read_parquet(io.BytesIO(data))
        return pd.read_csv(io.BytesIO(data), sep="\t" if ext == ".tsv" else ",")
    except Exception:
        return None


def old_engine(case: Case) -> set[tuple[str, str | None]]:
    """
    Motor actual tal com l'usa el pipeline. Un canvi d'extensió és un canvi
    de ruta: el pipeline veu un fitxer eliminat i un d'afegit.
    """
    if case.old_ext != case.new_ext:
        return {("C421", None), ("C422", None)}
    before = _read_like_pipeline(case.old, case.old_ext)
    after = _read_like_pipeline(case.new, case.new_ext)
    labels = change_diff.classify_file_change("eval", before, after, "old", "new")
    return {(label.code, None) for label in labels}


ENGINES = {"old": old_engine}
