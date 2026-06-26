from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class CoachEntry:
    move_number: int
    color: str
    move: str
    row: int | None
    col: int | None
    zone: str
    tenuki: bool
    captures: int = 0
    status: str = "waiting"
    black_winrate: float | None = None
    white_winrate: float | None = None
    score_lead: float | None = None
    score_text: str = "No score yet"
    top_move: str | None = None
    played_rank: int | None = None
    best_score_lead: float | None = None
    best_black_winrate: float | None = None
    winrate_delta: float | None = None
    score_delta: float | None = None
    explanation: list[str] = field(default_factory=list)
    wait_for_analysis_signature: str | None = None


class UniversalMoveCoach:
    """
    Passive coach that watches board-state changes.

    This means it works for normal play, SGF replay, and AI self-play,
    because it does not depend on mouse clicks. Any time the board changes,
    the coach records a move and attaches KataGo analysis when available.
    """

    def __init__(self, log_dir: str = "analysis_logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_path = self.log_dir / "go_sensei_coach_session.md"
        self.entries: list[CoachEntry] = []

        self.previous_board_signature: tuple[str, ...] | None = None
        self.previous_matrix: list[list[str | None]] | None = None

        self.previous_focus: tuple[int, int] | None = None
        self.previous_ready_black_winrate: float | None = None
        self.previous_ready_score_lead: float | None = None

        self.session_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_written_count = -1
        self.last_written_ready_count = -1

    # -----------------------------
    # Board reading
    # -----------------------------

    def read_board_matrix(self, window: Any) -> list[list[str | None]]:
        board = getattr(window, "board", None)
        size = int(getattr(board, "size", 19) or 19)

        matrix: list[list[str | None]] = []

        for row in range(size):
            row_values: list[str | None] = []

            for col in range(size):
                stone = self.read_cell(board, row, col)
                row_values.append(stone)

            matrix.append(row_values)

        return matrix

    def read_cell(self, board: Any, row: int, col: int) -> str | None:
        value = None

        if board is None:
            return None

        for method_name in ["get", "get_stone", "stone_at", "get_intersection"]:
            method = getattr(board, method_name, None)
            if callable(method):
                try:
                    value = method(row, col)
                    break
                except Exception:
                    try:
                        value = method((row, col))
                        break
                    except Exception:
                        pass

        if value is None and hasattr(board, "grid"):
            try:
                value = board.grid[row][col]
            except Exception:
                pass

        if value is None and hasattr(board, "stones"):
            try:
                value = board.stones.get((row, col))
            except Exception:
                pass

        return self.normalize_stone(value)

    def normalize_stone(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).lower()

        if "empty" in text or "none" in text:
            return None

        if text in {"0", ".", "-", ""}:
            return None

        if "black" in text or text.endswith(".b") or text == "b":
            return "B"

        if "white" in text or text.endswith(".w") or text == "w":
            return "W"

        return None

    def board_signature(self, matrix: list[list[str | None]]) -> tuple[str, ...]:
        return tuple("".join(cell or "." for cell in row) for row in matrix)

    def count_stones(self, matrix: list[list[str | None]]) -> int:
        return sum(1 for row in matrix for cell in row if cell is not None)

    # -----------------------------
    # Move detection
    # -----------------------------

    def detect_move(
        self,
        old: list[list[str | None]],
        new: list[list[str | None]],
    ) -> tuple[str, int | None, int | None, int]:
        added: list[tuple[int, int, str]] = []
        removed = 0

        size = len(new)

        for row in range(size):
            for col in range(size):
                old_cell = old[row][col]
                new_cell = new[row][col]

                if old_cell != new_cell:
                    if old_cell is None and new_cell is not None:
                        added.append((row, col, new_cell))
                    elif old_cell is not None and new_cell is None:
                        removed += 1
                    elif old_cell is not None and new_cell is not None:
                        added.append((row, col, new_cell))

        if added:
            row, col, color = added[-1]
            return color, row, col, removed

        return "?", None, None, removed

    def coord_name(self, row: int | None, col: int | None, size: int) -> str:
        if row is None or col is None:
            return "Pass/Unknown"

        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        file_label = letters[col]
        rank_label = size - row

        return f"{file_label}{rank_label}"

    def point_zone(self, row: int | None, col: int | None, size: int) -> str:
        if row is None or col is None:
            return "unknown"

        edge_distance = min(row, col, size - 1 - row, size - 1 - col)

        if edge_distance <= 4 and (
            (row <= 6 or row >= size - 7) and (col <= 6 or col >= size - 7)
        ):
            return "corner"

        if edge_distance <= 3:
            return "side"

        return "center"

    def is_tenuki(self, row: int | None, col: int | None) -> bool:
        if row is None or col is None or self.previous_focus is None:
            return False

        old_row, old_col = self.previous_focus
        distance = abs(row - old_row) + abs(col - old_col)

        return distance >= 10

    # -----------------------------
    # KataGo / analysis extraction
    # -----------------------------

    def get_value(self, obj: Any, *names: str) -> Any:
        for name in names:
            if obj is None:
                continue

            if isinstance(obj, dict) and name in obj:
                return obj[name]

            if hasattr(obj, name):
                return getattr(obj, name)

        return None

    def get_current_analysis(self, window: Any) -> Any:
        method = getattr(window, "get_current_analysis_result", None)
        if callable(method):
            try:
                result = method()
                if result:
                    return result
            except Exception:
                pass

        possible_names = [
            "analysis_result",
            "current_analysis_result",
            "latest_analysis_result",
            "last_analysis_result",
            "current_analysis",
            "latest_analysis",
            "last_analysis",
            "katago_result",
            "analysis_data",
            "root_analysis",
        ]

        for name in possible_names:
            value = getattr(window, name, None)
            if value:
                return value

        analyzer = getattr(window, "live_analyzer", None)
        if analyzer is not None:
            for name in possible_names:
                value = getattr(analyzer, name, None)
                if value:
                    return value

        return None

    def root_info(self, result: Any) -> Any:
        return (
            self.get_value(result, "rootInfo", "root_info", "root")
            or result
        )

    def normalize_percent(self, value: Any) -> float | None:
        if value is None:
            return None

        try:
            number = float(value)
        except Exception:
            return None

        if 0.0 <= number <= 1.0:
            number *= 100.0

        return max(0.0, min(100.0, number))

    def black_winrate_percent(self, result: Any) -> float | None:
        root = self.root_info(result)

        value = self.get_value(
            root,
            "black_winrate_percent",
            "root_winrate_percent",
            "blackWinrate",
            "black_winrate",
            "winrate",
        )

        if value is None:
            value = self.get_value(
                result,
                "black_winrate_percent",
                "root_winrate_percent",
                "blackWinrate",
                "black_winrate",
                "winrate",
            )

        return self.normalize_percent(value)

    def score_lead(self, result: Any) -> float | None:
        root = self.root_info(result)

        value = self.get_value(
            root,
            "scoreLead",
            "score_lead",
            "root_score_lead",
            "scoreMean",
            "score_mean",
        )

        if value is None:
            value = self.get_value(
                result,
                "scoreLead",
                "score_lead",
                "root_score_lead",
                "scoreMean",
                "score_mean",
            )

        try:
            return float(value)
        except Exception:
            return None

    def move_infos(self, result: Any) -> list[Any]:
        value = self.get_value(
            result,
            "moveInfos",
            "move_infos",
            "top_moves",
            "moves",
            "recommendations",
        )

        if isinstance(value, list):
            return value

        return []

    def move_name_from_info(self, info: Any) -> str | None:
        value = self.get_value(info, "move", "coord", "coordinate", "point")

        if value is None:
            return None

        if isinstance(value, list) and len(value) >= 2:
            return None

        return str(value).upper()

    def analysis_signature(self, result: Any) -> str | None:
        if not result:
            return None

        black = self.black_winrate_percent(result)
        score = self.score_lead(result)
        infos = self.move_infos(result)

        top_parts: list[str] = []

        for info in infos[:5]:
            move = self.move_name_from_info(info)
            visits = self.get_value(info, "visits", "visit_count")
            wr = self.get_value(info, "winrate", "black_winrate", "blackWinrate")
            sc = self.get_value(info, "scoreLead", "score_lead", "scoreMean")
            top_parts.append(f"{move}:{visits}:{wr}:{sc}")

        return f"{black}:{score}:" + "|".join(top_parts)

    # -----------------------------
    # Coach update loop
    # -----------------------------

    def update(self, window: Any) -> None:
        matrix = self.read_board_matrix(window)
        signature = self.board_signature(matrix)
        result = self.get_current_analysis(window)
        result_signature = self.analysis_signature(result)

        if self.previous_board_signature is None:
            self.previous_board_signature = signature
            self.previous_matrix = matrix
            return

        if signature != self.previous_board_signature:
            if self.count_stones(matrix) == 0:
                self.entries.clear()
                self.previous_focus = None
                self.previous_ready_black_winrate = None
                self.previous_ready_score_lead = None
                self.previous_board_signature = signature
                self.previous_matrix = matrix
                self.write_log()
                return

            if self.previous_matrix is not None:
                color, row, col, captures = self.detect_move(self.previous_matrix, matrix)
            else:
                color, row, col, captures = "?", None, None, 0

            size = len(matrix)
            move = self.coord_name(row, col, size)
            zone = self.point_zone(row, col, size)
            tenuki = self.is_tenuki(row, col)

            entry = CoachEntry(
                move_number=len(self.entries) + 1,
                color="Black" if color == "B" else "White" if color == "W" else "Unknown",
                move=move,
                row=row,
                col=col,
                zone=zone,
                tenuki=tenuki,
                captures=captures,
                wait_for_analysis_signature=result_signature,
            )

            entry.explanation.append(
                f"{entry.color} played {entry.move} in the {entry.zone}."
            )

            if entry.tenuki:
                entry.explanation.append(
                    "This is a tenuki-style move: the play shifted away from the previous local area."
                )

            if captures > 0:
                entry.explanation.append(
                    f"This move also changed captured stones: {captures} stone(s) were removed."
                )

            self.entries.append(entry)

            if row is not None and col is not None:
                self.previous_focus = (row, col)

            self.previous_board_signature = signature
            self.previous_matrix = matrix

            self.request_fresh_analysis(window)
            self.write_log()

        self.try_enrich_latest_entry(result)

    def request_fresh_analysis(self, window: Any) -> None:
        # Try common analysis refresh methods without depending on one exact UI name.
        for method_name in [
            "coach_request_fresh_analysis",
            "request_live_analysis",
            "request_analysis",
            "request_analysis_update",
            "analyze_current_position",
            "update_analysis",
            "start_analysis",
        ]:
            method = getattr(window, method_name, None)

            if callable(method):
                try:
                    method()
                    return
                except TypeError:
                    pass
                except Exception:
                    return

    def try_enrich_latest_entry(self, result: Any) -> None:
        if not self.entries or not result:
            return

        entry = self.entries[-1]

        if entry.status == "ready":
            return

        current_signature = self.analysis_signature(result)

        if (
            entry.wait_for_analysis_signature is not None
            and current_signature == entry.wait_for_analysis_signature
        ):
            # This is probably still the previous position's analysis.
            return

        self.enrich_entry(entry, result)
        self.write_log()

    def enrich_entry(self, entry: CoachEntry, result: Any) -> None:
        black = self.black_winrate_percent(result)
        score = self.score_lead(result)

        entry.black_winrate = black
        entry.white_winrate = 100.0 - black if black is not None else None
        entry.score_lead = score
        entry.status = "ready"

        if score is not None:
            if score > 0:
                entry.score_text = f"Black by {score:.1f}"
            elif score < 0:
                entry.score_text = f"White by {abs(score):.1f}"
            else:
                entry.score_text = "Even"

        if black is not None and self.previous_ready_black_winrate is not None:
            entry.winrate_delta = black - self.previous_ready_black_winrate

        if score is not None and self.previous_ready_score_lead is not None:
            entry.score_delta = score - self.previous_ready_score_lead

        infos = self.move_infos(result)

        if infos:
            top = infos[0]
            entry.top_move = self.move_name_from_info(top)

            top_wr = self.get_value(top, "winrate", "black_winrate", "blackWinrate")
            top_score = self.get_value(top, "scoreLead", "score_lead", "scoreMean")

            entry.best_black_winrate = self.normalize_percent(top_wr)

            try:
                entry.best_score_lead = float(top_score)
            except Exception:
                entry.best_score_lead = None

            for index, info in enumerate(infos[:10], start=1):
                name = self.move_name_from_info(info)

                if name and name.upper() == entry.move.upper():
                    entry.played_rank = index
                    break

        self.build_explanation(entry)

        if black is not None:
            self.previous_ready_black_winrate = black

        if score is not None:
            self.previous_ready_score_lead = score

    def build_explanation(self, entry: CoachEntry) -> None:
        if entry.black_winrate is not None and entry.white_winrate is not None:
            entry.explanation.append(
                f"After this move: Black win probability {entry.black_winrate:.1f}%, White {entry.white_winrate:.1f}%."
            )

        entry.explanation.append(f"Estimated score: {entry.score_text}.")

        if entry.winrate_delta is not None:
            side = "Black" if entry.winrate_delta > 0 else "White"
            entry.explanation.append(
                f"Winrate swing: {side} gained about {abs(entry.winrate_delta):.1f} percentage points."
            )

            if abs(entry.winrate_delta) >= 12:
                entry.explanation.append(
                    "Coach note: this was a major swing. Review this move carefully."
                )
            elif abs(entry.winrate_delta) >= 5:
                entry.explanation.append(
                    "Coach note: this was a meaningful swing, not just a small preference."
                )
            else:
                entry.explanation.append(
                    "Coach note: this move did not drastically change the game evaluation."
                )

        if entry.score_delta is not None:
            if entry.score_delta > 0:
                entry.explanation.append(
                    f"Score movement: Black improved by about {abs(entry.score_delta):.1f} points."
                )
            elif entry.score_delta < 0:
                entry.explanation.append(
                    f"Score movement: White improved by about {abs(entry.score_delta):.1f} points."
                )

        if entry.top_move:
            entry.explanation.append(f"KataGo's top suggestion after this position: {entry.top_move}.")

        if entry.played_rank == 1:
            entry.explanation.append(
                "The played move matches KataGo's top candidate. This is engine-approved."
            )
        elif entry.played_rank is not None:
            entry.explanation.append(
                f"The played move appears in KataGo's top candidates at rank #{entry.played_rank}."
            )
        else:
            entry.explanation.append(
                "The played move was not found in the visible top candidates, so compare it against KataGo's main line."
            )

        if entry.tenuki:
            entry.explanation.append(
                "Strategic idea: because this move leaves the previous area, ask whether the earlier fight was truly urgent or only emotionally uncomfortable."
            )

        if entry.zone == "corner":
            entry.explanation.append(
                "Board logic: corner moves are efficient because the board edges help secure territory quickly."
            )
        elif entry.zone == "side":
            entry.explanation.append(
                "Board logic: side moves often expand frameworks, reduce moyos, or create running room for groups."
            )
        elif entry.zone == "center":
            entry.explanation.append(
                "Board logic: center moves are usually about influence, attack, connection, or whole-board pressure rather than immediate territory."
            )

        if entry.black_winrate is not None:
            if entry.black_winrate >= 98 or entry.black_winrate <= 2:
                entry.explanation.append(
                    "Decisive position: win probability is saturated, so score lead is more useful than winrate for comparing moves."
                )

    # -----------------------------
    # Markdown log
    # -----------------------------

    def write_log(self) -> None:
        ready_count = sum(1 for entry in self.entries if entry.status == "ready")

        if (
            len(self.entries) == self.last_written_count
            and ready_count == self.last_written_ready_count
        ):
            return

        self.last_written_count = len(self.entries)
        self.last_written_ready_count = ready_count

        lines: list[str] = []
        lines.append("# Go Sensei Coach Session")
        lines.append("")
        lines.append(f"Started: {self.session_started}")
        lines.append("")
        lines.append("This log watches every board change, so it works during normal play, SGF replay, and AI self-play.")
        lines.append("")
        lines.append("---")
        lines.append("")

        if not self.entries:
            lines.append("No moves recorded yet.")
            self.log_path.write_text("\n".join(lines), encoding="utf-8")
            return

        for entry in self.entries:
            marker = "READY" if entry.status == "ready" else "WAITING FOR KATAGO"
            lines.append(f"## Move {entry.move_number}: {entry.color} {entry.move} — {marker}")
            lines.append("")

            if entry.black_winrate is not None and entry.white_winrate is not None:
                lines.append(f"- Win probability: Black {entry.black_winrate:.1f}% / White {entry.white_winrate:.1f}%")

            lines.append(f"- Estimated score: {entry.score_text}")

            if entry.winrate_delta is not None:
                lines.append(f"- Winrate swing: {entry.winrate_delta:+.1f} percentage points for Black")

            if entry.score_delta is not None:
                lines.append(f"- Score swing: {entry.score_delta:+.1f} points for Black")

            if entry.top_move:
                lines.append(f"- KataGo top suggestion after this move: {entry.top_move}")

            if entry.played_rank is not None:
                lines.append(f"- Played move rank: #{entry.played_rank}")
            else:
                lines.append("- Played move rank: not in visible top candidates yet")

            lines.append("")
            lines.append("### Coach explanation")
            lines.append("")

            for note in entry.explanation:
                lines.append(f"- {note}")

            lines.append("")

        self.log_path.write_text("\n".join(lines), encoding="utf-8")

    def latest_summary_lines(self) -> list[str]:
        if not self.entries:
            return ["Coach is watching the board.", "Play, replay SGF, or start AI self-play."]

        entry = self.entries[-1]

        lines = [
            f"Move {entry.move_number}: {entry.color} {entry.move}",
            f"Score: {entry.score_text}",
        ]

        if entry.black_winrate is not None and entry.white_winrate is not None:
            lines.append(
                f"Winrate: B {entry.black_winrate:.1f}% / W {entry.white_winrate:.1f}%"
            )
        else:
            lines.append("Waiting for KataGo analysis...")

        if entry.top_move:
            lines.append(f"KataGo likes: {entry.top_move}")

        if entry.played_rank == 1:
            lines.append("Played move: top engine candidate")
        elif entry.played_rank is not None:
            lines.append(f"Played move rank: #{entry.played_rank}")
        else:
            lines.append("Played move: not in visible top candidates")

        if entry.tenuki:
            lines.append("Tenuki/global shift detected.")

        lines.append(r"Log: analysis_logs\go_sensei_coach_session.md")

        return lines
