"""
Avalua els motors sobre els casos de `experiments/mutations.py` i escriu
`experiments/report.md`.

Mètriques per codi, a nivell de cas: TP si el codi és requerit i detectat,
FN si és requerit i no detectat, FP si es detecta i no és ni requerit ni
permès. El report només mostra el conjunt reservat (`heldout`); el de
calibratge és per ajustar llindars.

Ús:
  python experiments/run_eval.py                       # reservat: motor antic (desat) vs nou
  python experiments/run_eval.py --split calibration   # per ajustar llindars
"""

import argparse
import json
import os
import pickle
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from experiments.adapters import ENGINES  # noqa: E402
from experiments.mutations import CACHE_DIR, MUTATIONS, Case, build_cases  # noqa: E402

from diffengine.output import TABULAR_CODES as CODES  # noqa: E402
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.md")
# Resultats del motor antic (change_diff.py, retirat) sobre el conjunt reservat,
# desats abans de retirar-lo.
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline_old_engine.json")


def _from_json(data: dict) -> dict:
    return {
        "per_code": {k: Counter(v) for k, v in data["per_code"].items()},
        "per_mutation": defaultdict(Counter, {k: Counter(v) for k, v in data["per_mutation"].items()}),
        "confusion": Counter({(m, e): n for m, e, n in data["confusion"]}),
        "per_subtype": defaultdict(Counter, {(c, s): Counter(v) for c, s, v in data["per_subtype"]}),
    }


def load_cases(split: str) -> list[Case]:
    path = os.path.join(CACHE_DIR, f"cases_{split}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    cases = build_cases(split)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(cases, f)
    return cases


def evaluate(cases: list[Case], engine) -> dict:
    per_code = {c: Counter() for c in CODES}
    per_subtype: dict[tuple[str, str], Counter] = defaultdict(Counter)
    confusion: Counter = Counter()
    per_mutation: dict[str, Counter] = defaultdict(Counter)
    for case in cases:
        labels = engine(case)
        predicted = {code for code, _ in labels}
        required = case.required_codes
        for code in CODES:
            if code in required and code in predicted:
                per_code[code]["tp"] += 1
            elif code in required:
                per_code[code]["fn"] += 1
            elif code in predicted and code not in case.allowed:
                per_code[code]["fp"] += 1
        missed = required - predicted
        extra = predicted - required - case.allowed
        for m in missed:
            for e in extra:
                confusion[(m, e)] += 1
        if len(case.mutations) == 1:
            name = case.mutations[0]
            ok = not missed and not extra
            per_mutation[name]["ok" if ok else "ko"] += 1
            for code, sub in case.required:
                if sub is not None:
                    per_subtype[(code, sub)]["hit" if (code, sub) in labels else "miss"] += 1
    return {"per_code": per_code, "per_subtype": per_subtype, "confusion": confusion, "per_mutation": per_mutation}


def _prf(c: Counter) -> tuple[str, str, str]:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    fmt = lambda x: "—" if x is None else f"{x:.2f}"  # noqa: E731
    return fmt(p), fmt(r), fmt(f)


def write_report(split: str, n_cases: int, results: dict[str, dict]) -> str:
    names = list(results)
    lines = [
        "# Avaluació del motor de detecció de canvis", "",
        f"Conjunt: **{split}** ({n_cases} casos, generats per `experiments/mutations.py`). "
        "Mètriques per codi a nivell de cas; un codi permès com a efecte secundari no compta com a FP.", "",
        "## Precisió / recall / F1 per codi", "",
        "| Codi | Suport | " + " | ".join(f"{n} P | {n} R | {n} F1" for n in names) + " |",
        "|---|---|" + "---|---|---|" * len(names),
    ]
    for code in CODES:
        support = results[names[0]]["per_code"][code]["tp"] + results[names[0]]["per_code"][code]["fn"]
        cells = []
        for n in names:
            cells += list(_prf(results[n]["per_code"][code]))
        lines.append(f"| {code} | {support} | " + " | ".join(cells) + " |")

    lines += ["", "## Casos d'una sola mutació resolts del tot", "",
              "Un cas és correcte si surten tots els codis requerits i cap de no permès.", "",
              "| Mutació | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for mut in sorted(MUTATIONS):
        cells = []
        for n in names:
            c = results[n]["per_mutation"].get(mut, Counter())
            total = c["ok"] + c["ko"]
            cells.append(f"{c['ok']}/{total}" if total else "—")
        lines.append(f"| {mut} | " + " | ".join(cells) + " |")

    for n in names:
        conf = results[n]["confusion"].most_common(12)
        lines += ["", f"## Confusions més freqüents ({n})", "",
                  "Codi requerit no detectat → codi no permès detectat al mateix cas.", "",
                  "| Requerit | Detectat en lloc seu | Casos |", "|---|---|---|"]
        lines += [f"| {m} | {e} | {k} |" for (m, e), k in conf] or ["| — | — | — |"]
        subs = results[n]["per_subtype"]
        if any(c["hit"] for c in subs.values()):
            lines += ["", f"## Subtipus ({n}, casos d'una sola mutació)", "", "| Codi | Subtipus | Encerts |", "|---|---|---|"]
            lines += [f"| {code} | {sub} | {c['hit']}/{c['hit'] + c['miss']} |" for (code, sub), c in sorted(subs.items())]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", default="heldout", choices=["calibration", "heldout"])
    parser.add_argument("--engines", nargs="*", default=list(ENGINES))
    args = parser.parse_args()

    cases = load_cases(args.split)
    results = {}
    if args.split == "heldout":
        with open(BASELINE) as f:
            results["old"] = _from_json(json.load(f))
    results.update({name: evaluate(cases, ENGINES[name]) for name in args.engines})
    report = write_report(args.split, len(cases), results)
    if args.split == "heldout":
        with open(REPORT, "w") as f:
            f.write(report)
    print(report)


if __name__ == "__main__":
    main()
