"""Deterministic specification for the ~500-record evaluation corpus.

This module is the ground truth. It picks names/roles/apps/instructions with
a fixed random seed and decides, in plain Python, what each record's content
IS and what the extraction pipeline SHOULD do with it — before any model has
seen anything. The LLM used later (scripts/generate_corpus.py) only phrases
each spec as natural dictation text; it never decides what the "right
answer" is. That separation is what keeps this an evaluation rather than "a
collection of successful examples chosen after the system was built."

Category counts (512 total), chosen to resemble real usage — mostly
ordinary dictation with nothing memory-worthy, plus enough of each edge case
to reveal where the system succeeds, abstains, or fails:

  negative_ordinary   260  ordinary dictation, nothing memory-worthy
  entity_clear         70  50 standalone + 10 role-update threads (x2)
  instruction_clear    50  40 standalone + 5 duplicate-restatement pairs (x2)
  task_clear           50  25 create+update threads (x2)
  ambiguous            25  hedged/uncertain — should not auto-confirm
  adversarial          25  hypothetical/reported/sarcastic — should extract nothing
  boundary_scope       20  8 same-name-different-app pairs (x2) + 4 explicit-global
  recurring_task       12  8 recurring commitments (must be held for confirmation) + 4
                            one-off controls (must NOT be over-flagged as recurring) —
                            added after the initial 500-record generation, once
                            recurring-commitment handling was built (see
                            app/services/extraction.py's task_recurrence field)
"""
import random
from datetime import datetime, timedelta

NAMES = [
    "Rahul", "Priya", "Aditya", "Kavya", "Rohan", "Sneha", "Vikram", "Ananya",
    "Karan", "Divya", "Arjun", "Meera", "Nikhil", "Pooja", "Sanjay", "Ritu",
    "Manish", "Neha", "Varun", "Isha",
]
ROLES = [
    "engineering lead", "design lead", "product manager", "data scientist",
    "marketing manager", "sales lead", "finance analyst", "engineering intern",
    "QA lead", "operations manager",
]
DEPARTMENTS = ["engineering", "design", "product", "marketing", "sales", "finance", "operations", "QA"]
APPS = ["slack", "email", "docs", "notes", "calendar"]
PROJECTS = [
    "the PRD for voice search v2", "the Q3 roadmap doc", "the onboarding redesign",
    "the pricing page rewrite", "the mobile app rewrite", "the API migration",
    "the analytics dashboard", "the security audit report", "the customer survey summary",
    "the hiring plan", "the vendor comparison sheet", "the incident postmortem",
    "the design system refresh", "the churn analysis", "the launch checklist",
    "the support macros rewrite", "the localization plan", "the outage runbook",
    "the interview loop redesign", "the pricing experiment writeup", "the annual review template",
    "the data retention policy", "the on-call rotation plan", "the marketing calendar",
    "the API docs overhaul",
]
INSTRUCTION_TEXTS = [
    "always CC my manager on client emails", "always start Slack messages to the design team with a quick TL;DR",
    "never schedule meetings before 10am", "always attach the latest deck version when emailing clients",
    "always use formal language when emailing external clients", "never CC external partners on internal threads",
    "always add a one-line summary at the top of long documents", "always loop in QA before marking a ticket done",
    "never send calendar invites without an agenda", "always sign off emails with 'Best, Div'",
]
NEGATIVE_TOPICS = [
    "a quick recap of everything you finished yesterday, purely retrospective with nothing currently in progress and no names or standing rules mentioned",
    "a reminder to yourself to buy groceries after work",
    "a note describing a bug you just found in the login flow, described technically with no names",
    "a recap of a meeting's agenda items without naming any attendees",
    "a description of what a paragraph in a document should say, purely about content",
    "a general question about how a feature should behave, with no names involved",
    "a grocery list",
    "a note about weather affecting your commute",
    "a brainstorm of possible names for a new feature",
    "a code comment explaining what a function does",
    "a reminder to yourself to stretch during a break",
    "a summary of a customer complaint, described generically without naming the customer",
    "the outline of a blog post about productivity",
    "a note about wanting to reorganize your desk",
    "a description of a chart to add to a slide deck",
    "a reminder to renew a subscription",
    "a note about a podcast episode you liked",
    "a description of a UI layout you want changed, with no names",
    "a summary of quarterly numbers, purely factual with no names",
    "a reminder to reply to a message later",
]
NAME_MENTION_TOPICS = [
    "grabbing coffee with {name} later, then getting back to work",
    "mentioning in passing that {name} said hi in the hallway",
    "a note that you're meeting {name} for lunch, with no other detail about who they are",
    "asking whether {name} is free Thursday, with nothing about their role",
]


