# ============ FILE: bet.py (COMPLETE ENHANCED VERSION) ============
import tkinter as tk
from tkinter import messagebox, ttk
import ctypes
from ctypes import wintypes
import pyautogui
import json
import csv
import os
import shutil
import sys
import time
import random
import threading
from pathlib import Path
from PIL import ImageGrab, ImageTk
from typing import Dict, List, Tuple, Optional
import logging
from datetime import datetime
from collections import Counter
import traceback
import statistics
import math

from autoclick_runtime import (
    ClickPlanError,
    build_bet_plan,
    create_click_actions,
    format_bet_plan,
    perform_click_actions,
)
from capture import ColorMatcher, GameAnalyzer, ScreenCaptureManager
from models import (
    AppConfig,
    AutomationState,
    CalibrationPoint,
    GameState,
    ThreadSafeState,
    DecisionRecord,
    DecisionStats,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


APP_NAME = "AutoClickerPro"


if os.name == "nt":
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040
    HWND_TOPMOST = wintypes.HWND(-1)
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND


def _get_window_text(hwnd: int) -> str:
    if os.name != "nt":
        return ""

    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def is_brave_window(hwnd: int) -> bool:
    if os.name != "nt" or not hwnd:
        return False

    if not user32.IsWindowVisible(hwnd):
        return False

    title = _get_window_text(hwnd)
    return bool(title and "brave" in title.lower())


def find_brave_window(preferred_hwnd: Optional[int] = None) -> Optional[int]:
    if os.name != "nt":
        return None

    if preferred_hwnd and is_brave_window(preferred_hwnd):
        return int(preferred_hwnd)

    foreground_hwnd = int(user32.GetForegroundWindow() or 0)
    if foreground_hwnd and is_brave_window(foreground_hwnd):
        return foreground_hwnd

    matches: List[int] = []

    @EnumWindowsProc
    def enum_windows_proc(hwnd, _lparam):
        try:
            if not is_brave_window(hwnd):
                return True
            matches.append(int(hwnd))
        except Exception:
            logger.exception("EnumWindows callback failed")
        return True

    user32.EnumWindows(enum_windows_proc, 0)
    return matches[0] if matches else None


def force_brave_window_on_top() -> bool:
    if os.name != "nt":
        return False

    hwnd = find_brave_window()
    if not hwnd:
        return False

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return True


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    if os.name != "nt" or not hwnd:
        return None

    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None

    return (
        int(rect.left),
        int(rect.top),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
    )


def restore_window_rect(hwnd: int, rect: Tuple[int, int, int, int], bring_to_front: bool = False) -> bool:
    if os.name != "nt" or not hwnd:
        return False

    x, y, width, height = rect

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    success = bool(user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST if bring_to_front else wintypes.HWND(0),
        x,
        y,
        width,
        height,
        SWP_SHOWWINDOW,
    ))
    if bring_to_front and success:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    return success


def get_runtime_data_dir() -> Path:
    """Return a writable directory for runtime data in both .py and .exe modes."""
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME

    return Path(__file__).resolve().parent / "config"


def get_legacy_config_dir() -> Path:
    """Old save location used before the executable-safe path fix."""
    base_path = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base_path / "config"


def ensure_runtime_data_dir() -> Path:
    runtime_dir = get_runtime_data_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def migrate_legacy_runtime_files(runtime_dir: Path):
    """Copy old config/calibration files into the new writable runtime directory once."""
    legacy_dir = get_legacy_config_dir()
    if legacy_dir.resolve() == runtime_dir.resolve() or not legacy_dir.exists():
        return

    for filename in ("app_config.json", "calibration.json", "calibration_frame.png", "simulate_results.csv", "simulate_round_detector.png"):
        source_path = legacy_dir / filename
        target_path = runtime_dir / filename
        if source_path.exists() and not target_path.exists():
            try:
                shutil.copy2(source_path, target_path)
            except Exception as exc:
                logger.warning(f"Failed to migrate {source_path} to {target_path}: {exc}")


def configure_file_logging(runtime_dir: Path):
    """Persist terminal-style logging to logs/terminal.log for all modules."""
    logs_dir = runtime_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / "terminal.log"
    resolved_log_path = str(log_path.resolve())
    root_logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            base_filename = getattr(handler, "baseFilename", None)
            if base_filename == resolved_log_path:
                return
            if base_filename and Path(base_filename).name == "application.log":
                root_logger.removeHandler(handler)
                handler.close()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


