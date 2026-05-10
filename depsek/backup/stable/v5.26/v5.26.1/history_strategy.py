from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


SETTLED_RESULTS = {"WIN", "WIN (x2)", "WIN (x3)", "LOSE"}
WINDOW_SIZE = 99
WARMUP_COUNT = 6
VALID_COOLDOWN_COUNTS = (9, 10)
PHASE_LABELS = (
    ("WARMUP", 1, 6),
    ("EARLY", 7, 30),
    ("MID", 31, 60),
    ("LATE", 61, 90),
    ("COOLDOWN", 91, 99),
)

# New analysis behavior for the cloned project:
# - keep recent windows as the main color signal
# - keep longer history as a weaker prior
# - decay older windows automatically
# - dampen stale older history when it disagrees with recent behavior
RECENT_WINDOW_CAP = 5
LONG_WINDOW_DECAY = 0.92
RECENT_WINDOW_DECAY = 0.97
RECENT_SHARE_DEFAULT = 0.68
LONG_SHARE_DEFAULT = 0.32
RECENT_SHARE_WHEN_STALE = 0.84
LONG_SHARE_WHEN_STALE = 0.16
RECENT_SHARE_WHEN_ALIGNED = 0.60
LONG_SHARE_WHEN_ALIGNED = 0.40
STRONG_DISAGREEMENT = 0.18
MILD_DISAGREEMENT = 0.08


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _amount_band(value: int) -> str:
    if value <= 15:
        return "LOW"
    if value <= 155:
        return "MID"
    if value <= 315:
        return "HIGH"
    return "DEEP"


def _extract_cycle_counter(text: object) -> Optional[int]:
    raw_text = str(text or "")
    marker = "counter="
    start = raw_text.rfind(marker)
    if start < 0:
        return None

    start += len(marker)
    digits: List[str] = []
    while start < len(raw_text) and raw_text[start].isdigit():
        digits.append(raw_text[start])
        start += 1

    if not digits:
        return None
    return int("".join(digits))


def _parse_result_boxes(value: object) -> Tuple[str, ...]:
    raw_boxes = [part.strip() for part in str(value or "").split("/") if part.strip()]
    return tuple(raw_boxes[:3])


def _boxes_signature(boxes: Tuple[str, ...]) -> str:
    return "/".join(boxes)


def _boxes_mix_signature(boxes: Tuple[str, ...]) -> str:
    counts = Counter(boxes)
    return "|".join(f"{color}x{counts[color]}" for color in sorted(counts))


def _phase_for_counter(counter: Optional[int]) -> str:
    if counter is None:
        return "UNKNOWN"
    for label, start, end in PHASE_LABELS:
        if start <= counter <= end:
            return label
    return "UNKNOWN"


def _skip_reason_family(text: object) -> str:
    raw_text = str(text or "").strip()
    if not raw_text:
        return "NONE"

    parts = raw_text.split("|")
    if not parts:
        return raw_text
    if parts[0] == "SKIP":
        return "|".join(parts[:3])
    return parts[0]


def _window_weight_sequence(window_count: int, decay: float, floor: float) -> List[float]:
    if window_count <= 0:
        return []

    raw_weights = [decay ** (window_count - 1 - index) for index in range(window_count)]
    max_weight = max(raw_weights) if raw_weights else 1.0
    normalized = [max(floor, value / max_weight) for value in raw_weights]
    return normalized


@dataclass
class HistoryCsvRow:
    result: str
    result_boxes: Tuple[str, ...]
    regime: str
    amount: int
    profit_change: float
    is_win: bool
    round_label: str
    skip_reason: str
    cycle_counter: Optional[int]
    cycle_phase: str = "UNKNOWN"
    window_index: int = 0


@dataclass(frozen=True)
class HistoryRecord:
    regime: str
    cycle_phase: str
    amount: int
    profit_change: float
    is_win: bool


@dataclass(frozen=True)
class AggregateStats:
    count: float
    wins: float
    profit: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.count if self.count else 0.0

    @property
    def avg_profit(self) -> float:
        return self.profit / self.count if self.count else 0.0


