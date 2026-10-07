"""
Quines dades va comparar el paper a la Taula 1 (Census Income)?

El paper només dona la URL de cada repositori (i de la pàgina de la UCI per
a D0). Aquest script prova totes les definicions plausibles i mesura quina
reprodueix millor la taula:

- D0: `adult.data`, `adult.test`, o tots dos (amb o sense el punt final de
  les etiquetes d'`adult.test`);
- cada D_i: cada fitxer de dades (mateixa extensió que el de la font) de la
  seva carpeta, o de l'arrel si la carpeta encara no existia; la
  concatenació dels que comparteixen columnes; i cada revisió del
  repositori amb contingut diferent fins a la data del paper.

Per a cada combinació: codis del motor contra `PAPER_GROUND_TRUTH`. Per a
cada variant de D_i: d'on surten les files (`adult.data`, `adult.test`, cap).

Ús:
  python eval/census_variants.py
Sortida: eval/census_variants/{revisions.json, variants.csv, provenance.csv, summary.md}
"""

import functools
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "notebooks"))
load_dotenv(os.path.join(ROOT, ".env"))

import errors  # noqa: E402
import validate_census_income as v  # noqa: E402
from diffengine import pairs  # noqa: E402
from diffengine.engine import diff_bytes  # noqa: E402
from diffengine.units import is_tabular_path  # noqa: E402
from huggingface_hub import list_repo_commits  # noqa: E402

OUT = os.path.join(ROOT, "eval", "census_variants")
PAPER_DATE = datetime(2026, 7, 4, tzinfo=timezone.utc)  # creació de paper.pdf: cap dada posterior
RETRY = functools.partial(errors.with_retry, **errors.DEFAULT_RETRY_CONFIG)

D0_VARIANTS = {
    "data": (("adult.data",), False),
    "test": (("adult.test",), True),
    "data+test": (("adult.data", "adult.test"), True),
    "data+test (amb punt)": (("adult.data", "adult.test"), False),
}

# Carpeta del repositori que correspon a cada versió (D3 i D4 comparteixen repositori).
FOLDER = {"D3": "income/", "D4": "income-no race/"}