class EventLogger:
    """Keep recent events in memory while routing file output to terminal.log."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.logs_dir = config_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.terminal_log_path = self.logs_dir / "terminal.log"
        self.recent_events = []
        self.max_recent_events = 100

    def log_event(self, event_type: str, description: str, **kwargs):
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "session_id": self.session_id,
            "event_type": event_type,
            "description": description,
            "data": kwargs,
        }

        self.recent_events.insert(0, {
            "timestamp": timestamp,
            "type": event_type,
            "description": description,
            "data": kwargs,
        })
        self.recent_events = self.recent_events[:self.max_recent_events]

        logger.info(description)
        logger.debug("Event details: %s", log_entry)

    def log_error(self, error_type: str, error: Exception, context: dict = None):
        details = context or {}
        logger.error("%s: %s | context=%s", error_type, error, details)
        logger.debug("Traceback for %s", error_type, exc_info=True)
        self.log_event("ERROR", f"{error_type}: {str(error)}", **{k: str(v) for k, v in details.items()})

    def export_for_ai(self) -> str:
        export_data = {
            "session_id": self.session_id,
            "export_time": datetime.now().isoformat(),
            "logs_directory": str(self.logs_dir),
            "log_files": {
                "terminal_log": str(self.terminal_log_path)
            },
            "recent_events": self.recent_events[:50]
        }
        return json.dumps(export_data, indent=2, ensure_ascii=False)

    def get_session_summary(self) -> str:
        summary = {
            "session_id": self.session_id,
            "start_time": self.session_id.replace("_", " "),
            "log_directory": str(self.logs_dir),
            "terminal_log": str(self.terminal_log_path),
            "recent_events_count": len(self.recent_events)
        }
        return json.dumps(summary, indent=2)


class AutomationEngine:
    def __init__(self, config: AppConfig, capture_mgr: ScreenCaptureManager, 
                 color_matcher: ColorMatcher, game_analyzer: GameAnalyzer, 
                 app: Optional['AutoClickerPro'] = None):
        self.config = config
        self.capture_mgr = capture_mgr
        self.game_analyzer = game_analyzer
        self.app = app
        self.state = ThreadSafeState()
        
        self._monitor_thread: Optional[threading.Thread] = None
        self._simulate_thread: Optional[threading.Thread] = None
        self._autoclick_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._simulate_halted = False
        self.last_bet_color: Optional[str] = None
        self.last_bet_value: Optional[str] = None
        self.last_bet_amount: Optional[str] = None
        self.last_result: Optional[str] = None
        self.last_c1_boxes: List[str] = []
        self.c1_history: List[List[str]] = []
        self.pending_round_number = 1
        self.round_count = 0
        self.detected_round_count = 0
        self.display_round_counter = 0
        self._last_display_round_signature: Optional[Tuple[Tuple[int, Tuple[str, ...]], ...]] = None
        self.win_count = 0
        self.lose_count = 0
        self.profit_total = 0.0
        self.loss_streak = 0
        self.bet_amount_steps = self._build_virtual_bet_steps(
            start=self.config.martingale_start,
            max_steps=self.config.martingale_max_steps,
            flat_cap=self.config.max_bet_per_round,
        )
        self.martingale_index = 0
        self.max_loss_streak = len(self.bet_amount_steps)
        self.bet_mode = "martingale"
        self.fib_prev_bet: Optional[int] = None
        self.fib_curr_bet: Optional[int] = None
        self.fib_history: List[int] = []
        self.last_prediction = "None"
        self.last_decision_reason = "Waiting for C1 history"
        self.last_decision_csv_reason = "WAIT_HISTORY"
        self.last_decision_score = 0.0
        self.last_decision_gap = 0.0
        self.last_decision_probability = 0.0
        self.last_expected_value = 0.0
        self.last_probability_edge = 0.0
        self.last_probability_samples = 0
        self.last_skip_reason = ""
        self.last_skip_csv_reason = ""
        self.last_regime = "RANGE"
        self.last_regime_reason = "Waiting for enough history"
        self._scheduled_idle_trigger_date: Optional[str] = None
        self._scheduled_idle_waiting_for_win = False
        self._brave_lock_hwnd: Optional[int] = None
        self._brave_lock_rect: Optional[Tuple[int, int, int, int]] = None
        
        # NEW: Decision tracking
        self.decision_history: List[DecisionRecord] = []
        self.decision_stats = DecisionStats()
        self.learning_mode = self.config.adaptive_learning_enabled
        self.last_decision_time = 0.0
        
        # Performance metrics
        self.start_time = time.time()
        self.total_clicks = 0
        self.last_performance_log = time.time()
        
        # Session recovery
        self._load_session_state()

    @staticmethod
    def _build_virtual_bet_steps(start: int, max_steps: int, flat_cap: Optional[int] = None) -> List[int]:
        steps = [start]
        while len(steps) < max_steps:
            next_step = (steps[-1] * 2) + start
            if flat_cap is not None:
                next_step = min(next_step, flat_cap)
            steps.append(next_step)
        return steps

    @staticmethod
    def _thread_is_running(thread: Optional[threading.Thread]) -> bool:
        return thread is not None and thread.is_alive()

    @staticmethod
    def _is_in_daily_idle_window(now: Optional[datetime] = None) -> bool:
        current = now or datetime.now()
        return (current.hour, current.minute) >= (3, 0) and (current.hour, current.minute) < (5, 0)

    def _is_daily_idle_due(self, now: Optional[datetime] = None) -> bool:
        current = now or datetime.now()
        if not self._is_in_daily_idle_window(current):
            return False
        today = current.strftime("%Y-%m-%d")
        return self._scheduled_idle_trigger_date != today

    def _request_idle_shutdown(self, message: str):
        self._clear_pending_bet()
        self._scheduled_idle_waiting_for_win = False
        self.state.set_monitor_idle_until(0)
        self.state.update_status(message)
        self._stop_event.set()
        self.state.state = AutomationState.IDLE
        self._save_session_state()

    def _handle_daily_idle_cutoff(self, prefix: str, first_round: bool = False) -> bool:
        if self._scheduled_idle_waiting_for_win:
            return False

        now = datetime.now()
        if not self._is_daily_idle_due(now):
            return False

        self._scheduled_idle_trigger_date = now.strftime("%Y-%m-%d")

        if first_round or self.loss_streak <= 0:
            self._request_idle_shutdown(
                f"{prefix}: 03:00 cutoff reached. Status set to Idle; manual restart required after 05:00 AM."
            )
            return True

        self._scheduled_idle_waiting_for_win = True
        self.state.update_status(
            f"{prefix}: 03:00 reached with active recovery. Extending until next WIN, then Idle."
        )
        return False

    def _stop_worker_threads(self, timeout: float = 2.5):
        for thread in (self._monitor_thread, self._simulate_thread, self._autoclick_thread):
            if self._thread_is_running(thread):
                thread.join(timeout=timeout)

    def _ensure_brave_on_top(self, context: str = ""):
        if force_brave_window_on_top():
            if context:
                logger.debug("Brave forced on top for %s", context)
        elif context:
            logger.debug("Brave window not found for %s", context)

    def _clear_brave_window_lock(self):
        self._brave_lock_hwnd = None
        self._brave_lock_rect = None

    def _get_resume_round_signature(
        self,
        game_state: Optional[GameState] = None,
    ) -> Optional[Tuple[Tuple[int, Tuple[str, ...]], ...]]:
        current_state = game_state or self.state.get_game_state()
        if (
            not current_state
            or current_state.any_unknown
            or current_state.has_invalid_board_pattern
            or self._is_cycle_reset_state(current_state)
        ):
            return None

        active_round = self._get_active_round_info(current_state)
        if not active_round:
            return None

        return active_round["signature"]

    def _arm_brave_window_lock(self, context: str = "") -> bool:
        if os.name != "nt" or not self.config.lock_brave_window_enabled:
            self._clear_brave_window_lock()
            return False

        hwnd = find_brave_window()
        if not hwnd:
            logger.warning("Brave lock skipped%s: window not found", f" for {context}" if context else "")
            self._clear_brave_window_lock()
            return False

        rect = None
        if self.app and hasattr(self.app, "get_saved_brave_rect"):
            rect = self.app.get_saved_brave_rect()

        if rect is None:
            rect = get_window_rect(hwnd)
        if not rect:
            logger.warning("Brave lock skipped%s: could not read window bounds", f" for {context}" if context else "")
            self._clear_brave_window_lock()
            return False

        self._brave_lock_hwnd = hwnd
        self._brave_lock_rect = rect
        logger.info("Brave lock armed%s at %s", f" for {context}" if context else "", rect)
        return True

    def _enforce_brave_window_lock(self, context: str = "", bring_to_front: bool = False) -> bool:
        if os.name != "nt" or not self.config.lock_brave_window_enabled:
            return False

        hwnd = self._brave_lock_hwnd
        target_rect = self._brave_lock_rect
        if not hwnd or not target_rect:
            if not self._arm_brave_window_lock(context):
                return False
            hwnd = self._brave_lock_hwnd
            target_rect = self._brave_lock_rect
            if not hwnd or not target_rect:
                return False

        current_rect = get_window_rect(hwnd)
        if current_rect != target_rect:
            success = restore_window_rect(hwnd, target_rect, bring_to_front=bring_to_front)
            if success:
                logger.info("Brave lock restored%s to %s", f" for {context}" if context else "", target_rect)
            return success

        if bring_to_front:
            return restore_window_rect(hwnd, target_rect, bring_to_front=True)

        return True

    def _get_active_round_info(self, game_state: Optional[GameState]) -> Optional[Dict[str, object]]:
        if not game_state or not game_state.columns or game_state.has_invalid_board_pattern:
            return None

        valid_suffix: List[Tuple[int, Tuple[str, ...]]] = []
        for column in reversed(game_state.columns[:self.config.total_columns]):
            if column.all_boxes_known and all(box in self.config.color_labels for box in column.boxes):
                valid_suffix.append((column.column_index, tuple(column.boxes)))
                continue
            break

        if not valid_suffix:
            return None

        valid_suffix.reverse()
        basis_index, basis_boxes = valid_suffix[0]
        return {
            "basis_index": basis_index,
            "boxes": list(basis_boxes),
            "valid_count": len(valid_suffix),
            "signature": tuple(valid_suffix),
        }

    @staticmethod
    def _calculate_history_overlap(
        stored_history: List[List[str]],
        visible_history: List[List[str]],
    ) -> int:
        max_overlap = min(len(stored_history), len(visible_history))
        for overlap in range(max_overlap, 0, -1):
            if stored_history[-overlap:] == visible_history[:overlap]:
                return overlap
        return 0

    def _get_visible_round_history(self, game_state: Optional[GameState]) -> List[List[str]]:
        active_round = self._get_active_round_info(game_state)
        if not active_round:
            return []

        signature = active_round["signature"]
        # Signature is newest->oldest within the valid suffix; reverse it so
        # history remains oldest->newest like c1_history.
        return [list(boxes) for _column_index, boxes in reversed(signature)]

    def _get_effective_round_history(
        self,
        game_state: Optional[GameState],
        limit: Optional[int] = None,
    ) -> List[List[str]]:
        stored_history = [list(round_boxes) for round_boxes in self.c1_history]
        visible_history = self._get_visible_round_history(game_state)

        if visible_history:
            overlap = self._calculate_history_overlap(stored_history, visible_history)
            combined_history = stored_history + visible_history[overlap:]
        else:
            combined_history = stored_history

        if limit is not None:
            return combined_history[-limit:]
        return combined_history

    def _update_display_round_counter(self, game_state: Optional[GameState]):
        if self._is_cycle_reset_state(game_state):
            logger.info("Cycle counter reset to 0: confidence dropped to 0")
            self.display_round_counter = 0
            self._last_display_round_signature = None
            return

        active_round = self._get_active_round_info(game_state)
        if not active_round:
            return

        signature = active_round["signature"]
        if signature == self._last_display_round_signature:
            return

        if self.display_round_counter <= 0:
            self.display_round_counter = int(active_round["valid_count"])
        else:
            self.display_round_counter = 1 if self.display_round_counter >= 100 else self.display_round_counter + 1

        self._last_display_round_signature = signature

    def _advance_detected_round_count(self):
        self.detected_round_count += 1

    def _reset_progression(self):
        self.bet_mode = "martingale"
        self.martingale_index = 0
        self.fib_prev_bet = None
        self.fib_curr_bet = None
        self.fib_history = []

    def _get_current_target_amount(self) -> int:
        if self.bet_mode == "fibonacci" and self.fib_prev_bet is not None and self.fib_curr_bet is not None:
            return self.fib_prev_bet + self.fib_curr_bet
        return self.bet_amount_steps[self.martingale_index]

    def _activate_fibonacci_mode(self, previous_bet: int, current_bet: int):
        self.bet_mode = "fibonacci"
        self.fib_prev_bet = previous_bet
        self.fib_curr_bet = current_bet
        self.fib_history = [previous_bet, current_bet]
        self.state.update_status(
            f"Progression switched to Fibonacci after {self.loss_streak} losses: next bet {previous_bet + current_bet}"
        )
    
    def _load_session_state(self):
        if self.app and hasattr(self.app, 'config_dir'):
            session_path = self.app.config_dir / "session_backup.json"
            if session_path.exists():
                try:
                    with open(session_path, 'r') as f:
                        session = json.load(f)
                    self.round_count = session.get("round_count", 0)
                    self.detected_round_count = session.get("detected_round_count", self.round_count)
                    self.win_count = session.get("win_count", 0)
                    self.lose_count = session.get("lose_count", 0)
                    self.profit_total = session.get("profit_total", 0.0)
                    self.loss_streak = session.get("loss_streak", 0)
                    self.martingale_index = session.get("martingale_index", 0)
                    self.c1_history = session.get("c1_history", [])
                    self.bet_mode = session.get("bet_mode", "martingale")
                    self.fib_prev_bet = session.get("fib_prev_bet")
                    self.fib_curr_bet = session.get("fib_curr_bet")
                    self.fib_history = session.get("fib_history", [])
                    if self.bet_mode == "fibonacci" and (
                        self.fib_prev_bet is None or self.fib_curr_bet is None
                    ):
                        self._reset_progression()
                    logger.info(f"Session recovered: {self.round_count} rounds, profit: {self.profit_total:.2f}")
                except Exception as e:
                    logger.error(f"Failed to load session: {e}")
    
    def _save_session_state(self):
        if self.app and hasattr(self.app, 'config_dir'):
            session = {
                "round_count": self.round_count,
                "detected_round_count": self.detected_round_count,
                "win_count": self.win_count,
                "lose_count": self.lose_count,
                "profit_total": self.profit_total,
                "loss_streak": self.loss_streak,
                "martingale_index": self.martingale_index,
                "bet_mode": self.bet_mode,
                "fib_prev_bet": self.fib_prev_bet,
                "fib_curr_bet": self.fib_curr_bet,
                "fib_history": self.fib_history[-20:],
                "c1_history": self.c1_history[-30:],
                "timestamp": datetime.now().isoformat()
            }
            try:
                session_path = self.app.config_dir / "session_backup.json"
                with open(session_path, 'w') as f:
                    json.dump(session, f, indent=2)
                logger.debug("Session state saved")
            except Exception as e:
                logger.error(f"Failed to save session: {e}")
    
    def _log_performance(self):
        if self.round_count > 0 and self.round_count % 100 == 0:
            elapsed = time.time() - self.start_time
            clicks_per_sec = self.total_clicks / elapsed if elapsed > 0 else 0
            rounds_per_hour = (self.round_count / elapsed) * 3600 if elapsed > 0 else 0
            logger.info(f"Performance: {clicks_per_sec:.2f} clicks/sec, {rounds_per_hour:.1f} rounds/hour")
            
            if hasattr(self.app, 'color_matcher'):
                cache_stats = self.app.color_matcher.get_cache_stats()
                logger.info(
                    "Color cache: %.1f%% hit rate (%s hits, %s misses, size %s/%s)",
                    cache_stats['hit_rate'],
                    cache_stats['hits'],
                    cache_stats['misses'],
                    cache_stats['cache_size'],
                    cache_stats['cache_maxsize'],
                )
    
    def _check_bet_limits(self, amount: int) -> bool:
        if amount > self.config.max_bet_per_round:
            self.state.update_status(f"Bet {amount} exceeds max {self.config.max_bet_per_round}")
            return False
        
        if self.config.loss_limit and self.profit_total <= -self.config.loss_limit:
            self.state.update_status(f"Loss limit reached: ${self.profit_total:.2f}")
            self._stop_event.set()
            return False
        
        if self.config.profit_target and self.profit_total >= self.config.profit_target:
            self.state.update_status(f"Profit target reached: ${self.profit_total:.2f}")
            self._stop_event.set()
            return False
        
        return True

    def start_monitoring(self) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        if not self.capture_mgr.validate_calibration():
            self.state.update_status("Calibration validation failed - points off-screen")
            return False
        if self._monitor_thread and self._monitor_thread.is_alive():
            return True
        self._stop_event.clear()
        self._clear_pending_bet()
        self._arm_brave_window_lock("monitor")
        self.state.state = AutomationState.MONITORING
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="MonitorThread", daemon=True)
        self._monitor_thread.start()
        return True
    
    def stop_all(self):
        self._stop_event.set()
        self._stop_worker_threads()
        self._simulate_halted = False
        self._clear_brave_window_lock()
        self.state.set_monitor_idle_until(0)
        self.state.state = AutomationState.IDLE
        self._save_session_state()

    def reset_records(self):
        self.stop_all()
        self.last_bet_color = None
        self.last_bet_value = None
        self.last_bet_amount = None
        self.last_result = None
        self.last_c1_boxes = []
        self.c1_history = []
        self.pending_round_number = 1
        self.round_count = 0
        self.detected_round_count = 0
        self.display_round_counter = 0
        self._last_display_round_signature = None
        self.win_count = 0
        self.lose_count = 0
        self.profit_total = 0.0
        self.loss_streak = 0
        self.martingale_index = 0
        self.bet_mode = "martingale"
        self.fib_prev_bet = None
        self.fib_curr_bet = None
        self.fib_history = []
        self.last_prediction = "None"
        self.last_decision_reason = "Waiting for C1 history"
        self.last_decision_csv_reason = "WAIT_HISTORY"
        self.last_decision_score = 0.0
        self.last_decision_gap = 0.0
        self.last_decision_probability = 0.0
        self.last_expected_value = 0.0
        self.last_probability_edge = 0.0
        self.last_probability_samples = 0
        self.last_skip_reason = ""
        self.last_skip_csv_reason = ""
        self.last_regime = "RANGE"
        self.last_regime_reason = "Waiting for enough history"
        self._scheduled_idle_trigger_date = None
        self._scheduled_idle_waiting_for_win = False
        self.start_time = time.time()
        self.total_clicks = 0
        self.decision_history = []
        self.decision_stats = DecisionStats()
        self.state.set_game_state(None)
        self.state.set_monitor_idle_until(0)
        self.state.update_status("Records reset. Status set to Idle.")
        
        if self.app and hasattr(self.app, 'config_dir'):
            session_path = self.app.config_dir / "session_backup.json"
            if session_path.exists():
                session_path.unlink()

    def start_simulation(self) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        if not self.capture_mgr.validate_calibration():
            self.state.update_status("Calibration validation failed - points off-screen")
            return False
        if self._simulate_thread and self._simulate_thread.is_alive() and not self._stop_event.is_set():
            return True
        if self._simulate_thread and self._simulate_thread.is_alive():
            self._simulate_thread.join(timeout=2)
        self._stop_event.clear()
        self._simulate_halted = False
        self._arm_brave_window_lock("simulate")
        self.state.state = AutomationState.SIMULATING
        self._simulate_thread = threading.Thread(target=self._simulate_round, name="SimulateThread", daemon=True)
        self._simulate_thread.start()
        return True

    def start_autoclick(self) -> bool:
        if not self.capture_mgr.is_fully_calibrated():
            return False
        if not self.capture_mgr.validate_calibration():
            self.state.update_status("Calibration validation failed - points off-screen")
            return False
        if self._autoclick_thread and self._autoclick_thread.is_alive() and not self._stop_event.is_set():
            return True
        if self._autoclick_thread and self._autoclick_thread.is_alive():
            self._autoclick_thread.join(timeout=2)
        self._stop_event.clear()
        self._simulate_halted = False
        self._arm_brave_window_lock("autoclick")
        self.state.state = AutomationState.AUTOCLICKING
        self._autoclick_thread = threading.Thread(target=self._autoclick_loop, name="AutoClickThread", daemon=True)
        self._autoclick_thread.start()
        return True
    
    def _get_confidence_level(
        self,
        score: float,
        gap: float,
        decision_probability: float = 0.0,
        expected_value: float = 0.0,
    ) -> str:
        if decision_probability >= 0.62 and expected_value >= 0.25:
            return "HIGH"
        elif decision_probability >= self.config.strategy_min_hit_probability and expected_value >= self.config.strategy_min_expected_value:
            return "MEDIUM"
        elif decision_probability > 0 or score > 0 or gap > 0:
            return "LOW"
        return "SKIP"
    
    def _calculate_color_scores(self, game_state: GameState) -> Dict[str, float]:
        if not game_state or not game_state.columns:
            return {}
        
        scores = {color: 0.0 for color in self.config.color_labels}
        column_weights = (1.60, 1.25, 0.95, 0.75, 0.55, 0.40, 0.28)
        recent_focus = {0: 0.55, 1: 0.30, 2: 0.15}
        
        for column_index, column in enumerate(game_state.columns[:self.config.total_columns]):
            counts = Counter(color for color in column.boxes if color in self.config.color_labels)
            if not counts:
                continue
            
            base_weight = column_weights[min(column_index, len(column_weights) - 1)]
            for color, count in counts.items():
                scores[color] += base_weight * count
                if count >= 2:
                    scores[color] += base_weight * 0.35 * (count - 1)
                if column_index in recent_focus:
                    scores[color] += recent_focus[column_index] * count
        
        recent_c1 = self._get_effective_round_history(game_state, limit=4)
        history_weights = (0.90, 0.65, 0.45, 0.30)
        for history_index, c1_boxes in enumerate(reversed(recent_c1)):
            counts = Counter(color for color in c1_boxes if color in self.config.color_labels)
            history_weight = history_weights[min(history_index, len(history_weights) - 1)]
            for color, count in counts.items():
                scores[color] += history_weight * count
        
        return scores

    def _build_board_signal_snapshot(self, game_state: Optional[GameState]) -> Dict:
        scores = self._calculate_color_scores(game_state) if game_state else {}
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_color = ranked[0][0] if ranked else None
        top_score = ranked[0][1] if ranked else 0.0
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        gap = top_score - second_score

        top_recent_hits = 0
        if game_state and game_state.columns and top_color:
            top_recent_hits = sum(1 for column in game_state.columns[:3] if top_color in column.boxes)

        return {
            "scores": scores,
            "ranked": ranked,
            "top_color": top_color,
            "top_score": top_score,
            "second_score": second_score,
            "gap": gap,
            "top_recent_hits": top_recent_hits,
        }

    def _softmax_color_priors(self, scores: Dict[str, float], temperature: float = 3.0) -> Dict[str, float]:
        if not scores:
            return {}

        max_score = max(scores.values())
        exp_values = {
            color: math.exp((score - max_score) / max(0.5, temperature))
            for color, score in scores.items()
        }
        total = sum(exp_values.values())
        if total <= 0:
            uniform = 1.0 / max(1, len(scores))
            return {color: uniform for color in scores}
        return {color: value / total for color, value in exp_values.items()}

    def _build_probability_snapshot(
        self,
        game_state: Optional[GameState],
        regime_info: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        board_snapshot = self._build_board_signal_snapshot(game_state)
        board_priors = self._softmax_color_priors(board_snapshot["scores"])
        window = max(6, self.config.strategy_probability_window)
        history_rounds = self._get_effective_round_history(game_state, limit=window)
        sample_size = len(history_rounds)
        weighted_total = 0.0
        board_box_total = max(1, self.config.total_columns * self.config.boxes_per_column)
        front_box_total = max(1, min(3, self.config.total_columns) * self.config.boxes_per_column)
        smoothing = 0.75
        models = []

        recent_weights: List[float] = []
        if history_rounds:
            denominator = max(1, len(history_rounds) - 1)
            for index in range(len(history_rounds)):
                progress = index / denominator if denominator else 1.0
                recent_weights.append(0.65 + (0.85 * progress))
            weighted_total = sum(recent_weights)

        for color in self.config.color_labels:
            counts = [smoothing, smoothing, smoothing, smoothing]

            for round_boxes, weight in zip(history_rounds, recent_weights):
                hits = sum(1 for box in round_boxes if box == color)
                counts[min(3, hits)] += weight

            probabilities = [count / sum(counts) for count in counts]
            board_prior = board_priors.get(color, 1.0 / max(1, len(self.config.color_labels)))

            board_boxes = 0
            front_boxes = 0
            recent_hits = 0
            if game_state and game_state.columns:
                board_boxes = sum(
                    1
                    for column in game_state.columns[:self.config.total_columns]
                    for box in column.boxes
                    if box == color
                )
                front_boxes = sum(
                    1
                    for column in game_state.columns[:3]
                    for box in column.boxes
                    if box == color
                )
                recent_hits = sum(1 for column in game_state.columns[:3] if color in column.boxes)

            board_support = (
                (board_prior * 0.55)
                + ((front_boxes / front_box_total) * 0.30)
                + ((board_boxes / board_box_total) * 0.15)
            )
            uniform_support = 1.0 / max(1, len(self.config.color_labels))
            boost = 1.0 + ((board_support / uniform_support) - 1.0) * self.config.strategy_probability_board_weight
            boost = max(0.55, min(2.40, boost))

            adjusted = [
                probabilities[0] / max(0.65, boost),
                probabilities[1] * (0.92 + (0.08 * boost)),
                probabilities[2] * (0.80 + (0.20 * boost)),
                probabilities[3] * (0.65 + (0.35 * boost)),
            ]
            adjusted_total = sum(adjusted) or 1.0
            adjusted = [value / adjusted_total for value in adjusted]

            hit_probability = 1.0 - adjusted[0]
            double_probability = adjusted[2] + adjusted[3]
            triple_probability = adjusted[3]
            average_hits = adjusted[1] + (2.0 * adjusted[2]) + (3.0 * adjusted[3])
            expected_value = average_hits - adjusted[0]

            models.append({
                "color": color,
                "distribution": adjusted,
                "empirical_distribution": probabilities,
                "board_prior": board_prior,
                "board_support": board_support,
                "boost": boost,
                "board_boxes": board_boxes,
                "front_boxes": front_boxes,
                "top_recent_hits": recent_hits,
                "hit_probability": hit_probability,
                "double_probability": double_probability,
                "triple_probability": triple_probability,
                "average_hits": average_hits,
                "expected_value": expected_value,
            })

        ranked = sorted(
            models,
            key=lambda item: (item["expected_value"], item["hit_probability"], item["average_hits"]),
            reverse=True,
        )
        top_model = ranked[0] if ranked else None
        second_model = ranked[1] if len(ranked) > 1 else None

        probability_edge = 0.0
        hit_edge = 0.0
        if top_model and second_model:
            probability_edge = top_model["expected_value"] - second_model["expected_value"]
            hit_edge = top_model["hit_probability"] - second_model["hit_probability"]

        return {
            "sample_size": sample_size,
            "weighted_total": weighted_total,
            "regime": regime_info["mode"] if regime_info else "",
            "board_snapshot": board_snapshot,
            "ranked": ranked,
            "top_model": top_model,
            "second_model": second_model,
            "probability_edge": probability_edge,
            "hit_edge": hit_edge,
        }

    def _detect_decision_regime(self, game_state: Optional[GameState]) -> Dict[str, object]:
        if not self.config.strategy_regime_enabled:
            return {
                "mode": "RANGE",
                "reason": "Regime filter disabled",
                "dominant_ratio": 0.0,
                "change_rate": 0.0,
                "entropy": 0.0,
            }

        window = max(4, self.config.strategy_regime_window)
        recent_rounds = self._get_effective_round_history(game_state, limit=window)
        board_signal = self._build_board_signal_snapshot(game_state)

        if len(recent_rounds) < 4:
            return {
                "mode": "RANGE",
                "reason": f"Warmup: only {len(recent_rounds)}/{window} recent rounds",
                "dominant_ratio": 0.0,
                "change_rate": 0.0,
                "entropy": 0.0,
            }

        flattened = [
            color
            for round_boxes in recent_rounds
            for color in round_boxes
            if color in self.config.color_labels
        ]
        if not flattened:
            return {
                "mode": "RANGE",
                "reason": "Warmup: no recent color history",
                "dominant_ratio": 0.0,
                "change_rate": 0.0,
                "entropy": 0.0,
            }

        counts = Counter(flattened)
        dominant_color, dominant_count = counts.most_common(1)[0]
        dominant_ratio = dominant_count / len(flattened)

        round_leaders = []
        for round_boxes in recent_rounds:
            round_counts = Counter(color for color in round_boxes if color in self.config.color_labels)
            if round_counts:
                round_leaders.append(round_counts.most_common(1)[0][0])

        transitions = max(1, len(round_leaders) - 1)
        changes = sum(
            1 for previous, current in zip(round_leaders, round_leaders[1:])
            if previous != current
        )
        change_rate = changes / transitions

        probabilities = [count / len(flattened) for count in counts.values()]
        entropy = 0.0
        if probabilities:
            entropy = -sum(prob * math.log(prob, 2) for prob in probabilities if prob > 0)
            entropy /= math.log(len(self.config.color_labels), 2)

        if dominant_ratio >= 0.40 and change_rate <= 0.45 and board_signal["top_score"] >= self.config.strategy_min_score:
            return {
                "mode": "TREND",
                "reason": (
                    f"{dominant_color} dominates {dominant_ratio*100:.0f}% of recent C1 boxes, "
                    f"leader changes {change_rate*100:.0f}%"
                ),
                "dominant_ratio": dominant_ratio,
                "change_rate": change_rate,
                "entropy": entropy,
            }

        if entropy >= 0.90 and dominant_ratio <= 0.26 and (
            change_rate >= 0.70 or board_signal["gap"] < self.config.strategy_min_gap
        ):
            return {
                "mode": "CHAOS",
                "reason": (
                    f"High entropy {entropy:.2f}, weak dominance {dominant_ratio*100:.0f}%, "
                    f"leader changes {change_rate*100:.0f}%"
                ),
                "dominant_ratio": dominant_ratio,
                "change_rate": change_rate,
                "entropy": entropy,
            }

        return {
            "mode": "RANGE",
            "reason": (
                f"Balanced board: {dominant_color} at {dominant_ratio*100:.0f}%, "
                f"entropy {entropy:.2f}, leader changes {change_rate*100:.0f}%"
            ),
            "dominant_ratio": dominant_ratio,
            "change_rate": change_rate,
            "entropy": entropy,
        }

    def _get_regime_thresholds(self, regime: str) -> Dict[str, float]:
        min_score = self.config.strategy_min_score
        min_gap = self.config.strategy_min_gap
        recent_columns = self.config.strategy_recent_columns_required
        min_hit_probability = self.config.strategy_min_hit_probability
        min_expected_value = self.config.strategy_min_expected_value
        min_probability_edge = self.config.strategy_min_probability_edge
        min_probability_samples = self.config.strategy_probability_min_samples
        allow_only_strong_signal = False

        if regime == "TREND":
            min_score = max(2.0, min_score - 0.20)
            min_gap = max(0.30, min_gap - 0.10)
            recent_columns = max(1, recent_columns - 1)
            min_hit_probability = max(0.35, min_hit_probability - 0.03)
            min_expected_value = max(-0.05, min_expected_value - 0.04)
            min_probability_edge = max(0.01, min_probability_edge - 0.01)
            min_probability_samples = max(6, min_probability_samples - 1)
        elif regime == "CHAOS":
            min_score = min(5.5, min_score + 0.80)
            min_gap = min(2.00, min_gap + 0.35)
            recent_columns = min(3, recent_columns + 1)
            min_hit_probability = min(0.70, min_hit_probability + 0.08)
            min_expected_value = min(0.60, min_expected_value + 0.10)
            min_probability_edge = min(0.20, min_probability_edge + 0.03)
            min_probability_samples = min(self.config.strategy_probability_window, min_probability_samples + 2)
            allow_only_strong_signal = True

        return {
            "min_score": min_score,
            "min_gap": min_gap,
            "recent_columns": recent_columns,
            "min_hit_probability": min_hit_probability,
            "min_expected_value": min_expected_value,
            "min_probability_edge": min_probability_edge,
            "min_probability_samples": min_probability_samples,
            "allow_only_strong_signal": allow_only_strong_signal,
        }

    def _build_compact_decision_reason(
        self,
        chosen_color: Optional[str],
        regime: str,
        score: float,
        gap: float,
        decision_probability: float,
        expected_value: float,
        probability_edge: float,
        probability_samples: int,
        thresholds: Dict[str, float],
        runner_up: Optional[str] = None,
    ) -> str:
        if chosen_color:
            return (
                f"PICK|{regime}|{chosen_color}|P{decision_probability:.2f}"
                f"|EV{expected_value:.2f}|E{probability_edge:.2f}"
            )

        if probability_samples < thresholds["min_probability_samples"]:
            return (
                f"SKIP|{regime}|SAMPLES|{probability_samples}"
                f"<{thresholds['min_probability_samples']}"
            )
        if decision_probability < thresholds["min_hit_probability"]:
            return (
                f"SKIP|{regime}|PROB|{decision_probability:.2f}"
                f"<{thresholds['min_hit_probability']:.2f}"
            )
        if expected_value < thresholds["min_expected_value"]:
            return (
                f"SKIP|{regime}|EV|{expected_value:.2f}"
                f"<{thresholds['min_expected_value']:.2f}"
            )
        if probability_edge < thresholds["min_probability_edge"]:
            return (
                f"SKIP|{regime}|EDGE|{probability_edge:.2f}"
                f"<{thresholds['min_probability_edge']:.2f}|{runner_up or 'N/A'}"
            )
        if thresholds["allow_only_strong_signal"]:
            return (
                f"SKIP|{regime}|CHAOS_GATE|P{decision_probability:.2f}"
                f"|EV{expected_value:.2f}"
            )
        return f"SKIP|{regime}|OTHER|S{score:.2f}|G{gap:.2f}"

    def _record_decision(self, game_state: GameState, chosen_color: Optional[str],
                         amount: int, reason: str, reaction_time_ms: float = 0,
                         regime: str = "UNKNOWN", regime_reason: str = "",
                         active_thresholds: Optional[Dict[str, float]] = None,
                         probability_snapshot: Optional[Dict[str, object]] = None):
        snapshot = (probability_snapshot or {}).get("board_snapshot") if probability_snapshot else None
        if not snapshot:
            snapshot = self._build_board_signal_snapshot(game_state)
        top_score = snapshot["top_score"]
        gap = snapshot["gap"]
        active_thresholds = active_thresholds or {}
        top_model = (probability_snapshot or {}).get("top_model") or {}
        decision_probability = float(top_model.get("hit_probability", 0.0))
        expected_value = float(top_model.get("expected_value", 0.0))
        probability_edge = float((probability_snapshot or {}).get("probability_edge", 0.0))
        probability_samples = int((probability_snapshot or {}).get("sample_size", 0))
        
        decision = DecisionRecord(
            timestamp=time.time(),
            round_number=self.pending_round_number,
            predicted_color=chosen_color,
            actual_c1_boxes=list(game_state.columns[0].boxes) if game_state and game_state.columns else [],
            bet_amount=amount if chosen_color else 0,
            decision_score=top_score,
            decision_gap=gap,
            confidence_level=self._get_confidence_level(
                top_score,
                gap,
                decision_probability=decision_probability,
                expected_value=expected_value,
            ),
            decision_reason=reason,
            regime=regime,
            regime_reason=regime_reason,
            active_min_score=active_thresholds.get("min_score", self.config.strategy_min_score),
            active_min_gap=active_thresholds.get("min_gap", self.config.strategy_min_gap),
            active_recent_columns=active_thresholds.get("recent_columns", self.config.strategy_recent_columns_required),
            strong_signal_only=bool(active_thresholds.get("allow_only_strong_signal", False)),
            decision_probability=decision_probability,
            expected_value=expected_value,
            probability_edge=probability_edge,
            probability_samples=probability_samples,
            outcome="PENDING",
            reaction_time_ms=reaction_time_ms
        )
        
        self.decision_history.append(decision)
        self.decision_stats.total_decisions += 1
        
        if chosen_color:
            self.decision_stats.bets_placed += 1
            if decision.confidence_level == "HIGH":
                self.decision_stats.high_conf_bets += 1
            elif decision.confidence_level == "MEDIUM":
                self.decision_stats.medium_conf_bets += 1
            else:
                self.decision_stats.low_conf_bets += 1
        else:
            self.decision_stats.bets_skipped += 1
        
        if len(self.decision_history) > 1000:
            self.decision_history = self.decision_history[-1000:]
        
        if self.learning_mode and self.decision_stats.total_decisions % 50 == 0 and self.decision_stats.total_decisions > 0:
            self._adjust_thresholds()
        
    
    def _adjust_thresholds(self):
        if len(self.decision_history) < 50:
            return
        
        recent = self.decision_history[-50:]
        recent_bets = [d for d in recent if d.predicted_color]
        skip_rate = (len(recent) - len(recent_bets)) / len(recent) if recent else 0.0
        
        if len(recent_bets) < 20:
            return
        
        high_conf_bets = [d for d in recent_bets if d.confidence_level == "HIGH"]
        med_conf_bets = [d for d in recent_bets if d.confidence_level == "MEDIUM"]
        low_conf_bets = [d for d in recent_bets if d.confidence_level == "LOW"]
        close_edge_bets = [
            d for d in recent_bets
            if d.probability_edge <= self.config.strategy_min_probability_edge + 0.02
        ]
        
        high_conf_wins = len([d for d in high_conf_bets if d.outcome == "WIN"])
        med_conf_wins = len([d for d in med_conf_bets if d.outcome == "WIN"])
        low_conf_wins = len([d for d in low_conf_bets if d.outcome == "WIN"])
        close_edge_wins = len([d for d in close_edge_bets if d.outcome == "WIN"])
        
        high_win_rate = high_conf_wins / len(high_conf_bets) if high_conf_bets else 0
        med_win_rate = med_conf_wins / len(med_conf_bets) if med_conf_bets else 0
        low_win_rate = low_conf_wins / len(low_conf_bets) if low_conf_bets else 0
        close_edge_win_rate = close_edge_wins / len(close_edge_bets) if close_edge_bets else 0
        
        old_min_probability = self.config.strategy_min_hit_probability
        old_min_expected_value = self.config.strategy_min_expected_value
        old_min_probability_edge = self.config.strategy_min_probability_edge

        if high_win_rate > 0.62 and med_win_rate > 0.52:
            self.config.strategy_min_hit_probability = min(0.70, self.config.strategy_min_hit_probability + 0.01)
            logger.info(
                " Increasing min_hit_probability to %.2f (high-confidence bets performing well)",
                self.config.strategy_min_hit_probability,
            )
        elif high_win_rate < 0.45 and med_win_rate < 0.42:
            self.config.strategy_min_hit_probability = min(0.75, self.config.strategy_min_hit_probability + 0.02)
            logger.info(
                " Tightening min_hit_probability to %.2f (high-confidence bets underperform)",
                self.config.strategy_min_hit_probability,
            )
        elif skip_rate > 0.72 and high_win_rate > 0.58:
            self.config.strategy_min_hit_probability = max(0.32, self.config.strategy_min_hit_probability - 0.01)
            logger.info(
                " Relaxing min_hit_probability to %.2f (skip rate %.1f%%)",
                self.config.strategy_min_hit_probability,
                skip_rate * 100,
            )

        if len(close_edge_bets) >= 12:
            if close_edge_win_rate < 0.45:
                self.config.strategy_min_probability_edge = min(0.18, self.config.strategy_min_probability_edge + 0.01)
                logger.info(
                    " Increasing min_probability_edge to %.2f (close probability races underperform)",
                    self.config.strategy_min_probability_edge,
                )
            elif close_edge_win_rate > 0.58 and skip_rate > 0.35:
                self.config.strategy_min_probability_edge = max(0.01, self.config.strategy_min_probability_edge - 0.01)
                logger.info(
                    " Decreasing min_probability_edge to %.2f (close races holding up)",
                    self.config.strategy_min_probability_edge,
                )

        average_expected_value = statistics.mean(d.expected_value for d in recent_bets) if recent_bets else 0.0
        if average_expected_value < 0.02 and high_win_rate < 0.48:
            self.config.strategy_min_expected_value = min(0.40, self.config.strategy_min_expected_value + 0.02)
            logger.info(
                " Increasing min_expected_value to %.2f (expected edge not converting)",
                self.config.strategy_min_expected_value,
            )
        elif average_expected_value > 0.18 and skip_rate > 0.70:
            self.config.strategy_min_expected_value = max(-0.05, self.config.strategy_min_expected_value - 0.01)
            logger.info(
                " Decreasing min_expected_value to %.2f (strong edge with heavy skipping)",
                self.config.strategy_min_expected_value,
            )

        self.config.strategy_min_hit_probability = max(0.30, min(0.75, self.config.strategy_min_hit_probability))
        self.config.strategy_min_expected_value = max(-0.05, min(0.40, self.config.strategy_min_expected_value))
        self.config.strategy_min_probability_edge = max(0.01, min(0.18, self.config.strategy_min_probability_edge))

        changes = []
        if abs(old_min_probability - self.config.strategy_min_hit_probability) > 0.001:
            changes.append(
                f"min_hit_prob {old_min_probability:.2f} -> {self.config.strategy_min_hit_probability:.2f}"
            )
        if abs(old_min_expected_value - self.config.strategy_min_expected_value) > 0.001:
            changes.append(
                f"min_ev {old_min_expected_value:.2f} -> {self.config.strategy_min_expected_value:.2f}"
            )
        if abs(old_min_probability_edge - self.config.strategy_min_probability_edge) > 0.001:
            changes.append(
                f"min_edge {old_min_probability_edge:.2f} -> {self.config.strategy_min_probability_edge:.2f}"
            )

        if changes:
            self.state.update_status(" Adaptive threshold adjusted: " + ", ".join(changes))
            if self.app:
                self.app.config_dirty = True
    
    def _update_decision_outcome(self, round_number: int, c1_boxes: List[str], 
                                  multiplier: int, profit_change: float):
        for decision in self.decision_history:
            if decision.round_number == round_number:
                decision.outcome = "WIN" if multiplier > 0 else "LOSS"
                decision.multiplier = multiplier
                decision.profit_change = profit_change
                decision.actual_c1_boxes = c1_boxes
                
                if decision.confidence_level == "HIGH" and decision.outcome == "WIN":
                    self.decision_stats.high_conf_wins += 1
                elif decision.confidence_level == "MEDIUM" and decision.outcome == "WIN":
                    self.decision_stats.medium_conf_wins += 1
                elif decision.confidence_level == "LOW" and decision.outcome == "WIN":
                    self.decision_stats.low_conf_wins += 1
                break
    
    def _predict_color_from_game_state(
        self,
        game_state: Optional[GameState],
    ) -> Tuple[Optional[str], str, Dict, Dict[str, object]]:
        if not game_state or not game_state.columns:
            regime_info = self._detect_decision_regime(game_state)
            self.last_regime = regime_info["mode"]
            self.last_regime_reason = regime_info["reason"]
            return None, "No stable board data available", regime_info, {"sample_size": 0, "ranked": [], "board_snapshot": {}}

        snapshot = self._build_board_signal_snapshot(game_state)
        if not snapshot["scores"]:
            regime_info = self._detect_decision_regime(game_state)
            self.last_regime = regime_info["mode"]
            self.last_regime_reason = regime_info["reason"]
            return None, "No color data available", regime_info, {"sample_size": 0, "ranked": [], "board_snapshot": snapshot}

        regime_info = self._detect_decision_regime(game_state)
        self.last_regime = regime_info["mode"]
        self.last_regime_reason = regime_info["reason"]
        thresholds = self._get_regime_thresholds(regime_info["mode"])
        probability_snapshot = self._build_probability_snapshot(game_state, regime_info)
        top_model = probability_snapshot.get("top_model")
        second_model = probability_snapshot.get("second_model")
        if not top_model:
            return None, "No probability model available", regime_info, probability_snapshot

        if probability_snapshot["sample_size"] < thresholds["min_probability_samples"]:
            return None, (
                f"{regime_info['mode']} regime: need more samples "
                f"({probability_snapshot['sample_size']}/{thresholds['min_probability_samples']})"
            ), regime_info, probability_snapshot

        runner_up = second_model["color"] if second_model else "N/A"
        if top_model["hit_probability"] < thresholds["min_hit_probability"]:
            return None, (
                f"{regime_info['mode']} regime: {top_model['color']} hit probability "
                f"{top_model['hit_probability']:.2f} below {thresholds['min_hit_probability']:.2f}"
            ), regime_info, probability_snapshot

        if top_model["expected_value"] < thresholds["min_expected_value"]:
            return None, (
                f"{regime_info['mode']} regime: {top_model['color']} expected value "
                f"{top_model['expected_value']:.2f} below {thresholds['min_expected_value']:.2f}"
            ), regime_info, probability_snapshot

        if probability_snapshot["probability_edge"] < thresholds["min_probability_edge"]:
            return None, (
                f"{regime_info['mode']} regime: {top_model['color']} edge "
                f"{probability_snapshot['probability_edge']:.2f} vs {runner_up}"
            ), regime_info, probability_snapshot

        if thresholds["allow_only_strong_signal"] and (
            top_model["double_probability"] < 0.18 or top_model["boost"] < 1.05
        ):
            return None, (
                f"CHAOS regime: skip {top_model['color']} despite lead "
                f"(p2+ {top_model['double_probability']:.2f}, boost {top_model['boost']:.2f})"
            ), regime_info, probability_snapshot

        return top_model["color"], (
            f"{regime_info['mode']} probability pick {top_model['color']}: "
            f"hit {top_model['hit_probability']:.2f}, EV {top_model['expected_value']:.2f}, "
            f"edge {probability_snapshot['probability_edge']:.2f}"
        ), regime_info, probability_snapshot
    
    def _choose_next_bet(self, game_state: Optional[GameState] = None) -> Tuple[Optional[str], int, Dict]:
        start_time = time.time()
        
        chosen_color, reason, regime_info, probability_snapshot = self._predict_color_from_game_state(game_state)
        amount = self._get_current_target_amount()

        snapshot = probability_snapshot.get("board_snapshot") or self._build_board_signal_snapshot(game_state)
        scores = snapshot["scores"]
        top_score = snapshot["top_score"]
        gap = snapshot["gap"]
        top_model = probability_snapshot.get("top_model") or {}
        decision_probability = float(top_model.get("hit_probability", 0.0))
        expected_value = float(top_model.get("expected_value", 0.0))
        probability_edge = float(probability_snapshot.get("probability_edge", 0.0))
        confidence = self._get_confidence_level(
            top_score,
            gap,
            decision_probability=decision_probability,
            expected_value=expected_value,
        )
        
        alternatives = []
        if len(snapshot["ranked"]) > 1:
            for color, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)[1:4]:
                alternatives.append(f"{color}:{score:.1f}")

        active_thresholds = self._get_regime_thresholds(regime_info["mode"])
        compact_reason = self._build_compact_decision_reason(
            chosen_color=chosen_color,
            regime=regime_info["mode"],
            score=top_score,
            gap=gap,
            decision_probability=decision_probability,
            expected_value=expected_value,
            probability_edge=probability_edge,
            probability_samples=int(probability_snapshot.get("sample_size", 0)),
            thresholds=active_thresholds,
            runner_up=(probability_snapshot.get("second_model") or {}).get("color"),
        )
        
        decision_metadata = {
            "score": top_score,
            "gap": gap,
            "decision_probability": decision_probability,
            "expected_value": expected_value,
            "probability_edge": probability_edge,
            "probability_samples": int(probability_snapshot.get("sample_size", 0)),
            "confidence": confidence,
            "alternatives": alternatives,
            "martingale_step": self.martingale_index + 1,
            "bet_mode": self.bet_mode,
            "loss_streak": self.loss_streak,
            "recent_win_rate": self.win_count / self.round_count if self.round_count > 0 else 0,
            "regime": regime_info["mode"],
            "regime_reason": regime_info["reason"],
            "active_min_score": active_thresholds["min_score"],
            "active_min_gap": active_thresholds["min_gap"],
            "active_recent_columns": active_thresholds["recent_columns"],
            "regime_strong_signal_only": active_thresholds["allow_only_strong_signal"],
            "compact_reason": compact_reason,
        }
        
        reaction_time = (time.time() - start_time) * 1000
        
        if game_state:
            self._record_decision(
                game_state,
                chosen_color,
                amount,
                reason,
                reaction_time,
                regime=regime_info["mode"],
                regime_reason=regime_info["reason"],
                active_thresholds=active_thresholds,
                probability_snapshot=probability_snapshot,
            )
        
        if chosen_color:
            self.last_decision_reason = (
                f"[{regime_info['mode']}] {reason} | Conf:{confidence} "
                f"P:{decision_probability:.2f} EV:{expected_value:.2f} "
                f"| Score:{top_score:.1f} Gap:{gap:.1f} | Alt: {', '.join(alternatives[:2])}"
            )
        else:
            self.last_decision_reason = (
                f"[{regime_info['mode']}] {reason} "
                f"(P:{decision_probability:.2f} EV:{expected_value:.2f} "
                f"Score:{top_score:.1f} Gap:{gap:.1f})"
            )
        self.last_decision_csv_reason = compact_reason
        self.last_skip_csv_reason = compact_reason if not chosen_color else ""
        
        self.last_decision_score = top_score
        self.last_decision_gap = gap
        self.last_decision_probability = decision_probability
        self.last_expected_value = expected_value
        self.last_probability_edge = probability_edge
        self.last_probability_samples = int(probability_snapshot.get("sample_size", 0))
        
        return chosen_color, amount, decision_metadata

    def _record_result_boxes(self, result_boxes: List[str], prefix: str) -> bool:
        self.last_result = "/".join(result_boxes)
        self.last_c1_boxes = list(result_boxes)
        self.c1_history.append(list(result_boxes))
        self.c1_history = self.c1_history[-30:]
        
        if not self.last_bet_color:
            return False
        
        self.round_count += 1
        base_stake = self._current_stake_value()
        
        matches = sum(1 for box in result_boxes if box == self.last_bet_color)
        
        if matches == 3:
            multiplier = 3
        elif matches == 2:
            multiplier = 2
        elif matches == 1:
            multiplier = 1
        else:
            multiplier = 0
        
        if multiplier > 0:
            profit_change = base_stake * multiplier
            self.win_count += 1
            self.loss_streak = 0
            self._reset_progression()
            self.profit_total += profit_change
            result = "WIN"
        else:
            profit_change = -base_stake
            self.lose_count += 1
            self.loss_streak += 1
            self.profit_total += profit_change
            result = "LOSE"
            
            if self.loss_streak >= self.max_loss_streak:
                self.state.update_status(f" HALTED: {self.loss_streak} consecutive losses")
                self._simulate_halted = True
                self._stop_event.set()
            elif self.bet_mode == "fibonacci":
                if self.fib_curr_bet is None:
                    self.fib_curr_bet = int(base_stake)
                if self.fib_prev_bet is None:
                    self.fib_prev_bet = int(base_stake)
                self.fib_prev_bet, self.fib_curr_bet = self.fib_curr_bet, int(base_stake)
                self.fib_history.append(int(base_stake))
                self.fib_history = self.fib_history[-20:]
            else:
                previous_index = max(0, self.martingale_index - 1)
                previous_bet = self.bet_amount_steps[previous_index]
                self.martingale_index = min(self.martingale_index + 1, len(self.bet_amount_steps) - 1)
                if self.loss_streak >= 9 and int(base_stake) == 2555:
                    self._activate_fibonacci_mode(previous_bet, int(base_stake))
        
        self._update_decision_outcome(self.round_count, result_boxes, multiplier, profit_change)
        
        decision = next((d for d in self.decision_history if d.round_number == self.round_count), None)
        if decision:
            status_msg = (
                f"{prefix} {result}: {self.last_bet_color} vs {result_boxes} "
                f"| {multiplier}x | {decision.confidence_level} conf "
                f"(score:{decision.decision_score:.1f}) | "
                f"Profit: {profit_change:+.2f} (Total: {self.profit_total:.2f})"
            )
        else:
            status_msg = f"{prefix} {result}: {self.last_bet_color} vs {result_boxes} | Profit: {profit_change:+.2f}"
        
        self.state.update_status(status_msg)
        
        self._append_simulation_csv(
            mode=prefix,
            round_number=self.round_count,
            c1_result=self.last_result,
            color_betted=self.last_bet_color,
            amount=self.last_bet_amount or self.last_bet_value or "",
            result=f"{result} (x{multiplier})" if multiplier > 1 else result,
            lose_streak=self.loss_streak if result == "LOSE" else 0,
            multiplier=multiplier,
            profit_change=profit_change,
            total_profit=self.profit_total,
            decision_score=decision.decision_score if decision else 0,
            score_gap=decision.decision_gap if decision else 0,
            confidence=decision.confidence_level if decision else "UNKNOWN",
            regime=decision.regime if decision else self.last_regime,
            regime_reason=decision.regime_reason if decision else self.last_regime_reason,
            active_min_score=decision.active_min_score if decision else self.config.strategy_min_score,
            active_min_gap=decision.active_min_gap if decision else self.config.strategy_min_gap,
            active_recent_columns=decision.active_recent_columns if decision else self.config.strategy_recent_columns_required,
            regime_strong_signal_only=decision.strong_signal_only if decision else False,
            decision_probability=decision.decision_probability if decision else self.last_decision_probability,
            expected_value=decision.expected_value if decision else self.last_expected_value,
            probability_edge=decision.probability_edge if decision else self.last_probability_edge,
            probability_samples=decision.probability_samples if decision else self.last_probability_samples,
            decision_reason=self.last_decision_csv_reason,
            skip_reason=self.last_skip_csv_reason,
        )
        
        self._save_session_state()
        self.pending_round_number = self.round_count + 1

        if result == "WIN" and self._scheduled_idle_waiting_for_win:
            self._request_idle_shutdown(
                f"{prefix}: recovery WIN completed after 03:00. Status set to Idle; manual restart required after 05:00 AM."
            )
        
        if self.round_count % 50 == 0:
            self._log_decision_metrics()
        
        return True
    
    def _log_decision_metrics(self):
        if self.decision_stats.total_decisions == 0:
            return
        
        logger.info("=" * 60)
        logger.info("DECISION QUALITY METRICS")
        logger.info("=" * 60)
        logger.info(f"Total Decisions: {self.decision_stats.total_decisions}")
        logger.info(f"Bets Placed: {self.decision_stats.bets_placed} ({self.decision_stats.bets_placed/self.decision_stats.total_decisions*100:.1f}%)")
        logger.info(f"Bets Skipped: {self.decision_stats.bets_skipped} ({self.decision_stats.bets_skipped/self.decision_stats.total_decisions*100:.1f}%)")
        logger.info(f"")
        logger.info(f"High Confidence: {self.decision_stats.high_conf_bets} bets, {self.decision_stats.high_conf_wins} wins ({self.decision_stats.high_conf_win_rate*100:.1f}%)")
        logger.info(f"Medium Confidence: {self.decision_stats.medium_conf_bets} bets, {self.decision_stats.medium_conf_wins} wins ({self.decision_stats.medium_conf_win_rate*100:.1f}%)")
        logger.info(f"Low Confidence: {self.decision_stats.low_conf_bets} bets, {self.decision_stats.low_conf_wins} wins ({self.decision_stats.low_conf_win_rate*100:.1f}%)")
        logger.info("=" * 60)
        
        if self.app and hasattr(self.app, 'event_logger'):
            self.app.event_logger.log_event(
                "DECISION_METRICS",
                f"Decision quality report at round {self.round_count}",
                total_decisions=self.decision_stats.total_decisions,
                bets_placed=self.decision_stats.bets_placed,
                high_conf_win_rate=f"{self.decision_stats.high_conf_win_rate*100:.1f}%",
                medium_conf_win_rate=f"{self.decision_stats.medium_conf_win_rate*100:.1f}%",
                current_threshold=self.config.strategy_min_score
            )
    
    def get_decision_analytics(self) -> Dict:
        if len(self.decision_history) == 0:
            return {"status": "No decisions recorded yet"}
        
        recent = self.decision_history[-100:]
        recent_bets = [d for d in recent if d.predicted_color]
        reaction_times = [d.reaction_time_ms for d in recent if d.reaction_time_ms > 0]
        regime_counts = Counter(d.regime for d in recent if d.regime)
        active_thresholds = self._get_regime_thresholds(self.last_regime)
        
        analytics = {
            "total_decisions": self.decision_stats.total_decisions,
            "bets_placed": self.decision_stats.bets_placed,
            "skip_rate": self.decision_stats.bets_skipped / self.decision_stats.total_decisions if self.decision_stats.total_decisions > 0 else 0,
            "high_conf_win_rate": self.decision_stats.high_conf_win_rate,
            "medium_conf_win_rate": self.decision_stats.medium_conf_win_rate,
            "low_conf_win_rate": self.decision_stats.low_conf_win_rate,
            "avg_decision_time_ms": statistics.mean(reaction_times) if reaction_times else 0,
            "avg_decision_probability": statistics.mean(
                d.decision_probability for d in recent_bets
            ) if recent_bets else 0,
            "avg_expected_value": statistics.mean(
                d.expected_value for d in recent_bets
            ) if recent_bets else 0,
            "current_thresholds": {
                "min_score": self.config.strategy_min_score,
                "min_gap": self.config.strategy_min_gap,
                "recent_columns": self.config.strategy_recent_columns_required,
                "min_hit_probability": self.config.strategy_min_hit_probability,
                "min_expected_value": self.config.strategy_min_expected_value,
                "min_probability_edge": self.config.strategy_min_probability_edge,
                "min_probability_samples": self.config.strategy_probability_min_samples,
            },
            "active_regime_thresholds": {
                "min_score": active_thresholds["min_score"],
                "min_gap": active_thresholds["min_gap"],
                "recent_columns": active_thresholds["recent_columns"],
                "min_hit_probability": active_thresholds["min_hit_probability"],
                "min_expected_value": active_thresholds["min_expected_value"],
                "min_probability_edge": active_thresholds["min_probability_edge"],
                "min_probability_samples": active_thresholds["min_probability_samples"],
            },
            "learning_mode": self.learning_mode,
            "active_regime": self.last_regime,
            "active_regime_reason": self.last_regime_reason,
            "regime_counts": dict(regime_counts),
        }
        
        if self.decision_stats.high_conf_win_rate < 0.45 and self.decision_stats.high_conf_bets > 20:
            analytics["suggestion"] = " High confidence bets are weak - tighten min_hit_probability or min_expected_value"
        elif self.decision_stats.high_conf_win_rate > 0.65 and self.decision_stats.high_conf_bets > 20:
            analytics["suggestion"] = " High confidence bets are holding up - probability filter is behaving well"
        elif self.decision_stats.bets_skipped / self.decision_stats.total_decisions > 0.7:
            analytics["suggestion"] = " Skipping many rounds - consider easing min_hit_probability or min_expected_value slightly"
        
        return analytics

    def _current_stake_value(self) -> float:
        if not self.last_bet_amount:
            return 0.0

        amount_text = "".join(ch if ch.isdigit() or ch == "." else " " for ch in self.last_bet_amount)
        try:
            amount = float(amount_text.split()[0])
        except (IndexError, ValueError):
            return 0.0

        return amount

    def _is_100_confidence_round(self, game_state: GameState) -> bool:
        return (
            bool(game_state.columns)
            and not game_state.any_unknown
            and game_state.all_columns_full
            and game_state.confidence_score >= 100
        )

    def _get_simulation_image_path(self) -> Path:
        base_dir = self.app.config_dir if self.app else Path(__file__).resolve().parent
        return base_dir / "simulate_round_detector.png"

    def _get_simulation_csv_path(self) -> Path:
        base_dir = self.app.config_dir if self.app else Path(__file__).resolve().parent
        return base_dir / "simulate_results.csv"

    def _capture_detectable_round(self, save_image: bool) -> Optional[GameState]:
        with self.capture_mgr.capture_region() as (screenshot, bbox):
            if screenshot is None:
                return None
                
            game_state = self.game_analyzer.analyze_game_state(screenshot, bbox)
            self.state.set_game_state(game_state)
            self._update_display_round_counter(game_state)

            if self._is_cycle_reset_state(game_state):
                return game_state

            if not self._get_active_round_info(game_state):
                return None

            if save_image:
                screenshot.save(self._get_simulation_image_path())

            return game_state

    def _is_cycle_reset_state(self, game_state: Optional[GameState]) -> bool:
        if not game_state:
            return False

        if game_state.confidence_score > 0:
            return False

        # Reset only on blank/unknown detection states, not on the
        # uniform-pattern safeguard that also forces confidence to 0.
        return game_state.blank_detected or game_state.any_unknown or not game_state.columns

    def _handle_cycle_reset_cooldown(self, prefix: str) -> bool:
        message = f"{prefix}: blank/unknown confidence 0 detected, cycle counter reset. Pending bet preserved."
        self.state.update_status(message)
        return True

    def _is_cycle_bet_cooldown_active(self) -> bool:
        return self.display_round_counter >= 91 and not self._scheduled_idle_waiting_for_win

    def _record_cycle_bet_cooldown(self, prefix: str, result_boxes: List[str], record_history: bool = False):
        c1_result = "/".join(result_boxes)
        self.last_result = c1_result
        self.last_c1_boxes = list(result_boxes)
        if record_history:
            self.c1_history.append(list(result_boxes))
            self.c1_history = self.c1_history[-30:]

        cooldown_reason = f"COOLDOWN_CYCLE_91|counter={self.display_round_counter}"
        self.last_skip_reason = "Cycle cooldown active from counter 91; Martingale state preserved."
        self.last_skip_csv_reason = cooldown_reason
        self.state.update_status(
            f"{prefix} COOLDOWN C{self.display_round_counter}: recording only, next bet waits for cycle reset"
        )

        self._append_simulation_csv(
            mode=prefix,
            round_number=f"CD-{self.detected_round_count}",
            c1_result=c1_result,
            color_betted="",
            amount="",
            result="COOLDOWN",
            lose_streak=self.loss_streak,
            multiplier=0,
            profit_change=0.0,
            total_profit=self.profit_total,
            decision_score=self.last_decision_score,
            score_gap=self.last_decision_gap,
            confidence="COOLDOWN",
            regime=self.last_regime,
            regime_reason=self.last_regime_reason,
            active_min_score=self.config.strategy_min_score,
            active_min_gap=self.config.strategy_min_gap,
            active_recent_columns=self.config.strategy_recent_columns_required,
            regime_strong_signal_only=False,
            decision_probability=self.last_decision_probability,
            expected_value=self.last_expected_value,
            probability_edge=self.last_probability_edge,
            probability_samples=self.last_probability_samples,
            decision_reason="Cycle cooldown active; no new bet placed",
            skip_reason=cooldown_reason,
        )
        self._save_session_state()

    def _append_simulation_csv(self, **kwargs):
        csv_path = self._get_simulation_csv_path()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with open(csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                if needs_header:
                    writer.writerow([
                        "Timestamp", "Mode", "Round", "Result Boxes", "Color Bet", "Amount",
                        "Result", "Loss Streak", "Multiplier", "Profit Change", "Total Profit",
                        "Decision Score", "Score Gap", "Confidence", "Regime", "Regime Reason",
                        "Decision Probability", "Expected Value", "Probability Edge", "Probability Samples",
                        "Active Min Score", "Active Min Gap", "Active Recent Columns", "Strong Signal Only",
                        "Decision Reason", "Skip Reason"
                    ])
                writer.writerow([
                    timestamp,
                    kwargs.get("mode", ""),
                    kwargs.get("round_number", ""),
                    kwargs.get("c1_result", ""),
                    kwargs.get("color_betted", ""),
                    kwargs.get("amount", ""),
                    kwargs.get("result", ""),
                    kwargs.get("lose_streak", 0),
                    kwargs.get("multiplier", 1),
                    f"{kwargs.get('profit_change', 0):.2f}",
                    f"{kwargs.get('total_profit', 0):.2f}",
                    f"{kwargs.get('decision_score', 0):.2f}",
                    f"{kwargs.get('score_gap', 0):.2f}",
                    kwargs.get("confidence", ""),
                    kwargs.get("regime", ""),
                    kwargs.get("regime_reason", "")[:200],
                    f"{kwargs.get('decision_probability', 0):.4f}",
                    f"{kwargs.get('expected_value', 0):.4f}",
                    f"{kwargs.get('probability_edge', 0):.4f}",
                    kwargs.get("probability_samples", ""),
                    f"{kwargs.get('active_min_score', 0):.2f}",
                    f"{kwargs.get('active_min_gap', 0):.2f}",
                    kwargs.get("active_recent_columns", ""),
                    "YES" if kwargs.get("regime_strong_signal_only") else "NO",
                    kwargs.get("decision_reason", "")[:200],
                    kwargs.get("skip_reason", "")[:100]
                ])
        except Exception as e:
            logger.warning(f"CSV write error: {e}")

    def _record_simulated_bet(self, chosen_color: str, bet_amount_label: str, use_x2: bool):
        self.last_bet_color = chosen_color
        amount = bet_amount_label.replace("Bet ", "")
        self.last_bet_amount = amount
        self.last_bet_value = f"{bet_amount_label}{' + X2' if use_x2 else ''}"
        self.state.update_status(f"SIMULATED BET R{self.pending_round_number}: {chosen_color} / {self.last_bet_value}")

    def _execute_autoclick_bet(self, chosen_color: str, target_amount: int) -> bool:
        extra_points = self.capture_mgr.get_extra_points()

        try:
            placements = build_bet_plan(target_amount)
            actions = create_click_actions(extra_points, chosen_color, placements)
            
            self.total_clicks += len(actions)
            
            completed = perform_click_actions(
                actions,
                marker_callback=self.app.show_click_marker if self.app else None,
                stop_requested=self._stop_event.is_set,
                move_duration_range=(0.04, 0.09),
                settle_range=(0.02, 0.05),
                pause_range=(0.07, 0.12),
                click_hold_range=(0.02, 0.05),
                temporary_pause_override=0.0,
            )
            if not completed:
                self.state.update_status("AutoClick stopped before the bet finished.")
                return False

            self.last_bet_color = chosen_color
            self.last_bet_amount = str(target_amount)
            self.last_bet_value = format_bet_plan(placements)
            status_message = (
                f"AUTOCLICK BET R{self.pending_round_number}: {chosen_color} / "
                f"{target_amount} [{self.last_bet_value}]"
            )
            self.state.update_status(status_message)

            if self.app and hasattr(self.app, "event_logger"):
                self.app.event_logger.log_event(
                    "AUTOCLICK_BET",
                    status_message,
                    round_number=self.pending_round_number,
                    bet_color=chosen_color,
                    bet_amount=target_amount,
                    click_plan=self.last_bet_value,
                )

            self._log_performance()
            self._save_session_state()
            
            return True
        except ClickPlanError as exc:
            self.state.update_status(f"AutoClick planning error: {exc}")
            logger.error("AutoClick planning error: %s", exc)
            return False
        except Exception as exc:
            self.state.update_status(f"AutoClick click error: {exc}")
            logger.error("AutoClick click error: %s", exc)
            return False

    def _clear_pending_bet(self):
        self.last_bet_color = None
        self.last_bet_amount = None
        self.last_bet_value = None

    def _skip_pending_bet(self, prefix: str):
        skipped_round_number = self.pending_round_number
        self._clear_pending_bet()
        self.last_skip_reason = self.last_decision_reason
        self.last_skip_csv_reason = self.last_decision_csv_reason
        self.state.update_status(f"{prefix} SKIP R{skipped_round_number}: {self.last_decision_reason}")
        
        self._append_simulation_csv(
            mode=prefix,
            round_number=skipped_round_number,
            c1_result=self.last_result or "",
            color_betted="",
            amount="",
            result="SKIP",
            lose_streak=self.loss_streak,
            multiplier=0,
            profit_change=0.0,
            total_profit=self.profit_total,
            decision_score=self.last_decision_score,
            score_gap=self.last_decision_gap,
            decision_probability=self.last_decision_probability,
            expected_value=self.last_expected_value,
            probability_edge=self.last_probability_edge,
            probability_samples=self.last_probability_samples,
            regime=self.last_regime,
            regime_reason=self.last_regime_reason,
            active_min_score=self._get_regime_thresholds(self.last_regime)["min_score"],
            active_min_gap=self._get_regime_thresholds(self.last_regime)["min_gap"],
            active_recent_columns=self._get_regime_thresholds(self.last_regime)["recent_columns"],
            regime_strong_signal_only=self._get_regime_thresholds(self.last_regime)["allow_only_strong_signal"],
            decision_reason=self.last_decision_csv_reason,
            skip_reason=self.last_skip_csv_reason,
        )
        
        self.round_count = skipped_round_number
        self.pending_round_number = skipped_round_number + 1

    def _monitor_loop(self):
        logger.info("Monitor loop started")
        last_round_signature = self._get_resume_round_signature()

        while not self._stop_event.is_set():
            idle_remaining = self.state.get_monitor_idle_remaining()
            if idle_remaining > 0:
                time.sleep(1)
                continue

            self._enforce_brave_window_lock("monitor")

            with self.capture_mgr.capture_region() as (screenshot, bbox):
                if screenshot is None:
                    time.sleep(self.config.column_check_interval)
                    continue
                    
                game_state = self.game_analyzer.analyze_game_state(screenshot, bbox)
                self.state.set_game_state(game_state)
                self._update_display_round_counter(game_state)

                if self._is_cycle_reset_state(game_state):
                    self._handle_cycle_reset_cooldown("LIVE")
                    last_round_signature = None
                    continue

                active_round = self._get_active_round_info(game_state)
                if not active_round:
                    continue

                signature = active_round["signature"]
                if signature == last_round_signature:
                    continue

                last_round_signature = signature
                self._advance_detected_round_count()
                self.state.update_status(
                    f" LIVE ACTIVE C{active_round['basis_index']} ({active_round['valid_count']} valid columns)"
                )

                if self.last_bet_color:
                    try:
                        self._record_result_boxes(active_round["boxes"], prefix="LIVE")
                    except Exception:
                        logger.exception("Failed to record LIVE round result")

                chosen_color, target_amount, _ = self._choose_next_bet(game_state)

                if chosen_color:
                    self.state.update_status(
                        f"LIVE READY R{self.pending_round_number}: {chosen_color} / {target_amount}"
                    )
                else:
                    self.state.update_status(
                        f"LIVE SKIP R{self.pending_round_number}: {self.last_decision_reason}"
                    )

                self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)

            time.sleep(self.config.column_check_interval)

        logger.info("Monitor loop stopped")

    def _simulate_round(self):
        try:
            first_round = not bool(self.last_bet_color)
            last_round_signature = self._get_resume_round_signature()

            while not self._stop_event.is_set():
                if self.config.lock_brave_window_enabled:
                    self._enforce_brave_window_lock("simulate", bring_to_front=True)
                else:
                    self._ensure_brave_on_top("simulate")
                game_state = self._capture_detectable_round(save_image=False)

                if game_state is None:
                    time.sleep(self.config.column_check_interval)
                    continue

                if self._is_cycle_reset_state(game_state):
                    self._handle_cycle_reset_cooldown("SIMULATE")
                    last_round_signature = None
                    self.state.update_status("Simulate: waiting for next active round...")
                    continue

                active_round = self._get_active_round_info(game_state)
                if not active_round:
                    time.sleep(self.config.column_check_interval)
                    continue

                if game_state.any_unknown:
                    self.state.update_status("Simulate: waiting for stable match...")
                    last_round_signature = None
                    time.sleep(self.config.column_check_interval)
                    continue

                signature = active_round["signature"]
                if signature == last_round_signature:
                    time.sleep(self.config.column_check_interval)
                    continue

                last_round_signature = signature
                self._advance_detected_round_count()
                was_first_round = first_round

                if first_round:
                    self.state.update_status(
                        f"SIMULATE: first active round detected at C{active_round['basis_index']}, placing virtual round 1 bet"
                    )
                    first_round = False
                else:
                    self._record_result_boxes(active_round["boxes"], prefix="SIMULATE")
                    if self._stop_event.is_set():
                        break

                if self._handle_daily_idle_cutoff("SIMULATE", first_round=was_first_round):
                    break

                if self._is_cycle_bet_cooldown_active():
                    self._record_cycle_bet_cooldown("SIMULATE", active_round["boxes"], record_history=was_first_round)
                    time.sleep(1)
                    self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)
                    self.state.update_status(f"Simulate cooldown countdown: {self.config.monitor_idle_seconds:.0f}s")

                    while not self._stop_event.is_set() and self.state.get_monitor_idle_remaining() > 0:
                        time.sleep(1)

                    self.state.update_status("Simulate: waiting for next active round...")
                    continue

                chosen_color, target_amount, _ = self._choose_next_bet(game_state)
                if chosen_color:
                    self._record_simulated_bet(chosen_color, f"Bet {target_amount}", False)
                else:
                    self._skip_pending_bet("SIMULATE")

                time.sleep(1)
                self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)
                self.state.update_status(f"Simulate countdown: {self.config.monitor_idle_seconds:.0f}s")

                while not self._stop_event.is_set() and self.state.get_monitor_idle_remaining() > 0:
                    time.sleep(1)

                self.state.update_status("Simulate: waiting for next active round...")

            if self._simulate_halted:
                self.state.state = AutomationState.IDLE
            elif self._stop_event.is_set():
                self.state.update_status("SIMULATE STOPPED")
                self.state.state = AutomationState.IDLE
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            self.state.update_status(f"Simulation error: {e}")
            self.state.state = AutomationState.IDLE

    def _autoclick_loop(self):
        try:
            first_round = not bool(self.last_bet_color)
            last_round_signature = self._get_resume_round_signature()

            while not self._stop_event.is_set():
                if self.config.lock_brave_window_enabled:
                    self._enforce_brave_window_lock("autoclick", bring_to_front=True)
                else:
                    self._ensure_brave_on_top("autoclick")
                game_state = self._capture_detectable_round(save_image=False)

                if game_state is None:
                    time.sleep(self.config.column_check_interval)
                    continue

                if self._is_cycle_reset_state(game_state):
                    self._handle_cycle_reset_cooldown("AUTOCLICK")
                    last_round_signature = None
                    self.state.update_status("AutoClick: waiting for next active round...")
                    continue

                active_round = self._get_active_round_info(game_state)
                if not active_round:
                    time.sleep(self.config.column_check_interval)
                    continue

                if game_state.any_unknown:
                    self.state.update_status("AutoClick: waiting for stable match...")
                    last_round_signature = None
                    time.sleep(self.config.column_check_interval)
                    continue

                signature = active_round["signature"]
                if signature == last_round_signature:
                    time.sleep(self.config.column_check_interval)
                    continue

                last_round_signature = signature
                self._advance_detected_round_count()
                was_first_round = first_round

                if first_round:
                    self.state.update_status(
                        f"AUTOCLICK: first active round detected at C{active_round['basis_index']}, placing round 1 bet"
                    )
                    first_round = False
                else:
                    self._record_result_boxes(active_round["boxes"], prefix="AUTOCLICK")
                    if self._stop_event.is_set():
                        break

                if self._handle_daily_idle_cutoff("AUTOCLICK", first_round=was_first_round):
                    break

                if self._is_cycle_bet_cooldown_active():
                    self._record_cycle_bet_cooldown("AUTOCLICK", active_round["boxes"], record_history=was_first_round)
                    time.sleep(1)
                    self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)
                    self.state.update_status(f"AutoClick cooldown countdown: {self.config.monitor_idle_seconds:.0f}s")

                    while not self._stop_event.is_set() and self.state.get_monitor_idle_remaining() > 0:
                        time.sleep(1)

                    self.state.update_status("AutoClick: waiting for next active round...")
                    continue

                chosen_color, target_amount, decision_meta = self._choose_next_bet(game_state)
                
                if chosen_color:
                    if not self._check_bet_limits(target_amount):
                        self._stop_event.set()
                        self.state.state = AutomationState.IDLE
                        break
                    
                    logger.info(f"Decision: {chosen_color} @ {target_amount} | "
                               f"Regime:{decision_meta['regime']} "
                               f"Conf:{decision_meta['confidence']} Score:{decision_meta['score']:.1f} "
                               f"Gap:{decision_meta['gap']:.1f} | Alt:{decision_meta['alternatives'][:2]}")
                    
                    if not self._execute_autoclick_bet(chosen_color, target_amount):
                        self._stop_event.set()
                        self.state.state = AutomationState.IDLE
                        break
                else:
                    self._skip_pending_bet("AUTOCLICK")

                time.sleep(1)
                self.state.set_monitor_idle_until(self.config.monitor_idle_seconds)
                self.state.update_status(f"AutoClick countdown: {self.config.monitor_idle_seconds:.0f}s")

                while not self._stop_event.is_set() and self.state.get_monitor_idle_remaining() > 0:
                    time.sleep(1)

                self.state.update_status("AutoClick: waiting for next active round...")

            self._log_decision_metrics()
            
        except Exception as e:
            logger.error(f"AutoClick error: {e}")
            self.state.update_status(f"AutoClick error: {e}")
            self.state.state = AutomationState.IDLE


class AutoClickerPro:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config_dir = ensure_runtime_data_dir()
        migrate_legacy_runtime_files(self.config_dir)
        configure_file_logging(self.config_dir)
        self.event_logger = EventLogger(self.config_dir)
        logger.info(f"Runtime data directory: {self.config_dir}")
        
        self.config_path = self.config_dir / "app_config.json"
        self.calibration_path = self.config_dir / "calibration.json"
        
        self.config = self._load_config()
        self.config_dirty = False
        self.capture_mgr = ScreenCaptureManager(self.config)
        self.color_matcher = ColorMatcher(self.config)
        self.game_analyzer = GameAnalyzer(self.config, self.capture_mgr, self.color_matcher)
        self.engine = AutomationEngine(self.config, self.capture_mgr, self.color_matcher, self.game_analyzer, self)
        
        self._calibration_window: Optional[tk.Toplevel] = None
        self._calibration_lock_after_id: Optional[str] = None
        self._calibration_brave_hwnd: Optional[int] = None
        self._calibration_brave_rect: Optional[Tuple[int, int, int, int]] = None
        self._saved_brave_rect: Optional[Tuple[int, int, int, int]] = None
        self._status_update_id = None
        self.status_mode_label = "Idle"
        
        self._setup_ui()
        self._load_calibration()
        self._schedule_ui_update()
    
    def _load_config(self) -> AppConfig:
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    app_config_data = data.get("app_config", {})
                    return AppConfig.from_dict(app_config_data)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
        return AppConfig()
    
    def _save_config(self, force: bool = False):
        if not force and self.config_path.exists() and not self.config_dirty:
            return
        try:
            with open(self.config_path, 'w') as f:
                json.dump({"app_config": self.config.to_dict(), "version": "2.3.0", "updated": datetime.now().isoformat()}, f, indent=2)
            self.config_dirty = False
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
    
    def _load_calibration(self):
        if not self.calibration_path.exists():
            return
        try:
            with open(self.calibration_path, 'r') as f:
                data = json.load(f)

            brave_rect = data.get("brave_window_rect")
            if (
                isinstance(brave_rect, list)
                and len(brave_rect) == 4
                and all(isinstance(value, int) for value in brave_rect)
            ):
                self._saved_brave_rect = tuple(brave_rect)
            else:
                self._saved_brave_rect = None
            
            self.capture_mgr.clear_calibration()

            point_entries = [
                point_data
                for point_data in data.get("points", [])
                if point_data.get("name") != "Gray"
            ]

            for i, point_data in enumerate(point_entries):
                point = CalibrationPoint.from_dict(i, point_data)
                self.capture_mgr.add_calibration_point(point)
                if point.rgb_sample and point.name in self.config.reference_color_labels:
                    self.color_matcher.set_reference(point.name, point.rgb_sample)
            
            loaded_points = len(self.capture_mgr.calibration_points)
            expected_points = self.config.total_calibration_points
            if loaded_points >= expected_points:
                self.status_var.set(f"Status: Calibration loaded ({loaded_points}/{expected_points} points)")
            else:
                self.status_var.set(f"Status: Partial calibration ({loaded_points}/{expected_points} points)")
            logger.info(f"Loaded {loaded_points} calibration points")
        except Exception as e:
            logger.error(f"Failed to load calibration: {e}")
    
    def _save_calibration(self):
        brave_rect = self._calibration_brave_rect or self._saved_brave_rect
        if brave_rect is not None:
            self._saved_brave_rect = brave_rect

        data = {
            "brave_window_rect": list(brave_rect) if brave_rect is not None else None,
            "points": [
                {"name": p.name, "x": p.x, "y": p.y, "rgb_sample": list(p.rgb_sample) if p.rgb_sample else None} 
                for p in sorted(self.capture_mgr.calibration_points.values(), key=lambda p: p.index)
            ],
        }
        try:
            with open(self.calibration_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("Calibration saved")
        except Exception as e:
            logger.error(f"Failed to save calibration: {e}")

    def get_saved_brave_rect(self) -> Optional[Tuple[int, int, int, int]]:
        return self._saved_brave_rect

    def _stop_calibration_window_lock(self):
        if self._calibration_lock_after_id:
            try:
                self.root.after_cancel(self._calibration_lock_after_id)
            except Exception:
                pass
        self._calibration_lock_after_id = None
        self._calibration_brave_hwnd = None
        self._calibration_brave_rect = None

    def _schedule_calibration_window_lock(self):
        self._calibration_lock_after_id = None

        if not self._calibration_window or not self._calibration_window.winfo_exists():
            self._stop_calibration_window_lock()
            return

        hwnd = self._calibration_brave_hwnd
        target_rect = self._calibration_brave_rect
        if os.name != "nt" or not hwnd or not target_rect:
            return

        try:
            current_rect = get_window_rect(hwnd)
            if current_rect and current_rect != target_rect:
                if restore_window_rect(hwnd, target_rect):
                    logger.info("Calibration lock restored Brave window to %s", target_rect)
        except Exception:
            logger.exception("Failed to enforce Brave calibration window lock")

        self._calibration_lock_after_id = self.root.after(250, self._schedule_calibration_window_lock)

    def _start_calibration_window_lock(self):
        self._stop_calibration_window_lock()

        if os.name != "nt":
            return

        preferred_hwnd = int(user32.GetForegroundWindow() or 0) if os.name == "nt" else 0
        hwnd = find_brave_window(preferred_hwnd=preferred_hwnd)
        if not hwnd:
            logger.warning("Calibration lock skipped: Brave window not found")
            return

        rect = get_window_rect(hwnd)
        if not rect:
            logger.warning("Calibration lock skipped: could not read Brave window bounds")
            return

        self._calibration_brave_hwnd = hwnd
        self._calibration_brave_rect = rect
        restore_window_rect(hwnd, rect, bring_to_front=True)
        logger.info("Calibration lock pinned Brave window at %s", rect)
        self._schedule_calibration_window_lock()

    def _close_calibration_window(self):
        self._stop_calibration_window_lock()
        if self._calibration_window:
            try:
                self._calibration_window.destroy()
            except Exception:
                pass
            self._calibration_window = None
    
    def _setup_ui(self):
        self.root.title("AutoClicker Pro - Enhanced with Analytics")
        window_width = 560
        window_height = 650
        screen_width = self.root.winfo_screenwidth()
        self.root.geometry(f"{window_width}x{window_height}+{screen_width - window_width - 20}+20")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        
        style = ttk.Style()
        style.theme_use('clam')
        
        title_frame = ttk.Frame(self.root)
        title_frame.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(title_frame, text="AUTOCLICKER PRO - ENHANCED", font=("Arial", 12, "bold")).pack()
        ttk.Label(title_frame, text=f"Martingale: {self.config.martingale_start} → up to {self.config.martingale_max_steps - 1} losses", font=("Arial", 8)).pack()
        
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=10)
        
        self.calibrate_btn = None
        self.monitor_btn = None
        self.simulate_btn = None
        self.autoclick_btn = None
        self.reset_btn = None
        self.learning_btn = None
        self.lock_brave_btn = None

        button_specs = [
            ("Calibrate", self.start_calibration, "#f0ad4e", 0, 0, "calibrate"),
            ("Monitor", self.start_monitoring, "#5cb85c", 0, 1, "monitor"),
            ("Simulate", self.start_simulation, "#0275d8", 0, 2, "simulate"),
            ("AutoClick", self.start_autoclick, "#8e44ad", 1, 0, "autoclick"),
            ("Reset", self.reset_records, "#f39c12", 1, 1, None),
            ("Analytics", self.show_decision_analytics, "#6c757d", 1, 2, None),
            ("Exit", self.exit_app, "#d9534f", 2, 1, None),
        ]
        
        for text, command, color, row, column, stop_action_name in button_specs:
            btn = tk.Button(
                button_frame,
                text=text,
                command=command,
                width=12,
                bg=color,
                fg="white",
                relief="raised",
                bd=1,
            )
            btn.grid(row=row, column=column, padx=2, pady=5)

            if stop_action_name:
                btn.bind("<Double-Button-1>", lambda e, action=stop_action_name: self.stop_action(action))

            if text == "Calibrate":
                self.calibrate_btn = btn
            elif text == "Monitor":
                self.monitor_btn = btn
            elif text == "Simulate":
                self.simulate_btn = btn
            elif text == "AutoClick":
                self.autoclick_btn = btn
            elif text == "Reset":
                self.reset_btn = btn

        self.learning_mode_var = tk.BooleanVar(value=self.config.adaptive_learning_enabled)
        self.learning_btn = tk.Button(
            button_frame,
            command=self.toggle_learning_mode,
            width=12,
            fg="white",
            relief="raised",
            bd=1,
        )
        self.learning_btn.grid(row=2, column=0, padx=2, pady=5)
        self._refresh_learning_button()

        self.lock_brave_var = tk.BooleanVar(value=self.config.lock_brave_window_enabled)
        self.lock_brave_btn = tk.Button(
            button_frame,
            command=self.toggle_brave_window_lock,
            width=12,
            fg="white",
            relief="raised",
            bd=1,
        )
        self.lock_brave_btn.grid(row=2, column=2, padx=2, pady=5)
        self._refresh_lock_brave_button()

        status_frame = ttk.LabelFrame(self.root, text="Status", padding=(10, 5))
        status_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.status_var = tk.StringVar(value="Ready - Not calibrated")
        ttk.Label(status_frame, textvariable=self.status_var, font=("Arial", 9)).pack(anchor="w")
        self.display_round_var = tk.StringVar(value="Cycle Counter: 0")
        ttk.Label(status_frame, textvariable=self.display_round_var, font=("Arial", 9)).pack(anchor="w")
        
        game_frame = ttk.LabelFrame(self.root, text="Game State", padding=(10, 5))
        game_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.columns_var = tk.StringVar(value="Columns: Not scanned")
        ttk.Label(game_frame, textvariable=self.columns_var, font=("Arial", 8)).pack(anchor="w")
        self.columns_var_row2 = tk.StringVar(value="")
        ttk.Label(game_frame, textvariable=self.columns_var_row2, font=("Arial", 8)).pack(anchor="w")
        self.confidence_var = tk.StringVar(value="Confidence: 0%")
        ttk.Label(game_frame, textvariable=self.confidence_var, font=("Arial", 8)).pack(anchor="w")

        stats_frame = ttk.LabelFrame(self.root, text="Statistics", padding=(10, 5))
        stats_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.rounds_var = tk.StringVar(value="Rounds: 0")
        self.win_lose_var = tk.StringVar(value="Wins: 0 | Loses: 0")
        self.profit_var = tk.StringVar(value="Profit: 0.00")
        self.martingale_var = tk.StringVar(value="Martingale: 5")
        self.current_bet_var = tk.StringVar(value="Current Bet: None")
        self.pending_bet_var = tk.StringVar(value="Pending Bet: None")
        self.last_c1_var = tk.StringVar(value="Last Result Boxes: None")
        self.decision_var = tk.StringVar(value="Decision: Waiting for C1 history")
        ttk.Label(stats_frame, textvariable=self.rounds_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.win_lose_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.profit_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.martingale_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.current_bet_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.pending_bet_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.last_c1_var, font=("Arial", 8)).pack(anchor="w")
        ttk.Label(stats_frame, textvariable=self.decision_var, font=("Arial", 8), wraplength=520).pack(anchor="w")
        
        info_frame = ttk.LabelFrame(self.root, text="Information", padding=(10, 5))
        info_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        self.calib_info_var = tk.StringVar(value=f"Calibration: 0/{self.config.total_columns * self.config.boxes_per_column} grid + 0/{len(self.config.extra_calibration_labels)} extra")
        ttk.Label(info_frame, textvariable=self.calib_info_var, font=("Arial", 8)).pack(anchor="w")
    
    def _refresh_learning_button(self):
        if not self.learning_btn:
            return

        enabled = self.learning_mode_var.get()
        label = "Learning: ON" if enabled else "Learning: OFF"
        color = "#16a34a" if enabled else "#6b7280"
        self.learning_btn.config(text=label, bg=color, activebackground=color)

    def _refresh_lock_brave_button(self):
        if not self.lock_brave_btn:
            return

        enabled = self.lock_brave_var.get()
        label = "Lock Brave: ON" if enabled else "Lock Brave: OFF"
        color = "#0f766e" if enabled else "#6b7280"
        self.lock_brave_btn.config(text=label, bg=color, activebackground=color)

    def toggle_learning_mode(self):
        enabled = not self.learning_mode_var.get()
        self.learning_mode_var.set(enabled)
        self.engine.learning_mode = enabled
        self.config.adaptive_learning_enabled = enabled
        self.config_dirty = True
        self._save_config()
        self._refresh_learning_button()
        status = "ENABLED" if self.engine.learning_mode else "DISABLED"
        self.status_var.set(f"Status: Adaptive Learning {status}")
        logger.info(f"Adaptive learning mode {status}")

    def toggle_brave_window_lock(self):
        enabled = not self.lock_brave_var.get()
        self.lock_brave_var.set(enabled)
        self.config.lock_brave_window_enabled = enabled
        self.config_dirty = True
        self._save_config()
        self._refresh_lock_brave_button()

        if enabled:
            armed = self.engine._arm_brave_window_lock("manual toggle")
            message = "Status: Brave window lock ENABLED" if armed else "Status: Brave lock enabled (Brave not found)"
        else:
            self.engine._clear_brave_window_lock()
            message = "Status: Brave window lock DISABLED"

        self.status_var.set(message)
        logger.info("Brave window lock %s", "ENABLED" if enabled else "DISABLED")
    
    def show_decision_analytics(self):
        analytics = self.engine.get_decision_analytics()
        
        dashboard = tk.Toplevel(self.root)
        dashboard.title("Decision Analytics Dashboard")
        dashboard.geometry("800x600")
        dashboard.attributes("-topmost", True)
        
        notebook = ttk.Notebook(dashboard)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tab 1: Performance
        perf_frame = ttk.Frame(notebook)
        notebook.add(perf_frame, text="Performance")
        
        metrics_frame = ttk.LabelFrame(perf_frame, text="Real-time Metrics", padding=10)
        metrics_frame.pack(fill="x", padx=10, pady=5)
        
        metrics = [
            ("Total Decisions", analytics.get("total_decisions", 0)),
            ("Bets Placed", analytics.get("bets_placed", 0)),
            ("Skip Rate", f"{analytics.get('skip_rate', 0)*100:.1f}%"),
            ("Avg Decision Time", f"{analytics.get('avg_decision_time_ms', 0):.0f}ms"),
            ("Active Regime", analytics.get("active_regime", "RANGE")),
        ]
        
        for i, (label, value) in enumerate(metrics):
            ttk.Label(metrics_frame, text=f"{label}:", font=("Arial", 10, "bold")).grid(row=i, column=0, sticky="e", padx=5, pady=2)
            ttk.Label(metrics_frame, text=str(value), font=("Arial", 10)).grid(row=i, column=1, sticky="w", padx=5, pady=2)
        
        # Confidence breakdown
        conf_frame = ttk.LabelFrame(perf_frame, text="Win Rate by Confidence Level", padding=10)
        conf_frame.pack(fill="x", padx=10, pady=5)
        
        conf_data = [
            ("HIGH", analytics.get("high_conf_win_rate", 0), self.engine.decision_stats.high_conf_bets),
            ("MEDIUM", analytics.get("medium_conf_win_rate", 0), self.engine.decision_stats.medium_conf_bets),
            ("LOW", analytics.get("low_conf_win_rate", 0), self.engine.decision_stats.low_conf_bets),
        ]
        
        for level, rate, count in conf_data:
            color = "#28a745" if rate > 0.55 else ("#ffc107" if rate > 0.45 else "#dc3545")
            ttk.Label(conf_frame, text=f"{level}:", font=("Arial", 10, "bold")).pack(anchor="w")
            ttk.Label(conf_frame, text=f"  {rate*100:.1f}% win rate ({count} bets)", foreground=color).pack(anchor="w")
        
        # Tab 2: Thresholds
        thresh_frame = ttk.Frame(notebook)
        notebook.add(thresh_frame, text="Thresholds")
        
        thresh_display = tk.Text(thresh_frame, height=15, font=("Courier", 10))
        thresh_display.pack(fill="both", expand=True, padx=10, pady=10)
        
        thresholds = analytics.get("current_thresholds", {})
        active_regime_thresholds = analytics.get("active_regime_thresholds", {})
        thresh_text = f"""
