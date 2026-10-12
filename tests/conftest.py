"""
Configuració compartida de pytest.

`src/` conté el codi del pipeline com a script (no és un paquet
instal·lable), així que afegim el directori al `sys.path` perquè els tests
puguin fer `import eligibility_scan` / `import errors` directament, sense
necessitat d'un `__init__.py` que convertiria `src/` en un paquet
Python real (cosa que no és la intenció: és una carpeta de scripts
d'anàlisi, no una llibreria).
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