@dataclass(frozen=True)
class TransitionStats:
    count: float
    presence_counts: Dict[str, float]
    total_hits: Dict[str, float]

    def hit_rate(self, color: str) -> float:
        return self.presence_counts.get(color, 0.0) / self.count if self.count else 0.0

    def avg_hits(self, color: str) -> float:
        return self.total_hits.get(color, 0.0) / self.count if self.count else 0.0

    def top_color(self) -> Optional[str]:
        if not self.total_hits:
            return None
        return max(
            self.total_hits.items(),
            key=lambda item: (item[1], self.presence_counts.get(item[0], 0.0), item[0]),
        )[0]


@dataclass(frozen=True)
class SkipReasonStats:
    count: float
    repeated_next_count: float
    unique_color_total: float

    @property
    def repeated_next_rate(self) -> float:
        return self.repeated_next_count / self.count if self.count else 0.0

    @property
    def avg_unique_colors(self) -> float:
        return self.unique_color_total / self.count if self.count else 0.0


@dataclass(frozen=True)
class ThresholdRecommendation:
    strategy_probability_window: int = 0
    strategy_probability_min_samples: int = 0
    strategy_min_hit_probability: float = 0.0
    strategy_min_expected_value: float = 0.0
    strategy_min_probability_edge: float = 0.0
    strategy_probability_board_weight: float = 0.0
    settled_bets: int = 0
    estimated_profit: float = 0.0

    def to_config_updates(self) -> Dict[str, object]:
        return {}


