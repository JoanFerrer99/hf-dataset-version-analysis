"""
Pas 5: com es representa un canvi i la taula de sortida.

- `Change`: un canvi detectat: codi de la taxonomia, columna i subtipus.
- `DiffResult`: els canvis d'un parell de taules més el seu estat.
- `classification_frame`: la taula que escriu la Fase 2
  (`change_classification.csv`).
- `TABULAR_CODES`, `CODE_DESCRIPTIONS`, `BREAKING_CODES`: la taxonomia.
"""

from dataclasses import dataclass, field

import pandas as pd

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
    :ivar code: codi de la taxonomia (`C223`, `C421`...).
    :ivar column: columna afectada (nom nou), o parell `a|b` per a C520.
    :ivar old_column: nom antic si és diferent (renoms).
    :ivar subtype: què explica el canvi (p.e. C422 `had_nulls`, C322 `log`).
    """

    code: str
    column: str | None = None
    old_column: str | None = None
    subtype: str | None = None


@dataclass
class DiffResult:
    status: str
    changes: list[Change] = field(default_factory=list)

    @property
    def codes(self) -> set[str]:
        """
        :return: els codis de canvi diferents que s'han detectat.
        """
        return {c.code for c in self.changes}


CLASSIFICATION_COLUMNS = ["dataset_id", "version_from", "version_to", "file_path", "code", "description",
                          "is_breaking"]


def classification_frame(rows: list[dict]) -> pd.DataFrame:
    """
    La taula de sortida de la Fase 2: un codi per taula i parell de versions,
    amb la descripció i si trenca. Si una taula té el mateix codi en diverses
    columnes, surt un sol cop.

    :param rows: una fila per canvi, amb `dataset_id`, `version_from`,
        `version_to`, `file_path` i `code`.
    :return: la taula, sense files repetides.
    """
    out = pd.DataFrame(rows, columns=CLASSIFICATION_COLUMNS[:5])
    out["description"] = out["code"].map(CODE_DESCRIPTIONS)
    out["is_breaking"] = out["code"].isin(BREAKING_CODES)
    return out.drop_duplicates().reset_index(drop=True)