def _dt(index: int) -> str:
    base = datetime(2026, 6, 1, 9, 0, 0)
    return (base + timedelta(hours=index * 3)).strftime("%Y-%m-%dT%H:%M:%S")


def _mk(rng, category, app, expected, phrasing_brief, adversarial=False, group=None, seq=None):
    return {
        "category": category, "app": app, "expected": expected, "phrasing_brief": phrasing_brief,
        "adversarial": adversarial, "group": group, "seq": seq,
    }


def _negative_ordinary(rng, n):
    specs = []
    for _ in range(int(n * 0.88)):
        topic = rng.choice(NEGATIVE_TOPICS)
        app = rng.choice(APPS)
        specs.append(_mk(
            rng, "negative_ordinary", app,
            {"extraction_type": "none", "expected_decision": "none", "notes": "ordinary dictation, nothing memory-worthy"},
            f"Dictate, naturally and in first person, {topic}.",
        ))
    for _ in range(n - len(specs)):
        name = rng.choice(NAMES)
        app = rng.choice(APPS)
        topic = rng.choice(NAME_MENTION_TOPICS).format(name=name)
        specs.append(_mk(
            rng, "negative_ordinary", app,
            {"extraction_type": "none", "expected_decision": "none", "notes": "name mentioned only in passing, no clarifying/instructing intent"},
            f"Dictate, naturally and in first person, {topic}.",
        ))
    return specs


def _entity_clear(rng, n_standalone, n_thread_pairs):
    specs = []
    for _ in range(n_standalone):
        name = rng.choice(NAMES)
        role = rng.choice(ROLES)
        dept = role.split()[0] if role.split()[0] in DEPARTMENTS else rng.choice(DEPARTMENTS)
        app = rng.choice(APPS)
        disambiguate = rng.random() < 0.5
        if disambiguate:
            other_dept = rng.choice([d for d in DEPARTMENTS if d != dept])
            brief = (
                f"Dictate a clear, explicit statement that {name} is your {role} in {dept}, "
                f"specifically disambiguating them from a different person also named {name} who is in {other_dept}."
            )
        else:
            brief = f"Dictate a clear, explicit statement that {name} is your {role}."
        specs.append(_mk(
            rng, "entity_clear", app,
            {
                "extraction_type": "entity", "expected_decision": "auto_confirmed",
                "entity_surface_form": name, "entity_resolved_as_contains": name,
                "notes": "unambiguous, self-contained identity statement",
            },
            brief,
        ))
    for t in range(n_thread_pairs):
        name = rng.choice(NAMES)
        role_a = rng.choice(ROLES)
        role_b = rng.choice([r for r in ROLES if r != role_a])
        app = rng.choice(APPS)
        group = f"entity_thread_{t}"
        specs.append(_mk(
            rng, "entity_clear", app,
            {
                "extraction_type": "entity", "expected_decision": "auto_confirmed",
                "entity_surface_form": name, "entity_resolved_as_contains": name,
                "notes": "first mention of this entity",
            },
            f"Dictate a clear, explicit statement that {name} is your {role_a}.",
            group=group, seq=0,
        ))
        specs.append(_mk(
            rng, "entity_clear", app,
            {
                "extraction_type": "entity", "expected_decision": "merged",
                "entity_surface_form": name, "entity_resolved_as_contains": name,
                "notes": f"role update for the same person established earlier in this app ({role_a} -> {role_b})",
            },
            f"Dictate a clear, explicit statement that {name} is actually now your {role_b}, "
            f"as an update to their role.",
            group=group, seq=1,
        ))
    return specs