@dataclass(frozen=True)
class HistoryStrategyModel:
    source_path: str
    source_mtime: float
    settled_bets: int
    hit_rate: float
    summed_profit: float
    recommendation: ThresholdRecommendation
    summary: str
    basis: str
    dangerous_amounts: Tuple[int, ...]
    complete_windows: int
    transition_pairs: int
    transition_exact: Dict[Tuple[str, str, str], TransitionStats]
    transition_mix: Dict[Tuple[str, str, str], TransitionStats]
    transition_phase: Dict[Tuple[str, str], TransitionStats]
    amount_recovery: Dict[Tuple[str, str, str], AggregateStats]
    skip_reason_outcomes: Dict[str, SkipReasonStats]
    recent_window_count: int
    transition_exact_recent: Dict[Tuple[str, str, str], TransitionStats]
    transition_mix_recent: Dict[Tuple[str, str, str], TransitionStats]
    transition_phase_recent: Dict[Tuple[str, str], TransitionStats]
    transition_exact_long: Dict[Tuple[str, str, str], TransitionStats]
    transition_mix_long: Dict[Tuple[str, str, str], TransitionStats]
    transition_phase_long: Dict[Tuple[str, str], TransitionStats]
    amount_recovery_recent: Dict[Tuple[str, str, str], AggregateStats]
    amount_recovery_long: Dict[Tuple[str, str, str], AggregateStats]

    def coordinated_probability_thresholds(
        self,
        base_thresholds: Dict[str, float],
        regime: str,
        amount: int,
        cycle_counter: Optional[int] = None,
    ) -> Dict[str, float]:
        del regime, amount, cycle_counter
        return dict(base_thresholds)

    def _blend_transition_stats(
        self,
        recent_stats: Optional[TransitionStats],
        long_stats: Optional[TransitionStats],
        candidate_color: str,
    ) -> Optional[Tuple[float, float, float, str]]:
        if not recent_stats and not long_stats:
            return None

        if recent_stats and not long_stats:
            return (
                recent_stats.count,
                recent_stats.hit_rate(candidate_color),
                recent_stats.avg_hits(candidate_color),
                f"recent:{recent_stats.count:.0f}",
            )

        if long_stats and not recent_stats:
            return (
                long_stats.count,
                long_stats.hit_rate(candidate_color),
                long_stats.avg_hits(candidate_color),
                f"long:{long_stats.count:.0f}",
            )

        assert recent_stats is not None and long_stats is not None
        recent_hit = recent_stats.hit_rate(candidate_color)
        recent_avg = recent_stats.avg_hits(candidate_color)
        long_hit = long_stats.hit_rate(candidate_color)
        long_avg = long_stats.avg_hits(candidate_color)

        recent_share = RECENT_SHARE_DEFAULT
        long_share = LONG_SHARE_DEFAULT
        disagreement = abs(recent_hit - long_hit) + (0.45 * abs(recent_avg - long_avg))
        if disagreement >= STRONG_DISAGREEMENT:
            recent_share = RECENT_SHARE_WHEN_STALE
            long_share = LONG_SHARE_WHEN_STALE
        elif disagreement <= MILD_DISAGREEMENT:
            recent_share = RECENT_SHARE_WHEN_ALIGNED
            long_share = LONG_SHARE_WHEN_ALIGNED

        total_share = recent_share + long_share
        blended_support = (recent_stats.count * recent_share) + (long_stats.count * long_share)
        blended_hit = ((recent_hit * recent_share) + (long_hit * long_share)) / total_share
        blended_avg = ((recent_avg * recent_share) + (long_avg * long_share)) / total_share
        source = f"recent:{recent_stats.count:.0f}/long:{long_stats.count:.0f}"
        return blended_support, blended_hit, blended_avg, source

    def _lookup_amount_stats(
        self,
        source_map: Dict[Tuple[str, str, str], AggregateStats],
        regime: str,
        phase: str,
        amount_band: str,
    ) -> Optional[AggregateStats]:
        keys = (
            (regime, phase, amount_band),
            ("*", phase, amount_band),
            ("*", "ANY", amount_band),
        )
        return next((source_map.get(key) for key in keys if source_map.get(key)), None)

    def _blend_amount_stats(
        self,
        recent_stats: Optional[AggregateStats],
        long_stats: Optional[AggregateStats],
    ) -> Optional[AggregateStats]:
        if not recent_stats and not long_stats:
            return None
        if recent_stats and not long_stats:
            return recent_stats
        if long_stats and not recent_stats:
            return long_stats

        assert recent_stats is not None and long_stats is not None
        recent_share = 0.70
        long_share = 0.30
        if (recent_stats.avg_profit >= 0) != (long_stats.avg_profit >= 0):
            recent_share = 0.82
            long_share = 0.18
        elif abs(recent_stats.win_rate - long_stats.win_rate) <= 0.06:
            recent_share = 0.62
            long_share = 0.38

        total_share = recent_share + long_share
        blended_count = (recent_stats.count * recent_share) + (long_stats.count * long_share)
        blended_wins = (recent_stats.wins * recent_share) + (long_stats.wins * long_share)
        blended_profit = (
            (recent_stats.avg_profit * recent_share) + (long_stats.avg_profit * long_share)
        ) * blended_count / total_share
        return AggregateStats(count=blended_count, wins=blended_wins, profit=blended_profit)

    def evaluate(
        self,
        regime: str,
        decision_probability: float,
        expected_value: float,
        probability_edge: float,
        probability_samples: int,
        amount: int,
        candidate_color: Optional[str] = None,
        result_boxes: Optional[Tuple[str, ...]] = None,
        cycle_counter: Optional[int] = None,
    ) -> Dict[str, object]:
        del decision_probability, expected_value, probability_edge, probability_samples

        phase = _phase_for_counter(cycle_counter)
        amount_band = _amount_band(amount)

        if not candidate_color or not result_boxes:
            return {
                "allow": True,
                "support": 0.0,
                "estimated_profit": 0.0,
                "estimated_win_rate": 0.0,
                "transition_support": 0.0,
                "transition_hit_rate": 0.0,
                "transition_avg_hits": 0.0,
                "message": "history transition gate missing candidate color or Result Boxes",
                "fallback": True,
            }

        signature = _boxes_signature(result_boxes)
        mix_signature = _boxes_mix_signature(result_boxes)
        transition_specs = [
            (
                (regime, phase, signature),
                self.transition_exact_recent,
                self.transition_exact_long,
                1.95,
                3.0,
                7.0,
                "exact-regime",
            ),
            (
                (regime, phase, mix_signature),
                self.transition_mix_recent,
                self.transition_mix_long,
                1.55,
                4.0,
                9.0,
                "mix-regime",
            ),
            (
                ("*", phase, signature),
                self.transition_exact_recent,
                self.transition_exact_long,
                1.18,
                5.0,
                12.0,
                "exact-phase",
            ),
            (
                ("*", phase, mix_signature),
                self.transition_mix_recent,
                self.transition_mix_long,
                0.98,
                6.0,
                16.0,
                "mix-phase",
            ),
            (
                (regime, phase),
                self.transition_phase_recent,
                self.transition_phase_long,
                0.78,
                8.0,
                22.0,
                "phase-regime",
            ),
            (
                ("*", phase),
                self.transition_phase_recent,
                self.transition_phase_long,
                0.58,
                10.0,
                30.0,
                "phase-all",
            ),
        ]

        weighted_hit_rate = 0.0
        weighted_avg_hits = 0.0
        total_weight = 0.0
        support = 0.0
        transition_sources: List[str] = []

        for key, recent_map, long_map, weight, recent_min, long_min, label in transition_specs:
            recent_stats = recent_map.get(key)
            if recent_stats and recent_stats.count < recent_min:
                recent_stats = None
            long_stats = long_map.get(key)
            if long_stats and long_stats.count < long_min:
                long_stats = None

            blended = self._blend_transition_stats(recent_stats, long_stats, candidate_color)
            if not blended:
                continue

            blended_support, hit_rate, avg_hits, source_note = blended
            confidence_weight = min(1.75, blended_support / 18.0) if blended_support else 0.0
            effective_weight = weight * confidence_weight
            weighted_hit_rate += hit_rate * effective_weight
            weighted_avg_hits += avg_hits * effective_weight
            total_weight += effective_weight
            support += blended_support * weight
            transition_sources.append(f"{label}:{source_note}")

        transition_hit_rate = weighted_hit_rate / total_weight if total_weight else 0.0
        transition_avg_hits = weighted_avg_hits / total_weight if total_weight else 0.0

        recent_amount_stats = self._lookup_amount_stats(
            self.amount_recovery_recent,
            regime,
            phase,
            amount_band,
        )
        long_amount_stats = self._lookup_amount_stats(
            self.amount_recovery_long,
            regime,
            phase,
            amount_band,
        )
        amount_stats = self._blend_amount_stats(recent_amount_stats, long_amount_stats)

        amount_message = "amount recovery unavailable"
        amount_block = False
        amount_profit = 0.0
        amount_win_rate = 0.0
        if amount_stats:
            amount_profit = amount_stats.avg_profit
            amount_win_rate = amount_stats.win_rate
            amount_message = (
                f"amount {amount_band} {amount_stats.count:.0f} weighted bets, "
                f"avg {amount_profit:+.0f}, win {amount_win_rate * 100:.1f}%"
            )
            if regime == "RANGE" and amount_band == "DEEP":
                if amount_stats.count >= 3.0 and (amount_profit <= 0 or amount_win_rate < 0.44):
                    amount_block = True
            elif amount_stats.count >= 5.0 and amount_profit < 0 and amount_win_rate < 0.38:
                amount_block = True

        min_support = 24.0
        min_hit_rate = 0.36
        min_avg_hits = 0.48
        weak_block_support = 38.0
        weak_block_hit = 0.34
        weak_block_avg = 0.45

        if regime == "CHAOS":
            min_support = 18.0
            min_hit_rate = 0.34
            min_avg_hits = 0.46
            weak_block_support = 28.0
            weak_block_hit = 0.33
            weak_block_avg = 0.43
        elif regime == "RANGE":
            min_support = 40.0
            min_hit_rate = 0.42
            min_avg_hits = 0.52
            weak_block_support = 54.0
            weak_block_hit = 0.40
            weak_block_avg = 0.50

            if phase in {"EARLY", "MID"}:
                min_support = 52.0
                min_hit_rate = 0.45
                min_avg_hits = 0.55
                weak_block_support = 66.0
                weak_block_hit = 0.43
                weak_block_avg = 0.52

            if amount_band == "DEEP":
                min_support += 12.0
                min_hit_rate += 0.03
                min_avg_hits += 0.04
                weak_block_support += 10.0
                weak_block_hit += 0.02
                weak_block_avg += 0.03

        if total_weight <= 0:
            fallback_message = (
                f"transition support too thin for {candidate_color} at {phase} from {signature}; {amount_message}"
            )
            return {
                "allow": not amount_block,
                "support": 0.0,
                "estimated_profit": amount_profit,
                "estimated_win_rate": amount_win_rate,
                "transition_support": 0.0,
                "transition_hit_rate": 0.0,
                "transition_avg_hits": 0.0,
                "message": fallback_message,
                "fallback": True,
            }

        estimated_profit = amount_profit
        estimated_win_rate = amount_win_rate
        allow = support >= min_support and transition_hit_rate >= min_hit_rate and transition_avg_hits >= min_avg_hits

        if support < min_support:
            allow = not amount_block
        if amount_block:
            allow = False
        if support >= weak_block_support and transition_hit_rate < weak_block_hit and transition_avg_hits < weak_block_avg:
            allow = False

        message = (
            f"ensemble support {support:.0f}, next-hit {transition_hit_rate * 100:.1f}%, "
            f"avg hits {transition_avg_hits:.2f}, sources {', '.join(transition_sources[:3]) or 'none'}, "
            f"{amount_message}"
        )

        return {
            "allow": allow,
            "support": support,
            "estimated_profit": estimated_profit,
            "estimated_win_rate": estimated_win_rate,
            "transition_support": support,
            "transition_hit_rate": transition_hit_rate,
            "transition_avg_hits": transition_avg_hits,
            "message": message,
            "fallback": False,
        }

    def recommend_positive_color(
        self,
        regime: str,
        amount: int,
        candidate_colors: Tuple[str, ...],
        preferred_color: Optional[str] = None,
        result_boxes: Optional[Tuple[str, ...]] = None,
        cycle_counter: Optional[int] = None,
    ) -> Dict[str, object]:
        evaluations: Dict[str, Dict[str, object]] = {}
        for color in candidate_colors:
            evaluations[color] = self.evaluate(
                regime=regime,
                decision_probability=0.0,
                expected_value=0.0,
                probability_edge=0.0,
                probability_samples=0,
                amount=amount,
                candidate_color=color,
                result_boxes=result_boxes,
                cycle_counter=cycle_counter,
            )

        preferred_evaluation = evaluations.get(preferred_color or "")
        strong_alternatives: List[Tuple[float, float, float, str, Dict[str, object]]] = []
        for color, evaluation in evaluations.items():
            if color == preferred_color:
                continue
            if not evaluation.get("allow", False):
                continue
            support = float(evaluation.get("support", 0.0))
            avg_hits = float(evaluation.get("transition_avg_hits", 0.0))
            hit_rate = float(evaluation.get("transition_hit_rate", 0.0))
            if support < 55.0 or avg_hits < 0.54 or hit_rate < 0.41:
                continue
            strong_alternatives.append((avg_hits, hit_rate, support, color, evaluation))

        strong_alternatives.sort(reverse=True)
        if preferred_evaluation and preferred_evaluation.get("allow", False):
            return {
                "selected_color": preferred_color,
                "selected_evaluation": preferred_evaluation,
                "preferred_evaluation": preferred_evaluation,
                "override": False,
                "message": str(preferred_evaluation.get("message", "")),
            }

        if strong_alternatives:
            _, _, _, selected_color, selected_evaluation = strong_alternatives[0]
            return {
                "selected_color": selected_color,
                "selected_evaluation": selected_evaluation,
                "preferred_evaluation": preferred_evaluation,
                "override": selected_color != preferred_color,
                "message": (
                    f"history positive override {preferred_color or 'None'} -> {selected_color}; "
                    f"{selected_evaluation.get('message', '')}"
                ),
            }

        fallback_evaluation = preferred_evaluation or {
            "allow": False,
            "message": "history positive override unavailable",
            "support": 0.0,
            "estimated_profit": 0.0,
            "estimated_win_rate": 0.0,
            "transition_support": 0.0,
            "transition_hit_rate": 0.0,
            "transition_avg_hits": 0.0,
            "fallback": True,
        }
        return {
            "selected_color": preferred_color,
            "selected_evaluation": fallback_evaluation,
            "preferred_evaluation": preferred_evaluation,
            "override": False,
            "message": str(fallback_evaluation.get("message", "")),
        }


