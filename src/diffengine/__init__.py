"""
Motor de detecció de canvis entre dues versions d'un dataset tabular.

La idea: abans de buscar canvis, decidir què correspon a què entre les
dues versions (quines taules, quines columnes, quines files). Un cop tot
està aparellat, el que no té parella s'ha afegit o eliminat, i el que en
té es compara cel·la a cel·la.

Entrades públiques:
- `engine.diff_bytes` / `engine.diff_tables`: dos fitxers o dues taules.
- `pairs.compare_revisions` + `pairs.revision_rows`: dues revisions d'un repositori.

Explicació completa, pas a pas: `docs/engine.md`.
"""
