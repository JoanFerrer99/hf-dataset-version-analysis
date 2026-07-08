"""
Configuració compartida de pytest.

`notebooks/` conté el codi del pipeline com a script (no és un paquet
instal·lable), així que afegim el directori al `sys.path` perquè els tests
puguin fer `import eligibility_scan` / `import errors` directament, sense
necessitat d'un `__init__.py` que convertiria `notebooks/` en un paquet
Python real (cosa que no és la intenció: és una carpeta de scripts
d'anàlisi, no una llibreria).
"""

import sys
from pathlib import Path

NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent / "notebooks"
if str(NOTEBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOKS_DIR))
