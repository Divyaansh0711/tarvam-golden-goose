"""Phrase eval/corpus_spec.py's deterministic specs as natural dictation
text via an LLM, and write eval/corpus/dictations.jsonl.

The LLM's only job here is phrasing — every spec already carries its own
expected outcome, decided independently in corpus_spec.py before any model
was involved. This script does not use app.services.llm.call_tool (which
logs to the product's model_calls table); this is offline dev tooling, not
product runtime, so it uses call_tool_raw directly and writes nothing to
the app database.

Usage:
    python scripts/generate_corpus.py                  # full ~500-record corpus
    python scripts/generate_corpus.py --pilot 24        # quick pilot batch to inspect quality
    python scripts/generate_corpus.py --batch-size 8    # briefs per LLM call (default 8)
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import GENERATION_MODEL
from app.services.llm import call_tool_raw
from eval.corpus_spec import _dt, build_specs

OUT_PATH = Path(__file__).resolve().parent.parent / "eval" / "corpus" / "dictations.jsonl"

SYSTEM_PROMPT = """You are helping build an evaluation corpus of realistic dictation transcripts \
for a speech-to-text product called Kivi. For each numbered brief below, write a short, natural, \
first-person dictation matching it exactly — the way a real person actually talks while dictating \
into their computer (casual, a little informal, not overly polished, 1-3 sentences).

For each brief, provide TWO versions of the SAME content:
- `raw_asr`: all lowercase, no punctuation, as a raw speech-recognition model would output it \
(minor natural disfluency like "um" or a repeated word is fine, but keep it readable).
- `formatted_text`: the cleaned-up version — capitalized, punctuated — as if a language model \
tidied up the raw ASR output. Same content and meaning as raw_asr, just formatted.

Follow each brief's content precisely: if it asks you to disambiguate two people, phrase both \
mentions; if it asks for hedging/uncertain language, keep it uncertain, don't make it confident; \
if it asks for hypothetical or reported speech, phrase it that way, not as a direct first-person \
statement. Return exactly one phrasing pair per brief, in the same order as the briefs."""

BATCH_TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "phrasings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "raw_asr": {"type": "string"},
                    "formatted_text": {"type": "string"},
                },
                "required": ["raw_asr", "formatted_text"],
            },
        },
    },
    "required": ["phrasings"],
}


def phrase_batch(specs: list[dict]) -> list[dict]:
    briefs = "\n".join(f"{i + 1}. {s['phrasing_brief']}" for i, s in enumerate(specs))
    parsed, _stats = call_tool_raw(
        model=GENERATION_MODEL,
        system=SYSTEM_PROMPT,
        user_message=briefs,
        tool_name="record_phrasings",
        tool_description="Record one raw_asr/formatted_text phrasing per numbered brief, in order.",
        tool_schema=BATCH_TOOL_SCHEMA,
        max_tokens=4000,
    )
    phrasings = parsed.get("phrasings", [])
    if len(phrasings) != len(specs):
        raise ValueError(f"expected {len(specs)} phrasings, got {len(phrasings)}")
    return phrasings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", type=int, default=None, help="only generate the first N specs")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--append-category", default=None,
        help="Generate only specs from this category and APPEND them to the existing corpus "
             "file with fresh, continuing ids — for adding a new category after the main corpus "
             "was already generated and committed, without reshuffling/invalidating it.",
    )
    args = parser.parse_args()

    existing_records = []
    if args.append_category:
        if not OUT_PATH.exists():
            raise SystemExit(f"--append-category requires an existing corpus at {OUT_PATH}")
        with open(OUT_PATH) as f:
            existing_records = [json.loads(line) for line in f]
        specs = [s for s in build_specs(seed=args.seed) if s["category"] == args.append_category]
        # Reassign ids/timestamps to continue the existing file's numbering,
        # ignoring wherever this category landed in the full shuffle.
        for offset, spec in enumerate(specs):
            index = len(existing_records) + offset
            spec["id"] = f"c{index + 1:04d}"
            spec["occurred_at"] = _dt(index)
        print(f"appending {len(specs)} '{args.append_category}' records after the existing {len(existing_records)}")
    else:
        specs = build_specs(seed=args.seed)

    if args.pilot:
        specs = specs[: args.pilot]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = list(existing_records)
    n_batches = (len(specs) + args.batch_size - 1) // args.batch_size

    for b in range(n_batches):
        batch = specs[b * args.batch_size : (b + 1) * args.batch_size]
        attempt = 0
        while True:
            attempt += 1
            try:
                phrasings = phrase_batch(batch)
                break
            except Exception as exc:
                if attempt >= 2:
                    raise
                print(f"  batch {b + 1}/{n_batches} failed ({exc}), retrying once...")
                time.sleep(2)

        for spec, phrasing in zip(batch, phrasings):
            records.append({
                "id": spec["id"], "category": spec["category"], "app": spec["app"],
                "occurred_at": spec["occurred_at"], "raw_asr": phrasing["raw_asr"],
                "formatted_text": phrasing["formatted_text"], "metadata": {},
                "expected": spec["expected"], "adversarial": spec["adversarial"],
                "group": spec["group"], "seq": spec["seq"],
            })
        print(f"batch {b + 1}/{n_batches} done ({len(records) - len(existing_records)}/{len(specs)} new records)")

    with open(OUT_PATH, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    if existing_records:
        print(f"\nAppended {len(records) - len(existing_records)} records; {len(records)} total in {OUT_PATH}")
    else:
        print(f"\nWrote {len(records)} records to {OUT_PATH}")


if __name__ == "__main__":
    main()