def _parse_history_rows(rows: Iterable[Dict[str, str]]) -> List[HistoryCsvRow]:
    parsed_rows: List[HistoryCsvRow] = []
    for row in rows:
        result = str(row.get("Result") or "").strip()
        result_boxes = _parse_result_boxes(row.get("Result Boxes") or row.get("C1 Result") or "")
        parsed_rows.append(
            HistoryCsvRow(
                result=result,
                result_boxes=result_boxes,
                regime=str(row.get("Regime") or "DATA"),
                amount=_to_int(row.get("Amount")),
                profit_change=_to_float(row.get("Profit Change")),
                is_win=result.startswith("WIN"),
                round_label=str(row.get("Round") or ""),
                skip_reason=str(row.get("Skip Reason") or ""),
                cycle_counter=_extract_cycle_counter(row.get("Skip Reason")),
            )
        )
    return parsed_rows


def _is_window_start(row: HistoryCsvRow) -> bool:
    return row.result == "WARMUP" and row.cycle_counter == 1


def _is_complete_window(window_rows: List[HistoryCsvRow]) -> bool:
    if len(window_rows) != WINDOW_SIZE:
        return False

    if any(not row.result_boxes for row in window_rows):
        return False

    first_rows = window_rows[:WARMUP_COUNT]
    if any(row.result != "WARMUP" for row in first_rows):
        return False
    if [row.cycle_counter for row in first_rows] != list(range(1, WARMUP_COUNT + 1)):
        return False

    if sum(1 for row in window_rows if row.result == "WARMUP") != WARMUP_COUNT:
        return False

    cooldown_start = next((index for index, row in enumerate(window_rows) if row.result == "COOLDOWN"), None)
    if cooldown_start is None:
        return False

    cooldown_rows = window_rows[cooldown_start:]
    if any(row.result != "COOLDOWN" for row in cooldown_rows):
        return False
    if len(cooldown_rows) not in VALID_COOLDOWN_COUNTS:
        return False

    expected_counters = list(range(91, 91 + len(cooldown_rows)))
    if [row.cycle_counter for row in cooldown_rows] != expected_counters:
        return False

    return True


