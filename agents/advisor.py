"""Per-position action advisor.

Consumes a reviewer.PositionContext and optional precomputed RollScenarios,
returns an ActionSuggestion with a hold/close/roll/reduce/let_expire
recommendation plus a confidence label and plain-English reason.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from agents.reviewer import PositionContext
from utils.roll_calculator import RollScenario


Action = Literal["hold", "close", "roll", "reduce", "let_expire"]
Confidence = Literal["low", "medium", "high"]

ROLL_VIABILITY_FLOOR: float = 50.0
PROFIT_TARGET_PCT: float = 0.50
STOP_LOSS_PCT: float = -1.00
ROLL_DTE_THRESHOLD: int = 21
EXPIRE_DTE_THRESHOLD: int = 2
ASSIGNMENT_PROXIMITY_PCT: float = 0.02


@dataclass(frozen=True)
class ActionSuggestion:
    """Recommendation for a single position."""
    action: Action
    confidence: Confidence
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    roll_scenarios: List[RollScenario] = field(default_factory=list)


def _return_pct(position: PositionContext) -> float:
    """Signed return: +0.5 means +50% of entry credit/debit recovered."""
    denom = max(abs(float(position.entry_cost)), 1e-9)
    return float(position.unrealized_pl) / denom


def _short_strike_under_test(position: PositionContext) -> Optional[float]:
    """Short strike closest to current_price; None if no STO legs or invalid spot."""
    spot = position.current_price
    if spot is None or spot <= 0:
        return None
    sto_strikes = []
    for leg in position.legs:
        if leg.get("action") == "STO" and leg.get("strike") is not None:
            try:
                sto_strikes.append(float(leg["strike"]))
            except (TypeError, ValueError):
                continue
    if not sto_strikes:
        return None
    return min(sto_strikes, key=lambda k: abs(k - spot))


def _assignment_proximity_pct(position: PositionContext) -> Optional[float]:
    """|short_strike - spot| / spot, or None if missing."""
    k = _short_strike_under_test(position)
    spot = position.current_price
    if k is None or spot is None or spot <= 0:
        return None
    return abs(k - spot) / spot


def _filter_viable(scenarios: Optional[List[RollScenario]]) -> List[RollScenario]:
    """Keep only scenarios with viability_score >= ROLL_VIABILITY_FLOOR."""
    if not scenarios:
        return []
    return [s for s in scenarios if getattr(s, "viability_score", 0) >= ROLL_VIABILITY_FLOOR]


def suggest_action(
    position: PositionContext,
    roll_scenarios: Optional[List[RollScenario]] = None,
) -> ActionSuggestion:
    """Run the decision tree and return an ActionSuggestion.

    roll_scenarios is attached to the result only when action == "roll" AND
    at least one passed-in scenario meets ROLL_VIABILITY_FLOOR.
    """
    metrics: Dict[str, Any] = {
        "return_pct": _return_pct(position),
        "dte": position.dte,
        "short_strike": _short_strike_under_test(position),
        "proximity_pct": _assignment_proximity_pct(position),
    }
    ret = metrics["return_pct"]
    dte = metrics["dte"]
    prox = metrics["proximity_pct"]

    if ret >= PROFIT_TARGET_PCT:
        return ActionSuggestion(
            action="close", confidence="high",
            reason=f"Profit target reached ({ret*100:.0f}% of entry).",
            metrics=metrics,
        )

    if ret <= STOP_LOSS_PCT:
        viable = _filter_viable(roll_scenarios)
        if viable:
            return ActionSuggestion(
                action="roll", confidence="high",
                reason="Loss exceeds 100% of credit; viable roll available.",
                metrics=metrics, roll_scenarios=viable,
            )
        return ActionSuggestion(
            action="close", confidence="high",
            reason="Loss exceeds 100% of credit; no viable roll.",
            metrics=metrics,
        )

    if dte <= EXPIRE_DTE_THRESHOLD:
        # let_expire requires a validated short strike that is clearly OTM.
        # Without that context (long-only position, missing spot, or short strike
        # within the assignment-proximity band), fall back to close.
        if (
            ret > 0
            and prox is not None
            and prox > ASSIGNMENT_PROXIMITY_PCT
        ):
            return ActionSuggestion(
                action="let_expire", confidence="high",
                reason=f"{dte} DTE, OTM, in profit — let expire.",
                metrics=metrics,
            )
        return ActionSuggestion(
            action="close", confidence="high",
            reason=f"{dte} DTE with assignment risk or a loss — close.",
            metrics=metrics,
        )

    if dte <= ROLL_DTE_THRESHOLD:
        viable = _filter_viable(roll_scenarios)
        if viable:
            return ActionSuggestion(
                action="roll", confidence="medium",
                reason=f"{dte} DTE inside roll window; viable roll available.",
                metrics=metrics, roll_scenarios=viable,
            )
        if prox is not None and prox <= ASSIGNMENT_PROXIMITY_PCT:
            return ActionSuggestion(
                action="close", confidence="medium",
                reason=f"{dte} DTE, short strike within {prox*100:.1f}% of spot, no viable roll.",
                metrics=metrics,
            )
        return ActionSuggestion(
            action="hold", confidence="low",
            reason=f"{dte} DTE, no viable roll, no immediate pressure.",
            metrics=metrics,
        )

    if prox is not None and prox <= ASSIGNMENT_PROXIMITY_PCT:
        return ActionSuggestion(
            action="reduce", confidence="medium",
            reason=f"Short strike within {prox*100:.1f}% of spot — consider reducing size.",
            metrics=metrics,
        )

    return ActionSuggestion(
        action="hold", confidence="low",
        reason="No exit triggers met.",
        metrics=metrics,
    )
