"""Thin wrapper around the Anthropic SDK. Every call goes through call_tool(),
which forces a single structured tool call (reliable JSON, no parsing games)
and logs latency/tokens/estimated cost to model_calls — the backing for the
eval's honest cost/latency reporting.

Pricing is Anthropic's first-party per-1M-token rate card (input/output),
current as of this build; if it drifts, update PRICING rather than treating
cost figures as exact billing.
"""
import sqlite3
import time

import anthropic

from app.config import ANTHROPIC_API_KEY

PRICING_PER_MILLION = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
}

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    return _client


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING_PER_MILLION.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


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
    """Force a single call to `tool_name` and return (parsed_input, call_stats).

    Forced tool_choice is well-supported on Haiku 4.5 / Sonnet 5 (unlike the
    newest Fable/Mythos tier) and gives schema-valid JSON without prompting
    tricks — see the `strict` flag below.
    """
    client = get_client()
    tool = {
        "name": tool_name,
        "description": tool_description,
        "input_schema": tool_schema,
        "strict": True,
    }

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

    conn.execute(
        """
        INSERT INTO model_calls
            (purpose, model, input_tokens, output_tokens, latency_ms, estimated_cost_usd,
             related_dictation_id, related_request_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (purpose, model, input_tokens, output_tokens, latency_ms, cost,
         related_dictation_id, related_request_id),
    )

    stats = {
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost,
    }
    return parsed, stats