def _collect_complete_windows(rows: List[HistoryCsvRow]) -> List[Tuple[HistoryCsvRow, ...]]:
    start_indexes = [index for index, row in enumerate(rows) if _is_window_start(row)]
    windows: List[Tuple[HistoryCsvRow, ...]] = []

    for position, start_index in enumerate(start_indexes):
        end_index = start_indexes[position + 1] if position + 1 < len(start_indexes) else len(rows)
        candidate = rows[start_index:end_index]
        if not _is_complete_window(candidate):
            continue

        window_number = len(windows) + 1
        for cycle_position, row in enumerate(candidate, start=1):
            row.cycle_counter = cycle_position
            row.cycle_phase = _phase_for_counter(cycle_position)
            row.window_index = window_number

        windows.append(tuple(candidate))

    return windows


def _parse_settled_rows(rows: Iterable[HistoryCsvRow]) -> List[HistoryRecord]:
    records: List[HistoryRecord] = []
    for row in rows:
        if row.result not in SETTLED_RESULTS:
            continue
        records.append(
            HistoryRecord(
                regime=row.regime,
                cycle_phase=row.cycle_phase,
                amount=row.amount,
                profit_change=row.profit_change,
                is_win=row.is_win,
            )
        )
    return records


def _freeze_transition_stats(
    raw: Dict[Tuple[str, ...], Dict[str, object]],
) -> Dict[Tuple[str, ...], TransitionStats]:
    frozen: Dict[Tuple[str, ...], TransitionStats] = {}
    for key, bucket in raw.items():
        frozen[key] = TransitionStats(
            count=float(bucket["count"]),
            presence_counts={color: float(value) for color, value in bucket["presence"].items()},
            total_hits={color: float(value) for color, value in bucket["hits"].items()},
        )
    return frozen


