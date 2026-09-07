"""Import an external corpus (Sarvam's, or any other) into the LIVE
application database, so it can be explored through the running Memory and
Hey Kivi screens afterward — this is the documented way to satisfy "import
the corpus, process it, inspect the resulting database and memory state,
and operate Hey Kivi against what it has learned."

Unlike scripts/run_eval.py, this does NOT score anything against an
"expected" outcome — there is no predetermined ground truth for a real
user's corpus. It just runs the real pipeline and writes a plain,
inspectable processing log: what was extracted (or correctly nothing) for
every record, with reasoning, latency, and citations, exactly as the brief
asks for ("the memory the system created, retrieved, changed, or rejected;
the provenance of that memory; ... the reason the system made its
decision").

Input format (JSONL, one record per line):
    {"raw_asr": "...", "formatted_text": "...", "app": "slack", "occurred_at": "2026-01-05T09:00:00", "metadata": {}}

Only `raw_asr` and `formatted_text` are required. `app` defaults to
"imported" if absent (our memory model scopes everything by app; if the
source corpus has no per-record application context, everything lands in
one shared scope rather than being silently guessed). `occurred_at`
defaults to the import time. `metadata` defaults to `{}`.

Usage:
    python scripts/import_corpus.py path/to/corpus.jsonl
    python scripts/import_corpus.py path/to/corpus.jsonl --limit 50   # quick partial import
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db
from app.services import extraction

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results" / "latest_import"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _with_retry(fn, *, retries: int = 1, delay: float = 2.0):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            attempt += 1
            if attempt > retries:
                raise
            print(f"    call failed ({exc}), retrying ({attempt}/{retries})...")
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_file", help="path to a JSONL file of {raw_asr, formatted_text, app?, occurred_at?, metadata?} records")
    parser.add_argument("--limit", type=int, default=None, help="only import the first N records")
    args = parser.parse_args()

    corpus_path = Path(args.corpus_file)
    if not corpus_path.exists():
        raise SystemExit(f"corpus file not found: {corpus_path}")

    with open(corpus_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    if args.limit:
        records = records[: args.limit]

    missing_required = [i for i, r in enumerate(records) if "raw_asr" not in r or "formatted_text" not in r]
    if missing_required:
        raise SystemExit(f"{len(missing_required)} record(s) missing required raw_asr/formatted_text, e.g. line {missing_required[0] + 1}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RESULTS_DIR / "import_log.jsonl"
    log_entries = []

    print(f"Importing {len(records)} records from {corpus_path} into the live database...")
    with get_db() as conn:
        for i, record in enumerate(records):
            app = record.get("app", "imported")
            occurred_at = record.get("occurred_at", _now_iso())
            metadata = record.get("metadata", {})

            start = time.monotonic()
            try:
                dictation_id, outcomes = _with_retry(lambda: extraction.ingest_dictation(
                    conn, app=app, occurred_at=occurred_at, raw_asr=record["raw_asr"],
                    formatted_text=record["formatted_text"], metadata=metadata, source="sarvam_import",
                ))
                error = None
            except Exception as exc:
                dictation_id, outcomes, error = None, [], str(exc)
            latency_ms = int((time.monotonic() - start) * 1000)

            log_entries.append({
                "line": i + 1, "app": app, "occurred_at": occurred_at,
                "input": {"raw_asr": record["raw_asr"], "formatted_text": record["formatted_text"]},
                "dictation_id": dictation_id, "outcomes": outcomes, "latency_ms": latency_ms, "error": error,
            })
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(records)} processed")

    with open(log_path, "w") as f:
        for entry in log_entries:
            f.write(json.dumps(entry) + "\n")

    n_extracted = sum(1 for e in log_entries if e["outcomes"])
    n_errors = sum(1 for e in log_entries if e["error"])
    total_latency = sum(e["latency_ms"] for e in log_entries)
    print(f"\nDone: {len(log_entries)} dictations processed, {n_extracted} produced at least one memory candidate, "
          f"{n_errors} failed, {total_latency / 1000:.1f}s total.")
    print(f"Per-record log: {log_path}")
    print("Inspect what was learned: start the app (uvicorn app.main:app) and visit /memory and /hey-kivi.")
    print("Reset back to empty afterward with: python scripts/reset.py")


if __name__ == "__main__":
    main()
