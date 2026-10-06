"""
Configuració del motor: tots els llindars i decisions provisionals en un sol
lloc, amb el valor per defecte documentat. Les decisions P* i U* es
descriuen a `docs/open_decisions.md`. Per provar uns altres valors:
`dataclasses.replace(DEFAULT_CONFIG, alpha=0.05)`.
"""

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EngineConfig:
    # --- L0: unitats i fitxers ---------------------------------------------
    concat_shards: bool = True
    """U1: concatena els shards (hf_shards / numbered) d'una taula si comparteixen esquema."""
    max_unit_bytes: int = 500 * 1024**2
    """U4: per sobre, la taula es marca `too_large_profile_only`."""

    # --- L1: càrrega i tipus ----------------------------------------------
    missing_tokens: tuple[str, ...] = ("", "?", "NA", "N/A", "n/a", "NaN", "nan", "null", "NULL", "None", "none", "-")
    """Valors que es llegeixen com a absents (comparats després de treure espais)."""
    text_min_distinct_share: float = 0.5
    """P6: una columna no numèrica és text lliure si té almenys aquesta proporció de valors distints..."""
    text_min_mean_length: float = 30.0
    """P6: ... i una longitud mitjana d'almenys aquests caràcters."""

    # --- L3: alineació de columnes ------------------------------------------
    column_match_min_validity: float = 0.95
    """Proporció de files aparellades que una explicació (identitat, bijecció, transformació) ha de reproduir."""
    numeric_rel_tolerance: float = 1e-6
    """Tolerància relativa per considerar iguals dos valors numèrics."""
    min_explained_rows: int = 5
    """Files canviades mínimes per atribuir un canvi de valors a una transformació (C322) o a una divisió de
    categoria (C312 `split`); per sota, són edicions de cel·les."""
    mostly_null_share: float = 0.8
    """C222 `mostly_null`: proporció de nuls a la columna eliminada."""

    # --- L4: alineació de files --------------------------------------------
    edited_row_min_agreement: float = 0.5
    """P2: proporció mínima de columnes aparellades on dues files han de coincidir per ser "la mateixa fila editada"."""
    key_min_overlap: float = 0.5
    """Una columna és clau si és única i no nul·la a les dues versions i comparteix aquesta proporció de valors."""
    max_pairing_columns: int = 40
    """Límit de columnes per a l'aparellament per "totes menys una"."""
    row_subtype_min_validity: float = 0.9
    """Validesa mínima per assignar un subtipus de fila (`outlier`, `predicate`...)."""

    # --- L5: detectors ------------------------------------------------------
    null_transition_is_c510: bool = True
    """P1: valor <-> nul en una fila aparellada és C510 (si no, C312/C322)."""
    kind_change_by_old_kind: bool = True
    """P3: una conversió entre tipus es codifica pel tipus antic."""
    report_representation: bool = True
    """P5: els canvis de representació es reporten amb subtipus `representation`."""
    transformation_suppresses_c530: bool = True
    """P8: una columna explicada per una transformació (C322) no genera C530."""

    c510_min_rate_delta: float = 0.01
    """C510: diferència mínima de proporció de nuls (efecte), a més de la prova estadística."""
    c520_min_delta: float = 0.1
    """C520: canvi mínim de correlació (|Δ|)."""
    c520_max_columns: int = 30
    """C520: màxim de columnes considerades (parells = n·(n-1)/2)."""
    c530_min_distance: float = 0.1
    """C530: distància mínima entre distribucions (KS per a numèriques, variació total per a categòriques)."""
    alpha: float = 0.01
    """Nivell de significació de les proves (filtre secundari: decideix la mida d'efecte)."""

    def hash(self) -> str:
        """Hash curt de la configuració, per guardar-lo amb cada resultat."""
        payload = json.dumps(asdict(self), sort_keys=True, default=list).encode()
        return hashlib.sha256(payload).hexdigest()[:12]


DEFAULT_CONFIG = EngineConfig()
