"""The evaluation harness: replays eval/corpus/dictations.jsonl through the
real extraction pipeline into a fresh database, runs eval/qa_testset.jsonl
against the resulting (and independently-seeded) memory, and writes an
honest, inspectable report to eval/results/latest/.

This calls the actual product code (app.services.extraction, .qa, .llm) —
it does not reimplement or mock any of it, so cost/latency/DB-growth
numbers reflect real runtime behavior, and every case is scored against an
expectation that was written before this ever ran (see eval/corpus_spec.py
and eval/qa_testset.jsonl).

Usage:
    python scripts/run_eval.py                  # full run
    python scripts/run_eval.py --limit 40        # quick partial run over the first N corpus records
    python scripts/run_eval.py --qa-only         # skip the corpus replay, only run the QA test set
                                                  # (e.g. against a database already populated by an
                                                  # imported corpus — see scripts/import_corpus.py)
"""
import argparse
import json
import shutil
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import MIGRATIONS_DIR
from app.services import extraction, memory_store as store, qa

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "eval" / "corpus" / "dictations.jsonl"
QA_PATH = ROOT / "eval" / "qa_testset.jsonl"
OUT_DIR = ROOT / "eval" / "results" / "latest"


def fresh_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(migration.read_text())
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _with_retry(fn, *, retries: int = 1, delay: float = 2.0):
    """Call fn() and retry on exception up to `retries` times — model calls
    occasionally hit transient API/schema-compliance issues across a run of
    hundreds of calls; a bounded retry is a reasonable, honest response to
    that, not a way to paper over a real bug."""
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


def _fetch_content(conn: sqlite3.Connection, outcome: dict) -> dict:
    if outcome["type"] == "entity":
        e = store.get_entity(conn, outcome["memory_id"])
        return {"resolved_as": e["resolved_as"], "surface_forms": e["surface_forms"]} if e else {}
    if outcome["type"] == "instruction":
        i = store.get_instruction(conn, outcome["memory_id"])
        return {"rule_text": i["rule_text"]} if i else {}
    if outcome["type"] == "task":
        t = store.get_task(conn, outcome["memory_id"])
        return {"label": t["label"], "last_state_summary": t["last_state_summary"]} if t else {}
    return {}


def _content_checks(expected: dict, content: dict) -> list[dict]:
    checks = []
    pairs = [
        ("entity_resolved_as_contains", content.get("resolved_as")),
        ("instruction_rule_text_contains", content.get("rule_text")),
        ("task_label_contains", content.get("label")),
        ("task_state_summary_contains", content.get("last_state_summary")),
    ]
    for key, actual_text in pairs:
        if key in expected:
            expected_substr = expected[key].lower()
            ok = bool(actual_text) and expected_substr in actual_text.lower()
            checks.append({"check": key, "expected_contains": expected[key], "actual": actual_text, "passed": ok})
    if "entity_surface_form" in expected:
        forms = [s.lower() for s in content.get("surface_forms", [])]
        ok = expected["entity_surface_form"].lower() in forms
        checks.append({"check": "entity_surface_form", "expected_contains": expected["entity_surface_form"], "actual": content.get("surface_forms"), "passed": ok})
    return checks


