"""
Classificador de canvis segons els codis estructurals/de contingut de la
taxonomia (C210-C530, `docs/taiga/taxonomy.md`). Reutilitza el motor de
diffing de `change_diff.py` sense reimplementar-lo -- només hi afegeix la
capa d'etiquetatge: traduir els fets estructurals que ja calcula
`change_diff.compute_all_diffs` a files `(dataset_id, version_from,
version_to, code, is_breaking)`.

**C100 (metadada) no es classifica** -- decisió explícita del projecte,
no un oblit: no és una comparació tabular (requeriria comparar dataset
card/llicència/format, no columnes/files), i el classificador se centra
en canvis estructurals/de contingut de dades.

Cridat per `eligibility_scan.classify_dataset` (`classify_changes=True`),
l'únic cridant real d'aquest mòdul.

Regla de disseny de la taxonomia (obligatòria): el classificador NO usa
informació de quina columna és el target del pipeline -- cap funció
d'aquest mòdul ni de `change_diff.py` en rep cap paràmetre.

`is_breaking`: heurística PRÒPIA d'aquest estudi (el paper no en defineix
cap de formal) -- "breaking" = un canvi que probablement trenca un
pipeline que llegeix el dataset per nom/posició/tipus sense adaptar-se:
C210 (ordre de columnes), C222 (eliminar columna), C223 (renom), C311/
C321 (canvi de tipus). La resta (afegir columna/fila, canvis de
valors/distribució/correlació/missings) es marquen `is_breaking=False`
-- poden afectar la qualitat del model, però no fan fallar un pipeline
que simplement llegeix el dataset.
"""

from dataclasses import dataclass

import pandas as pd

import change_diff as cd

BREAKING_CODES = frozenset({"C210", "C222", "C223", "C311", "C321"})


@dataclass
class ChangeLabel:
    """
    Una etiqueta de canvi: un codi de taxonomia detectat entre dues
    instantànies d'UN dataset.

    :ivar dataset_id: identificador del dataset.
    :ivar version_from: etiqueta de la versió anterior (SHA de commit).
    :ivar version_to: etiqueta de la versió posterior (SHA de commit).
    :ivar code: codi de la taxonomia (`"C210"`...`"C530"`).
    :ivar is_breaking: `True` si el codi és a `BREAKING_CODES`.
    """

    dataset_id: str
    version_from: str
    version_to: str
    code: str
    is_breaking: bool


def classify_diffs(diffs: dict, dataset_id: str, version_from: str, version_to: str) -> list[ChangeLabel]:
    """
    Tradueix els fets estructurals de `change_diff.compute_all_diffs` a
    etiquetes de codi (C210-C530). NO recalcula res -- només llegeix els
    booleans ja calculats i hi afegeix `is_breaking` (vegeu la
    documentació del mòdul per a la regla).

    :param diffs: sortida de `change_diff.compute_all_diffs(before, after)`.
    :param dataset_id: identificador del dataset.
    :param version_from: SHA del commit anterior.
    :param version_to: SHA del commit posterior.
    :return: llista de `ChangeLabel`, una per codi amb senyal detectat
        (`diffs[code]` truthy). `C410` mai s'hi inclou si `diffs["C410"]`
        és `None` (no detectable, vegeu `change_diff.compute_all_diffs`).
    """
    return [
        ChangeLabel(dataset_id, version_from, version_to, code, is_breaking=code in BREAKING_CODES)
        for code in cd.TABULAR_CODES
        if diffs.get(code)
    ]


def classify_file_change(
    dataset_id: str,
    before_df: pd.DataFrame | None,
    after_df: pd.DataFrame | None,
    version_from: str,
    version_to: str,
) -> list[ChangeLabel]:
    """
    Classifica el canvi d'UN fitxer tabular concret entre dues revisions
    -- usada per `eligibility_scan.classify_dataset` (`classify_changes=
    True`) per a cada fitxer tabular (`change_diff.is_tabular_path`) que
    canvia en un commit substantiu.

    :param dataset_id: identificador del dataset.
    :param before_df: contingut del fitxer a la revisió anterior, o
        `None` si el fitxer no hi existia (acabat d'afegir).
    :param after_df: contingut a la revisió posterior, o `None` si el
        fitxer ha estat eliminat.
    :param version_from: SHA del commit anterior.
    :param version_to: SHA del commit posterior.
    :return: si `before_df`/`after_df` són tots dos `None`, `[]`. Si
        NOMÉS un dels dos és `None` (fitxer afegit o eliminat sencer),
        UNA etiqueta aproximada (`C421` si afegit, `C422` si eliminat) --
        sense verificar-ho a nivell de fila (no hi ha ID d'instància
        estable entre fitxers/chunks, limitació ja documentada a
        `change_diff.diff_row_count`). Si tots dos existeixen, el
        resultat de `classify_diffs(change_diff.compute_all_diffs(...))`.
    """
    if before_df is None and after_df is None:
        return []
    if before_df is None:
        return [ChangeLabel(dataset_id, version_from, version_to, "C421", is_breaking=False)]
    if after_df is None:
        return [ChangeLabel(dataset_id, version_from, version_to, "C422", is_breaking=False)]

    diffs = cd.compute_all_diffs(before_df, after_df)
    return classify_diffs(diffs, dataset_id, version_from, version_to)
