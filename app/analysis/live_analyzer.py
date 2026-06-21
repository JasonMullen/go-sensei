from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, replace
from typing import Optional

from app.analysis.katago_client import KataGoAnalysisResult, KataGoClient, KataGoSettings
from app.core.board import Board
from app.core.stone import Stone


@dataclass
class LiveAnalysisRequest:
    request_id: int
    board: Board
    current_player: Stone


@dataclass
class LiveAnalysisState:
    is_thinking: bool = False
    latest_result: Optional[KataGoAnalysisResult] = None
    latest_error: Optional[str] = None
    latest_request_id: int = 0
    completed_request_id: int = 0
    latest_elapsed_seconds: Optional[float] = None
    latest_status_message: str = "Idle"


class LiveAnalysisService:
    def __init__(
        self,
        settings: Optional[KataGoSettings] = None,
        max_visits: int = 4,
        verbose: bool = True,
    ) -> None:
        base_settings = settings or KataGoSettings.from_environment()
        self.settings = replace(base_settings, max_visits=max_visits)
        self.verbose = verbose

        self._requests: queue.Queue[LiveAnalysisRequest] = queue.Queue()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        self._next_request_id = 0
        self._state = LiveAnalysisState()

    def log(self, message: str) -> None:
        if self.verbose:
            print(f"[Live KataGo] {message}", flush=True)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self.log("Starting background engine thread...")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="LiveKataGoAnalysis",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.log("Stopping background engine thread...")
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=2)

    def request_analysis(self, board: Board, current_player: Stone) -> None:
        self.start()

        self._next_request_id += 1
        request_id = self._next_request_id
        board_snapshot = board.copy()

        with self._lock:
            self._state.is_thinking = True
            self._state.latest_error = None
            self._state.latest_request_id = request_id
            self._state.latest_status_message = (
                f"Queued analysis #{request_id} for {current_player.name}"
            )

        self._clear_pending_requests()

        self.log(f"Queued analysis #{request_id} for {current_player.name}")

        self._requests.put(
            LiveAnalysisRequest(
                request_id=request_id,
                board=board_snapshot,
                current_player=current_player,
            )
        )

    def clear(self) -> None:
        self._clear_pending_requests()

        with self._lock:
            self._state = LiveAnalysisState(latest_status_message="Analysis cleared")

        self.log("Cleared live analysis state.")

    def get_state(self) -> LiveAnalysisState:
        with self._lock:
            return LiveAnalysisState(
                is_thinking=self._state.is_thinking,
                latest_result=self._state.latest_result,
                latest_error=self._state.latest_error,
                latest_request_id=self._state.latest_request_id,
                completed_request_id=self._state.completed_request_id,
                latest_elapsed_seconds=self._state.latest_elapsed_seconds,
                latest_status_message=self._state.latest_status_message,
            )

    def _clear_pending_requests(self) -> None:
        cleared = 0

        while True:
            try:
                self._requests.get_nowait()
                cleared += 1
            except queue.Empty:
                break

        if cleared:
            self.log(f"Discarded {cleared} older pending request(s).")

    def _worker_loop(self) -> None:
        try:
            missing_files = self.settings.missing_files()

            if missing_files:
                message = "KataGo missing files: " + ", ".join(
                    str(path) for path in missing_files
                )

                with self._lock:
                    self._state.is_thinking = False
                    self._state.latest_error = message
                    self._state.latest_status_message = message

                self.log(message)
                return

            self.log("Opening KataGo process...")

            with KataGoClient(self.settings) as client:
                self.log("KataGo process is ready.")

                while not self._stop_event.is_set():
                    try:
                        request = self._requests.get(timeout=0.25)
                    except queue.Empty:
                        continue

                    started_at = time.perf_counter()
                    thinking_message = (
                        f"Engine analyzing request #{request.request_id} "
                        f"for {request.current_player.name}"
                    )

                    with self._lock:
                        self._state.is_thinking = True
                        self._state.latest_status_message = thinking_message

                    self.log(thinking_message + "...")

                    try:
                        result = client.analyze_board(
                            board=request.board,
                            current_player=request.current_player,
                        )

                        elapsed = time.perf_counter() - started_at
                        done_message = (
                            f"Done request #{request.request_id} in {elapsed:.2f}s"
                        )

                        with self._lock:
                            if request.request_id >= self._state.completed_request_id:
                                self._state.latest_result = result
                                self._state.latest_error = None
                                self._state.completed_request_id = request.request_id
                                self._state.latest_elapsed_seconds = elapsed
                                self._state.latest_status_message = done_message
                                self._state.is_thinking = (
                                    self._state.completed_request_id
                                    < self._state.latest_request_id
                                )

                        self.log(done_message)

                        if result.root_winrate_percent is not None:
                            self.log(f"Winrate: {result.root_winrate_percent:.2f}%")

                        if result.root_score_lead is not None:
                            self.log(f"Score lead: {result.root_score_lead:+.2f}")

                        best_moves = [move.move for move in result.best_moves[:5]]
                        self.log(f"Best moves: {', '.join(best_moves)}")

                    except Exception as exc:
                        message = str(exc)

                        with self._lock:
                            self._state.latest_error = message
                            self._state.latest_status_message = f"ERROR: {message}"
                            self._state.is_thinking = False

                        self.log(f"ERROR: {message}")

        except Exception as exc:
            message = str(exc)

            with self._lock:
                self._state.latest_error = message
                self._state.latest_status_message = f"FATAL ERROR: {message}"
                self._state.is_thinking = False

            self.log(f"FATAL ERROR: {message}")
