from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.board import Board
from app.core.coordinates import point_to_human
from app.core.stone import Stone


@dataclass(frozen=True)
class KataGoSettings:
    executable_path: Path
    model_path: Path
    config_path: Path
    rules: str = "tromp-taylor"
    komi: float = 7.5
    max_visits: int = 100
    analysis_pv_len: int = 12
    timeout_seconds: float = 90.0

    @classmethod
    def from_environment(cls) -> "KataGoSettings":
        return cls(
            executable_path=Path(
                os.getenv("KATAGO_EXECUTABLE", "engines/katago/katago.exe")
            ),
            model_path=Path(
                os.getenv("KATAGO_MODEL", "engines/katago/model.bin.gz")
            ),
            config_path=Path(
                os.getenv("KATAGO_CONFIG", "engines/katago/analysis.cfg")
            ),
            rules=os.getenv("KATAGO_RULES", "tromp-taylor"),
            komi=float(os.getenv("KATAGO_KOMI", "7.5")),
            max_visits=int(os.getenv("KATAGO_MAX_VISITS", "100")),
            analysis_pv_len=int(os.getenv("KATAGO_PV_LEN", "12")),
        )

    def missing_files(self) -> list[Path]:
        missing: list[Path] = []

        for path in [self.executable_path, self.model_path, self.config_path]:
            if not path.exists():
                missing.append(path)

        return missing


@dataclass(frozen=True)
class KataGoMoveInfo:
    move: str
    winrate: float
    visits: int
    score_lead: float | None
    prior: float | None
    pv: list[str]
    order: int | None

    @property
    def winrate_percent(self) -> float:
        return self.winrate * 100


@dataclass(frozen=True)
class KataGoAnalysisResult:
    query_id: str
    board_size: int
    current_player: Stone
    root_winrate: float | None
    root_score_lead: float | None
    root_visits: int | None
    best_moves: list[KataGoMoveInfo]
    raw_response: dict[str, Any]

    @property
    def root_winrate_percent(self) -> float | None:
        if self.root_winrate is None:
            return None

        return self.root_winrate * 100


def board_to_initial_stones(board: Board) -> list[list[str]]:
    initial_stones: list[list[str]] = []

    for row in range(board.size):
        for col in range(board.size):
            stone = board.grid[row][col]

            if stone is None:
                continue

            coordinate = point_to_human(row, col, board.size)
            initial_stones.append([stone.value, coordinate])

    return initial_stones


def build_analysis_query(
    board: Board,
    current_player: Stone,
    settings: KataGoSettings,
    query_id: str | None = None,
) -> dict[str, Any]:
    if query_id is None:
        query_id = f"go-sensei-{uuid.uuid4().hex}"

    return {
        "id": query_id,
        "initialStones": board_to_initial_stones(board),
        "moves": [],
        "initialPlayer": current_player.value,
        "rules": settings.rules,
        "komi": settings.komi,
        "boardXSize": board.size,
        "boardYSize": board.size,
        "analyzeTurns": [0],
        "maxVisits": settings.max_visits,
        "analysisPVLen": settings.analysis_pv_len,
    }


def parse_analysis_response(
    response: dict[str, Any],
    board_size: int,
) -> KataGoAnalysisResult:
    if "error" in response:
        raise RuntimeError(f"KataGo error: {response['error']}")

    root_info = response.get("rootInfo", {})
    current_player_text = root_info.get("currentPlayer", "B")

    if current_player_text == "W":
        current_player = Stone.WHITE
    else:
        current_player = Stone.BLACK

    move_infos = response.get("moveInfos", [])
    best_moves: list[KataGoMoveInfo] = []

    for move_info in move_infos:
        best_moves.append(
            KataGoMoveInfo(
                move=str(move_info.get("move", "")),
                winrate=float(move_info.get("winrate", 0.0)),
                visits=int(move_info.get("visits", 0)),
                score_lead=optional_float(move_info.get("scoreLead")),
                prior=optional_float(move_info.get("prior")),
                pv=list(move_info.get("pv", [])),
                order=optional_int(move_info.get("order")),
            )
        )

    best_moves.sort(
        key=lambda move: (
            move.order if move.order is not None else 999_999,
            -move.visits,
        )
    )

    return KataGoAnalysisResult(
        query_id=str(response.get("id", "")),
        board_size=board_size,
        current_player=current_player,
        root_winrate=optional_float(root_info.get("winrate")),
        root_score_lead=optional_float(root_info.get("scoreLead")),
        root_visits=optional_int(root_info.get("visits")),
        best_moves=best_moves,
        raw_response=response,
    )


def optional_float(value: Any) -> float | None:
    if value is None:
        return None

    return float(value)


def optional_int(value: Any) -> int | None:
    if value is None:
        return None

    return int(value)


class KataGoClient:
    def __init__(self, settings: KataGoSettings) -> None:
        self.settings = settings
        self.process: subprocess.Popen[str] | None = None
        self.stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    def __enter__(self) -> "KataGoClient":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return

        missing_files = self.settings.missing_files()

        if missing_files:
            missing_text = "\n".join(f"- {path}" for path in missing_files)
            raise FileNotFoundError(
                "KataGo is not fully configured. Missing files:\n"
                f"{missing_text}\n\n"
                "Set these environment variables or place files in engines/katago:\n"
                "- KATAGO_EXECUTABLE\n"
                "- KATAGO_MODEL\n"
                "- KATAGO_CONFIG"
            )

        command = [
            str(self.settings.executable_path),
            "analysis",
            "-config",
            str(self.settings.config_path),
            "-model",
            str(self.settings.model_path),
        ]

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            daemon=True,
        )
        self._stderr_thread.start()

    def close(self) -> None:
        if self.process is None:
            return

        if self.process.stdin is not None:
            self.process.stdin.close()

        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()

        self.process = None

    def analyze_board(
        self,
        board: Board,
        current_player: Stone,
        query_id: str | None = None,
    ) -> KataGoAnalysisResult:
        query = build_analysis_query(
            board=board,
            current_player=current_player,
            settings=self.settings,
            query_id=query_id,
        )

        response = self.send_query(query)
        return parse_analysis_response(response, board_size=board.size)

    def send_query(self, query: dict[str, Any]) -> dict[str, Any]:
        self.start()

        if self.process is None:
            raise RuntimeError("KataGo process did not start.")

        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("KataGo process pipes are unavailable.")

        query_id = str(query["id"])
        query_line = json.dumps(query, separators=(",", ":"))

        self.process.stdin.write(query_line + "\n")
        self.process.stdin.flush()

        while True:
            if self.process.poll() is not None:
                stderr_text = "\n".join(self.stderr_lines[-20:])
                raise RuntimeError(
                    "KataGo exited before returning analysis.\n"
                    f"Recent stderr:\n{stderr_text}"
                )

            line = self.process.stdout.readline()

            if not line:
                continue

            response = json.loads(line)

            if "error" in response:
                raise RuntimeError(f"KataGo error: {response['error']}")

            if response.get("id") != query_id:
                continue

            if response.get("isDuringSearch") is True:
                continue

            return response

    def _read_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return

        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip())