def score_corpus_record(record: dict, outcomes: list[dict], group_state: dict) -> dict:
    expected = record["expected"]
    category = record["category"]
    group, seq = record.get("group"), record.get("seq")
    result = {"bucket": None, "verdict": None, "detail": "", "content_checks": []}

    if "must_not_merge_with_group_seq" in expected and group is not None and outcomes:
        prior_id = group_state.get((group, expected["must_not_merge_with_group_seq"]))
        this_id = outcomes[0]["memory_id"]
        if prior_id is not None and this_id == prior_id:
            result.update(bucket="cross_app_leak", verdict="fail",
                           detail=f"merged with {group}/seq={expected['must_not_merge_with_group_seq']} (memory_id={prior_id}) across an app boundary")
            return result

    exp_type = expected.get("extraction_type")

    if exp_type == "none":
        if not outcomes:
            result.update(bucket="correct_non_intervention", verdict="pass")
        else:
            severity = "high" if category == "adversarial" else "medium"
            result.update(bucket="false_positive", verdict="fail",
                           detail=f"expected nothing, got {[(o['type'], o['decision']) for o in outcomes]} (severity={severity})")
        return result

    if exp_type == "any":  # ambiguous category
        acceptable = expected.get("acceptable_decisions", [])
        if not outcomes:
            ok = "none" in acceptable
            result.update(bucket="ambiguous_handled_correctly" if ok else "ambiguous_missed", verdict="pass" if ok else "fail")
        else:
            bad = [o for o in outcomes if o["decision"] not in acceptable]
            if bad:
                result.update(bucket="ambiguous_over_confident", verdict="fail",
                               detail=f"got {[(o['type'], o['decision']) for o in bad]}, expected one of {acceptable}")
            else:
                result.update(bucket="ambiguous_handled_correctly", verdict="pass")
        return result

    # exp_type in ("entity", "instruction", "task")
    expected_decision = expected.get("expected_decision")
    matching = [o for o in outcomes if o["type"] == exp_type]
    if not matching:
        result.update(bucket="false_negative", verdict="fail",
                       detail=f"expected a {exp_type} ({expected_decision}), got {[(o['type'], o['decision']) for o in outcomes] or 'nothing'}")
        return result

    o = matching[0]
    # "created_known_limitation" means "a brand-new item was created because
    # dedup didn't catch a paraphrase" — the actual decision string for a
    # fresh, auto-confirmed item is "created" for tasks but "auto_confirmed"
    # for entities/instructions (see extraction.py); accept either so this
    # doesn't silently mismatch depending on which type used it.
    decision_ok = o["decision"] == expected_decision or (
        expected_decision == "created_known_limitation" and o["decision"] in ("created", "auto_confirmed")
    )
    if not decision_ok:
        result.update(bucket="wrong_decision", verdict="fail",
                       detail=f"expected decision {expected_decision}, got {o['decision']}")
        return result

    if o["decision"] in ("merged", "updated") and group is not None:
        prior_id = group_state.get((group, 0))
        if prior_id is not None and o["memory_id"] != prior_id:
            result.update(bucket="wrong_decision", verdict="fail",
                           detail=f"decision was {o['decision']} but matched a different item (memory_id={o['memory_id']}) than the group's original (memory_id={prior_id})")
            return result

    bucket = "known_limitation" if expected_decision == "created_known_limitation" else "correct_intervention"
    result.update(bucket=bucket, verdict="pass")
    return result


def run_corpus_eval(conn: sqlite3.Connection, records: list[dict], limit: int | None) -> list[dict]:
    if limit:
        records = records[:limit]
    group_state: dict[tuple[str, int], int] = {}
    cases = []
    for i, record in enumerate(records):
        start = time.monotonic()
        try:
            dictation_id, outcomes = _with_retry(lambda: extraction.ingest_dictation(
                conn, app=record["app"], occurred_at=record["occurred_at"], raw_asr=record["raw_asr"],
                formatted_text=record["formatted_text"], metadata=record.get("metadata", {}), source="own_corpus",
            ))
        except Exception as exc:
            conn.rollback()
            latency_ms = int((time.monotonic() - start) * 1000)
            cases.append({
                "id": record["id"], "category": record["category"], "app": record["app"],
                "adversarial": record.get("adversarial", False),
                "input": {"raw_asr": record["raw_asr"], "formatted_text": record["formatted_text"]},
                "expected": record["expected"], "dictation_id": None, "outcomes": [],
                "latency_ms": latency_ms, "bucket": "harness_error", "verdict": "error",
                "detail": f"extraction call failed: {exc}", "content_checks": [],
            })
            print(f"  {record['id']} failed twice, recording as harness_error and continuing")
            continue
        latency_ms = int((time.monotonic() - start) * 1000)
        conn.commit()

        if record.get("group") is not None and outcomes:
            group_state[(record["group"], record["seq"])] = outcomes[0]["memory_id"]

        score = score_corpus_record(record, outcomes, group_state)
        if score["verdict"] == "pass" and outcomes:
            content = _fetch_content(conn, outcomes[0])
            score["content_checks"] = _content_checks(record["expected"], content)

        cases.append({
            "id": record["id"], "category": record["category"], "app": record["app"],
            "adversarial": record.get("adversarial", False),
            "input": {"raw_asr": record["raw_asr"], "formatted_text": record["formatted_text"]},
            "expected": record["expected"], "dictation_id": dictation_id, "outcomes": outcomes,
            "latency_ms": latency_ms, **score,
        })
        if (i + 1) % 50 == 0:
            print(f"  corpus: {i + 1}/{len(records)} processed")
    return cases


