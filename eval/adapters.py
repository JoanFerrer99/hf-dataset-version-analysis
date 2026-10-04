"""
Adaptador del motor: rep un `Case` i retorna les etiquetes que detecta, com a
conjunt de `(codi, subtipus)`. Els resultats del motor antic (`change_diff.py`,
retirat) són a `eval/baseline_old_engine.json`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notebooks"))

from diffengine.engine import diff_bytes  # noqa: E402

from eval.mutations import Case  # noqa: E402


def new_engine(case: Case) -> set[tuple[str, str | None]]:
    """Motor v2 (`notebooks/diffengine`)."""
    result = diff_bytes(case.old, case.old_ext, case.new, case.new_ext)
    return {(c.code, c.subtype.split(":")[0] if c.subtype else None) for c in result.changes}


ENGINES = {"new": new_engine}
