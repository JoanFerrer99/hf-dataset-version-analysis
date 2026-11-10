"""
Pas 1 (primera part): quines taules té un repositori en una revisió.

És el primer pas del motor (vegeu l'índex a `engine.py`).

A Hugging Face, un dataset no és un fitxer. Es reparteix en subsets (p.e.
un per idioma) i en splits o particions (`train`, `test`). Un split gran es
parteix en **shards**: fitxers amb les mateixes columnes que guarden,
cadascun, un bloc de files consecutives del split. Per exemple,
`train-00000-of-00003.parquet` és el shard 0 (es compta des de 0) d'un
total de 3; unint els 3 en ordre es recupera el split sencer. Els episodis
numerats de LeRobot (`episode_000000.parquet`…) funcionen igual.

La unitat que compara el motor és la **taula (subset, split)**, tal com la
mostra el Hub: tots els shards d'un split formen una sola taula. Així, si
entre dues versions les mateixes files es parteixen en més o menys fitxers,
no surt cap canvi. `classify_naming` reconeix com es reparteix una taula
(un fitxer, shards del Hub, episodis numerats o noms sense relació).
Explicació completa: `docs/architecture.md`, secció 2.2.

Per saber quines taules hi ha, `resolve_units` fa servir les mateixes regles
que la llibreria `datasets`: recrea l'arbre de fitxers com a fitxers buits
en un directori temporal (no es descarrega res) i li pregunta quines
particions hi veu. S'hi afegeixen dos casos que `datasets` no cobreix:

- els repositoris de vídeo o d'imatge amb taules (p.e. LeRobot, amb més
  vídeos que parquets): els fitxers tabulars que la media no fa servir es
  resolen com a taules pròpies, en lloc de quedar fora;
- els repositoris que `datasets` no sap llegir: cada fitxer tabular passa a
  ser una taula.

Abans, es tria el format: si una revisió té fitxers tabulars de més d'un
format, només es compara el primer de la llista de formats (`EngineConfig.formats`,
que el pipeline llegeix de `config/formats.toml`). Els fitxers dels altres
formats queden exclosos (`other_format`).
"""

import os
import re
import tempfile
from dataclasses import dataclass, field

from diffengine.config import DEFAULT_CONFIG

READABLE_FORMATS = ("csv", "tsv", "parquet", "jsonl", "json")
"""Els formats que sap llegir el motor (`load.load_table`)."""

# Constructors de `datasets` que llegeixen taules. La resta (imagefolder,
# audiofolder...) són repositoris de media: el seu metadata.csv no és un dataset.
TABULAR_BUILDERS = {"parquet", "csv", "json", "arrow"}
_BUILDER_EXTENSIONS = {"parquet": (".parquet",), "csv": (".csv", ".tsv"), "json": (".json", ".jsonl"), "arrow": (".arrow",)}