def _instruction_clear(rng, n_standalone, n_dup_pairs):
    specs = []
    used = set()
    for _ in range(n_standalone):
        text = rng.choice(INSTRUCTION_TEXTS)
        app = rng.choice(APPS)
        specs.append(_mk(
            rng, "instruction_clear", app,
            {
                "extraction_type": "instruction", "expected_decision": "auto_confirmed",
                "instruction_rule_text_contains": _key_phrase(text),
                "notes": "explicit standing rule stated in plain language",
            },
            f"Dictate a clear, explicit standing rule for your own future behaviour: \"{text}\".",
        ))
    # A few near-verbatim restatements — current dedup (exact normalized match)
    # should catch these.
    for i in range(n_dup_pairs - 2):
        text = INSTRUCTION_TEXTS[i % len(INSTRUCTION_TEXTS)]
        app = rng.choice(APPS)
        group = f"instr_dup_{i}"
        specs.append(_mk(
            rng, "instruction_clear", app,
            {"extraction_type": "instruction", "expected_decision": "auto_confirmed", "notes": "first statement of this rule"},
            f"Dictate a clear, explicit standing rule: \"{text}\".", group=group, seq=0,
        ))
        specs.append(_mk(
            rng, "instruction_clear", app,
            {"extraction_type": "instruction", "expected_decision": "duplicate_ignored", "notes": "near-verbatim restatement of the same rule"},
            f"Dictate the same rule again, nearly word-for-word: \"{text}\".", group=group, seq=1,
        ))
    # A couple of paraphrased restatements — documented limitation, exact-text
    # dedup won't catch a reworded restatement. Labelled so the eval reports
    # this honestly rather than scoring it as a plain failure.
    for i in range(2):
        text = INSTRUCTION_TEXTS[(i + 5) % len(INSTRUCTION_TEXTS)]
        app = rng.choice(APPS)
        group = f"instr_paraphrase_{i}"
        specs.append(_mk(
            rng, "instruction_clear", app,
            {"extraction_type": "instruction", "expected_decision": "auto_confirmed", "notes": "first statement of this rule"},
            f"Dictate a clear, explicit standing rule: \"{text}\".", group=group, seq=0,
        ))
        specs.append(_mk(
            rng, "instruction_clear", app,
            {
                "extraction_type": "instruction", "expected_decision": "created_known_limitation",
                "notes": "paraphrased restatement of an existing rule — exact-text dedup won't recognize this as a duplicate; documented limitation, not scored as a bug",
            },
            f"Dictate the same rule again but reworded in different words, meaning the same thing as \"{text}\".",
            group=group, seq=1,
        ))
    return specs


def _task_clear(rng, n_threads):
    specs = []
    progress_states = [
        ("the outline", "the intro"), ("a first draft", "stakeholder review"),
        ("initial research", "a rough draft"), ("the data pull", "the first chart"),
    ]
    for t in range(n_threads):
        project = rng.choice(PROJECTS)
        app = rng.choice(["docs", "notes"])
        (done1, done2) = rng.choice(progress_states)
        group = f"task_thread_{t}"
        label_variant_a = project
        label_variant_b = project.replace("the ", "", 1) if project.startswith("the ") else project
        specs.append(_mk(
            rng, "task_clear", app,
            {
                "extraction_type": "task", "expected_decision": "created",
                "task_label_contains": _key_phrase(project), "task_state_summary_contains": done1,
                "notes": "explicit statement of current work state",
            },
            f"Dictate that you're currently working on {label_variant_a}, and that {done1} is done, "
            f"but {done2} still needs to happen.",
            group=group, seq=0,
        ))
        specs.append(_mk(
            rng, "task_clear", app,
            {
                "extraction_type": "task", "expected_decision": "updated",
                "task_label_contains": _key_phrase(project), "task_state_summary_contains": done2,
                "notes": "progress update on the same work, phrased slightly differently than the first mention",
            },
            f"Dictate, continuing about {label_variant_b} (phrase the name slightly differently than "
            f"\"{label_variant_a}\"), that {done2} is now also done.",
            group=group, seq=1,
        ))
    return specs


