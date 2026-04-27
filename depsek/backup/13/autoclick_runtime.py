from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import random
import time
from typing import Callable, Dict, List, Optional, Tuple

import pyautogui


CHIP_VALUES: Dict[str, int] = {
    "Bet 5": 5,
    "Bet 10": 10,
    "Bet 20": 20,
    "Bet 50": 50,
}


class ClickPlanError(Exception):
    """Raised when the requested bet cannot be expressed with calibrated controls."""


@dataclass(frozen=True)
class BetPlacement:
    chip_label: str
    total_amount: int
    x2_clicks: int = 0

    @property
    def click_cost(self) -> int:
        return 2 + self.x2_clicks

    @property
    def description(self) -> str:
        if self.x2_clicks <= 0:
            return f"{self.total_amount} via {self.chip_label}"
        return f"{self.total_amount} via {self.chip_label} + X2x{self.x2_clicks}"


@dataclass(frozen=True)
class ClickAction:
    label: str
    x: int
    y: int


def build_bet_plan(target_amount: int) -> List[BetPlacement]:
    if target_amount <= 0:
        raise ClickPlanError("Bet amount must be greater than zero.")

    candidate_map: Dict[int, BetPlacement] = {}
    largest_base = max(CHIP_VALUES.values())

    for chip_label, base_value in CHIP_VALUES.items():
        value = base_value
        x2_clicks = 0
        while value <= target_amount:
            candidate = BetPlacement(
                chip_label=chip_label,
                total_amount=value,
                x2_clicks=x2_clicks,
            )
            existing = candidate_map.get(value)
            if existing is None or candidate.click_cost < existing.click_cost:
                candidate_map[value] = candidate
            value *= 2
            x2_clicks += 1

    candidates = sorted(candidate_map.values(), key=lambda item: (-item.total_amount, item.click_cost))
    require_x2 = target_amount > largest_base

    @lru_cache(maxsize=None)
    def solve(remaining: int, used_x2: bool) -> Optional[Tuple[int, int, Tuple[BetPlacement, ...]]]:
        if remaining == 0:
            if not require_x2 or used_x2:
                return (0, 0, ())
            return None

        best_result: Optional[Tuple[int, int, Tuple[BetPlacement, ...]]] = None
        for candidate in candidates:
            if candidate.total_amount > remaining:
                continue

            next_used_x2 = used_x2 or candidate.x2_clicks > 0
            tail = solve(remaining - candidate.total_amount, next_used_x2)
            if tail is None:
                continue

            total_cost = candidate.click_cost + tail[0]
            placement_count = 1 + tail[1]
            plan = (candidate,) + tail[2]
            proposal = (total_cost, placement_count, plan)

            if best_result is None or proposal[:2] < best_result[:2]:
                best_result = proposal

        return best_result

    result = solve(target_amount, False)
    if result is None:
        raise ClickPlanError(f"Unable to build a click plan for amount {target_amount}.")

    return list(result[2])


def create_click_actions(
    extra_points: Dict[str, Tuple[int, int]],
    chosen_color: str,
    placements: List[BetPlacement],
) -> List[ClickAction]:
    color_label = f"Bet {chosen_color}"
    if color_label not in extra_points:
        raise ClickPlanError(f"Missing calibration for {color_label}")

    if any(item.x2_clicks > 0 for item in placements) and "X2" not in extra_points:
        raise ClickPlanError("Missing calibration for X2")

    color_x, color_y = extra_points[color_label]
    actions: List[ClickAction] = []

    for placement in placements:
        if placement.chip_label not in extra_points:
            raise ClickPlanError(f"Missing calibration for {placement.chip_label}")

        chip_x, chip_y = extra_points[placement.chip_label]
        actions.append(ClickAction(label=placement.chip_label, x=chip_x, y=chip_y))

        # Place the selected chip on the chosen color first, then apply X2 to
        # multiply that placed amount. This matches the intended UI workflow.
        actions.append(ClickAction(label=color_label, x=color_x, y=color_y))

        if placement.x2_clicks > 0:
            x2_x, x2_y = extra_points["X2"]
            for _ in range(placement.x2_clicks):
                actions.append(ClickAction(label="X2", x=x2_x, y=x2_y))

    return actions


def perform_click_actions(
    actions: List[ClickAction],
    marker_callback: Optional[Callable[[int, int, str], None]] = None,
    stop_requested: Optional[Callable[[], bool]] = None,
    pause_range: Tuple[float, float] = (0.18, 0.32),
):
    for action in actions:
        if stop_requested and stop_requested():
            return False

        pyautogui.click(action.x, action.y)
        if marker_callback:
            marker_callback(action.x, action.y, action.label)

        time.sleep(random.uniform(*pause_range))

    return True


def format_bet_plan(placements: List[BetPlacement]) -> str:
    return " + ".join(item.description for item in placements)
