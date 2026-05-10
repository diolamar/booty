import tkinter as tk
from tkinter import messagebox, ttk
import pyautogui
import json
import random
import time
import threading
from pathlib import Path
from PIL import Image, ImageGrab, ImageTk
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum
import logging
from contextlib import contextmanager
from datetime import datetime
from collections import deque
import math

from button_actions import (
    exit_app as exit_app_action,
    start_auto_bet,
    start_calibration as start_calibration_action,
    start_monitoring as start_monitoring_action,
    start_random_betting as start_random_betting_action,
    toggle_pause as toggle_pause_action,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============= Configuration =============
@dataclass
class BettingStrategy:
    """Configuration for betting strategy"""
    base_bet: str = "Bet 10"  # Default bet amount
    bet_progression: Tuple[str, ...] = ("Bet 5", "Bet 10", "Bet 20", "Bet 50")
    increase_on_win: bool = True
    increase_on_loss: bool = False
    reset_on_win: bool = True
    max_consecutive_losses: int = 3
    win_streak_bonus: bool = True
    
@dataclass
class AppConfig:
    """Centralized configuration with validation"""
    total_columns: int = 7
    boxes_per_column: int = 3
    color_sample_radius: int = 3
    color_match_max_score: float = 18000.0
    blank_match_max_score: float = 12000.0
    automation_loop_idle_seconds: float = 0.05
    monitor_captures_per_second: int = 5
    monitor_blank_allowance_seconds: float = 2.0
    monitor_idle_seconds: float = 20.0
    monitor_capture_padding: int = 30
    click_interval_seconds: float = 3.0
    calibration_timeout_seconds: float = 300.0
    column_check_interval: float = 0.5
    max_unknown_retries: int = 10
    unknown_retry_delay: float = 0.3
    black_detection_threshold: int = 45
    
    # Color labels
    color_labels: Tuple[str, ...] = ("Yellow", "White", "Pink", "Blue", "Red", "Green")
    blank_color_label: str = "Blank Color"
    bet_color_labels: Tuple[str, ...] = (
        "Bet Yellow",
        "Bet White",
        "Bet Pink",
        "Bet Blue",
        "Bet Red",
        "Bet Green",
    )
    bet_labels: Tuple[str, ...] = ("Bet 5", "Bet 10", "Bet 20", "Bet 50")
    action_labels: Tuple[str, ...] = ("X2",)
    
    # Betting strategy
    betting_strategy: BettingStrategy = field(default_factory=BettingStrategy)
    
    def __post_init__(self):
        self.extra_calibration_labels = (
            self.color_labels + 
            self.bet_color_labels +
            self.bet_labels + 
            self.action_labels
        )
        self.reference_color_labels = self.color_labels
        self.total_calibration_points = (
            (self.total_columns * self.boxes_per_column) + 
            len(self.extra_calibration_labels)
        )
    
    @property
    def monitor_interval_seconds(self) -> float:
        return 1.0 / self.monitor_captures_per_second

    def get_bet_color_label(self, color_name: str) -> str:
        return f"Bet {color_name}"
    
    def to_dict(self) -> dict:
        data = asdict(self)
        data['betting_strategy'] = asdict(self.betting_strategy)
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AppConfig':
        normalized = dict(data)
        tuple_fields = ("color_labels", "bet_color_labels", "bet_labels", "action_labels")
        
        for field_name in tuple_fields:
            field_value = normalized.get(field_name)
            if isinstance(field_value, list):
                normalized[field_name] = tuple(field_value)
        
        if 'betting_strategy' in normalized and isinstance(normalized['betting_strategy'], dict):
            betting_data = normalized.pop('betting_strategy')
            normalized['betting_strategy'] = BettingStrategy(**betting_data)
        
        return cls(**normalized)


class AutomationState(Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    WAITING_FOR_COLUMNS = "waiting_for_columns"
    ANALYZING = "analyzing"
    CLICKING = "clicking"
    PAUSED = "paused"
    CALIBRATING = "calibrating"
    ERROR = "error"
    RANDOM_BETTING = "random_betting"


@dataclass
class ColumnAnalysis:
    column_index: int
    boxes: List[str]
    is_full: bool
    has_unknown: bool
    box_debug: List[str] = field(default_factory=list)
    winning_color: Optional[str] = None
    is_winning_column: bool = False
    
    @property
    def all_boxes_known(self) -> bool:
        return not self.has_unknown and self.is_full
    
    @property
    def display_text(self) -> str:
        return f"C{self.column_index}: {'/'.join(self.boxes)}"


@dataclass
class GameState:
    timestamp: float
    columns: List[ColumnAnalysis]
    all_columns_full: bool
    any_unknown: bool
    blank_detected: bool
    recommended_bet: str
    recommended_color: Optional[str]
    confidence_score: float
    
    @property
    def is_ready_for_action(self) -> bool:
        return (
            self.all_columns_full
            and not self.any_unknown
            and not self.blank_detected
            and not self.has_uniform_column_pattern
        )
    
    @property
    def winning_column_color(self) -> Optional[str]:
        if self.columns and self.columns[0].all_boxes_known:
            return self.columns[0].boxes[0] if self.columns[0].boxes else None
        return None

    @property
    def winning_column_boxes(self) -> List[str]:
        if self.columns and self.columns[0].all_boxes_known:
            return list(self.columns[0].boxes)
        return []

    @property
    def has_uniform_column_pattern(self) -> bool:
        if not self.columns:
            return False
        if any(not col.all_boxes_known for col in self.columns):
            return False
        first_pattern = tuple(self.columns[0].boxes)
        return all(tuple(col.boxes) == first_pattern for col in self.columns[1:])


@dataclass
class BettingStats:
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    current_streak: int = 0
    last_bet_amount: str = "Bet 10"
    last_result: Optional[str] = None
    history: List[Dict] = field(default_factory=list)
    
    def record_bet(self, amount: str, color: str):
        self.last_bet_amount = amount
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "amount": amount,
            "color": color,
            "result": None
        })

    def has_pending_bet(self) -> bool:
        return any(entry.get("result") is None for entry in self.history)

    def get_latest_pending_bet(self) -> Optional[Dict]:
        for entry in reversed(self.history):
            if entry.get("result") is None:
                return entry
        return None
    
    def record_result(self, won: bool, color: str):
        pending_bet = self.get_latest_pending_bet()
        if pending_bet is None:
            return

        self.total_bets += 1

        if won:
            self.wins += 1
            self.consecutive_losses = 0
            self.consecutive_wins += 1
            self.current_streak = self.consecutive_wins if self.consecutive_wins > 0 else -self.consecutive_losses
            self.last_result = "WIN"
        else:
            self.losses += 1
            self.consecutive_wins = 0
            self.consecutive_losses += 1
            self.current_streak = -self.consecutive_losses
            self.last_result = "LOSS"
        
        pending_bet["result"] = "WIN" if won else "LOSS"
        pending_bet["streak"] = self.current_streak
    
    def get_win_rate(self) -> float:
        if self.total_bets == 0:
            return 0.0
        return (self.wins / self.total_bets) * 100
    
    def get_next_bet_amount(self, strategy: BettingStrategy) -> str:
        try:
            bet_index = strategy.bet_progression.index(self.last_bet_amount)
        except ValueError:
            bet_index = 1
        
        if self.last_result == "WIN" and strategy.increase_on_win:
            next_index = min(bet_index + 1, len(strategy.bet_progression) - 1)
            return strategy.bet_progression[next_index]
        elif self.last_result == "LOSS" and strategy.increase_on_loss:
            next_index = min(bet_index + 1, len(strategy.bet_progression) - 1)
            return strategy.bet_progression[next_index]
        elif self.last_result == "WIN" and strategy.reset_on_win:
            return strategy.base_bet
        else:
            return self.last_bet_amount


@dataclass
class CalibrationPoint:
    index: int
    name: str
    x: int
    y: int
    rgb_sample: Optional[Tuple[int, int, int]] = None
    
    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "rgb_sample": self.rgb_sample}
    
    @classmethod
    def from_dict(cls, index: int, name: str, data: dict) -> 'CalibrationPoint':
        return cls(
            index=index,
            name=name,
            x=data["x"],
            y=data["y"],
            rgb_sample=tuple(data["rgb_sample"]) if data.get("rgb_sample") else None
        )
    
    @property
    def coord(self) -> Tuple[int, int]:
        return (self.x, self.y)