# Fitxers JSON de metadades, no de dades: del Hub/`datasets` i de LeRobot (`meta/info.json`, `meta/stats.json`).
METADATA_FILES = {"dataset_info.json", "dataset_infos.json", "dataset_dict.json", "state.json", "info.json",
                  "stats.json"}

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
    :ivar builder: format inferit (també per a repositoris de media, on les
        taules són els fitxers tabulars que la media no fa servir).
    :ivar error: motiu si `datasets` no ha pogut resoldre el repositori; llavors
        cada fitxer tabular és una taula (`naming="single"`, split = ruta).
    """

    units: list[Unit] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    builder: str | None = None
    error: str | None = None


def file_format(path: str) -> str:
    """
    :param path: ruta d'un fitxer.
    :return: l'extensió, en minúscules i sense el punt (p.e. `csv`).
    """
    return os.path.splitext(path)[1].lower().lstrip(".")


def is_tabular_path(path: str, formats: tuple[str, ...] = READABLE_FORMATS) -> bool:
    """
    Diu si un fitxer és una taula, només pel nom.

    :param path: ruta del fitxer dins del repositori.
    :param formats: formats que compten com a taules (per defecte, tots els que sap llegir el motor).
    :return: `True` si el format és a `formats` i no és un fitxer de metadades conegut.
    """
    return file_format(path) in formats and os.path.basename(path) not in METADATA_FILES


def preferred_format(paths: list[str], formats: tuple[str, ...]) -> str | None:
    """
    El format que es compara en una revisió.

    :param paths: fitxers de la revisió.
    :param formats: formats tabulars, en ordre de preferència.
    :return: el primer de `formats` que té algun fitxer tabular a `paths`, o `None` si no n'hi ha cap.
    """
    present = {file_format(p) for p in paths if is_tabular_path(p, formats)}
    return next((f for f in formats if f in present), None)


def classify_naming(files: list[str]) -> str:
    """
    Diu com es reparteix una taula en fitxers, segons els noms.

    :param files: rutes dels fitxers de la taula.
    :return: `single` (un fitxer), `hf_shards` (`train-00000-of-00003`...),
        `numbered` (mateix nom amb un número que canvia) o `distinct` (noms no relacionats).
    """
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
    Del README, conserva només la part de configuració que descriu les
    particions. La resta de metadades pot fer fallar la llibreria `datasets`.

    :param readme_text: contingut del README.
    :return: un README mínim amb només la configuració, o `None` si no n'hi ha.
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


def resolve_units(paths: list[str], readme_text: str | None = None,
                  formats: tuple[str, ...] = DEFAULT_CONFIG.formats) -> RepoLayout:
    """
    Troba les taules d'una revisió d'un repositori, sense descarregar dades.

    Tria el format que es compara (`preferred_format`), recrea l'arbre de
    fitxers com a fitxers buits en un directori temporal, sense els fitxers
    tabulars dels altres formats, i li pregunta a la llibreria `datasets` quines
    particions hi veu. Els fitxers partits d'una mateixa partició formen una
    sola taula.

    :param paths: tots els fitxers del repositori en aquella revisió.
    :param readme_text: contingut del README (pot descriure les particions), o `None`.
    :param formats: formats tabulars, en ordre de preferència (`EngineConfig.formats`).
    :return: les taules trobades i els fitxers tabulars que no formen part de cap taula, amb el motiu.
    """
    from datasets.load import LocalDatasetModuleFactory

    chosen = preferred_format(paths, formats)
    layout = RepoLayout()
    layout.excluded = {p: "other_format" for p in paths if is_tabular_path(p, formats) and file_format(p) != chosen}
    with tempfile.TemporaryDirectory(prefix="hf_layout_") as root:
        for path in paths:
            # El README es reescriu a sota; les metadades buides farien fallar `datasets` en llegir-les.
            if path == "README.md" or os.path.basename(path) in METADATA_FILES:
                continue
            # Els altres formats tabulars, també els que no són a `formats`: `datasets` no els ha de veure.
            if file_format(path) in READABLE_FORMATS and file_format(path) != chosen:
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
            layout.units = [Unit("default", path, (path,), file_format(path), "single")
                            for path in sorted(paths) if is_tabular_path(path, (chosen,))]
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

    if builder not in TABULAR_BUILDERS:
        # Repositori de media (p.e. LeRobot: més vídeos que parquet). El metadata.csv
        # del constructor de media no és un dataset, però les taules que no fa servir
        # sí: es resolen soles, amb les mateixes regles i sense el README (que descriu la media).
        tabular = [p for p in paths if is_tabular_path(p, (chosen,))]
        layout.excluded.update({p: "media_metadata" for p in tabular if p in used})
        loose = [p for p in tabular if p not in used]
        if loose:
            inner = resolve_units(loose, formats=(chosen,))
            layout.units, layout.error = inner.units, inner.error
            layout.excluded.update(inner.excluded)
        return layout

    for path in paths:
        if is_tabular_path(path, (chosen,)) and path not in used:
            same_format = path.lower().endswith(_BUILDER_EXTENSIONS[builder])
            layout.excluded[path] = "outside_any_split" if same_format else "other_format"
    return layout