def _ambiguous(rng, n):
    templates = [
        "Dictate, hesitantly, something like \"I think that might be {name} from {dept}, not totally sure though\" — expressing real doubt about an identity, not a confident statement.",
        "Dictate, as a passing thought rather than a firm rule, something like \"maybe we should always cc someone on these\" — vague, without committing to it as a real standing rule.",
        "Dictate, reporting uncertain secondhand information, something like \"he mentioned something about needing a manager cc'd on stuff, not sure if that's an actual rule\".",
        "Dictate, vaguely and without naming the work clearly, something like \"I guess I'm sort of still working on that thing from before\".",
    ]
    specs = []
    for _ in range(n):
        name = rng.choice(NAMES)
        dept = rng.choice(DEPARTMENTS)
        app = rng.choice(APPS)
        brief = rng.choice(templates).format(name=name, dept=dept)
        specs.append(_mk(
            rng, "ambiguous", app,
            {
                "extraction_type": "any", "acceptable_decisions": ["pending_confirmation", "none"],
                "notes": "hedged/uncertain statement — should not auto-confirm",
            },
            brief,
        ))
    return specs


def _adversarial(rng, n):
    templates = [
        "Dictate a hypothetical, conditional statement like \"if I were you, I'd always cc the manager on client emails\" — advice about what someone ELSE should do, not a rule for yourself.",
        "Dictate reported speech like \"she told me she always ccs her manager on client emails\" — describing someone else's habit, not stating your own rule.",
        "Dictate something sarcastic/rhetorical like \"oh sure, like I'd ever remember to cc my manager\" — not a real commitment to a rule.",
        "Dictate a name mentioned only in passing with no identifying/clarifying intent, like \"grabbing coffee with {name} later, anyway, back to the doc\".",
        "Dictate a third-person report about someone else's work, like \"{name} mentioned she's still working on the deck\" — not your own task.",
    ]
    specs = []
    for _ in range(n):
        name = rng.choice(NAMES)
        app = rng.choice(APPS)
        brief = rng.choice(templates).format(name=name)
        specs.append(_mk(
            rng, "adversarial", app,
            {"extraction_type": "none", "expected_decision": "none", "notes": "near-miss phrasing that must not create memory"},
            brief, adversarial=True,
        ))
    return specs


def _boundary_scope(rng, n_pairs, n_global):
    specs = []
    for p in range(n_pairs):
        name = rng.choice(NAMES)
        role_a, role_b = rng.sample(ROLES, 2)
        app_a, app_b = rng.sample(APPS, 2)
        group = f"boundary_pair_{p}"
        specs.append(_mk(
            rng, "boundary_scope", app_a,
            {
                "extraction_type": "entity", "expected_decision": "auto_confirmed",
                "entity_surface_form": name, "entity_resolved_as_contains": name,
                "notes": f"entity scoped to {app_a} only",
            },
            f"Dictate a clear, explicit statement that {name} is your {role_a}.",
            group=group, seq=0,
        ))
        specs.append(_mk(
            rng, "boundary_scope", app_b,
            {
                "extraction_type": "entity", "expected_decision": "auto_confirmed",
                "entity_surface_form": name, "entity_resolved_as_contains": name,
                "notes": f"a DIFFERENT {name}, scoped to {app_b} only — must NOT merge with the {app_a}-scoped one",
                "must_not_merge_with_group_seq": 0,
            },
            f"Dictate a clear, explicit statement that a different person, also named {name}, is your {role_b}.",
            group=group, seq=1,
        ))
    for _ in range(n_global):
        name = rng.choice(NAMES)
        role = rng.choice(ROLES)
        app = rng.choice(APPS)
        phrase = rng.choice(["on all my devices", "everywhere I use Kivi", "in general, not just here"])
        specs.append(_mk(
            rng, "boundary_scope", app,
            {
                "extraction_type": "entity", "expected_decision": "auto_confirmed", "expected_scope": "global",
                "entity_surface_form": name, "entity_resolved_as_contains": name,
                "notes": "explicit statement that this applies broadly, not just to this app",
            },
            f"Dictate a clear, explicit statement that {name} is your {role}, and explicitly say this "
            f"applies \"{phrase}\".",
        ))
    return specs


_KEY_PHRASE_STOPWORDS = {
    "always", "never", "with", "your", "that", "from", "this", "have", "without",
    "before", "after", "using", "also", "just", "attach", "start", "when", "into",
}


def _key_phrase(text: str) -> str:
    """A short, stable, content-bearing substring to check for in extracted
    content later — robust to the model's own paraphrasing of the rest of
    the sentence. Picks the longest non-generic word as a simple proxy for
    "most specific"; this is a soft sanity check in the eval, not a strict
    match, so it doesn't need to be more sophisticated than that."""
    words = [w.strip(",.'\"") for w in text.split() if len(w) > 4 and w.lower() not in _KEY_PHRASE_STOPWORDS]
    return max(words, key=len) if words else text


