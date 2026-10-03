"""
L0 (part 1): quines taules té un repositori en una revisió.

Un "dataset" del motor és una taula (subset, split) tal com la mostra el
Hub. La resolució la fa la llibreria `datasets` amb les seves pròpies
regles (patró de shards, noms de split, YAML `configs` del README, un sol
format per dataset), sobre una còpia buida de l'arbre de fitxers: no es
descarrega cap dada.
"""

import os
import re
import tempfile
from dataclasses import dataclass, field

TABULAR_EXTENSIONS = (".parquet", ".csv", ".tsv", ".json", ".jsonl")

# Constructors de `datasets` que llegeixen taules. La resta (imagefolder,
# audiofolder...) són repositoris de media: el seu metadata.csv no és un dataset.
TABULAR_BUILDERS = {"parquet", "csv", "json", "arrow"}
_BUILDER_EXTENSIONS = {"parquet": (".parquet",), "csv": (".csv", ".tsv"), "json": (".json", ".jsonl"), "arrow": (".arrow",)}

_HF_SHARD = re.compile(r"-\d{5}-of-\d{5}(?=\.)")
_TRAILING_NUMBER = re.compile(r"\d+(?=\.[^./]+$)")


@dataclass(frozen=True)
class Unit:
    """
    Una taula (subset, split) d'una revisió.

    :ivar subset: nom del subset (config); `"default"` si no n'hi ha.
    :ivar split: nom del split.
    :ivar files: rutes dins del repositori, en ordre de shard.
    :ivar builder: format que n'infereix `datasets` (`parquet`, `csv`...).
    :ivar naming: com es reparteixen els fitxers: `single`, `hf_shards`
        (`train-00000-of-00003`), `numbered` (mateix nom amb número
        variable, p.e. episodis LeRobot) o `distinct` (noms no relacionats).
    """

    subset: str
    split: str
    files: tuple[str, ...]
    builder: str
    naming: str


@dataclass
class RepoLayout:
    """
    Resultat de resoldre un repositori en una revisió.

    :ivar units: taules tabulars trobades.
    :ivar excluded: fitxers tabulars que no formen part de cap taula, amb el motiu.
    :ivar builder: format inferit (també per a repositoris de media).
    :ivar error: motiu si `datasets` no ha pogut resoldre el repositori.
    """

    units: list[Unit] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    builder: str | None = None
    error: str | None = None


def is_tabular_path(path: str) -> bool:
    return path.lower().endswith(TABULAR_EXTENSIONS)


def classify_naming(files: list[str]) -> str:
    """Patró de noms d'un grup de fitxers (vegeu `Unit.naming`)."""
    if len(files) == 1:
        return "single"
    if all(_HF_SHARD.search(f) for f in files):
        return "hf_shards"
    stems = {_TRAILING_NUMBER.sub("#", os.path.basename(f)) for f in files}
    if len(stems) == 1 and all(_TRAILING_NUMBER.search(os.path.basename(f)) for f in files):
        return "numbered"
    return "distinct"


def _configs_only_readme(readme_text: str) -> str | None:
    """
    README amb només la clau `configs` del YAML: és l'única que afecta la
    resolució, i així un tipus de feature desconegut (p.e. `VideoFrame`)
    no la fa fallar.
    """
    import yaml

    match = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", readme_text, re.DOTALL)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or "configs" not in meta:
        return None
    return "---\n" + yaml.safe_dump({"configs": meta["configs"]}) + "---\n"


def resolve_units(paths: list[str], readme_text: str | None = None) -> RepoLayout:
    """
    Resol les taules (subset, split) d'una revisió amb les regles de `datasets`.

    :param paths: tots els fitxers del repositori en aquella revisió.
    :param readme_text: contingut del `README.md` (pel YAML `configs`), o `None`.
    :return: `RepoLayout` amb les taules i els fitxers tabulars exclosos.
    """
    from datasets.load import LocalDatasetModuleFactory

    layout = RepoLayout()
    with tempfile.TemporaryDirectory(prefix="hf_layout_") as root:
        for path in paths:
            if path == "README.md":
                continue
            full = os.path.join(root, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "w").close()
        readme = _configs_only_readme(readme_text) if readme_text else None
        if readme is not None:
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
                f.write(readme)

        try:
            module = LocalDatasetModuleFactory(root).get_module()
        except Exception as exc:
            layout.error = f"{type(exc).__name__}: {exc}"[:200]
            for path in paths:
                if is_tabular_path(path):
                    layout.excluded[path] = "unresolved"
            return layout

        builder = module.module_path.rsplit(".", 1)[-1]
        layout.builder = builder
        prefix = root.rstrip("/") + "/"
        used: set[str] = set()
        for config in module.builder_configs_parameters.builder_configs:
            data_files = config.data_files or {}
            if hasattr(data_files, "resolve"):
                # Amb `configs` al YAML, `datasets` hi deixa patrons sense resoldre.
                try:
                    data_files = data_files.resolve(root)
                except FileNotFoundError:
                    continue
            for split, files in data_files.items():
                rel = sorted(f.split(prefix, 1)[-1] for f in files)
                used.update(rel)
                if builder in TABULAR_BUILDERS:
                    layout.units.append(Unit(
                        subset=config.name or "default", split=str(split), files=tuple(rel),
                        builder=builder, naming=classify_naming(rel),
                    ))

    for path in paths:
        if not is_tabular_path(path):
            continue
        if builder not in TABULAR_BUILDERS:
            layout.excluded[path] = "media_metadata" if path in used else "outside_any_split"
        elif path not in used:
            same_format = path.lower().endswith(_BUILDER_EXTENSIONS[builder])
            layout.excluded[path] = "outside_any_split" if same_format else "other_format"
    return layout