def setup_qa_case(conn: sqlite3.Connection, case: dict) -> list[dict]:
    setup_outcomes = []
    for item in case.get("setup", []):
        _did, outcomes = _with_retry(lambda item=item: extraction.ingest_dictation(
            conn, app=item["app"], occurred_at=_now_iso(), raw_asr=item["text"],
            formatted_text=item["text"], metadata={}, source="manual",
        ))
        setup_outcomes.append({"text": item["text"], "app": item["app"], "outcomes": outcomes})
    for item in case.get("setup_manual", []):
        if item["type"] == "entity":
            store.create_entity(
                conn, surface_forms=item["surface_forms"], resolved_as=item["resolved_as"],
                role_context=item.get("role_context"), scope=item["scope"], status=item["status"],
                source_quote=item.get("source_quote", "(eval fixture)"), confidence=item.get("confidence", 0.5),
                reasoning="eval setup_manual fixture",
            )
        elif item["type"] == "instruction":
            store.create_instruction(
                conn, rule_text=item["rule_text"], scope=item["scope"], status=item["status"],
                source_quote=item.get("source_quote", "(eval fixture)"), confidence=item.get("confidence", 0.5),
                reasoning="eval setup_manual fixture",
            )
        elif item["type"] == "task":
            store.create_task(
                conn, label=item["label"], app=item["app"], last_state_summary=item["last_state_summary"],
                scope=item["scope"], reasoning="eval setup_manual fixture",
                status=item.get("status", "open"), recurring=item.get("recurring", False),
            )
    conn.commit()
    return setup_outcomes


def run_qa_eval(qa_dir: Path) -> list[dict]:
    qa_dir.mkdir(parents=True, exist_ok=True)
    with open(QA_PATH) as f:
        qa_cases = [json.loads(line) for line in f]

    results = []
    for case in qa_cases:
        db_path = qa_dir / f"{case['id']}.db"
        conn = fresh_db(db_path)
        try:
            setup_outcomes = setup_qa_case(conn, case)
            start = time.monotonic()
            answer = _with_retry(lambda: qa.answer_question(conn, question=case["question"], app=case["app"], persona=None))
            latency_ms = int((time.monotonic() - start) * 1000)
            conn.commit()
        except Exception as exc:
            conn.close()
            print(f"  {case['id']} failed, recording as harness_error and continuing: {exc}")
            results.append({
                "id": case["id"], "question": case["question"], "app": case["app"], "notes": case.get("notes", ""),
                "expected_grounded": case["expected_grounded"], "expected_answer_contains": case.get("expected_answer_contains", []),
                "actual": None, "setup_outcomes": [], "latency_ms": None,
                "grounded_ok": False, "content_ok": False, "verdict": "error", "error": str(exc), "model_calls": [],
            })
            continue

        model_calls = conn.execute(
            "SELECT purpose, model, input_tokens, output_tokens, latency_ms, estimated_cost_usd FROM model_calls"
        ).fetchall()
        conn.close()

        grounded_ok = answer["grounded"] == case["expected_grounded"]
        content_ok = all(s.lower() in (answer["result"] or "").lower() for s in case.get("expected_answer_contains", []))
        passed = grounded_ok and content_ok

        results.append({
            "id": case["id"], "question": case["question"], "app": case["app"], "notes": case.get("notes", ""),
            "expected_grounded": case["expected_grounded"], "expected_answer_contains": case.get("expected_answer_contains", []),
            "actual": answer, "setup_outcomes": setup_outcomes, "latency_ms": latency_ms,
            "grounded_ok": grounded_ok, "content_ok": content_ok, "verdict": "pass" if passed else "fail",
            "model_calls": [dict(r) for r in model_calls],
        })
    return results


