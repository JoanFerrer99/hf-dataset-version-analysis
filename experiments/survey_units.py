"""
Mesura quantes taules (subset, split) dels repositoris elegibles tenen més
d'un fitxer, i per què, abans de fixar la unitat de "dataset" del motor v2.

Agafa els elegibles de tots els `data/run_*/eligibility_report_*.csv` i, si
n'hi ha, les revisions de `versions_*.csv` (si no, `main`). Per revisió:
llista de fitxers + README, sense descarregar dades.

Ús:
  python experiments/survey_units.py            # resultats a experiments/survey/
"""

import functools
import glob
import json
import os
import sys
from collections import Counter

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import errors  # noqa: E402
from diffengine import pairs  # noqa: E402

RETRY = functools.partial(errors.with_retry, **errors.DEFAULT_RETRY_CONFIG)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "experiments", "survey")
CACHE = os.path.join(OUT, "cache.json")


def _md(df: pd.DataFrame) -> str:
    """Taula markdown sense dependre de `tabulate`."""
    cols = list(df.columns)
    rows = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    rows += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)


def eligible_revisions() -> dict[str, list[str]]:
    """`{repo_id: [revisions en ordre cronològic]}`."""
    repos: set[str] = set()
    for f in glob.glob(os.path.join(ROOT, "data", "run_*", "eligibility_report_*.csv")):
        df = pd.read_csv(f)
        repos.update(df.loc[df["eligible"] == True, "dataset_id"])  # noqa: E712
    revisions: dict[str, list[str]] = {r: [] for r in repos}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "run_*", "versions_*.csv"))):
        df = pd.read_csv(f).sort_values(["dataset_id", "version_order"])
        for repo, group in df.groupby("dataset_id"):
            for sha in group["commit_sha"]:
                if repo in revisions and sha not in revisions[repo]:
                    revisions[repo].append(sha)
    return {r: (revs or ["main"]) for r, revs in sorted(revisions.items())}


def fetch_layout(repo: str, revision: str, token: str) -> dict:
    """Llista fitxers i README d'una revisió i en resol les taules (mateix codi que el motor)."""
    try:
        rev = pairs.list_revision(repo, revision, token, call=RETRY)
    except Exception as exc:
        return {"error": f"tree: {errors.classify_error(exc).value}"}
    layout = rev.layout
    return {
        "builder": layout.builder,
        "error": layout.error,
        "n_files": len(rev.sizes),
        "units": [{"subset": u.subset, "split": u.split, "files": list(u.files), "naming": u.naming,
                   "builder": u.builder} for u in layout.units],
        "excluded": layout.excluded,
    }


def main() -> None:
    load_dotenv(os.path.join(ROOT, ".env"))
    token = os.getenv("HF_TOKEN")
    os.makedirs(OUT, exist_ok=True)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

    targets = eligible_revisions()
    print(f"{len(targets)} repositoris, {sum(len(v) for v in targets.values())} revisions")
    for repo, revisions in targets.items():
        for rev in revisions:
            key = f"{repo}@{rev}"
            if key not in cache:
                print(f"  {key}")
                cache[key] = fetch_layout(repo, rev, token)
                with open(CACHE, "w") as f:
                    json.dump(cache, f)

    unit_rows, excl_rows, change_rows = [], [], []
    for repo, revisions in targets.items():
        prev = None
        for i, rev in enumerate(revisions):
            lay = cache[f"{repo}@{rev}"]
            for u in lay.get("units", []):
                unit_rows.append({"repo": repo, "revision": rev, "version": i + 1, "subset": u["subset"],
                                  "split": u["split"], "builder": u["builder"], "n_files": len(u["files"]),
                                  "naming": u["naming"]})
            for path, reason in lay.get("excluded", {}).items():
                excl_rows.append({"repo": repo, "revision": rev, "path": path, "reason": reason})
            if prev is not None and not lay.get("error") and not prev.get("error"):
                old = {(u["subset"], u["split"]): set(u["files"]) for u in prev.get("units", [])}
                new = {(u["subset"], u["split"]): set(u["files"]) for u in lay.get("units", [])}
                for key in sorted(old.keys() | new.keys()):
                    a, b = old.get(key, set()), new.get(key, set())
                    change_rows.append({
                        "repo": repo, "version_from": i, "version_to": i + 1, "subset": key[0], "split": key[1],
                        "status": "added" if not a else "removed" if not b else "same_files" if a == b else "files_changed",
                        "n_old": len(a), "n_new": len(b), "kept": len(a & b),
                    })
            prev = lay

    units = pd.DataFrame(unit_rows)
    excl = pd.DataFrame(excl_rows)
    changes = pd.DataFrame(change_rows)
    units.to_csv(os.path.join(OUT, "units.csv"), index=False)
    excl.to_csv(os.path.join(OUT, "excluded.csv"), index=False)
    changes.to_csv(os.path.join(OUT, "unit_changes.csv"), index=False)

    latest = units.sort_values("version").groupby(["repo", "subset", "split"]).tail(1)
    errors_ = Counter(v.get("error") is not None for v in cache.values() if v)
    lines = [
        "# Enquesta d'unitats (subset, split) als repositoris elegibles", "",
        f"- Repositoris: {len(targets)}; revisions consultades: {len(cache)}; "
        f"revisions no resoltes: {errors_[True]}",
        f"- Repositoris amb almenys una taula tabular (última versió): {latest['repo'].nunique()}",
        f"- Taules (última versió de cada repositori): {len(latest)}", "",
        "## Taules per patró de fitxers (última versió)", "",
        _md(latest["naming"].value_counts().rename_axis("naming").reset_index(name="taules")), "",
        "## Fitxers per taula (última versió)", "",
        _md(latest["n_files"].describe().round(1).to_frame().T), "",
        "## Fitxers tabulars fora de cap taula", "",
        (_md(excl.drop_duplicates(["repo", "path"])["reason"].value_counts().rename_axis("motiu")
             .reset_index(name="fitxers")) if len(excl) else "(cap)"), "",
        "## Entre versions consecutives (mateixa taula)", "",
        (_md(changes["status"].value_counts().rename_axis("estat").reset_index(name="parells"))
         if len(changes) else "(sense versions)"), "",
    ]
    if len(changes):
        fc = changes[changes.status == "files_changed"]
        lines += [f"- Parells amb fitxers canviats on cap fitxer es manté (aparellar per ruta falla del tot): "
                  f"{int((fc.kept == 0).sum())} de {len(fc)}", ""]
    with open(os.path.join(OUT, "summary.md"), "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
