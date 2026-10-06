"""
L6: model de sortida.

- `Change`: un canvi detectat (una fila de la taula de canvis).
- `DiffResult`: els canvis d'un parell de versions més el seu estat.
- `changes_frame` / `status_frame`: taules llargues per escriure a CSV/parquet.
- `legacy_frame`: export amb les columnes del CSV antic, més `file_path`.
"""

import json
from dataclasses import asdict, dataclass, field

import pandas as pd

ENGINE_VERSION = "2.2.0"
"""Es desa a cada fila de sortida, amb el hash de la configuració."""

# Els 14 codis tabulars de la taxonomia (C100, metadades, és fora d'abast).
TABULAR_CODES = ("C210", "C221", "C222", "C223", "C311", "C312", "C321", "C322",
                 "C410", "C421", "C422", "C510", "C520", "C530")

CODE_DESCRIPTIONS = {
    "C210": "Ordre de columnes", "C221": "Afegir columna", "C222": "Eliminar columna",
    "C223": "Renombrar columna", "C311": "Tipus de columna categòrica",
    "C312": "Valors d'una columna categòrica", "C321": "Tipus de columna numèrica",
    "C322": "Valors d'una columna numèrica", "C410": "Ordre de files", "C421": "Afegir fila",
    "C422": "Eliminar fila", "C510": "Missings", "C520": "Correlacions", "C530": "Distribució de les dades",
}

# Trenquen l'EXECUCIÓ d'un pipeline que llegeix per nom/posició/tipus/ordre;
# no mesura l'impacte en la qualitat del model (docs/taxonomy.md).
BREAKING_CODES = frozenset({"C210", "C222", "C223", "C311", "C321", "C410"})

@dataclass
class Change:
    """
    :ivar column: columna afectada (nom nou), o parell `a|b` per a C520.
    :ivar old_column: nom antic si és diferent (renoms).
    :ivar n_affected: files o cel·les afectades, si aplica.
    :ivar confidence: validesa de l'explicació o 1 - p de la prova.
    :ivar evidence: dades de suport (mapatge, fórmula, estadístics).
    """

    code: str
    column: str | None = None
    old_column: str | None = None
    subtype: str | None = None
    n_affected: int | None = None
    share_affected: float | None = None
    confidence: float = 1.0
    evidence: dict = field(default_factory=dict)


@dataclass
class DiffResult:
    status: str
    changes: list[Change] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def codes(self) -> set[str]:
        return {c.code for c in self.changes}


CHANGE_COLUMNS = ["repo_id", "old_rev", "new_rev", "file_path", "old_file_path", "code", "column", "old_column",
                  "subtype", "n_affected", "share_affected", "confidence", "evidence_json", "engine_version",
                  "config_hash"]
"""Esquema de la taula de canvis (format llarg, una fila per canvi)."""


def changes_frame(result: DiffResult, key: dict, engine_version: str, config_hash: str) -> pd.DataFrame:
    """
    :param key: `repo_id`, `old_rev`, `new_rev`, `file_path`, `old_file_path`.
    """
    rows = []
    for c in result.changes:
        row = {**key, **asdict(c)}
        row["evidence_json"] = json.dumps(row.pop("evidence"), default=str, sort_keys=True)
        row["engine_version"] = engine_version
        row["config_hash"] = config_hash
        rows.append(row)
    return pd.DataFrame(rows, columns=CHANGE_COLUMNS)


def status_frame(result: DiffResult, key: dict) -> pd.DataFrame:
    info = result.info
    return pd.DataFrame([{
        **key, "status": result.status,
        "alignment_method": info.get("row_alignment"),
        "key_columns": ",".join(info.get("key_columns", [])),
        "matched_row_share": info.get("matched_row_share"),
        "format_old": info.get("format_old"), "format_new": info.get("format_new"),
        "detail": info.get("reason") or info.get("error"),
    }])


def legacy_frame(changes: pd.DataFrame) -> pd.DataFrame:
    """Columnes del CSV antic (`dataset_id, version_from, version_to, code, description, is_breaking`) + `file_path`."""
    out = pd.DataFrame({
        "dataset_id": changes["repo_id"], "version_from": changes["old_rev"], "version_to": changes["new_rev"],
        "file_path": changes["file_path"], "code": changes["code"],
    })
    out["description"] = out["code"].map(CODE_DESCRIPTIONS)
    out["is_breaking"] = out["code"].isin(BREAKING_CODES)
    return out.drop_duplicates().reset_index(drop=True)