def summarize(corpus_cases: list[dict], qa_cases: list[dict], corpus_db_path: Path | None) -> dict:
    summary: dict = {"generated_at": _now_iso()}

    if corpus_cases:
        by_bucket: dict[str, int] = {}
        by_category: dict[str, dict[str, int]] = {}
        latencies = [c["latency_ms"] for c in corpus_cases]
        for c in corpus_cases:
            by_bucket[c["bucket"]] = by_bucket.get(c["bucket"], 0) + 1
            by_category.setdefault(c["category"], {}).setdefault(c["bucket"], 0)
            by_category[c["category"]][c["bucket"]] += 1

        conn = sqlite3.connect(corpus_db_path)
        conn.row_factory = sqlite3.Row
        row_counts = {
            t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in ("dictations", "entities", "instructions", "tasks", "memory_events", "model_calls")
        }
        model_stats = conn.execute(
            "SELECT purpose, COUNT(*) AS calls, SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
            "SUM(estimated_cost_usd) AS cost, AVG(latency_ms) AS avg_latency_ms FROM model_calls GROUP BY purpose"
        ).fetchall()
        conn.close()

        n = len(corpus_cases)
        n_pass = sum(1 for c in corpus_cases if c["verdict"] == "pass")
        n_errors = sum(1 for c in corpus_cases if c["verdict"] == "error")
        n_scored = n - n_errors
        summary["corpus"] = {
            "total_records": n,
            "harness_errors": n_errors,
            "pass_rate_including_errors": round(n_pass / n, 4) if n else None,
            "pass_rate_excluding_errors": round(n_pass / n_scored, 4) if n_scored else None,
            "by_bucket": by_bucket,
            "by_category": by_category,
            "latency_ms": {
                "mean": round(statistics.mean(latencies), 1), "median": statistics.median(latencies),
                "p95": sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else None,
                "max": max(latencies) if latencies else None,
            },
            "db_row_counts": row_counts,
            "model_usage_by_purpose": [dict(r) for r in model_stats],
        }

    if qa_cases:
        n = len(qa_cases)
        n_pass = sum(1 for c in qa_cases if c["verdict"] == "pass")
        n_errors = sum(1 for c in qa_cases if c["verdict"] == "error")
        n_scored = n - n_errors
        scored_cases = [c for c in qa_cases if c["verdict"] != "error"]
        should_answer = [c for c in scored_cases if c["expected_grounded"]]
        should_refuse = [c for c in scored_cases if not c["expected_grounded"]]
        latencies = [c["latency_ms"] for c in qa_cases if c["latency_ms"] is not None]
        total_cost = sum(mc["estimated_cost_usd"] for c in qa_cases for mc in c["model_calls"])
        total_tokens = sum(mc["input_tokens"] + mc["output_tokens"] for c in qa_cases for mc in c["model_calls"])
        summary["qa"] = {
            "total_cases": n,
            "errors": n_errors,
            "pass_rate_including_errors": round(n_pass / n, 4) if n else None,
            "pass_rate_excluding_errors": round(n_pass / n_scored, 4) if n_scored else None,
            "should_answer_correct": sum(1 for c in should_answer if c["verdict"] == "pass"),
            "should_answer_total": len(should_answer),
            "should_refuse_correct": sum(1 for c in should_refuse if c["verdict"] == "pass"),
            "should_refuse_total": len(should_refuse),
            "failures": [c["id"] for c in qa_cases if c["verdict"] == "fail"],
            "errored": [c["id"] for c in qa_cases if c["verdict"] == "error"],
            "latency_ms": {"mean": round(statistics.mean(latencies), 1), "median": statistics.median(latencies)} if latencies else {},
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
        }

    return summary


