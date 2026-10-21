"""
Tots els llindars i les opcions del motor, en un sol lloc.

Cada camp porta el valor per defecte i explica què fa el motor amb ell. Les
opcions que encara s'han de confirmar amb el director s'expliquen a
`docs/open_decisions.md`, i les que ja estan tancades, a
`docs/decisions_tfg.txt` (T-20). Per provar uns altres valors sense tocar el
codi: `dataclasses.replace(DEFAULT_CONFIG, alpha=0.05)`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    # --- Pas 1: quines taules es comparen -----------------------------------
    concat_shards: bool = True
    """Una taula partida en diversos fitxers (shards del Hub com
    `train-00000-of-00003.parquet`, o episodis numerats de LeRobot) es llegeix
    com una sola taula: els fitxers s'uneixen en ordre, només si tots tenen les
    mateixes columnes. Amb `False`, cada fitxer es compara pel seu compte, i
    un canvi en com està partida la taula sortiria com a fitxers sencers
    afegits i eliminats."""
    max_unit_bytes: int = 500 * 1024**2
    """Mida màxima d'una taula, sumant la versió antiga i la nova. Per sobre,
    no es descarrega ni es compara: la parella queda amb l'estat `too_large` i
    sense cap codi."""

    # --- Pas 2: llegir cada taula -------------------------------------------
    missing_tokens: tuple[str, ...] = ("", "?", "NA", "N/A", "n/a", "NaN", "nan", "null", "NULL", "None", "none", "-")
    """Valors que es llegeixen com a absents (comparats després de treure espais)."""
    text_min_distinct_share: float = 0.5
    """Una columna de text es tracta com a text lliure, i no com a categòrica,
    si almenys aquesta proporció dels seus valors són diferents..."""
    text_min_mean_length: float = 30.0
    """... i els valors fan, de mitjana, almenys aquests caràcters."""

    # --- Pas 3a/3c: aparellar columnes --------------------------------------
    column_match_min_validity: float = 0.95
    """Proporció de files aparellades que una explicació (identitat, bijecció, transformació) ha de reproduir."""
    numeric_rel_tolerance: float = 1e-6
    """Tolerància relativa per considerar iguals dos valors numèrics."""
    min_explained_rows: int = 5
    """Files canviades mínimes per atribuir un canvi de valors a una transformació (C322) o a una divisió de
    categoria (C312 `split`); per sota, són edicions de cel·les."""
    same_column_min_shared_values: float = 0.5
    """Renom sobre una altra mostra de files: proporció mínima dels valors distints nous que ja hi eren
    (columna amb ≥ 20 valors distints), a més de no canviar de distribució (`c530_min_distance`)."""
    mostly_null_share: float = 0.8
    """C222 `mostly_null`: proporció de nuls a la columna eliminada."""

    # --- Pas 3b: aparellar files --------------------------------------------
    edited_row_min_agreement: float = 0.5
    """Dues files que no són idèntiques encara poden ser la mateixa fila amb
    alguna cel·la editada, si coincideixen en almenys aquesta proporció de les
    columnes que serveixen per aparellar. Si no hi arriben, la fila antiga
    compta com a eliminada (C422) i la nova com a afegida (C421)."""
    key_min_overlap: float = 0.5
    """Una columna és clau si és única i no nul·la a les dues versions i comparteix aquesta proporció de valors."""
    max_pairing_columns: int = 40
    """Límit de columnes per a l'aparellament per "totes menys una"."""
    row_subtype_min_validity: float = 0.9
    """Validesa mínima per assignar un subtipus de fila (`outlier`, `predicate`...)."""

    # --- Pas 4: detectar els canvis -----------------------------------------
    null_transition_is_c510: bool = True
    """Una cel·la d'una fila aparellada que passa de tenir valor a estar buida,
    o al revés, es reporta com a canvi de valors absents (C510), no com a canvi
    de valor (C312/C322). Amb `False`, aquestes cel·les no es busquen: només
    es mira si canvia la proporció de buits de tota la columna."""
    kind_change_by_old_kind: bool = True
    """Quan una columna passa de categòrica a numèrica, o al revés, el codi es
    tria pel tipus que tenia a la versió antiga: C311 si era categòrica, C321
    si era numèrica. Amb `False`, es triaria pel tipus nou."""
    report_representation: bool = True
    """Els canvis que només afecten com s'escriuen els valors d'una columna
    numèrica (coma decimal, notació científica) es reporten com a C322
    `representation`, en lloc d'amagar-los. Els espais o les majúscules en una
    categòrica (C312 `representation`) es reporten sempre. Canviar el símbol
    que vol dir "absent" no es reporta mai."""
    transformation_suppresses_c530: bool = True
    """Si els valors nous d'una columna s'expliquen a partir dels antics amb una
    fórmula (C322: multiplicar per un factor, logaritme, min-max,
    estandardització...) o amb soroll afegit, no s'hi afegeix també un canvi de
    distribució (C530)."""

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


DEFAULT_CONFIG = EngineConfig()