def _build_transition_models_weighted(
    windows: Iterable[Tuple[HistoryCsvRow, ...]],
    window_weights: Iterable[float],
) -> Tuple[
    Dict[Tuple[str, str, str], TransitionStats],
    Dict[Tuple[str, str, str], TransitionStats],
    Dict[Tuple[str, str], TransitionStats],
    int,
]:
    exact_raw: Dict[Tuple[str, ...], Dict[str, object]] = defaultdict(
        lambda: {"count": 0.0, "presence": defaultdict(float), "hits": defaultdict(float)}
    )
    mix_raw: Dict[Tuple[str, ...], Dict[str, object]] = defaultdict(
        lambda: {"count": 0.0, "presence": defaultdict(float), "hits": defaultdict(float)}
    )
    phase_raw: Dict[Tuple[str, ...], Dict[str, object]] = defaultdict(
        lambda: {"count": 0.0, "presence": defaultdict(float), "hits": defaultdict(float)}
    )
    pair_count = 0

    for window, window_weight in zip(windows, window_weights):
        for current_row, next_row in zip(window, window[1:]):
            if not current_row.result_boxes or not next_row.result_boxes:
                continue

            pair_count += 1
            next_counts = Counter(next_row.result_boxes)
            exact_key = _boxes_signature(current_row.result_boxes)
            mix_key = _boxes_mix_signature(current_row.result_boxes)
            keyed_targets = (
                (exact_raw, (current_row.regime, current_row.cycle_phase, exact_key)),
                (exact_raw, ("*", current_row.cycle_phase, exact_key)),
                (mix_raw, (current_row.regime, current_row.cycle_phase, mix_key)),
                (mix_raw, ("*", current_row.cycle_phase, mix_key)),
                (phase_raw, (current_row.regime, current_row.cycle_phase)),
                (phase_raw, ("*", current_row.cycle_phase)),
            )

            for target, key in keyed_targets:
                bucket = target[key]
                bucket["count"] += window_weight
                for color, hits in next_counts.items():
                    bucket["presence"][color] += window_weight
                    bucket["hits"][color] += hits * window_weight

    return (
        _freeze_transition_stats(exact_raw),
        _freeze_transition_stats(mix_raw),
        _freeze_transition_stats(phase_raw),
        pair_count,
    )


