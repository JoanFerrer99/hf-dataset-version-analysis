"""
Genera `tests/fixtures/run_sample/`: una execució sintètica petita, amb els
mateixos fitxers i columnes que una carpeta `data/run_<id>/` (secció 10 de
`docs/architecture.md`), per provar el magatzem a la CI sense xarxa.

Fa servir les mateixes funcions que escriuen els fitxers reals
(`write_results`, `VersionRow`, `classification_frame`, `status_frame`),
perquè el format no se'n separi. Les dates són fixes: el resultat és sempre
el mateix.

12 datasets: 3 elegibles (2 pel Criteri A, 1 pel B), 4 aturats al filtre 1,
2 al filtre 2, 1 al filtre 3, 1 inaccessible i 1 amb error.

Ús (des de l'arrel del repositori):
  python tests/fixtures/make_run_sample.py
"""

import csv
import hashlib
import json
import os
import sys
from dataclasses import asdict

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

import eligibility_scan as es  # noqa: E402
from diffengine.output import classification_frame, status_frame  # noqa: E402
from version_extractor import VersionRow  # noqa: E402

OUT = os.path.join(HERE, "run_sample")
TIMESTAMP = "2026-01-15T10:00:00"
REASONS = es.ELIGIBILITY_REASONS


def sha(label: str) -> str:
    """SHA de commit fals (40 xifres hexadecimals), sempre el mateix per a cada etiqueta."""
    return hashlib.sha1(label.encode()).hexdigest()


def report_row(dataset_id, tags, branches, tabular_commits, reason, *, status="classified", error_category="",
               error="", files=None, share=None, created_at=None, license_=None, downloads=None):
    """Una fila de `classify_dataset`, amb les claus en el mateix ordre."""
    return {
        "dataset_id": dataset_id, "num_tags": tags, "num_branches": branches,
        "num_tabular_commits": tabular_commits, "eligible": reason in (REASONS["A"], REASONS["B"]),
        "eligibility_reason": reason, "status": status, "error_category": error_category, "error": error,
        "tabular_commits": [], "num_data_files": files, "tabular_file_share": share,
        "created_at": created_at, "license": license_, "downloads": downloads,
    }


REPORT = [
    report_row("org/tags-a", 3, 1, 3, REASONS["A"], files=4, share=0.5,
               created_at="2024-11-02T09:00:00+00:00", license_="mit", downloads=120),
    report_row("org/sessions-b", 0, 2, 4, REASONS["B"], files=3, share=1.0,
               created_at="2025-01-20T12:30:00+00:00", license_="cc-by-4.0", downloads=35),
    report_row("org/tags-c", 2, 1, 2, REASONS["A"], files=1, share=1.0,
               created_at="2025-04-01T08:00:00+00:00", license_=None, downloads=0),
    *[report_row(f"org/single-{i}", 0, 1, 0, REASONS["no_version_marks"]) for i in range(1, 5)],
    report_row("org/videos", 2, 1, 0, REASONS["no_tabular_files"], files=6, share=0.0,
               created_at="2025-02-11T10:00:00+00:00", license_="apache-2.0", downloads=7),
    report_row("org/images", 0, 3, 0, REASONS["no_tabular_files"], files=10, share=0.0,
               created_at="2025-03-03T10:00:00+00:00", license_=None, downloads=2),
    report_row("org/one-session", 0, 2, 3, REASONS["no_tabular_commits"], files=2, share=1.0,
               created_at="2025-05-05T10:00:00+00:00", license_="mit", downloads=11),
    report_row("org/gated", 0, 0, 0, "", status="access_restricted", error_category="access_restricted",
               error="403 Client Error"),
    report_row("org/busy", 0, 0, 0, "", status="error", error_category="rate_limited", error="429 Client Error"),
]

