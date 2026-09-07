"""Thin wrapper around whichever LLM provider is configured. Every call goes
through call_tool(), which forces a single structured tool call (reliable
JSON, no parsing games) and logs latency/tokens/estimated cost to
model_calls — the backing for the eval's honest cost/latency reporting.

Provider is chosen by app.config.LLM_PROVIDER. Callers (extraction.py, and
Hey Kivi's tools/QA later) never see which provider is behind call_tool() —
that's what lets the provider swap the same day the position was clarified,
touching only this file.

"anthropic" is the documented provider for submission (see README/RUN.md).
"groq" is a temporary dev-time substitute for when no Anthropic key is
available; its per-call cost is not tracked (see estimate_cost_usd) since
real cost accounting resumes once back on Anthropic.

Pricing (Anthropic) is Anthropic's first-party per-1M-token rate card,
current as of this build; if it drifts, update PRICING_PER_MILLION rather
than treating cost figures as exact billing.
"""
import json
import sqlite3
import time

from app.config import ANTHROPIC_API_KEY, GROQ_API_KEY, LLM_PROVIDER

PRICING_PER_MILLION = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
}

_anthropic_client = None
_groq_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    return _anthropic_client


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        import groq
        _groq_client = groq.Groq(api_key=GROQ_API_KEY or None)
    return _groq_client


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING_PER_MILLION.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


def _call_tool_anthropic(*, model, system, user_message, tool_name, tool_description, tool_schema, max_tokens):
    client = _get_anthropic_client()
    tool = {"name": tool_name, "description": tool_description, "input_schema": tool_schema, "strict": True}

    start = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user_message}],
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    parsed = tool_use.input if tool_use else {}
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = estimate_cost_usd(model, input_tokens, output_tokens)
    return parsed, {"latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens, "estimated_cost_usd": cost}


def _call_tool_groq(*, model, system, user_message, tool_name, tool_description, tool_schema, max_tokens):
    client = _get_groq_client()
    tools = [{
        "type": "function",
        "function": {"name": tool_name, "description": tool_description, "parameters": tool_schema, "strict": True},
    }]

    start = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_message}],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    parsed = json.loads(tool_calls[0].function.arguments) if tool_calls else {}
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    # Not tracked for this temporary dev provider — real cost accounting
    # resumes once back on Anthropic, the documented submission provider.
    cost = 0.0
    return parsed, {"latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens, "estimated_cost_usd": cost}


_PROVIDER_IMPLS = {"anthropic": _call_tool_anthropic, "groq": _call_tool_groq}


def call_tool_raw(
    *,
    model: str,
    system: str,
    user_message: str,
    tool_name: str,
    tool_description: str,
    tool_schema: dict,
    max_tokens: int = 1024,
) -> tuple[dict, dict]:
    """Force a single call to `tool_name` and return (parsed_input, call_stats),
    dispatched to the configured provider — with no database logging. This is
    the primitive call_tool() wraps; use it directly only for tooling that
    genuinely isn't part of the product's own runtime (e.g. offline eval
    corpus generation), so model_calls stays a true record of product usage,
    not dev-time scaffolding."""
    impl = _PROVIDER_IMPLS[LLM_PROVIDER]
    return impl(
        model=model, system=system, user_message=user_message, tool_name=tool_name,
        tool_description=tool_description, tool_schema=tool_schema, max_tokens=max_tokens,
    )


def call_tool(
    *,
    conn: sqlite3.Connection,
    purpose: str,
    model: str,
    system: str,
    user_message: str,
    tool_name: str,
    tool_description: str,
    tool_schema: dict,
    related_dictation_id: int | None = None,
    related_request_id: int | None = None,
    max_tokens: int = 1024,
) -> tuple[dict, dict]:
    """Force a single call to `tool_name`, log it to model_calls, and return
    (parsed_input, call_stats). Dispatches to the configured provider
    (app.config.LLM_PROVIDER); callers don't need to know or care which one
    is behind it."""
    parsed, stats = call_tool_raw(
        model=model, system=system, user_message=user_message, tool_name=tool_name,
        tool_description=tool_description, tool_schema=tool_schema, max_tokens=max_tokens,
    )

    conn.execute(
        """
        INSERT INTO model_calls
            (purpose, model, input_tokens, output_tokens, latency_ms, estimated_cost_usd,
             related_dictation_id, related_request_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (purpose, model, stats["input_tokens"], stats["output_tokens"], stats["latency_ms"],
         stats["estimated_cost_usd"], related_dictation_id, related_request_id),
    )
    return parsed, stats