# Noms de les columnes numèriques que identifiquen una persona, a cada versió.
_KEY_ALIASES = {
    "age": ("age",),
    "fnlwgt": ("fnlwgt", "finalweight"),
    "gain": ("capitalgain",),
    "loss": ("capitalloss",),
    "hours": ("hoursperweek", "hoursworkedperweek"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", str(name).lower())


def _read(data: bytes, ext: str) -> pd.DataFrame:
    if ext == ".parquet":
        return pd.read_parquet(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data), sep=None, engine="python", skipinitialspace=True)


def _key_frame(df: pd.DataFrame) -> pd.DataFrame | None:
    """Columnes clau presents (edat, fnlwgt, guanys, pèrdues, hores), amb nom comú."""
    by_norm = {_norm(c): c for c in df.columns}
    cols = {}
    for key, aliases in _KEY_ALIASES.items():
        found = next((by_norm[a] for a in aliases if a in by_norm), None)
        if found is not None and pd.api.types.is_numeric_dtype(df[found]):
            cols[key] = df[found]
    return pd.DataFrame(cols) if len(cols) >= 3 else None


def provenance(df: pd.DataFrame, uci: dict[str, pd.DataFrame]) -> dict:
    """Proporció de files de `df` que són a `adult.data`, a `adult.test` o a cap (per les columnes clau)."""
    keys = _key_frame(df)
    if keys is None:
        return {"key_columns": "", "in_data": None, "in_test": None, "in_neither": None}
    cols = list(keys.columns)
    sets = {name: set(map(tuple, _key_frame(u)[cols].itertuples(index=False))) for name, u in uci.items()}
    rows = list(map(tuple, keys.itertuples(index=False)))
    in_data = sum(r in sets["data"] for r in rows)
    in_test = sum(r in sets["test"] and r not in sets["data"] for r in rows)
    n = max(len(rows), 1)
    return {"key_columns": ",".join(cols), "in_data": in_data / n, "in_test": in_test / n,
            "in_neither": (len(rows) - in_data - in_test) / n}


def file_variants(version: str, token: str) -> list[dict]:
    """Revisions del repositori (fins a la data del paper) amb contingut diferent als fitxers de la versió."""
    source = v.CENSUS_INCOME_SOURCES[version]
    repo, folder = source["repo_id"], FOLDER.get(version, "")
    commits = RETRY(lambda: list(list_repo_commits(repo, repo_type="dataset", token=token)))
    seen, out = set(), []
    for c in sorted(commits, key=lambda c: c.created_at):
        if c.created_at > PAPER_DATE:
            continue
        rev = pairs.list_revision(repo, c.commit_id, token, call=RETRY)
        ext = os.path.splitext(source["filename"])[1]
        data_files = [p for p in rev.sizes if is_tabular_path(p) and p.endswith(ext)]
        # La carpeta de la versió; si encara no existia (mstz/adult abans de 2025-10), els fitxers de l'arrel.
        files = sorted(p for p in data_files if p.startswith(folder)) or sorted(p for p in data_files if "/" not in p)
        signature = tuple((p, rev.content_ids[p]) for p in files)
        if not files or signature in seen:
            continue
        seen.add(signature)
        out.append({"version": version, "repo": repo, "revision": c.commit_id, "date": c.created_at.isoformat(),
                    "files": files})
    return out


def load_variant(version: str, revision: str, files: list[str], token: str) -> list[tuple[str, bytes, str]]:
    """Cada fitxer sol i, si n'hi ha més d'un amb les mateixes columnes, tots concatenats (com a CSV)."""
    loaded = [(f, *v.download_census_income_version(version, token, filename=f, revision=revision)) for f in files]
    variants = [(f, data, ext) for f, data, ext in loaded]
    frames = [_read(data, ext) for _, data, ext in loaded]
    if len(frames) > 1 and all(list(fr.columns) == list(frames[0].columns) for fr in frames):
        joined = pd.concat(frames, ignore_index=True).to_csv(index=False).encode()
        variants.append(("+".join(files), joined, ".csv"))
    return variants


def score(version: str, codes: set[str]) -> dict:
    paper = v.PAPER_GROUND_TRUTH[version] - {"C100"}
    return {"tp": len(codes & paper), "fp": len(codes - paper), "fn": len(paper - codes),
            "fp_codes": ",".join(sorted(codes - paper)), "fn_codes": ",".join(sorted(paper - codes))}


def main() -> None:
    token = os.getenv("HF_TOKEN")
    os.makedirs(OUT, exist_ok=True)

    revisions = [r for version in v.CENSUS_INCOME_SOURCES for r in file_variants(version, token)]
    with open(os.path.join(OUT, "revisions.json"), "w") as f:
        json.dump(revisions, f, indent=1)
    print(f"{len(revisions)} revisions amb contingut diferent")

    d0 = {name: v.download_uci_adult(files, strip) for name, (files, strip) in D0_VARIANTS.items()}
    uci = {"data": _read(d0["data"], ".csv"), "test": _read(d0["test"], ".csv")}

    rows, prov = [], []
    for r in revisions:
        for label, data, ext in load_variant(r["version"], r["revision"], r["files"], token):
            base = {"version": r["version"], "revision": r["revision"][:7], "date": r["date"][:10], "file": label,
                    "rows": len(_read(data, ext))}
            prov.append({**base, **provenance(_read(data, ext), uci)})
            for d0_name, d0_bytes in d0.items():
                result = diff_bytes(d0_bytes, ".csv", data, ext)
                rows.append({**base, "d0": d0_name, "status": result.status,
                             **score(r["version"], result.codes if result.status == "ok" else set())})
            print(f"  {r['version']} {r['revision'][:7]} {label}")

    variants = pd.DataFrame(rows)
    variants.to_csv(os.path.join(OUT, "variants.csv"), index=False)
    pd.DataFrame(prov).to_csv(os.path.join(OUT, "provenance.csv"), index=False)
    write_summary(variants, pd.DataFrame(prov))


def write_summary(variants: pd.DataFrame, prov: pd.DataFrame) -> None:
    def md(df: pd.DataFrame) -> str:
        lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
        lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in df.itertuples(index=False)]
        return "\n".join(lines)

    variants = variants.assign(errors=variants.fp + variants.fn)
    best = variants.sort_values(["version", "errors", "fp"]).groupby("version").head(3)
    # Una sola D0 per a totes les versions: per a cada D0, la millor variant de cada D_i.
    per_d0 = (variants.sort_values("errors").groupby(["d0", "version"]).head(1)
              .groupby("d0")[["tp", "fp", "fn"]].sum().reset_index())
    per_d0["precision"] = (per_d0.tp / (per_d0.tp + per_d0.fp)).round(3)
    per_d0["recall"] = (per_d0.tp / (per_d0.tp + per_d0.fn)).round(3)
    text = [
        "# Quines dades va comparar el paper (Census Income)", "",
        "Generat per `eval/census_variants.py`. Errors = FP + FN contra la Taula 1 (sense C100).", "",
        "## Millor variant per D0 (la millor revisió/fitxer de cada D_i)", "", md(per_d0), "",
        "## Les 3 millors combinacions per versió", "",
        md(best[["version", "d0", "revision", "date", "file", "rows", "tp", "fp", "fn", "fp_codes", "fn_codes"]]), "",
        "## Procedència de les files de cada variant", "",
        md(prov.round(3)), "",
    ]
    with open(os.path.join(OUT, "summary.md"), "w") as f:
        f.write("\n".join(text))


if __name__ == "__main__":
    main()
