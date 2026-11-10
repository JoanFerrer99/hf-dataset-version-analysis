"""
Configuració compartida de pytest.

`src/` conté el codi del pipeline com a script (no és un paquet
instal·lable), així que afegim el directori al `sys.path` perquè els tests
puguin fer `import eligibility_scan` / `import errors` directament, sense
necessitat d'un `__init__.py` que convertiria `src/` en un paquet
Python real (cosa que no és la intenció: és una carpeta de scripts
d'anàlisi, no una llibreria).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory):
    """
    El magatzem de la fixture sintètica (`tests/fixtures/run_sample/`), construït
    amb dbt un sol cop per a tots els tests que el fan servir (interfície i figures).
    """
    import build_warehouse as bw

    path = str(tmp_path_factory.mktemp("warehouse") / "run_sample.duckdb")
    run_sample = os.path.join(bw.REPO_ROOT, "tests", "fixtures", "run_sample")
    command = [bw.dbt_executable(), "build", "--project-dir", bw.PROJECT_DIR, "--profiles-dir", bw.PROJECT_DIR,
               "--vars", json.dumps({"run_dir": run_sample})]
    subprocess.run(command, cwd=bw.REPO_ROOT, env={**os.environ, "WAREHOUSE_PATH": path}, check=True,
                   capture_output=True)
    return path
