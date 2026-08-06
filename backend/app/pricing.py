"""Per-model token pricing used to attribute cost to events.

Prices are USD per 1M tokens. Unknown models fall back to DEFAULT_PRICING so the
cost meter always shows *something* sensible rather than zero.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float


PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4.1": ModelPricing(2.00, 8.00),
    "gpt-4.1-mini": ModelPricing(0.40, 1.60),
    "scripted-demo-agent": ModelPricing(0.15, 0.60),  # curated library traces (4o-mini rates)
}

DEFAULT_PRICING = ModelPricing(1.00, 3.00)


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    p = PRICING.get(model, DEFAULT_PRICING)
    return round(
        tokens_in / 1_000_000 * p.input_per_mtok
        + tokens_out / 1_000_000 * p.output_per_mtok,
        8,
    )