@dataclass
class ColorMatchResult:
    color_name: str
    score: float
    rgb_value: Tuple[int, int, int]
    is_match: bool = True


class ThreadSafeState:
    def __init__(self):
        self._lock = threading.RLock()
        self._state = AutomationState.IDLE
        self._paused = False
        self._blank_detected_at: Optional[float] = None
        self._monitor_idle_until: float = 0.0
        self._last_status: str = ""
        self._last_column_colors: List[str] = []
        self._current_game_state: Optional[GameState] = None
        self._betting_stats = BettingStats()
        self._match_output_enabled = False
        self._last_resolved_c1_boxes: Tuple[str, ...] = tuple()
        self._waiting_for_result = False
    
    @property
    def state(self) -> AutomationState:
        with self._lock:
            return self._state
    
    @state.setter
    def state(self, value: AutomationState):
        with self._lock:
            self._state = value
            logger.info(f"State changed to: {value.value}")
    
    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused
    
    def toggle_pause(self):
        with self._lock:
            self._paused = not self._paused
            return self._paused
    
    def start_blank_timer(self):
        with self._lock:
            self._blank_detected_at = time.time()
    
    def reset_blank_timer(self):
        with self._lock:
            self._blank_detected_at = None
    
    def get_blank_elapsed(self) -> Optional[float]:
        with self._lock:
            if self._blank_detected_at is None:
                return None
            return time.time() - self._blank_detected_at
    
    def set_monitor_idle_until(self, seconds: float):
        with self._lock:
            self._monitor_idle_until = time.time() + seconds
    
    def get_monitor_idle_remaining(self) -> float:
        with self._lock:
            remaining = self._monitor_idle_until - time.time()
            return max(0, remaining)
    
    def update_status(self, status: str):
        with self._lock:
            self._last_status = status
    
    def get_status(self) -> str:
        with self._lock:
            return self._last_status
    
    def set_game_state(self, state: GameState):
        with self._lock:
            self._current_game_state = state
    
    def get_game_state(self) -> Optional[GameState]:
        with self._lock:
            return self._current_game_state
    
    def get_betting_stats(self) -> BettingStats:
        with self._lock:
            return self._betting_stats

    def set_last_resolved_c1_boxes(self, boxes: Tuple[str, ...]):
        with self._lock:
            self._last_resolved_c1_boxes = tuple(boxes)

    def get_last_resolved_c1_boxes(self) -> Tuple[str, ...]:
        with self._lock:
            return self._last_resolved_c1_boxes
    
    def set_waiting_for_result(self, waiting: bool):
        with self._lock:
            self._waiting_for_result = waiting
    
    def is_waiting_for_result(self) -> bool:
        with self._lock:
            return self._waiting_for_result

    def enable_match_output(self):
        with self._lock:
            self._match_output_enabled = True

    def disable_match_output(self):
        with self._lock:
            self._match_output_enabled = False

    def is_match_output_enabled(self) -> bool:
        with self._lock:
            return self._match_output_enabled
    
    def update_betting_stats(self, func):
        with self._lock:
            return func(self._betting_stats)


class ColorMatcher:
    def __init__(self, config: AppConfig):
        self.config = config
        self.reference_colors: Dict[str, Tuple[int, int, int]] = {}
    
    @staticmethod
    def normalize_color(rgb: Tuple[int, int, int]) -> Tuple[float, float, float]:
        total = max(sum(rgb), 1)
        return tuple(c / total for c in rgb)
    
    def calculate_score(self, rgb: Tuple[int, int, int], reference: Tuple[int, int, int]) -> float:
        raw_distance = sum((rgb[i] - reference[i]) ** 2 for i in range(3))
        norm_rgb = self.normalize_color(rgb)
        norm_ref = self.normalize_color(reference)
        balance_distance = sum((norm_rgb[i] - norm_ref[i]) ** 2 for i in range(3)) * 100000
        return raw_distance + balance_distance
    
    def match_color(self, rgb: Tuple[int, int, int], max_score: Optional[float] = None) -> ColorMatchResult:
        if not self.reference_colors:
            return ColorMatchResult("Unknown", float('inf'), rgb, False)
        
        best_name = None
        best_score = float('inf')
        
        for name, ref_rgb in self.reference_colors.items():
            if name == self.config.blank_color_label:
                continue
            score = self.calculate_score(rgb, ref_rgb)
            if score < best_score:
                best_name = name
                best_score = score
        
        max_allowed = max_score or self.config.color_match_max_score
        is_match = best_score <= max_allowed
        
        return ColorMatchResult(
            color_name=best_name or "Unknown",
            score=best_score,
            rgb_value=rgb,
            is_match=is_match
        )
    
    def is_blank_color(self, rgb: Tuple[int, int, int]) -> bool:
        return max(rgb) <= self.config.black_detection_threshold
    
    def set_reference(self, name: str, rgb: Tuple[int, int, int]):
        self.reference_colors[name] = rgb
        logger.debug(f"Reference color set: {name} = {rgb}")


class ScreenCaptureManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.calibration_points: Dict[int, CalibrationPoint] = {}
        self._cached_bbox: Optional[Tuple[int, int, int, int]] = None
        self._last_capture_time: float = 0
    
    def add_calibration_point(self, point: CalibrationPoint):
        self.calibration_points[point.index] = point
        self._cached_bbox = None
    
    def get_all_coords(self) -> List[Tuple[int, int]]:
        return [p.coord for p in sorted(self.calibration_points.values(), key=lambda p: p.index)]
    
    def get_grid_points(self) -> List[List[Tuple[int, int]]]:
        grid_count = self.config.total_columns * self.config.boxes_per_column
        grid_points = [self.calibration_points[i].coord for i in range(grid_count) if i in self.calibration_points]
        
        if len(grid_points) < grid_count:
            return []
        
        return [
            grid_points[i * self.config.boxes_per_column:(i + 1) * self.config.boxes_per_column]
            for i in range(self.config.total_columns)
        ]
    
    def get_extra_points(self) -> Dict[str, Tuple[int, int]]:
        start_idx = self.config.total_columns * self.config.boxes_per_column
        extra_points = {}
        
        for i, label in enumerate(self.config.extra_calibration_labels):
            idx = start_idx + i
            if idx in self.calibration_points:
                extra_points[label] = self.calibration_points[idx].coord
        
        return extra_points
    
    def get_monitor_points(self) -> List[Tuple[int, int]]:
        points = self.get_all_coords()
        if not points:
            return []
        
        grid_count = self.config.total_columns * self.config.boxes_per_column
        reference_indices = set(range(grid_count, grid_count + len(self.config.reference_color_labels)))
        
        return [p for i, p in enumerate(points) if i < grid_count or i in reference_indices]
    
    def get_capture_bbox(self, padding: Optional[int] = None) -> Optional[Tuple[int, int, int, int]]:
        points = self.get_monitor_points()
        if not points:
            return None
        
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        pad = padding or self.config.monitor_capture_padding
        
        left = max(0, min(xs) - pad)
        top = max(0, min(ys) - pad)
        right = max(xs) + pad + 1
        bottom = max(ys) + pad + 1
        
        return (left, top, right, bottom)
    
    @contextmanager
    def capture_region(self):
        screenshot = None
        try:
            bbox = self.get_capture_bbox()
            if bbox:
                screenshot = ImageGrab.grab(bbox=bbox).convert("RGB")
                yield screenshot, bbox
            else:
                screenshot = ImageGrab.grab().convert("RGB")
                yield screenshot, None
        finally:
            if screenshot:
                screenshot.close()
    
    def get_pixel_rgb(self, screenshot: Image.Image, point: Tuple[int, int], bbox: Optional[Tuple[int, int, int, int]] = None) -> Tuple[int, int, int]:
        x, y = point
        if bbox:
            x -= bbox[0]
            y -= bbox[1]
        
        radius = self.config.color_sample_radius
        left = max(0, x - radius)
        top = max(0, y - radius)
        right = min(screenshot.width - 1, x + radius)
        bottom = min(screenshot.height - 1, y + radius)
        
        total_r = total_g = total_b = 0
        count = 0
        
        for px in range(left, right + 1):
            for py in range(top, bottom + 1):
                r, g, b = screenshot.getpixel((px, py))
                total_r += r
                total_g += g
                total_b += b
                count += 1
        
        if count == 0:
            return screenshot.getpixel((x, y))
        
        return (total_r // count, total_g // count, total_b // count)
    
    def is_fully_calibrated(self) -> bool:
        return len(self.calibration_points) >= self.config.total_calibration_points


class GameAnalyzer:
    def __init__(self, config: AppConfig, capture_mgr: ScreenCaptureManager, color_matcher: ColorMatcher):
        self.config = config
        self.capture_mgr = capture_mgr
        self.color_matcher = color_matcher
    
    def analyze_columns(self, screenshot: Image.Image, bbox: Optional[Tuple]) -> List[ColumnAnalysis]:
        grid_points = self.capture_mgr.get_grid_points()
        if not grid_points:
            return []
        
        columns = []
        for col_idx, column_points in enumerate(grid_points):
            box_colors = []
            box_debug = []
            has_unknown = False
            is_full = True
            
            for box_idx, point in enumerate(column_points):
                rgb = self.capture_mgr.get_pixel_rgb(screenshot, point, bbox)
                
                if self.color_matcher.is_blank_color(rgb):
                    box_colors.append("Blank")
                    box_debug.append(f"Blank rgb={rgb}")
                    is_full = False
                else:
                    match = self.color_matcher.match_color(rgb)
                    color_name = match.color_name if match.is_match else "Unknown"
                    box_colors.append(color_name)
                    box_debug.append(f"{color_name} rgb={rgb} best={match.color_name} score={match.score:.0f}")
                    if color_name == "Unknown":
                        has_unknown = True
            
            columns.append(ColumnAnalysis(
                column_index=col_idx + 1,
                boxes=box_colors,
                is_full=is_full,
                has_unknown=has_unknown,
                box_debug=box_debug
            ))
        
        return columns
    
    def analyze_game_state(self, screenshot: Image.Image, bbox: Optional[Tuple]) -> GameState:
        columns = self.analyze_columns(screenshot, bbox)
        
        total_boxes = len(columns) * self.config.boxes_per_column if columns else 0
        blank_boxes = sum(1 for col in columns for box in col.boxes if box == "Blank") if columns else 0
        blank_detected = total_boxes > 0 and blank_boxes == total_boxes
        
        all_columns_full = all(col.is_full for col in columns) if columns else False
        any_unknown = any(col.has_unknown for col in columns) if columns else False
        
        recommended_color = None
        if columns and columns[0].all_boxes_known:
            recommended_color = columns[0].boxes[0]
        
        if columns:
            known_boxes = sum(1 for col in columns for box in col.boxes if box not in ["Blank", "Unknown"])
            total_boxes_count = len(columns) * self.config.boxes_per_column
            confidence = (known_boxes / total_boxes_count) * 100 if total_boxes_count > 0 else 0
        else:
            confidence = 0

        game_state = GameState(
            timestamp=time.time(),
            columns=columns,
            all_columns_full=all_columns_full,
            any_unknown=any_unknown,
            blank_detected=blank_detected,
            recommended_bet=self.config.betting_strategy.base_bet,
            recommended_color=recommended_color,
            confidence_score=confidence
        )

        if game_state.has_uniform_column_pattern:
            game_state.confidence_score = 0
            game_state.recommended_color = None
        
        return game_state
    
    def wait_for_ready_state(self, max_retries: int = None) -> Optional[GameState]:
        max_retries = max_retries or self.config.max_unknown_retries
        retries = 0
        
        while retries < max_retries:
            with self.capture_mgr.capture_region() as (screenshot, bbox):
                game_state = self.analyze_game_state(screenshot, bbox)
                
                if game_state.is_ready_for_action:
                    logger.info("Game state ready for action")
                    return game_state
                
                if game_state.blank_detected:
                    logger.debug("Blank detected, waiting...")
                elif game_state.any_unknown:
                    logger.debug(f"Unknown colors detected (retry {retries + 1}/{max_retries})")
                elif not game_state.all_columns_full:
                    logger.debug("Columns not full, waiting...")
            
            time.sleep(self.config.unknown_retry_delay)
            retries += 1
        
        logger.warning("Timeout waiting for ready game state")
        return None


class RandomBetManager:
    BASE_MARTINGALE_AMOUNT = 5
    BET_BUTTON_VALUES = {"Bet 5": 5, "Bet 10": 10, "Bet 20": 20, "Bet 50": 50}
    PRE_CLICK_DELAY_RANGE = (1.0, 2.0)
    
    def __init__(self, config: AppConfig, capture_mgr: ScreenCaptureManager, app: Optional['AutoClickerPro'] = None):
        self.config = config
        self.capture_mgr = capture_mgr
        self.app = app  # Reference to the main app for visual feedback
        self.stats = BettingStats()
        self._last_bet_time: float = 0
        self._is_running = False
        self._bet_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._game_analyzer = None
        self._idle_until: float = 0.0
        self._last_resolved_c1_boxes: Tuple[str, ...] = tuple()
    
    def _get_game_analyzer(self):
        if self._game_analyzer is None:
            color_matcher = ColorMatcher(self.config)
            if hasattr(self.capture_mgr, 'calibration_points'):
                start_idx = self.config.total_columns * self.config.boxes_per_column
                for i, color_label in enumerate(self.config.color_labels):
                    idx = start_idx + i
                    if idx in self.capture_mgr.calibration_points:
                        point = self.capture_mgr.calibration_points[idx]
                        if point.rgb_sample:
                            color_matcher.set_reference(color_label, point.rgb_sample)
            self._game_analyzer = GameAnalyzer(self.config, self.capture_mgr, color_matcher)
        return self._game_analyzer
    
    def start_random_betting(self, interval_seconds: float = 5.0) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        
        if self._bet_thread and self._bet_thread.is_alive():
            return True
        
        self._stop_event.clear()
        self._is_running = True
        self._bet_thread = threading.Thread(target=self._random_bet_loop, args=(interval_seconds,), name="RandomBetThread", daemon=True)
        self._bet_thread.start()
        return True
    
    def stop_random_betting(self):
        self._stop_event.set()
        self._is_running = False
        if self._bet_thread:
            self._bet_thread.join(timeout=2)
    
    def _random_bet_loop(self, interval_seconds: float):
        logger.info("Random betting loop started")
        while not self._stop_event.is_set():
            try:
                idle_remaining = self.get_idle_remaining()
                if idle_remaining > 0:
                    time.sleep(min(1.0, idle_remaining))
                    continue

                if not self._wait_for_random_bet_ready():
                    time.sleep(0.5)
                    continue

                time.sleep(1.0)

                if not self._place_random_bet():
                    time.sleep(1)
                    continue

                result_declared = self._check_bet_result()
                if not result_declared:
                    logger.warning("Random bet result was not declared; retrying next loop")
                    time.sleep(1.0)
                    continue
                
            except Exception as e:
                logger.error(f"Error in random betting loop: {e}")
                time.sleep(2)
        
        logger.info("Random betting loop stopped")

    def _wait_for_random_bet_ready(self) -> bool:
        try:
            with self.capture_mgr.capture_region() as (screenshot, bbox):
                game_analyzer = self._get_game_analyzer()
                game_state = game_analyzer.analyze_game_state(screenshot, bbox)
        except Exception as e:
            logger.error(f"Failed to analyze random bet readiness: {e}")
            return False

        is_ready = (
            game_state.confidence_score >= 100
            and not game_state.any_unknown
            and game_state.all_columns_full
            and not game_state.blank_detected
            and not game_state.has_uniform_column_pattern
            and bool(game_state.winning_column_boxes)
            and tuple(game_state.winning_column_boxes) != self._last_resolved_c1_boxes
        )
        return is_ready

    def _wait_for_stable_result_state(self, timeout_seconds: float = 12.0) -> Optional[GameState]:
        deadline = time.time() + timeout_seconds
        last_c1_boxes: Optional[Tuple[str, ...]] = None
        confirmed_reads = 0
        latest_readable_state: Optional[GameState] = None
        while not self._stop_event.is_set() and time.time() < deadline:
            try:
                with self.capture_mgr.capture_region() as (screenshot, bbox):
                    game_state = self._get_game_analyzer().analyze_game_state(screenshot, bbox)
            except Exception as e:
                logger.error(f"Failed to analyze random bet result state: {e}")
                time.sleep(0.5)
                continue

            if (game_state.confidence_score >= 100 and not game_state.has_uniform_column_pattern and
                not game_state.any_unknown and game_state.all_columns_full and not game_state.blank_detected and
                game_state.winning_column_boxes and tuple(game_state.winning_column_boxes) != self._last_resolved_c1_boxes):
                latest_readable_state = game_state
                current_c1_boxes = tuple(game_state.winning_column_boxes)
                if current_c1_boxes == last_c1_boxes:
                    confirmed_reads += 1
                else:
                    last_c1_boxes = current_c1_boxes
                    confirmed_reads = 1
                if confirmed_reads >= 2:
                    return game_state
            else:
                last_c1_boxes = None
                confirmed_reads = 0
            time.sleep(0.5)
        return latest_readable_state

    def _get_next_martingale_amount(self) -> int:
        consecutive_losses = self.stats.consecutive_losses
        return self.BASE_MARTINGALE_AMOUNT * ((2 ** (consecutive_losses + 1)) - 1)

    def _resolve_color_button_label(self, color_name: str, extra_points: Dict[str, Tuple[int, int]]) -> Optional[str]:
        preferred_label = self.config.get_bet_color_label(color_name)
        if preferred_label in extra_points:
            return preferred_label
        if color_name in extra_points:
            return color_name
        return None

    def _compute_bet_button_sequence(self, target_amount: int, available_buttons: Dict[str, Tuple[int, int]], has_x2: bool) -> Optional[List[str]]:
        if target_amount <= 0:
            return None
        available_values = {label: value for label, value in self.BET_BUTTON_VALUES.items() if label in available_buttons}
        if not available_values:
            return None
        queue = deque([(0, [])])
        visited = {0}
        while queue:
            current_amount, steps = queue.popleft()
            if current_amount == target_amount:
                return steps
            for label, value in sorted(available_values.items(), key=lambda item: item[1], reverse=True):
                next_amount = current_amount + value
                if next_amount <= target_amount and next_amount not in visited:
                    visited.add(next_amount)
                    queue.append((next_amount, steps + [label]))
            if has_x2 and current_amount > 0:
                doubled_amount = current_amount * 2
                if doubled_amount <= target_amount and doubled_amount not in visited:
                    visited.add(doubled_amount)
                    queue.append((doubled_amount, steps + ["X2"]))
        return None

    def _format_target_bet_label(self, target_amount: int) -> str:
        if target_amount in self.BET_BUTTON_VALUES.values():
            return f"Bet {target_amount}"
        return f"Martingale {target_amount}"
    
    def _place_random_bet(self) -> bool:
        extra_points = self.capture_mgr.get_extra_points()
        available_colors = [color for color in self.config.color_labels if self._resolve_color_button_label(color, extra_points)]
        has_x2 = "X2" in extra_points
        if not available_colors:
            logger.error("No colors available for random betting")
            return False

        target_amount = self._get_next_martingale_amount()
        button_sequence = self._compute_bet_button_sequence(target_amount, extra_points, has_x2)
        if not button_sequence:
            logger.error(f"Could not compute button sequence for target amount {target_amount}")
            return False

        if self.stats.history and len(available_colors) > 1:
            previous_color = self.stats.history[-1].get("color")
            available_colors = [color for color in available_colors if color != previous_color] or available_colors

        bet_color = random.choice(available_colors)
        
        try:
            for button_label in button_sequence:
                button_coord = extra_points[button_label]
                pyautogui.click(button_coord[0], button_coord[1])
                # Show visual feedback for bet amount clicks
                if self.app:
                    self.app.show_click_mark(button_coord[0], button_coord[1])
                time.sleep(0.1)
            
            color_button_label = self._resolve_color_button_label(bet_color, extra_points)
            if not color_button_label:
                logger.error(f"No calibrated bet button found for color {bet_color}")
                return False

            color_coord = extra_points[color_button_label]
            pyautogui.click(color_coord[0], color_coord[1])
            # Show visual feedback for color click
            if self.app:
                self.app.show_click_mark(color_coord[0], color_coord[1])
            
            self._last_bet_time = time.time()
            self.stats.record_bet(self._format_target_bet_label(target_amount), bet_color)
            self._idle_until = time.time() + self.config.monitor_idle_seconds
            
            logger.info("Random martingale bet placed: target=%s buttons=%s color=%s", target_amount, " -> ".join(button_sequence), bet_color)
            return True
        except Exception as e:
            logger.error(f"Failed to place random bet: {e}")
            return False
    
    def _check_bet_result(self) -> Optional[bool]:
        pending_bet = self.stats.get_latest_pending_bet()
        if pending_bet is None:
            return None

        while not self._stop_event.is_set():
            idle_remaining = self.get_idle_remaining()
            if idle_remaining <= 0:
                break
            time.sleep(min(1.0, idle_remaining))
        
        game_state = self._wait_for_stable_result_state()
        if not game_state:
            logger.warning("Timed out waiting for a stable random bet result state")
            return None

        c1_boxes = game_state.winning_column_boxes
        if not c1_boxes:
            return None

        last_bet_color = pending_bet["color"]
        won = last_bet_color in c1_boxes
        self.stats.record_result(won, c1_boxes[0])
        self._last_resolved_c1_boxes = tuple(c1_boxes)
        logger.info("Random bet result: %s (C1: %s, Bet: %s)", "WIN" if won else "LOSS", "/".join(c1_boxes), last_bet_color)
        return won
    
    def get_stats(self) -> BettingStats:
        return self.stats
    
    def is_running(self) -> bool:
        return self._is_running

    def get_idle_remaining(self) -> float:
        return max(0.0, self._idle_until - time.time())


class BettingManager:
    def __init__(self, config: AppConfig, capture_mgr: ScreenCaptureManager, stats: Optional[BettingStats] = None):
        self.config = config
        self.capture_mgr = capture_mgr
        self.stats = stats or BettingStats()
        self._last_bet_time: float = 0
    
    def select_bet_amount(self, quick_mode: bool = False) -> str:
        if quick_mode:
            return self.config.betting_strategy.base_bet
        return self.stats.get_next_bet_amount(self.config.betting_strategy)
    
    def select_bet_color(self, game_state: GameState, quick_mode: bool = False) -> Optional[str]:
        if quick_mode:
            if self.stats.history:
                for bet in reversed(self.stats.history):
                    if bet.get("result") == "WIN":
                        return bet.get("color")
            return "Yellow"
        if game_state.recommended_color:
            return game_state.recommended_color
        if game_state.columns:
            all_colors = [box for col in game_state.columns for box in col.boxes if box not in ["Blank", "Unknown"]]
            if all_colors:
                from collections import Counter
                most_common = Counter(all_colors).most_common(1)
                if most_common:
                    return most_common[0][0]
        return None

    def select_random_bet_color(self) -> Optional[str]:
        extra_points = self.capture_mgr.get_extra_points()
        available_colors = [color for color in self.config.color_labels if self._resolve_color_button_label(color, extra_points)]
        if not available_colors:
            return None
        if self.stats.history and len(available_colors) > 1:
            previous_color = self.stats.history[-1].get("color")
            available_colors = [color for color in available_colors if color != previous_color] or available_colors
        return random.choice(available_colors)

    def _resolve_color_button_label(self, color_name: str, extra_points: Dict[str, Tuple[int, int]]) -> Optional[str]:
        preferred_label = self.config.get_bet_color_label(color_name)
        if preferred_label in extra_points:
            return preferred_label
        if color_name in extra_points:
            return color_name
        return None

    def simulate_bet(self, amount: str, color: str) -> bool:
        extra_points = self.capture_mgr.get_extra_points()
        if amount not in extra_points:
            logger.error(f"Bet amount {amount} not calibrated for simulation")
            return False
        if not self._resolve_color_button_label(color, extra_points):
            logger.error(f"Color {color} not calibrated for simulation")
            return False

        self._last_bet_time = time.time()
        self.stats.record_bet(amount, color)
        logger.info(f"Simulated bet: {amount} on {color}")
        return True
    
    def place_bet(self, amount: str, color: str, quick_mode: bool = False) -> bool:
        extra_points = self.capture_mgr.get_extra_points()
        if amount not in extra_points:
            logger.error(f"Bet amount {amount} not calibrated")
            return False
        color_button_label = self._resolve_color_button_label(color, extra_points)
        if not color_button_label:
            logger.error(f"Color {color} not calibrated")
            return False
        
        try:
            click_delay = 0.05 if quick_mode else 0.2
            bet_coord = extra_points[amount]
            pyautogui.click(bet_coord[0], bet_coord[1])
            time.sleep(click_delay)
            color_coord = extra_points[color_button_label]
            pyautogui.click(color_coord[0], color_coord[1])
            self._last_bet_time = time.time()
            self.stats.record_bet(amount, color)
            logger.info(f"Placed bet: {amount} on {color} (quick_mode={quick_mode})")
            return True
        except Exception as e:
            logger.error(f"Failed to place bet: {e}")
            return False
    
    def should_bet(self, game_state: GameState, quick_mode: bool = False) -> bool:
        if quick_mode:
            return game_state.blank_detected
        if self.stats.has_pending_bet():
            return False
        if not game_state.is_ready_for_action:
            return False
        if game_state.confidence_score < 50:
            logger.debug(f"Low confidence ({game_state.confidence_score:.1f}%), waiting")
            return False
        if time.time() - self._last_bet_time < self.config.click_interval_seconds:
            return False
        return True
    
    def record_outcome(self, game_state: GameState) -> Optional[bool]:
        pending_bet = self.stats.get_latest_pending_bet()
        if pending_bet is None:
            logger.debug("No pending bet to record")
            return None
        
        c1_boxes = game_state.winning_column_boxes
        if not c1_boxes:
            logger.debug("No C1 boxes available to determine outcome")
            return None
        
        last_bet_color = pending_bet["color"]
        won = last_bet_color in c1_boxes
        self.stats.record_result(won, c1_boxes[0])
        
        logger.info("Bet result: %s | Bet: %s | C1: %s", "WIN" if won else "LOSS", last_bet_color, "/".join(c1_boxes))
        return won


class AutomationEngine:
    def __init__(self, config: AppConfig, capture_mgr: ScreenCaptureManager, 
                 color_matcher: ColorMatcher, game_analyzer: GameAnalyzer, 
                 betting_manager: BettingManager, app: Optional['AutoClickerPro'] = None):
        self.config = config
        self.capture_mgr = capture_mgr
        self.color_matcher = color_matcher
        self.game_analyzer = game_analyzer
        self.betting_manager = betting_manager
        self.app = app  # Reference to the main app for visual feedback
        self.state = ThreadSafeState()
        self.random_bet_manager = RandomBetManager(config, capture_mgr, app)
        
        self._monitor_thread: Optional[threading.Thread] = None
        self._clicker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._blank_bet_triggered = False
        self.betting_manager.stats = self.state.get_betting_stats()
    
    def start_monitoring(self) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        if self._monitor_thread and self._monitor_thread.is_alive():
            return True
        self._stop_event.clear()
        self.state.state = AutomationState.MONITORING
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="MonitorThread", daemon=True)
        self._monitor_thread.start()
        return True
    def start_clicking(self) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        if self._clicker_thread and self._clicker_thread.is_alive():
            return True
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self.start_monitoring()
        self._stop_event.clear()
        self._blank_bet_triggered = False
        self.state.state = AutomationState.CLICKING
        self._clicker_thread = threading.Thread(target=self._clicker_loop, name="ClickerThread", daemon=True)
        self._clicker_thread.start()
        return True

    
    def _wait_for_100_percent_confidence(self, timeout_seconds: float = 20.0) -> Optional[GameState]:
        """Wait for a game state with 100% confidence, no unknowns, all columns full"""
        deadline = time.time() + timeout_seconds
        last_valid_state = None
        
        while not self._stop_event.is_set() and time.time() < deadline:
            if self.state.paused:
                time.sleep(0.5)
                continue
            
            with self.capture_mgr.capture_region() as (screenshot, bbox):
                game_state = self.game_analyzer.analyze_game_state(screenshot, bbox)
            
            # Check for 100% confidence and valid state
            is_valid = (
                game_state.confidence_score >= 100
                and not game_state.any_unknown
                and game_state.all_columns_full
                and not game_state.blank_detected
                and not game_state.has_uniform_column_pattern
                and game_state.winning_column_boxes
            )
            
            if is_valid:
                # Require two consecutive reads for stability
                if last_valid_state and last_valid_state.winning_column_boxes == game_state.winning_column_boxes:
                    self.state.update_status(f"✓ 100% confidence confirmed - C1: {'/'.join(game_state.winning_column_boxes)}")
                    return game_state
                last_valid_state = game_state
            else:
                last_valid_state = None
            
            time.sleep(0.3)
        
        return None

    def _get_random_available_color(self) -> Optional[str]:
        """Get a random color that is calibrated and available"""
        extra_points = self.capture_mgr.get_extra_points()
        available_colors = []
        
        for color in self.config.color_labels:
            preferred_label = self.config.get_bet_color_label(color)
            if preferred_label in extra_points or color in extra_points:
                available_colors.append(color)
        
        if not available_colors:
            return None
        
        # Avoid betting same color twice in a row if possible
        stats = self.state.get_betting_stats()
        if stats.history and len(available_colors) > 1:
            last_bet = stats.history[-1].get("color")
            if last_bet in available_colors:
                available_colors = [c for c in available_colors if c != last_bet] or available_colors
        
        return random.choice(available_colors)
        
    def _clicker_loop(self):
        """Infinite simulated betting loop - waits for 100% confidence, places random bet, waits for countdown, then declares result, repeats"""
        logger.info("Clicker loop started - Infinite Simulated Betting Mode")

        while not self._stop_event.is_set():
            if self.state.paused:
                time.sleep(self.config.automation_loop_idle_seconds)
                continue

            # Step 1: Wait for 100% confidence to place a bet
            self.state.update_status("Waiting for 100% confidence to place bet...")

            game_state = self._wait_for_100_percent_confidence(timeout_seconds=20.0)
            if not game_state:
                self.state.update_status("Timeout waiting for 100% confidence - retrying...")
                time.sleep(1)
                continue

            # Step 2: Place random bet
            bet_color = self._get_random_available_color()
            if not bet_color:
                self.state.update_status("No available colors for betting - retrying...")
                time.sleep(1)
                continue

            bet_amount = self.config.betting_strategy.base_bet

            self.state.state = AutomationState.ANALYZING
            self.state.update_status(f"🎲 100% confidence achieved! Placing virtual bet: {bet_amount} on {bet_color}")

            if self.betting_manager.simulate_bet(bet_amount, bet_color):
                self.state.set_waiting_for_result(True)
                self.state.update_status(f"✓ Virtual bet placed: {bet_amount} on {bet_color}. Waiting for result...")
            else:
                self.state.update_status("✗ Failed to place bet - retrying...")
                time.sleep(1)
                continue

            # Step 3: Wait for next 100% confidence (capture result state)
            self.state.update_status("Waiting for result confirmation (next 100% confidence)...")

            result_state = self._wait_for_100_percent_confidence(timeout_seconds=20.0)
            if not result_state:
                self.state.update_status("Timeout waiting for result - skipping...")
                self.state.set_waiting_for_result(False)
                time.sleep(2)
                continue

            # Step 4: Store result data but don't declare yet
            c1_boxes = result_state.winning_column_boxes
            if not c1_boxes:
                self.state.update_status("No C1 boxes found - cannot determine result")
                self.state.set_waiting_for_result(False)
                time.sleep(2)
                continue

            # Store the result data for later declaration
            pending_bet = self.betting_manager.stats.get_latest_pending_bet()
            if not pending_bet:
                self.state.update_status("No pending bet found - skipping...")
                self.state.set_waiting_for_result(False)
                time.sleep(2)
                continue

            bet_color = pending_bet["color"]
            won = bet_color in c1_boxes

            # Update last resolved boxes to avoid re-reading same result
            self.state.set_last_resolved_c1_boxes(tuple(c1_boxes))

            # Step 5: Start idle countdown before declaring result
            self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)
            self.state.update_status(f"Bet placed. Starting idle countdown ({self.config.monitor_idle_seconds}s) before declaring result...")

            # Step 6: Wait for idle countdown to complete
            while not self._stop_event.is_set() and not self.state.paused:
                idle_remaining = self.state.get_monitor_idle_remaining()
                if idle_remaining <= 0:
                    break
                self.state.update_status(f"Idle countdown: {idle_remaining:.1f}s remaining...")
                time.sleep(min(0.5, idle_remaining))

            if self._stop_event.is_set() or self.state.paused:
                continue

            # Step 7: Now declare the result after countdown is complete
            self.state.state = AutomationState.ANALYZING
            if won:
                self.betting_manager.stats.record_result(True, c1_boxes[0])
                self.state.update_status(f"✅ WIN! Bet: {bet_color} | C1: {'/'.join(c1_boxes)}")
            else:
                self.betting_manager.stats.record_result(False, c1_boxes[0])
                self.state.update_status(f"❌ LOSS! Bet: {bet_color} | C1: {'/'.join(c1_boxes)}")

            self.state.set_waiting_for_result(False)

            # Step 8: Wait 2 seconds before next round
            self.state.update_status("Result declared. Waiting 2 seconds before next round...")
            time.sleep(2)
            
            # Loop repeats infinitely
        
        logger.info("Clicker loop stopped")
    
    def start_random_betting(self, interval_seconds: float = 5.0) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        self.stop_all()
        if self.random_bet_manager.start_random_betting(interval_seconds):
            self.state.state = AutomationState.RANDOM_BETTING
            return True
        return False
    
    def stop_random_betting(self):
        self.random_bet_manager.stop_random_betting()
        if self.state.state == AutomationState.RANDOM_BETTING:
            self.state.state = AutomationState.IDLE
    
    def stop_all(self):
        self._stop_event.set()
        self.state.state = AutomationState.IDLE
        self.state.reset_blank_timer()
        self._blank_bet_triggered = False
        self.state.set_waiting_for_result(False)
        self.stop_random_betting()
    
    def pause(self):
        self.state.toggle_pause()
        if self.state.paused:
            self.state.state = AutomationState.PAUSED
        else:
            self.state.state = AutomationState.CLICKING if self._clicker_thread and self._clicker_thread.is_alive() else AutomationState.MONITORING
    
    def _monitor_loop(self):
        logger.info("Monitor loop started")
        while not self._stop_event.is_set():
            if self.state.paused:
                time.sleep(self.config.monitor_interval_seconds)
                continue
            idle_remaining = self.state.get_monitor_idle_remaining()
            if idle_remaining > 0:
                self.state.update_status(f"Idle for {idle_remaining:.0f}s")
                time.sleep(1)
                continue
            with self.capture_mgr.capture_region() as (screenshot, bbox):
                game_state = self.game_analyzer.analyze_game_state(screenshot, bbox)
                self.state.set_game_state(game_state)
                if game_state.blank_detected:
                    self._handle_blank_detected()
                else:
                    blank_elapsed = self.state.get_blank_elapsed()
                    if blank_elapsed is not None and blank_elapsed >= self.config.monitor_blank_allowance_seconds:
                        self.state.enable_match_output()
                    self.state.reset_blank_timer()
                if game_state.blank_detected:
                    pass
                elif not self.state.is_match_output_enabled():
                    self.state.update_status("Waiting for black screen trigger before reading matches...")
                elif game_state.columns:
                    if not game_state.any_unknown:
                        column_status = " | ".join([col.display_text for col in game_state.columns])
                        self.state.update_status(f"Cols: {column_status}")
                        self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)
                        self.state.disable_match_output()
                    else:
                        self.state.update_status("Waiting for stable color match...")
            time.sleep(self.config.column_check_interval)
        logger.info("Monitor loop stopped")
    
    def _handle_blank_detected(self):
        self.state.disable_match_output()
        elapsed = self.state.get_blank_elapsed()
        if elapsed is None:
            self.state.start_blank_timer()
            self.state.update_status("⚡ BLANK DETECTED - Triggering immediate auto-bet! ⚡")
            self._blank_bet_triggered = False
            if self.state.state == AutomationState.CLICKING and not self._blank_bet_triggered:
                self._trigger_immediate_bet()
        elif elapsed < self.config.monitor_blank_allowance_seconds:
            remaining = self.config.monitor_blank_allowance_seconds - elapsed
            self.state.update_status(f"Black detected, waiting {remaining:.1f}s before reading matches...")
        else:
            self.state.update_status("Black trigger confirmed. Waiting for colors to appear...")
    
    def _trigger_immediate_bet(self):
        try:
            self._blank_bet_triggered = True
            game_state = self.state.get_game_state()
            if not game_state:
                self.state.update_status("No game state available for immediate bet")
                return
            self.state.state = AutomationState.ANALYZING
            self.state.update_status("⚡ ANALYZING FOR IMMEDIATE BET ⚡")
            bet_amount = self.betting_manager.select_bet_amount(quick_mode=True)
            bet_color = self.betting_manager.select_random_bet_color()
            if not bet_color:
                self.state.update_status("No suitable color found for immediate bet")
                self.state.state = AutomationState.CLICKING
                return
            self.state.state = AutomationState.CLICKING
            self.state.update_status(f"⚡ VIRTUAL BET: {bet_amount} on {bet_color} ⚡")
            if self.betting_manager.simulate_bet(bet_amount, bet_color):
                self.state.update_status("✓ Virtual bet recorded successfully!")
                self.state.set_waiting_for_result(True)
                threading.Thread(target=self._delayed_result_check_stable, daemon=True).start()
            else:
                self.state.update_status(f"✗ Failed to place immediate bet")
        except Exception as e:
            logger.error(f"Error in immediate bet trigger: {e}")
            self.state.update_status(f"Error triggering immediate bet")
    
    def _delayed_result_check_stable(self):
        """Check the latest clean result, then start countdown for the next round."""
        self.state.update_status("Waiting for latest 100% confidence capture...")

        deadline = time.time() + 20.0
        result_state = None

        while time.time() < deadline and not self._stop_event.is_set():
            if self.state.paused:
                time.sleep(0.5)
                continue

            with self.capture_mgr.capture_region() as (screenshot, bbox):
                candidate_state = self.game_analyzer.analyze_game_state(screenshot, bbox)

            is_ready_for_result = (
                candidate_state.confidence_score >= 100
                and not candidate_state.has_uniform_column_pattern
                and not candidate_state.blank_detected
                and not candidate_state.any_unknown
                and candidate_state.all_columns_full
                and candidate_state.winning_column_boxes
            )

            if is_ready_for_result:
                current_c1_boxes = tuple(candidate_state.winning_column_boxes)
                self.state.update_status(
                    f"100% confidence reached | Latest C1: {'/'.join(current_c1_boxes)} | Declaring in 1s..."
                )
                time.sleep(1.0)
                result_state = candidate_state
                break

            status_parts = []
            if candidate_state.confidence_score < 100:
                status_parts.append(f"confidence={candidate_state.confidence_score:.0f}%")
            if candidate_state.any_unknown:
                status_parts.append("has unknowns")
            if not candidate_state.all_columns_full:
                status_parts.append("columns not full")
            if candidate_state.blank_detected:
                status_parts.append("blank detected")
            if candidate_state.has_uniform_column_pattern:
                status_parts.append("uniform pattern")
            if status_parts:
                self.state.update_status(f"Waiting for 100% confidence... ({', '.join(status_parts)})")

            time.sleep(0.5)

        if not result_state:
            self.state.update_status("Timeout waiting for result - no win/loss declared")
            self.state.set_waiting_for_result(False)
            return

        pending_bet = self.betting_manager.stats.get_latest_pending_bet()
        if not pending_bet:
            self.state.update_status("No pending bet to record")
            self.state.set_waiting_for_result(False)
            return

        won = self.betting_manager.record_outcome(result_state)
        if won is not None:
            self.state.set_last_resolved_c1_boxes(tuple(result_state.winning_column_boxes))
            stats = self.state.get_betting_stats()
            c1_text = "/".join(result_state.winning_column_boxes)
            bet_color = pending_bet["color"]

            self.state.update_status(
                f"{'WIN' if won else 'LOSE'} | Bet: {bet_color} | Result: {c1_text} | "
                f"Total: {stats.total_bets} | Wins: {stats.wins} | Losses: {stats.losses}"
            )
            logger.info("Bet recorded: %s - Bet on %s, C1 showed %s", "WIN" if won else "LOSS", bet_color, c1_text)

        self.state.set_waiting_for_result(False)
        self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)

    def _clicker_loop(self):
        """Auto-clicking loop that continuously places bets round after round."""
        logger.info("Clicker loop started")
        
        while not self._stop_event.is_set():
            if self.state.paused:
                time.sleep(self.config.automation_loop_idle_seconds)
                continue

            # If waiting for result, don't place new bet
            if self.state.is_waiting_for_result():
                self.state.update_status("Waiting for previous bet result...")
                time.sleep(1.0)
                continue

            idle_remaining = self.state.get_monitor_idle_remaining()
            if idle_remaining > 0:
                time.sleep(min(1.0, idle_remaining))
                continue
            
            game_state = self.state.get_game_state()
            if not game_state:
                time.sleep(0.5)
                continue
            
            last_resolved_c1_boxes = self.state.get_last_resolved_c1_boxes()
            
            if game_state.blank_detected:
                time.sleep(0.2)
                continue
            
            if not self.betting_manager.should_bet(game_state, quick_mode=False):
                if game_state.any_unknown:
                    self.state.update_status("Waiting for columns to stabilize (unknown colors present)...")
                elif not game_state.all_columns_full:
                    self.state.update_status("Waiting for all columns to fill...")
                time.sleep(0.5)
                continue

            if game_state.any_unknown or not game_state.all_columns_full or game_state.confidence_score < 100:
                self.state.update_status("Waiting for 100% confidence before next simulate round...")
                time.sleep(0.5)
                continue

            current_c1 = tuple(game_state.winning_column_boxes) if game_state.winning_column_boxes else tuple()
            
            # Check if we have a fresh C1 result (different from last resolved one)
            if (game_state.has_uniform_column_pattern or not current_c1 or
                (last_resolved_c1_boxes and current_c1 == last_resolved_c1_boxes)):
                if last_resolved_c1_boxes and current_c1 == last_resolved_c1_boxes:
                    self.state.update_status(f"Waiting for new C1 result (currently: {'/'.join(current_c1)})...")
                else:
                    self.state.update_status("Waiting for a fresh C1 result before next simulate round...")
                time.sleep(0.5)
                continue
            
            # Ready to place a new bet
            self.state.state = AutomationState.ANALYZING
            self.state.update_status(f"Analyzing game state (confidence: {game_state.confidence_score:.1f}%)...")
            
            bet_amount = self.betting_manager.select_bet_amount(quick_mode=False)
            bet_color = self.betting_manager.select_random_bet_color()
            
            if not bet_color:
                self.state.update_status("No suitable color found for betting")
                self.state.state = AutomationState.CLICKING
                time.sleep(1)
                continue
            
            self.state.state = AutomationState.CLICKING
            self.state.update_status(f"Recording virtual bet {bet_amount} on {bet_color}...")
            
            if self.betting_manager.simulate_bet(bet_amount, bet_color):
                self.state.set_waiting_for_result(True)
                self.state.update_status("Virtual bet recorded! Waiting for latest capture to declare result...")
                threading.Thread(target=self._delayed_result_check_stable, daemon=True).start()
                # Wait a bit before checking for next round condition
                time.sleep(2.0)
            else:
                self.state.update_status(f"Failed to place bet")
                time.sleep(0.5)


