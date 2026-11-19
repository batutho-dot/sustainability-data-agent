"""Price per million tokens, standard Claude API rates (USD).

Source: Anthropic's model table as shipped in the claude-api reference (cached 2026-11-03).
Haiku 5.5 costs more above 100K input tokens in one request; that rate is applied per request.
Check https://platform.claude.com/docs/en/about-claude/pricing before relying on these.
"""

from __future__ import annotations

PRICES = {
    # model: (input, output, input above 100K, output above 100K) per 1M tokens
    "claude-haiku-5-5": (0.10, 0.50, 0.50, 2.50),
    "claude-sonnet-5-5": (2.00, 10.00, 2.00, 10.00),
}
LONG_PROMPT = 100_000


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES:
        raise KeyError(f"No price for {model}; add it to pricing.PRICES first.")
    inp, out, inp_long, out_long = PRICES[model]
    if input_tokens > LONG_PROMPT:
        inp, out = inp_long, out_long
    return (input_tokens * inp + output_tokens * out) / 1_000_000