def _build_amount_recovery_weighted(
    windows: Iterable[Tuple[HistoryCsvRow, ...]],
    window_weights: Iterable[float],
) -> Dict[Tuple[str, str, str], AggregateStats]:
    raw: Dict[Tuple[str, ...], List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    def bump(key: Tuple[str, str, str], row: HistoryCsvRow, weight: float):
        bucket = raw[key]
        bucket[0] += weight
        bucket[1] += weight if row.is_win else 0.0
        bucket[2] += row.profit_change * weight

    for window, window_weight in zip(windows, window_weights):
        for row in window:
            if row.result not in SETTLED_RESULTS:
                continue
            band = _amount_band(row.amount)
            keys = (
                (row.regime, row.cycle_phase, band),
                ("*", row.cycle_phase, band),
                ("*", "ANY", band),
            )
            for key in keys:
                bump(key, row, window_weight)

    return {
        key: AggregateStats(count=values[0], wins=values[1], profit=values[2])
        for key, values in raw.items()
    }


def _build_skip_reason_outcomes(
    windows: Iterable[Tuple[HistoryCsvRow, ...]],
) -> Dict[str, SkipReasonStats]:
    raw: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    for window in windows:
        for current_row, next_row in zip(window, window[1:]):
            if current_row.result not in {"SKIP", "WARMUP", "COOLDOWN"}:
                continue

            family = _skip_reason_family(current_row.skip_reason)
            bucket = raw[family]
            bucket[0] += 1.0
            bucket[1] += 1.0 if len(set(next_row.result_boxes)) < len(next_row.result_boxes) else 0.0
            bucket[2] += float(len(set(next_row.result_boxes)))

    return {
        key: SkipReasonStats(
            count=values[0],
            repeated_next_count=values[1],
            unique_color_total=values[2],
        )
        for key, values in raw.items()
    }


def build_history_strategy_model(csv_path: Path, window_limit: int = 0) -> HistoryStrategyModel:
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.DictReader(handle))

    parsed_rows = _parse_history_rows(raw_rows)
    all_complete_windows = _collect_complete_windows(parsed_rows)
    available_complete_windows = len(all_complete_windows)
    requested_window_limit = max(0, int(window_limit))
    if requested_window_limit > 0 and available_complete_windows > requested_window_limit:
        complete_windows = all_complete_windows[-requested_window_limit:]
    else:
        complete_windows = all_complete_windows

    recent_window_count = min(RECENT_WINDOW_CAP, len(complete_windows))
    recent_windows = complete_windows[-recent_window_count:] if recent_window_count else []
    long_windows = list(complete_windows)
    long_weights = _window_weight_sequence(len(long_windows), LONG_WINDOW_DECAY, floor=0.35)
    recent_weights = _window_weight_sequence(len(recent_windows), RECENT_WINDOW_DECAY, floor=0.75)

    window_rows = [row for window in complete_windows for row in window]
    records = _parse_settled_rows(window_rows)

    settled_bets = len(records)
    hit_rate = sum(1 for record in records if record.is_win) / settled_bets if settled_bets else 0.0
    summed_profit = sum(record.profit_change for record in records)

    transition_exact_long, transition_mix_long, transition_phase_long, transition_pairs = _build_transition_models_weighted(
        long_windows,
        long_weights,
    )
    transition_exact_recent, transition_mix_recent, transition_phase_recent, _ = _build_transition_models_weighted(
        recent_windows,
        recent_weights,
    )
    amount_recovery_long = _build_amount_recovery_weighted(long_windows, long_weights)
    amount_recovery_recent = _build_amount_recovery_weighted(recent_windows, recent_weights)
    skip_reason_outcomes = _build_skip_reason_outcomes(complete_windows)

    amount_profit: Dict[int, float] = defaultdict(float)
    amount_count: Dict[int, int] = defaultdict(int)
    regime_profit: Dict[str, float] = defaultdict(float)
    for record in records:
        amount_profit[record.amount] += record.profit_change
        amount_count[record.amount] += 1
        regime_profit[record.regime] += record.profit_change

    dangerous_amounts = tuple(
        amount
        for amount, profit in sorted(amount_profit.items())
        if amount >= 315 and amount_count[amount] >= 3 and profit < 0
    )
    worst_regime = min(regime_profit.items(), key=lambda item: item[1])[0] if regime_profit else "DATA"
    recommendation = ThresholdRecommendation(
        settled_bets=settled_bets,
        estimated_profit=summed_profit,
    )

    if not complete_windows:
        summary = "History Analysis: No complete 99-row windows found yet."
        basis = "History Basis: Need complete 99-row windows"
        if requested_window_limit > 0 and available_complete_windows <= 0:
            basis += f" | Requested {requested_window_limit}, available 0"
    else:
        if requested_window_limit > 0:
            if requested_window_limit > available_complete_windows:
                window_scope_text = (
                    f"requested {requested_window_limit}, using {len(complete_windows)} available complete windows"
                )
            else:
                window_scope_text = f"using last {len(complete_windows)} complete windows"
        else:
            window_scope_text = f"{len(complete_windows)} complete windows"

        summary = (
            f"History Analysis: {window_scope_text}, {settled_bets} settled bets, "
            f"{summed_profit:+.0f} summed profit, {transition_pairs} Result Boxes transitions. "
            f"Recent boost: last {recent_window_count} windows, long prior decay {LONG_WINDOW_DECAY:.2f}. "
            f"Main leak: {worst_regime}, weak deep stages "
            f"{', '.join(str(value) for value in dangerous_amounts[:4]) if dangerous_amounts else 'none'}."
        )
        basis = (
            "History Basis: weighted recent+long Result Boxes transitions, recency decay, cycle phase, amount recovery, skip behavior"
        )
        if requested_window_limit > 0 and requested_window_limit > available_complete_windows:
            basis += (
                f" | Requested {requested_window_limit} windows exceeded valid complete windows; using {len(complete_windows)}"
            )
        elif requested_window_limit > 0:
            basis += f" | Window cap: last {len(complete_windows)} complete windows"
        else:
            basis += " | Window cap: all complete windows"
        basis += f" | Recent ensemble slice: last {recent_window_count}"

    return HistoryStrategyModel(
        source_path=str(csv_path),
        source_mtime=csv_path.stat().st_mtime,
        settled_bets=settled_bets,
        hit_rate=hit_rate,
        summed_profit=summed_profit,
        recommendation=recommendation,
        summary=summary,
        basis=basis,
        dangerous_amounts=dangerous_amounts,
        complete_windows=len(complete_windows),
        transition_pairs=transition_pairs,
        transition_exact=transition_exact_long,
        transition_mix=transition_mix_long,
        transition_phase=transition_phase_long,
        amount_recovery=amount_recovery_long,
        skip_reason_outcomes=skip_reason_outcomes,
        recent_window_count=recent_window_count,
        transition_exact_recent=transition_exact_recent,
        transition_mix_recent=transition_mix_recent,
        transition_phase_recent=transition_phase_recent,
        transition_exact_long=transition_exact_long,
        transition_mix_long=transition_mix_long,
        transition_phase_long=transition_phase_long,
        amount_recovery_recent=amount_recovery_recent,
        amount_recovery_long=amount_recovery_long,
    )