def _recurring_task(rng, n_recurring, n_one_off_control):
    """Recurring commitments ('a weekly call with Rahul') have no natural end,
    so they should be held for confirmation rather than auto-committed as an
    ordinary task (see app/services/extraction.py's task_recurrence field).
    The one-off controls are calendar-shaped statements that must NOT be
    flagged as recurring, to check the extractor isn't over-triggering on
    every calendar mention."""
    specs = []
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for _ in range(n_recurring):
        name = rng.choice(NAMES)
        day = rng.choice(days)
        app = rng.choice(["calendar", "slack"])
        specs.append(_mk(
            rng, "recurring_task", app,
            {
                "extraction_type": "task", "expected_decision": "pending_confirmation",
                "expected_task_recurrence": "recurring", "task_label_contains": name,
                "notes": "recurring commitment with no natural end — must be held for confirmation, not auto-committed",
            },
            f"Dictate that you have a standing weekly commitment with {name} every {day} — phrase it "
            f"clearly as an ongoing routine, not a one-time event.",
        ))
    for _ in range(n_one_off_control):
        name = rng.choice(NAMES)
        day = rng.choice(days)
        app = rng.choice(["calendar", "slack"])
        specs.append(_mk(
            rng, "recurring_task", app,
            {
                "extraction_type": "task", "expected_decision": "created",
                "expected_task_recurrence": "one_off", "task_label_contains": name,
                "notes": "a single specific meeting, not recurring — must not be over-flagged as needing confirmation",
            },
            f"Dictate that you have a one-time call with {name} this coming {day} to discuss a specific "
            f"topic — phrase it clearly as a single, specific meeting, not a routine.",
        ))
    return specs


def build_specs(seed: int = 42, include_recurring_task: bool = False) -> list[dict]:
    """Reproduces the committed corpus. Defaults to exactly the original
    500 records (c0001-c0500) — recurring_task is opt-in via
    `include_recurring_task`, since in the actual committed corpus it was
    generated later and appended with continuing ids (see
    scripts/generate_corpus.py's --append-category), not interleaved into
    the main 500's shuffle. Passing include_recurring_task=True draws from
    the SAME rng position that produced the already-committed c0501-c0512
    (recurring_task's draws happen after all seven other categories'
    either way, so its content is identical regardless of this flag) —
    only the ids/ordering differ, and --append-category already reassigns
    those explicitly rather than relying on this function's own ordering."""
    rng = random.Random(seed)
    specs = []
    specs += _negative_ordinary(rng, 260)
    specs += _entity_clear(rng, 50, 10)
    specs += _instruction_clear(rng, 40, 5)
    specs += _task_clear(rng, 25)
    specs += _ambiguous(rng, 25)
    specs += _adversarial(rng, 25)
    specs += _boundary_scope(rng, 8, 4)
    if include_recurring_task:
        specs += _recurring_task(rng, 8, 4)

    # Shuffle at the group level, not the flat-record level: a threaded
    # record (seq=1, e.g. a task update) must never end up scheduled before
    # its own seq=0 record. Ungrouped specs are each their own singleton
    # group. This still interleaves categories realistically.
    buckets: dict[str, list[dict]] = {}
    next_singleton = 0
    for spec in specs:
        if spec["group"] is None:
            key = f"__singleton_{next_singleton}"
            next_singleton += 1
        else:
            key = spec["group"]
        buckets.setdefault(key, []).append(spec)

    bucket_list = list(buckets.values())
    for bucket in bucket_list:
        bucket.sort(key=lambda s: (s["seq"] is not None, s["seq"] or 0))
    rng.shuffle(bucket_list)
    flat = [spec for bucket in bucket_list for spec in bucket]

    for i, spec in enumerate(flat):
        spec["id"] = f"c{i + 1:04d}"
        spec["occurred_at"] = _dt(i)
    return flat


if __name__ == "__main__":
    all_specs = build_specs()
    from collections import Counter
    counts = Counter(s["category"] for s in all_specs)
    print(f"Total specs: {len(all_specs)}")
    for cat, count in counts.items():
        print(f"  {cat}: {count}")