Current Decision Thresholds:
{'='*40}

Base Min Score:          {thresholds.get('min_score', 0):.2f}
Base Min Score Gap:      {thresholds.get('min_gap', 0):.2f}
Base Recent Columns:     {thresholds.get('recent_columns', 0)}
Base Min Hit Prob:       {thresholds.get('min_hit_probability', 0):.2f}
Base Min Expected Value: {thresholds.get('min_expected_value', 0):.2f}
Base Min Edge:           {thresholds.get('min_probability_edge', 0):.2f}

Active Regime:           {analytics.get('active_regime', 'RANGE')}
Regime Reason:           {analytics.get('active_regime_reason', 'n/a')}
Active Min Score:        {active_regime_thresholds.get('min_score', 0):.2f}
Active Min Score Gap:    {active_regime_thresholds.get('min_gap', 0):.2f}
Active Recent Columns:   {active_regime_thresholds.get('recent_columns', 0)}
Active Min Hit Prob:     {active_regime_thresholds.get('min_hit_probability', 0):.2f}
Active Min Expected Val: {active_regime_thresholds.get('min_expected_value', 0):.2f}
Active Min Edge:         {active_regime_thresholds.get('min_probability_edge', 0):.2f}

Adaptive Learning:      {'ENABLED' if analytics.get('learning_mode') else 'DISABLED'}

