"""
Pas 1 (primera part): quins fitxers formen el dataset en una revisió.

És el primer pas del motor (vegeu l'índex a `engine.py`).

Un repositori és un dataset (decisió T-37). Les seves dades poden estar
repartides en molts fitxers: shards (`train-00000-of-00003.parquet`), un
fitxer per split (`train.csv`, `test.csv`), un CSV per any, un fitxer per
document... Però es comparen com un sol dataset: els fitxers s'uneixen en
ordre (`load.load_files`). Així, si entre dues versions les mateixes files es
reparteixen en més o menys fitxers, no surt cap canvi.

Els fitxers del dataset (`dataset_files`) són els fitxers de dades tabulars de
la revisió, amb la mateixa regla que l'elegibilitat de la Fase 0:

- d'un dels formats de `EngineConfig.formats` (`config/formats.toml` o
  `--formats`, T-36 i T-42); si n'hi ha de més d'un, tots formen el dataset:
  cada fitxer es llegeix en un DataFrame i el format ja no importa (T-44);
- que no siguin metadades: res de dins de `meta/`, `meta_data/` o `.github/`
  (p.e. els índexs d'episodis de LeRobot), ni els JSON de metadades del Hub.
"""

import os
import re
from dataclasses import dataclass

from diffengine.config import DEFAULT_CONFIG

READABLE_FORMATS = ("csv", "tsv", "parquet", "jsonl", "json")
"""Els formats que sap llegir el motor (`load.load_table`)."""

METADATA_PREFIXES = ("meta/", "meta_data/", ".github/")
"""Carpetes de metadades: el que hi ha a dins no és el dataset (p.e. `meta/episodes.jsonl` de LeRobot)."""

# Fitxers JSON de metadades, no de dades: del Hub/`datasets`, de LeRobot (`info.json`, `stats.json`) i altres.
METADATA_FILES = {"dataset_info.json", "dataset_infos.json", "dataset_dict.json", "state.json", "info.json",
                  "stats.json", "changelog.json"}

_NUMBERS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class DatasetFiles:
    """
    Els fitxers del dataset en una revisió.

    :ivar files: els fitxers que es comparen, en ordre natural (`file_2` abans de `file_10`).
    :ivar formats: els formats d'aquests fitxers, en l'ordre de la llista de formats.
    """

    files: tuple[str, ...]
    formats: tuple[str, ...] = ()

    @property
    def fmt(self) -> str | None:
        """
        :return: els formats units amb `+` (p.e. `csv+parquet`), o `None` si la revisió no té cap fitxer de dades.
        """
        return "+".join(self.formats) or None


def file_format(path: str) -> str:
    """
    :param path: ruta d'un fitxer.
    :return: l'extensió, en minúscules i sense el punt (p.e. `csv`).
    """
    return os.path.splitext(path)[1].lower().lstrip(".")


def is_metadata_path(path: str) -> bool:
    """
    :param path: ruta del fitxer dins del repositori.
    :return: `True` si és dins d'una carpeta de metadades o és un JSON de metadades conegut.
    """
    return path.startswith(METADATA_PREFIXES) or os.path.basename(path) in METADATA_FILES


def is_tabular_path(path: str, formats: tuple[str, ...] = READABLE_FORMATS) -> bool:
    """
    Diu si un fitxer és de dades tabulars, només pel nom.

    :param path: ruta del fitxer dins del repositori.
    :param formats: formats que compten (per defecte, tots els que sap llegir el motor).
    :return: `True` si el format és a `formats` i no és un fitxer de metadades.
    """
    return file_format(path) in formats and not is_metadata_path(path)


def natural_order(path: str) -> list:
    """Clau d'ordenació que compara els números pel valor: `file_2` va abans de `file_10`."""
    return [int(part) if part.isdigit() else part for part in _NUMBERS.split(path)]


def dataset_files(paths: list[str], formats: tuple[str, ...] = DEFAULT_CONFIG.formats) -> DatasetFiles:
    """
    Els fitxers que formen el dataset en una revisió, sense descarregar res.

    :param paths: tots els fitxers del repositori en aquella revisió.
    :param formats: formats tabulars (`EngineConfig.formats`).
    :return: els fitxers de dades de qualsevol d'aquests formats, en ordre natural, i els formats que hi surten.
    """
    files = sorted((p for p in paths if is_tabular_path(p, formats)), key=natural_order)
    present = {file_format(p) for p in files}
    return DatasetFiles(tuple(files), tuple(f for f in formats if f in present))
