"""
Motor de detecció de canvis entre versions de datasets tabulars de Hugging Face.

Entrades públiques:
- `engine.diff_bytes` / `engine.diff_tables`: dos fitxers o dues taules.
- `pairs.compare_revisions` + `pairs.revision_rows`: dues revisions d'un repositori.

Disseny: `docs/engine.md`; decisions provisionals: `docs/open_decisions.md`.
"""