{'='*40}

Interpretation:
- Higher min_hit_probability = fewer, safer entries
- Higher min_expected_value = stronger positive edge required
- Higher min_probability_edge = avoids thin races between top colors
"""
        thresh_display.insert("1.0", thresh_text)
        thresh_display.configure(state="disabled")
        
        # Tab 3: Suggestions
        suggest_frame = ttk.Frame(notebook)
        notebook.add(suggest_frame, text="Suggestions")
        
        suggestion = analytics.get("suggestion", "No suggestions at this time. Continue monitoring.")
        ttk.Label(suggest_frame, text="AI Recommendations:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=10)
        ttk.Label(suggest_frame, text=suggestion, font=("Arial", 10), wraplength=700).pack(anchor="w", padx=10, pady=5)
        
        # Export button
        def export_analytics():
            export_path = self.config_dir / f"analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(export_path, 'w') as f:
                json.dump(analytics, f, indent=2)
            messagebox.showinfo("Exported", f"Analytics saved to {export_path}")
        
        ttk.Button(dashboard, text="Export Analytics", command=export_analytics).pack(pady=10)
    
    def _schedule_ui_update(self):
        self._update_ui()
        self._status_update_id = self.root.after(500, self._schedule_ui_update)

    def show_click_marker(self, x: int, y: int, label: str):
        self.root.after(0, lambda: self._create_click_marker(x, y, label))

    def _create_click_marker(self, x: int, y: int, label: str):
        marker = tk.Toplevel(self.root)
        marker.overrideredirect(True)
        marker.attributes("-topmost", True)
        marker.configure(bg="#ff00ff")

        try:
            marker.wm_attributes("-transparentcolor", "#ff00ff")
        except tk.TclError:
            pass

        marker.geometry(f"80x80+{max(0, x - 40)}+{max(0, y - 40)}")

        canvas = tk.Canvas(marker, width=80, height=80, bg="#ff00ff", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_oval(18, 18, 62, 62, outline="#ff3b30", width=3)
        canvas.create_text(40, 11, text=label.replace("Bet ", ""), fill="#ff3b30", font=("Arial", 8, "bold"))
        marker.after(2000, marker.destroy)
    
    def _update_ui(self):
        current = len(self.capture_mgr.calibration_points)
        grid_needed = self.config.total_columns * self.config.boxes_per_column
        extra_needed = len(self.config.extra_calibration_labels)
        self.calib_info_var.set(f"Calibration: {min(current, grid_needed)}/{grid_needed} grid + {max(0, current - grid_needed)}/{extra_needed} extra")
        
        game_state = self.engine.state.get_game_state()
        if game_state and game_state.columns:
            if game_state.has_uniform_column_pattern:
                self.columns_var.set("Columns: Invalid repeated color pattern detected")
                self.columns_var_row2.set("")
            elif game_state.has_excess_all_white_columns:
                self.columns_var.set("Columns: Invalid white cluster detected")
                self.columns_var_row2.set("")
            elif not game_state.any_unknown:
                formatted_columns = [f"C{col.column_index}[{':'.join(col.boxes)}]" for col in game_state.columns]
                self.columns_var.set("Columns: " + " | ".join(formatted_columns[:3]))
                self.columns_var_row2.set("         " + " | ".join(formatted_columns[3:7]))
            else:
                self.columns_var.set("Columns: Waiting for stable match...")
                self.columns_var_row2.set("")
            self.confidence_var.set(f"Confidence: {game_state.confidence_score:.1f}%")
        else:
            self.columns_var.set("Columns: Waiting for data...")
            self.columns_var_row2.set("")
            self.confidence_var.set("Confidence: 0%")

        current_bet = "None"
        if self.engine.last_bet_color:
            current_bet = self.engine.last_bet_color
            if self.engine.last_bet_value:
                current_bet = f"{current_bet} / {self.engine.last_bet_value}"

        last_c1 = "None"
        if self.engine.last_c1_boxes:
            last_c1 = " / ".join(self.engine.last_c1_boxes)

        self.rounds_var.set(f"Rounds: {self.engine.detected_round_count}")
        self.win_lose_var.set(f"Wins: {self.engine.win_count} | Loses: {self.engine.lose_count}")
        self.profit_var.set(f"Profit: {self.engine.profit_total:.2f}")
        current_martingale = self.engine.bet_amount_steps[self.engine.martingale_index]
        self.martingale_var.set(
            f"Martingale: {current_martingale} | Loss streak: {self.engine.loss_streak}/{self.engine.max_loss_streak - 1}"
        )
        self.current_bet_var.set(f"Current Bet: {current_bet}")
        self.pending_bet_var.set(f"Pending Bet: R{self.engine.pending_round_number} - {current_bet}")
        self.last_c1_var.set(f"Last Result Boxes: {last_c1}")
        self.decision_var.set(f"Decision: {self.engine.last_decision_reason}")
        
        idle_remaining = self.engine.state.get_monitor_idle_remaining()
        self.display_round_var.set(f"Cycle Counter: {self.engine.display_round_counter}")
        if self._calibration_window:
            self.status_var.set("Status: Calibrating")
        elif self.engine.state.state == AutomationState.IDLE:
            self.status_var.set("Status: Idle")
        elif idle_remaining > 0:
            self.status_var.set(f"Status: {self.status_mode_label} - Countdown {idle_remaining:.0f}s")
        elif self.engine.state.state in (AutomationState.MONITORING, AutomationState.SIMULATING, AutomationState.AUTOCLICKING):
            self.status_var.set(f"Status: {self.status_mode_label}")
    
    def stop_action(self, action: str):
        logger.info(f"Double-click detected on {action} - stopping")
        self.engine.stop_all()
        
        if self._calibration_window:
            self._close_calibration_window()
        
        self.engine.state.state = AutomationState.IDLE
        
        self.status_mode_label = "Idle"
        self.status_var.set("Status: Idle (stopped)")
        
        btn = None
        if action == "calibrate":
            btn = self.calibrate_btn
        elif action == "monitor":
            btn = self.monitor_btn
        elif action == "simulate":
            btn = self.simulate_btn
        elif action == "autoclick":
            btn = self.autoclick_btn
        
        if btn:
            original_bg = btn.cget("bg")
            btn.config(bg="#ff6666")
            self.root.after(500, lambda: btn.config(bg=original_bg))
    
    def start_calibration(self):
        if self._calibration_window:
            return
        
        self.engine.stop_all()
        self._start_calibration_window_lock()
        
        self._calibration_window = tk.Toplevel(self.root)
        self._calibration_window.title("Calibration")
        self._calibration_window.attributes("-fullscreen", True)
        
        screenshot = ImageGrab.grab().convert("RGB")
        screenshot_path = self.config_dir / "calibration_frame.png"
        screenshot.save(screenshot_path)
        
        bg_image = ImageTk.PhotoImage(screenshot)
        canvas = tk.Canvas(self._calibration_window, cursor="cross")
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=bg_image, anchor="nw")
        canvas.bg_image = bg_image
        canvas.screenshot = screenshot
        
        temp_points = []
        
        def get_point_name(index: int) -> str:
            grid_count = self.config.total_columns * self.config.boxes_per_column
            if index < grid_count:
                col = (index // self.config.boxes_per_column) + 1
                box = (index % self.config.boxes_per_column) + 1
                return f"Column {col}, Box {box}"
            extra_idx = index - grid_count
            if extra_idx < len(self.config.extra_calibration_labels):
                return self.config.extra_calibration_labels[extra_idx]
            return f"Extra {extra_idx + 1}"
        
        instruction_var = tk.StringVar()
        
        def update_instruction_banner():
            current_index = len(temp_points)
            if current_index >= self.config.total_calibration_points:
                instruction_var.set(f"Complete: {len(temp_points)}/{self.config.total_calibration_points} points")
                return
            point_name = get_point_name(current_index)
            instruction_var.set(f"Click: {point_name} ({current_index + 1}/{self.config.total_calibration_points})")
        
        def on_click(event):
            idx = len(temp_points)
            if idx >= self.config.total_calibration_points:
                return
            
            point_name = get_point_name(idx)
            rgb_sample = None
            if point_name in self.config.reference_color_labels:
                rgb_sample = self.capture_mgr.get_pixel_rgb(screenshot, (event.x, event.y), None)
            
            point = CalibrationPoint(
                index=idx,
                name=point_name,
                x=event.x,
                y=event.y,
                rgb_sample=rgb_sample,
            )
            
            temp_points.append(point)
            self.capture_mgr.add_calibration_point(point)
            
            if rgb_sample:
                self.color_matcher.set_reference(point_name, rgb_sample)
            
            color = "red" if point_name in self.config.reference_color_labels else "yellow"
            canvas.create_oval(event.x - 5, event.y - 5, event.x + 5, event.y + 5, fill=color, outline="white")
            canvas.create_text(event.x + 10, event.y - 10, text=f"{idx + 1}", fill="white", anchor="w")
            
            remaining = self.config.total_calibration_points - len(temp_points)
            self._calibration_window.title(f"Calibration - {remaining} left")
            update_instruction_banner()
            
            if len(temp_points) >= self.config.total_calibration_points:
                self._save_calibration()
                self._close_calibration_window()
                messagebox.showinfo("Success", f"Calibration complete! {len(temp_points)} points saved.")
        
        def on_escape(event):
            if len(temp_points) > 0:
                if messagebox.askyesno("Cancel", f"Save {len(temp_points)} points?"):
                    self._save_calibration()
            self._close_calibration_window()
        
        canvas.bind("<Button-1>", on_click)
        self._calibration_window.bind("<Escape>", on_escape)
        self._calibration_window.protocol("WM_DELETE_WINDOW", lambda: on_escape(None))
        
        instruction_frame = tk.Frame(self._calibration_window, bg="black", bd=1, relief="solid")
        instruction_frame.place(x=10, y=10)
        
        tk.Label(instruction_frame, textvariable=instruction_var, bg="black", fg="#ffd966",
                 font=("Arial", 14, "bold"), padx=12, pady=8).pack(anchor="w")
        
        tk.Label(self._calibration_window, text="Click points in order. Press ESC to cancel.",
                 bg="black", fg="white", font=("Arial", 11), padx=12, pady=8).place(x=10, y=58)
        update_instruction_banner()
    
    def start_monitoring(self):
        if not self.capture_mgr.is_fully_calibrated():
            messagebox.showwarning("Not Calibrated", "Please complete calibration first.")
            return

        monitor_running = (
            self.engine._monitor_thread
            and self.engine._monitor_thread.is_alive()
            and not self.engine._stop_event.is_set()
        )

        if monitor_running:
            self.engine.stop_all()
            self.status_mode_label = "Idle"
            self.status_var.set("Status: Idle")
            return

        if self.engine.state.state != AutomationState.IDLE:
            self.engine.stop_all()
        
        if self.engine.start_monitoring():
            self.status_mode_label = "Monitoring"
            self.status_var.set("Status: Monitoring")
        else:
            messagebox.showerror("Error", "Failed to start monitoring")

    def start_simulation(self):
        if not self.capture_mgr.is_fully_calibrated():
            messagebox.showwarning("Not Calibrated", "Please complete calibration first.")
            return

        simulate_running = (
            self.engine._simulate_thread
            and self.engine._simulate_thread.is_alive()
            and not self.engine._stop_event.is_set()
        )

        if simulate_running:
            self.engine.stop_all()
            self.status_mode_label = "Idle"
            self.status_var.set("Status: Idle")
            return

        if self.engine.state.state != AutomationState.IDLE:
            self.engine.stop_all()

        self.engine._ensure_brave_on_top("start simulation")

        if self.engine.start_simulation():
            self.status_mode_label = "Simulating"
            self.status_var.set("Status: Simulating")
        else:
            messagebox.showerror("Error", "Failed to start simulation")

    def start_autoclick(self):
        if not self.capture_mgr.is_fully_calibrated():
            messagebox.showwarning("Not Calibrated", "Please complete calibration first.")
            return

        autoclick_running = (
            self.engine._autoclick_thread
            and self.engine._autoclick_thread.is_alive()
            and not self.engine._stop_event.is_set()
        )

        if autoclick_running:
            self.engine.stop_all()
            self.status_mode_label = "Idle"
            self.status_var.set("Status: Idle")
            return

        if self.engine.state.state != AutomationState.IDLE:
            self.engine.stop_all()

        self.engine._ensure_brave_on_top("start autoclick")

        if self.engine.start_autoclick():
            self.status_mode_label = "AutoClick"
            self.status_var.set("Status: AutoClick")
        else:
            messagebox.showerror("Error", "Failed to start AutoClick")

    def reset_records(self):
        if self._calibration_window:
            self._close_calibration_window()

        self.engine.reset_records()
        self.status_mode_label = "Idle"
        self.status_var.set("Status: Idle (records reset)")
    
    def exit_app(self):
        if self._status_update_id:
            self.root.after_cancel(self._status_update_id)
        self._stop_calibration_window_lock()
        self.engine.stop_all()
        self._save_config()
        self.root.quit()
        self.root.destroy()


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
        print("\n Shutting down gracefully...")
        app.exit_app()


if __name__ == "__main__":
    main()