VERSIONS = [
    # dataset, etiqueta, ordre, origen, data, autors, mida, commits de la sessió
    ("org/tags-a", "v1.0", 1, "tag", "2025-01-10T10:00:00+00:00", "ana", 1_000, 1),
    ("org/tags-a", "v1.1", 2, "tag", "2025-03-05T10:00:00+00:00", "ana", 1_200, 1),
    ("org/tags-a", "v2.0", 3, "tag", "2025-06-20T10:00:00+00:00", "ana,bob", 1_500, 1),
    ("org/sessions-b", "session-1", 1, "commit_session", "2025-02-01T09:00:00+00:00", "carla", 5_000, 2),
    ("org/sessions-b", "session-2", 2, "commit_session", "2025-02-15T18:00:00+00:00", "carla", 5_400, 2),
    ("org/tags-c", "v1", 1, "tag", "2025-04-10T10:00:00+00:00", "dani", 900_000_000, 1),
    ("org/tags-c", "v2", 2, "tag", "2025-07-01T10:00:00+00:00", "dani", 950_000_000, 1),
]

TRAIN, TEST = "data/train.csv", "data/test.csv"
SHARDS = "data/train-00000-of-00002.parquet,data/train-00001-of-00002.parquet"
# (dataset, versió antiga, versió nova): [(taula, fitxers, estat, codis)]
COMPARISONS = {
    ("org/tags-a", "v1.0", "v1.1"): [("default/train", TRAIN, "ok", ["C221", "C421"]),
                                     ("default/test", TEST, "identical_content", [])],
    ("org/tags-a", "v1.1", "v2.0"): [("default/train", TRAIN, "ok", ["C222", "C223", "C510"]),
                                     ("default/test", TEST, "ok", []),
                                     ("meta/info.parquet", "meta/info.parquet", "excluded", [])],
    ("org/sessions-b", "session-1", "session-2"): [("default/train", SHARDS, "ok", ["C312", "C530"]),
                                                   ("labels.json", "labels.json", "parse_failed", [])],
    ("org/tags-c", "v1", "v2"): [("default/train", "data/train.parquet", "too_large", [])],
}

FAILURES = [
    ("2026-01-15T09:10:00+00:00", "sampling", "org/gated", "access_restricted", "403 Client Error", 0),
    ("2026-01-15T09:20:00+00:00", "sampling", "org/busy", "rate_limited", "429 Client Error", 5),
]


def main(out: str = OUT) -> None:
    """
    :param out: carpeta on s'escriu la fixture.
    """
    os.makedirs(out, exist_ok=True)

    es.OUTPUT_DIR = out
    _, json_path, _ = es.write_results(REPORT, total_scanned=5_000)
    with open(json_path, encoding="utf-8") as f:
        summary = json.load(f)
    summary["timestamp"] = TIMESTAMP
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    versions = [VersionRow(dataset_id=ds, version_label=label, version_order=order, version_source=source,
                           commit_sha=sha(f"{ds}@{label}"), commit_date=date, authors=authors,
                           approx_size_bytes=size, session_commit_count=count, status="ok")
                for ds, label, order, source, date, authors, size, count in VERSIONS]
    pd.DataFrame([asdict(v) for v in versions]).to_csv(os.path.join(out, "versions.csv"), index=False)

    changes, statuses = [], []
    for (ds, old, new), tables in COMPARISONS.items():
        pair = {"dataset_id": ds, "version_from": sha(f"{ds}@{old}"), "version_to": sha(f"{ds}@{new}")}
        for table, files, status, codes in tables:
            changes += [{**pair, "table": table, "file_path": files, "code": code} for code in codes]
            statuses.append({**pair, "table": table, "file_path": files, "status": status, "n_codes": len(codes)})
    classification_frame(changes).to_csv(os.path.join(out, "change_classification.csv"), index=False)
    status_frame(statuses).to_csv(os.path.join(out, "comparison_status.csv"), index=False)

    with open(os.path.join(out, "failures.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "source", "dataset_id", "error_category", "error_message",
                         "retries_attempted"])
        writer.writerows(FAILURES)


if __name__ == "__main__":
    main()
