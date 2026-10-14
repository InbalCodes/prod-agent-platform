"""Token prices, versioned in code so every cost number is reproducible.

Estimates for observability and evals — not billing. Update PRICES_AS_OF when editing.
"""

from dataclasses import dataclass

from agent_platform.llm.client import Usage

PRICES_AS_OF = "2026-10-06"

CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute cache writes cost 1.25x base input


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(
        input_per_mtok=4.00, output_per_mtok=20.00, cache_read_per_mtok=0.20
    ),
    "claude-sonnet-5-5": ModelPrice(
        input_per_mtok=2.00, output_per_mtok=10.00, cache_read_per_mtok=0.20
    ),
}


def estimate_cost_usd(model: str, usage: Usage) -> float | None:
    """Return the estimated cost, or None for a model without a known price."""
    price = PRICES.get(model)
    if price is None:
        return None
    cost = (
        usage.input_tokens * price.input_per_mtok
        + usage.output_tokens * price.output_per_mtok
        + usage.cache_read_input_tokens * price.cache_read_per_mtok
        + usage.cache_creation_input_tokens * price.input_per_mtok * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    return round(cost, 6)
