"""
Pas 4: detectors de canvis, un mòdul per perspectiva de la taxonomia (paper §4):

- `columns_set.py`   C2xx: conjunt de columnes (ordre, afegir, eliminar, renom)
- `column_kind.py`   C3xx: tipus i valors d'una columna
- `rows_set.py`      C4xx: conjunt de files (ordre, afegir, eliminar)
- `data.py`          C5xx: característiques de les dades (nuls, correlació, distribució)

C1xx (metadades) és fora d'abast. Els detectors s'executen en l'ordre de
`DETECTORS`: els de tipus i valors deixen anotacions al `Context` (columnes
que han canviat de tipus o que una transformació explica) que fan servir
els de C5xx.
"""

from diffengine.detectors.column_kind import detect_kinds, detect_values
from diffengine.detectors.columns_set import detect_column_set
from diffengine.detectors.common import Context, find_identifiers
from diffengine.detectors.data import detect_correlation, detect_distribution, detect_missing
from diffengine.detectors.rows_set import detect_order, detect_rows

DETECTORS = (detect_column_set, detect_kinds, detect_values, detect_order, detect_rows, detect_missing,
             detect_correlation, detect_distribution)

# Detectors que comparen files aparellades: la seva evidència diu com s'han aparellat.
PAIRED_DETECTORS = {detect_values, detect_order, detect_rows, detect_missing}
# Detectors de files: la confiança depèn de si l'aparellament és ambigu.
ROW_DETECTORS = {detect_order, detect_rows}

__all__ = ["DETECTORS", "PAIRED_DETECTORS", "ROW_DETECTORS", "Context", "find_identifiers"]