class AutoClickerPro:
    def __init__(self, root: tk.Tk, config_path: Optional[Path] = None):
        self.root = root
        self.config_path = config_path or Path(__file__).resolve().parent / "config" / "app_config.json"
        
        self.config = self._load_config()
        self.capture_mgr = ScreenCaptureManager(self.config)
        self.color_matcher = ColorMatcher(self.config)
        self.game_analyzer = GameAnalyzer(self.config, self.capture_mgr, self.color_matcher)
        self.betting_manager = BettingManager(self.config, self.capture_mgr)
        self.engine = AutomationEngine(self.config, self.capture_mgr, self.color_matcher, self.game_analyzer, self.betting_manager, self)
        
        self._calibration_window: Optional[tk.Toplevel] = None
        self._status_update_id = None
        self.random_bet_interval = tk.DoubleVar(value=5.0)
        self.status_mode_label = "Idle"
        self._status_before_pause = "Idle"
        
        self._setup_ui()
        self._load_calibration()
        self._schedule_ui_update()
    
    def _load_config(self) -> AppConfig:
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    return AppConfig.from_dict(data.get("app_config", {}))
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
        return AppConfig()
    
    def _save_config(self):
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump({"app_config": self.config.to_dict(), "version": "2.2.0", "updated": datetime.now().isoformat()}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
    
    def _load_calibration(self):
        calib_path = self.config_path.parent / "calibration.json"
        if not calib_path.exists():
            return
        try:
            with open(calib_path, 'r') as f:
                data = json.load(f)
            next_index = 0
            for point_data in data.get("points", []):
                point_name = point_data.get("name", f"Point_{next_index}")
                if point_name == self.config.blank_color_label:
                    continue
                if next_index >= self.config.total_calibration_points:
                    break
                point = CalibrationPoint.from_dict(next_index, point_name, point_data)
                self.capture_mgr.add_calibration_point(point)
                if point.rgb_sample and point.name in self.config.reference_color_labels:
                    self.color_matcher.set_reference(point.name, point.rgb_sample)
                next_index += 1
            loaded_points = len(self.capture_mgr.calibration_points)
            expected_points = self.config.total_calibration_points
            self.status_mode_label = "Calibration Loaded"
            if loaded_points >= expected_points:
                self.status_var.set(f"Status: Calibration loaded successfully ({loaded_points}/{expected_points} points)")
            else:
                self.status_var.set(f"Status: Calibration partially loaded ({loaded_points}/{expected_points} points)")
            logger.info(f"Loaded {len(self.capture_mgr.calibration_points)} calibration points")
        except Exception as e:
            logger.error(f"Failed to load calibration: {e}")
    
    def _save_calibration(self):
        calib_path = self.config_path.parent / "calibration.json"
        data = {"points": [{"name": p.name, "x": p.x, "y": p.y, "rgb_sample": list(p.rgb_sample) if p.rgb_sample else None} for p in sorted(self.capture_mgr.calibration_points.values(), key=lambda p: p.index)]}
        try:
            calib_path.parent.mkdir(parents=True, exist_ok=True)
            with open(calib_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("Calibration saved")
        except Exception as e:
            logger.error(f"Failed to save calibration: {e}")

    def _create_calibration_point(self, index: int, name: str, x: int, y: int, rgb_sample: Optional[Tuple[int, int, int]] = None) -> CalibrationPoint:
        return CalibrationPoint(index=index, name=name, x=x, y=y, rgb_sample=rgb_sample)
    
    def _setup_ui(self):
        self.root.title("AutoClicker Pro v2.2 - Continuous Betting Mode")
        window_width = 560
        window_height = 550
        screen_width = self.root.winfo_screenwidth()
        self.root.geometry(f"{window_width}x{window_height}+{screen_width - window_width - 20}+20")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        
        style = ttk.Style()
        style.theme_use('clam')
        
        title_frame = ttk.Frame(self.root)
        title_frame.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(title_frame, text="AUTOMATION CONTROL - CONTINUOUS BETTING", font=("Arial", 12, "bold")).pack()
        
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=10)
        
        row1_buttons = [("📸 Calibrate", self.start_calibration, "#f0ad4e"), ("👁️ Monitor", self.start_monitoring, "#5cb85c"), ("🎲 Random Bet", self.start_random_betting, "#9b59b6")]
        for i, (text, command, color) in enumerate(row1_buttons):
            btn = tk.Button(button_frame, text=text, command=command, width=12, bg=color, fg="white", relief="raised", bd=1)
            btn.grid(row=0, column=i, padx=2, pady=5)
        
        row2_buttons = [("⚡ Simulate", self.start_clicking, "#5bc0de"), ("⏸️ Pause", self.toggle_pause, "#f7b267"), ("❌ Exit", self.exit_app, "#d9534f")]
        for i, (text, command, color) in enumerate(row2_buttons):
            btn = tk.Button(button_frame, text=text, command=command, width=12, bg=color, fg="white" if color != "#f7b267" else "black", relief="raised", bd=1)
            btn.grid(row=1, column=i, padx=2, pady=5)
        
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=(10, 5))
        status_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.status_var = tk.StringVar(value="Ready - Not calibrated")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, font=("Arial", 9))
        self.status_label.pack(anchor="w")
        
        game_frame = ttk.LabelFrame(self.root, text="Game State", padding=(10, 5))
        game_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.columns_var = tk.StringVar(value="Columns: Not scanned")
        ttk.Label(game_frame, textvariable=self.columns_var, font=("Arial", 8)).pack(anchor="w")
        self.columns_var_row2 = tk.StringVar(value="")
        ttk.Label(game_frame, textvariable=self.columns_var_row2, font=("Arial", 8)).pack(anchor="w")
        self.confidence_var = tk.StringVar(value="Confidence: 0%")
        ttk.Label(game_frame, textvariable=self.confidence_var, font=("Arial", 8)).pack(anchor="w")
        
        stats_frame = ttk.LabelFrame(self.root, text="Betting Statistics", padding=(10, 5))
        stats_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.stats_var = tk.StringVar(value="Bets: 0 | Wins: 0 | Losses: 0 | Win Rate: 0% | Streak: 0")
        ttk.Label(stats_frame, textvariable=self.stats_var, font=("Arial", 8)).pack(anchor="w")
        self.last_bet_var = tk.StringVar(value="Current Bet: None")
        ttk.Label(stats_frame, textvariable=self.last_bet_var, font=("Arial", 8)).pack(anchor="w")
        
        info_frame = ttk.LabelFrame(self.root, text="Information", padding=(10, 5))
        info_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        self.calib_info_var = tk.StringVar(value=f"Calibration: 0/{self.config.total_columns * self.config.boxes_per_column} grid + 0/{len(self.config.extra_calibration_labels)} extra")
        ttk.Label(info_frame, textvariable=self.calib_info_var, font=("Arial", 8)).pack(anchor="w")
        self.progress = ttk.Progressbar(info_frame, mode='indeterminate', length=300)
        self.progress.pack(pady=(10, 0))
        strategy_text = f"Strategy: Base={self.config.betting_strategy.base_bet} | Progression={'→'.join(self.config.betting_strategy.bet_progression)} | Mode: Continuous Betting"
        ttk.Label(info_frame, text=strategy_text, font=("Arial", 7)).pack(anchor="w", pady=(5, 0))
    
    def _schedule_ui_update(self):
        self._update_ui()
        self._status_update_id = self.root.after(500, self._schedule_ui_update)
    
    def _update_ui(self):
        total_needed = self.config.total_calibration_points
        current = len(self.capture_mgr.calibration_points)
        extra_needed = len(self.config.extra_calibration_labels)
        grid_needed = self.config.total_columns * self.config.boxes_per_column
        self.calib_info_var.set(f"Calibration: {min(current, grid_needed)}/{grid_needed} grid + {max(0, current - grid_needed)}/{extra_needed} extra")
        
        game_state = self.engine.state.get_game_state()
        if game_state and game_state.columns:
            if game_state.has_uniform_column_pattern:
                self.columns_var.set("Columns: Invalid repeated color pattern detected")
                self.columns_var_row2.set("")
            elif not game_state.any_unknown:
                formatted_columns = [f"C{col.column_index}[{':'.join(col.boxes)}]" for col in game_state.columns]
                self.columns_var.set("Columns: " + " | ".join(formatted_columns[:3]))
                self.columns_var_row2.set("         " + " | ".join(formatted_columns[3:7]))
            else:
                self.columns_var.set("Columns: Waiting for stable match...")
                self.columns_var_row2.set("")
            ready_status = "⚡ READY" if game_state.blank_detected else "✓ Ready" if game_state.is_ready_for_action else "⏳ Waiting"
            self.confidence_var.set(f"Confidence: {game_state.confidence_score:.1f}% | {ready_status}")
        else:
            self.columns_var.set("Columns: Waiting for data...")
            self.columns_var_row2.set("")
            self.confidence_var.set("Confidence: 0%")
        
        if self.engine.state.state == AutomationState.RANDOM_BETTING:
            random_stats = self.engine.random_bet_manager.get_stats()
            self.stats_var.set(f"[RANDOM MODE] Bets: {random_stats.total_bets} | Wins: {random_stats.wins} | Losses: {random_stats.losses} | Win Rate: {random_stats.get_win_rate():.1f}% | Streak: {random_stats.current_streak}")
            pending_random_bet = random_stats.get_latest_pending_bet()
            if pending_random_bet:
                self.last_bet_var.set(f"[RANDOM] Current Bet: {pending_random_bet['amount']} on {pending_random_bet['color']}")
            else:
                self.last_bet_var.set("[RANDOM] Current Bet: Waiting for next round")
        else:
            stats = self.engine.state.get_betting_stats()
            self.stats_var.set(f"Bets: {stats.total_bets} | Wins: {stats.wins} | Losses: {stats.losses} | Win Rate: {stats.get_win_rate():.1f}% | Streak: {stats.current_streak}")
            pending_bet = stats.get_latest_pending_bet()
            if pending_bet:
                self.last_bet_var.set(f"Current Bet: {pending_bet['amount']} on {pending_bet['color']}")
            else:
                self.last_bet_var.set("Current Bet: Waiting for next round")
        
        idle_remaining = self.engine.state.get_monitor_idle_remaining()
        random_idle_remaining = self.engine.random_bet_manager.get_idle_remaining()
        if self._calibration_window:
            self.status_var.set("Status: Calibrating")
            self.progress.start(10)
        elif self.engine.state.state == AutomationState.IDLE:
            self.status_var.set("Status: Idle")
            self.progress.stop()
        elif self.engine.state.state == AutomationState.RANDOM_BETTING and random_idle_remaining > 0:
            self.status_var.set(f"Status: Random Betting - Idle countdown {random_idle_remaining:.0f}s")
            self.progress.start(15)
        elif self.engine.state.state == AutomationState.PAUSED:
            self.status_var.set("Status: Paused")
            self.progress.stop()
        elif idle_remaining > 0 and game_state and not game_state.any_unknown:
            self.status_var.set(f"Status: {self.status_mode_label} - Idle countdown {idle_remaining:.0f}s")
            self.progress.start(10)
        elif self.engine.state.state == AutomationState.MONITORING:
            self.status_var.set("Status: Monitoring")
            self.progress.start(10)
        elif self.engine.state.state == AutomationState.CLICKING:
            self.status_var.set("Status: Simulating - Continuous Betting")
            self.progress.start(10)
        elif self.engine.state.state == AutomationState.RANDOM_BETTING:
            self.status_var.set("Status: Random Betting")
            self.progress.start(15)
        elif self.engine.state.state == AutomationState.ANALYZING:
            self.status_var.set(f"Status: {self.status_mode_label}")
            self.progress.start(20)
        elif self.engine.state.state == AutomationState.WAITING_FOR_COLUMNS:
            self.status_var.set(f"Status: {self.status_mode_label}")
            self.progress.start(5)
    
    def start_calibration(self):
        start_calibration_action(self)
    
    def start_monitoring(self):
        start_monitoring_action(self)
    
    def start_random_betting(self):
        start_random_betting_action(self)
    
    def start_clicking(self):
        start_auto_bet(self)
    
    def toggle_pause(self):
        toggle_pause_action(self)
    
    def exit_app(self):
        exit_app_action(self)

    def show_click_mark(self, x: int, y: int):
        """Show a small red mark at click coordinates that disappears after 2 seconds"""
        try:
            dot_size = 8
            offset = dot_size // 2
            mark_window = tk.Toplevel(self.root)
            mark_window.attributes("-topmost", True)
            mark_window.overrideredirect(True)
            mark_window.geometry(f"{dot_size}x{dot_size}+{x-offset}+{y-offset}")
            
            canvas = tk.Canvas(mark_window, width=dot_size, height=dot_size, bg="", highlightthickness=0)
            canvas.pack()
            
            canvas.create_oval(1, 1, dot_size - 1, dot_size - 1, fill="red", outline="red")
            
            try:
                mark_window.attributes("-alpha", 0.9)
            except:
                pass
            
            def destroy_mark():
                try:
                    mark_window.destroy()
                except:
                    pass
            
            mark_window.after(2000, destroy_mark)
            
        except Exception as e:
            logger.error(f"Failed to show click mark: {e}")

def main():
    try:
        import PIL
        import pyautogui
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Please install: pip install pillow pyautogui")
        return
    
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    
    root = tk.Tk()
    app = AutoClickerPro(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.exit_app()


if __name__ == "__main__":
    main()