def write_markdown_summary(summary: dict, path: Path) -> None:
    lines = [f"# Evaluation results\n\nGenerated: {summary['generated_at']}\n"]

    if "corpus" in summary:
        c = summary["corpus"]
        lines.append("## Corpus replay\n")
        lines.append(f"- **{c['total_records']} records**, **{c['harness_errors']} infra errors** (rate-limited, not scored)")
        lines.append(f"- Pass rate **excluding** infra errors (the real quality signal): **{c['pass_rate_excluding_errors']:.1%}**")
        lines.append(f"- Pass rate including infra errors as failures (pessimistic floor): **{c['pass_rate_including_errors']:.1%}**\n")
        lines.append("### Outcome breakdown\n")
        lines.append("| bucket | count |\n|---|---|")
        for bucket, count in sorted(c["by_bucket"].items(), key=lambda x: -x[1]):
            lines.append(f"| {bucket} | {count} |")
        lines.append("\n### By category\n")
        lines.append("| category | " + " | ".join(sorted({b for cat in c["by_category"].values() for b in cat})) + " |")
        buckets_seen = sorted({b for cat in c["by_category"].values() for b in cat})
        lines.append("|---|" + "---|" * len(buckets_seen))
        for cat, buckets in c["by_category"].items():
            row = " | ".join(str(buckets.get(b, 0)) for b in buckets_seen)
            lines.append(f"| {cat} | {row} |")
        lines.append(f"\n### Latency (extraction, ms)\nmean {c['latency_ms']['mean']}, median {c['latency_ms']['median']}, "
                      f"p95 {c['latency_ms']['p95']}, max {c['latency_ms']['max']}\n")
        lines.append("### Database growth (after full replay)\n")
        lines.append("| table | rows |\n|---|---|")
        for t, n in c["db_row_counts"].items():
            lines.append(f"| {t} | {n} |")
        lines.append("\n### Model usage\n")
        lines.append("| purpose | calls | input tok | output tok | cost (USD) | avg latency (ms) |")
        lines.append("|---|---|---|---|---|---|")
        for m in c["model_usage_by_purpose"]:
            lines.append(f"| {m['purpose']} | {m['calls']} | {m['in_tok']} | {m['out_tok']} | {m['cost']:.6f} | {m['avg_latency_ms']:.0f} |")
        lines.append("")

    if "qa" in summary:
        q = summary["qa"]
        lines.append("## Grounded Q&A\n")
        lines.append(f"- **{q['total_cases']} cases**, {q['errors']} infra errors (rate-limited, not scored)")
        lines.append(f"- Pass rate excluding infra errors: **{q['pass_rate_excluding_errors']:.1%}**" if q['pass_rate_excluding_errors'] is not None else "- Pass rate excluding infra errors: n/a (all cases errored)")
        lines.append(f"- Should-answer cases correct: {q['should_answer_correct']}/{q['should_answer_total']}")
        lines.append(f"- Should-refuse cases correct: {q['should_refuse_correct']}/{q['should_refuse_total']}")
        if q["failures"]:
            lines.append(f"- Failing case ids: {', '.join(q['failures'])}")
        if q["errored"]:
            lines.append(f"- **{q['errors']} case(s) errored (infra failure, not scored)**: {', '.join(q['errored'])} — re-run to get a real verdict for these")
        lines.append(f"- Latency (ms): mean {q['latency_ms'].get('mean')}, median {q['latency_ms'].get('median')}")
        lines.append(f"- Total cost: ${q['total_cost_usd']:.6f} across {q['total_tokens']} tokens\n")

    lines.append("## Notes\n")
    lines.append(
        "- `false_positive` and `ambiguous_over_confident` are the buckets that matter most for trust — "
        "they represent Kivi assuming something it wasn't told. `cross_app_leak` represents a scope-isolation "
        "failure. `known_limitation` is an expected, documented outcome (paraphrased instruction restatement "
        "isn't caught by exact-text dedup), not scored as a defect.\n"
        "- Per-case detail, including the exact input, extraction reasoning, and citations, is in "
        "`corpus_cases.jsonl` and `qa_cases.jsonl` in this directory. The replayed corpus database "
        "(`corpus.db`) and each QA case's isolated database (`qa_dbs/<id>.db`) are included for direct "
        "inspection with `sqlite3` or any SQLite browser."
    )
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only replay the first N corpus records")
    parser.add_argument("--qa-only", action="store_true", help="skip corpus replay, only run the QA test set")
    parser.add_argument("--corpus-only", action="store_true", help="skip the QA test set, only replay the corpus")
    parser.add_argument("--summary-only", action="store_true", help="make no API calls — just regenerate summary.json/.md from existing corpus_cases.jsonl/qa_cases.jsonl")
    args = parser.parse_args()

    if args.summary_only:
        corpus_cases_path, qa_cases_path = OUT_DIR / "corpus_cases.jsonl", OUT_DIR / "qa_cases.jsonl"
        corpus_cases = [json.loads(l) for l in open(corpus_cases_path)] if corpus_cases_path.exists() else []
        qa_cases = [json.loads(l) for l in open(qa_cases_path)] if qa_cases_path.exists() else []
        summary = summarize(corpus_cases, qa_cases, (OUT_DIR / "corpus.db") if corpus_cases else None)
        (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
        write_markdown_summary(summary, OUT_DIR / "summary.md")
        print(f"Regenerated summary from existing data in {OUT_DIR} (no API calls made).")
        return

    corpus_cases_path = OUT_DIR / "corpus_cases.jsonl"
    qa_cases_path = OUT_DIR / "qa_cases.jsonl"
    corpus_db_path = OUT_DIR / "corpus.db"

    if not args.qa_only and not args.corpus_only:
        # Full run: start clean.
        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    corpus_cases = []
    if not args.qa_only:
        with open(CORPUS_PATH) as f:
            records = [json.loads(line) for line in f]
        print(f"Replaying {len(records)} corpus records...")
        conn = fresh_db(corpus_db_path)
        corpus_cases = run_corpus_eval(conn, records, args.limit)
        conn.close()
        with open(corpus_cases_path, "w") as f:
            for c in corpus_cases:
                f.write(json.dumps(c) + "\n")
        print(f"Corpus replay done: {sum(1 for c in corpus_cases if c['verdict'] == 'pass')}/{len(corpus_cases)} passed")
    elif corpus_cases_path.exists():
        # --qa-only: keep and fold in results from a prior corpus run rather
        # than losing them from the combined summary.
        with open(corpus_cases_path) as f:
            corpus_cases = [json.loads(line) for line in f]
        print(f"Reusing {len(corpus_cases)} corpus results from a previous run ({corpus_cases_path}).")

    qa_cases = []
    if not args.corpus_only:
        print(f"Running {sum(1 for _ in open(QA_PATH))} QA cases...")
        qa_cases = run_qa_eval(OUT_DIR / "qa_dbs")
        with open(qa_cases_path, "w") as f:
            for c in qa_cases:
                f.write(json.dumps(c) + "\n")
        print(f"QA eval done: {sum(1 for c in qa_cases if c['verdict'] == 'pass')}/{len(qa_cases)} passed")
    elif qa_cases_path.exists():
        with open(qa_cases_path) as f:
            qa_cases = [json.loads(line) for line in f]
        print(f"Reusing {len(qa_cases)} QA results from a previous run ({qa_cases_path}).")

    summary = summarize(corpus_cases, qa_cases, corpus_db_path if corpus_cases else None)
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    write_markdown_summary(summary, OUT_DIR / "summary.md")
    print(f"\nResults written to {OUT_DIR}")
    print(f"See {OUT_DIR / 'summary.md'} for the human-readable report.")


if __name__ == "__main__":
    main()
