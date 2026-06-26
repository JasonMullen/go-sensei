
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class CoachReview:
    move_number: int
    color: str
    move: str
    row: int | None
    col: int | None
    captures: int
    pre: dict[str, Any] | None
    verdict: str = "Review"
    move_text: str = "Waiting for move feedback..."
    impact_text: str = "Waiting for move feedback..."
    lesson_text: str = "Waiting for move feedback."
    status: str = "ready"


class DetailedLeftCoach:
    def __init__(self) -> None:
        self.previous_signature = None
        self.previous_matrix = None
        self.previous_focus = None
        self.latest_snapshot = None
        self.latest_snapshot_signature = None
        self.pending_review = None
        self.entries = []
        self.last_completed_post_signature = None

        self.log_dir = Path("analysis_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "go_sensei_detailed_coach.md"
        self.started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def clear(self) -> None:
        self.previous_signature = None
        self.previous_matrix = None
        self.previous_focus = None
        self.latest_snapshot = None
        self.latest_snapshot_signature = None
        self.pending_review = None
        self.entries = []
        self.last_completed_post_signature = None
        self.write_log()

    def normalize_stone(self, value):
        if value is None:
            return None

        text = str(value).lower().strip()

        if text in {"", ".", "-", "0", "none"} or "empty" in text:
            return None

        if "black" in text or text == "b" or text.endswith(".b"):
            return "B"

        if "white" in text or text == "w" or text.endswith(".w"):
            return "W"

        return None

    def read_cell(self, board, row, col):
        value = None

        for method_name in ("get", "get_stone", "stone_at", "get_intersection"):
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

    def read_board_matrix(self, window):
        board = getattr(window, "board", None)
        size = int(getattr(board, "size", 19) or 19)

        matrix = []

        for row in range(size):
            row_values = []

            for col in range(size):
                row_values.append(self.read_cell(board, row, col))

            matrix.append(row_values)

        return matrix

    def board_signature(self, matrix):
        return tuple("".join(cell or "." for cell in row) for row in matrix)

    def stone_count(self, matrix):
        return sum(1 for row in matrix for cell in row if cell is not None)

    def detect_move(self, old_matrix, new_matrix):
        added = []
        removed = 0

        for row in range(len(new_matrix)):
            for col in range(len(new_matrix)):
                old_cell = old_matrix[row][col]
                new_cell = new_matrix[row][col]

                if old_cell == new_cell:
                    continue

                if old_cell is None and new_cell is not None:
                    added.append((row, col, new_cell))
                elif old_cell is not None and new_cell is None:
                    removed += 1
                elif old_cell is not None and new_cell is not None:
                    added.append((row, col, new_cell))

        if added:
            row, col, color = added[-1]
            return row, col, color, removed

        return None, None, "?", removed

    def board_change_stats(self, old_matrix, new_matrix):
        added = 0
        removed = 0

        for row in range(len(new_matrix)):
            for col in range(len(new_matrix)):
                old_cell = old_matrix[row][col]
                new_cell = new_matrix[row][col]

                if old_cell == new_cell:
                    continue

                if old_cell is None and new_cell is not None:
                    added += 1
                elif old_cell is not None and new_cell is None:
                    removed += 1
                else:
                    added += 1
                    removed += 1

        return added, removed

    def looks_like_backward_navigation(self, old_matrix, new_matrix) -> bool:
        old_count = self.stone_count(old_matrix)
        new_count = self.stone_count(new_matrix)
        added, removed = self.board_change_stats(old_matrix, new_matrix)

        if new_count == 0:
            return True

        if added == 1:
            return False

        if new_count < old_count:
            return True

        if added + removed > 3:
            return True

        if removed > 0 and added == 0:
            return True

        return False

    def coord_name(self, row, col, size):
        if row is None or col is None:
            return "Pass/Unknown"

        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        return f"{letters[col]}{size - row}"

    def get_value(self, obj, *names):
        for name in names:
            if obj is None:
                continue

            if isinstance(obj, dict) and name in obj:
                return obj[name]

            if hasattr(obj, name):
                return getattr(obj, name)

        return None

    def normalize_percent(self, value):
        if value is None:
            return None

        try:
            number = float(value)
        except Exception:
            return None

        if 0.0 <= number <= 1.0:
            number *= 100.0

        return max(0.0, min(100.0, number))

    def candidate_has_analysis(self, obj):
        if obj is None:
            return False

        if isinstance(obj, dict):
            keys = set(obj.keys())
            useful = {
                "rootInfo",
                "root_info",
                "moveInfos",
                "move_infos",
                "best_moves",
                "top_moves",
                "recommendations",
                "black_winrate_percent",
                "root_winrate_percent",
                "scoreLead",
                "score_lead",
            }
            return bool(keys & useful)

        for name in (
            "rootInfo",
            "root_info",
            "moveInfos",
            "move_infos",
            "best_moves",
            "top_moves",
            "recommendations",
            "black_winrate_percent",
            "root_winrate_percent",
            "scoreLead",
            "score_lead",
        ):
            if hasattr(obj, name):
                return True

        return False

    def collect_analysis_candidates(self, window):
        candidates = []

        names = (
            "current_analysis_result",
            "latest_analysis_result",
            "last_analysis_result",
            "analysis_result",
            "current_analysis",
            "latest_analysis",
            "last_analysis",
            "katago_result",
            "analysis_data",
            "root_analysis",
        )

        for name in names:
            value = getattr(window, name, None)

            if value:
                candidates.append(value)

        for container_name in (
            "analysis_state",
            "analysis_service",
            "live_analyzer",
            "analyzer",
            "katago_analyzer",
            "katago_client",
            "reviewer",
            "game_reviewer",
            "live_move_coach",
        ):
            container = getattr(window, container_name, None)

            if container is None:
                continue

            if self.candidate_has_analysis(container):
                candidates.append(container)

            for name in names + ("result", "current_result", "latest_result"):
                value = getattr(container, name, None)

                if value:
                    candidates.append(value)

        return [item for item in candidates if self.candidate_has_analysis(item)]

    def root_info(self, result):
        return self.get_value(result, "rootInfo", "root_info", "root") or result

    def extract_moves(self, result):
        raw = self.get_value(
            result,
            "best_moves",
            "moveInfos",
            "move_infos",
            "top_moves",
            "moves",
            "recommendations",
        )

        if raw is None:
            root = self.root_info(result)
            raw = self.get_value(
                root,
                "best_moves",
                "moveInfos",
                "move_infos",
                "top_moves",
                "moves",
                "recommendations",
            )

        if not isinstance(raw, list):
            return []

        parsed = []

        for index, info in enumerate(raw[:10], start=1):
            move = self.get_value(info, "move", "coord", "coordinate", "point")

            if move is None:
                continue

            move = str(move).upper()

            visits = self.get_value(info, "visits", "visit_count")
            wr = self.get_value(
                info,
                "black_winrate_percent",
                "winrate_percent",
                "blackWinrate",
                "black_winrate",
                "winrate",
            )
            score = self.get_value(info, "scoreLead", "score_lead", "scoreMean", "score_mean")
            pv = self.get_value(info, "pv", "principalVariation", "principal_variation", "variation")

            try:
                visits = int(visits)
            except Exception:
                visits = 0

            try:
                score = float(score)
            except Exception:
                score = None

            parsed.append(
                {
                    "move": move,
                    "rank": index,
                    "visits": visits,
                    "black_winrate": self.normalize_percent(wr),
                    "score": score,
                    "pv": pv if isinstance(pv, list) else [],
                }
            )

        return parsed

    def extract_snapshot(self, window):
        snapshots = []

        for result in self.collect_analysis_candidates(window):
            root = self.root_info(result)

            black_wr = self.get_value(
                root,
                "black_winrate_percent",
                "root_winrate_percent",
                "blackWinrate",
                "black_winrate",
                "winrate",
            )

            if black_wr is None:
                black_wr = self.get_value(
                    result,
                    "black_winrate_percent",
                    "root_winrate_percent",
                    "blackWinrate",
                    "black_winrate",
                    "winrate",
                )

            black_wr = self.normalize_percent(black_wr)

            score = self.get_value(
                root,
                "scoreLead",
                "score_lead",
                "root_score_lead",
                "scoreMean",
                "score_mean",
            )

            if score is None:
                score = self.get_value(
                    result,
                    "scoreLead",
                    "score_lead",
                    "root_score_lead",
                    "scoreMean",
                    "score_mean",
                )

            try:
                score = float(score)
            except Exception:
                score = None

            moves = self.extract_moves(result)

            if black_wr is None and score is None and not moves:
                continue

            signature = str(
                (
                    round(black_wr, 3) if black_wr is not None else None,
                    round(score, 3) if score is not None else None,
                    [
                        (
                            m["move"],
                            m["visits"],
                            round(m["black_winrate"], 3) if m["black_winrate"] is not None else None,
                            round(m["score"], 3) if m["score"] is not None else None,
                        )
                        for m in moves[:5]
                    ],
                )
            )

            snapshots.append(
                {
                    "black_winrate": black_wr,
                    "white_winrate": 100.0 - black_wr if black_wr is not None else None,
                    "score": score,
                    "moves": moves,
                    "signature": signature,
                }
            )

        if not snapshots:
            return None

        snapshots.sort(key=lambda item: len(item["moves"]), reverse=True)
        return snapshots[0]

    def request_analysis(self, window):
        for method_name in (
            "request_live_analysis",
            "request_analysis",
            "request_analysis_update",
            "analyze_current_position",
            "update_analysis",
            "start_analysis",
        ):
            method = getattr(window, method_name, None)

            if callable(method):
                try:
                    method()
                    return
                except Exception:
                    pass

        for container_name in ("live_analyzer", "analysis_service", "analyzer", "katago_analyzer"):
            container = getattr(window, container_name, None)

            if container is None:
                continue

            for method_name in (
                "request_live_analysis",
                "request_analysis",
                "request_analysis_update",
                "analyze_current_position",
                "update_analysis",
                "start_analysis",
            ):
                method = getattr(container, method_name, None)

                if callable(method):
                    try:
                        method()
                        return
                    except Exception:
                        pass

    def score_text(self, score):
        if score is None:
            return "No score yet"

        if score > 0:
            return f"Black by {score:.2f}"

        if score < 0:
            return f"White by {abs(score):.2f}"

        return "Even"

    def pv_text(self, move):
        if not move:
            return "No variation shown."

        pv = move.get("pv") or []

        if not pv:
            return "No variation shown."

        return " ".join(str(item).upper() for item in pv[:8])

    def game_phase(self, stone_count):
        if stone_count <= 30:
            return "opening"

        if stone_count <= 120:
            return "middle game"

        return "endgame"

    def zone_and_pattern(self, row, col):
        if row is None or col is None:
            return "unknown", None

        edge = min(row, col, 18 - row, 18 - col)

        if edge <= 4 and ((row <= 6 or row >= 12) and (col <= 6 or col >= 12)):
            zone = "corner"
        elif edge <= 3:
            zone = "side"
        else:
            zone = "center"

        vertical = min(row + 1, 19 - row)
        horizontal = min(col + 1, 19 - col)

        pattern = None

        if vertical <= 7 and horizontal <= 7:
            a, b = sorted([vertical, horizontal])
            pattern = f"{a}-{b}"

        return zone, pattern

    def local_context(self, matrix, row, col, color_code):
        if row is None or col is None:
            return {
                "friendly_near": 0,
                "enemy_near": 0,
                "friendly_wide": 0,
                "enemy_wide": 0,
                "density": 0,
            }

        enemy_code = "W" if color_code == "B" else "B"
        friendly_near = 0
        enemy_near = 0
        friendly_wide = 0
        enemy_wide = 0

        for r in range(len(matrix)):
            for c in range(len(matrix)):
                if r == row and c == col:
                    continue

                stone = matrix[r][c]

                if stone is None:
                    continue

                dist = abs(r - row) + abs(c - col)

                if dist <= 2:
                    if stone == color_code:
                        friendly_near += 1
                    elif stone == enemy_code:
                        enemy_near += 1

                if dist <= 5:
                    if stone == color_code:
                        friendly_wide += 1
                    elif stone == enemy_code:
                        enemy_wide += 1

        return {
            "friendly_near": friendly_near,
            "enemy_near": enemy_near,
            "friendly_wide": friendly_wide,
            "enemy_wide": enemy_wide,
            "density": friendly_wide + enemy_wide,
        }

    def general_idea(self, zone, pattern):
        if pattern == "3-3":
            return "General idea: 3-3 is direct territory. It takes the corner clearly, but it usually gives the opponent outside influence."

        if pattern == "3-4":
            return "General idea: 3-4 is flexible. It balances corner territory with outside development, so direction of play matters."

        if pattern == "4-4":
            return "General idea: 4-4 is fast and influence-oriented. It values speed, outside development, and whole-board potential."

        if pattern == "3-5":
            return "General idea: 3-5 is high and ambitious. It aims at outside pressure, but can become thin without support."

        if pattern == "4-5":
            return "General idea: 4-5 is a high-pressure point. It often invites fighting or large-scale influence."

        if zone == "corner":
            return "General idea: corner moves are efficient because two board edges help secure territory."

        if zone == "side":
            return "General idea: side moves usually expand a framework, reduce the opponent, or help a weak group run."

        if zone == "center":
            return "General idea: center moves are usually about influence, connection, attack, escape, or whole-board pressure."

        return "General idea: judge this move by how it changes nearby groups and whole-board direction."

    def why_here(self, review, matrix, stone_count, tenuki):
        zone, pattern = self.zone_and_pattern(review.row, review.col)
        phase = self.game_phase(stone_count)
        color_code = "B" if review.color == "Black" else "W" if review.color == "White" else "?"
        local = self.local_context(matrix, review.row, review.col, color_code)

        top_move = None
        black_wr = None
        white_wr = None
        score = None

        if self.latest_snapshot:
            moves = self.latest_snapshot.get("moves") or []

            if moves:
                top_move = moves[0].get("move")

            black_wr = self.latest_snapshot.get("black_winrate")
            white_wr = self.latest_snapshot.get("white_winrate")
            score = self.latest_snapshot.get("score")

        lines = []

        lines.append(f"Move context: {review.color} {review.move} is a {phase} move in the {zone}.")

        if pattern:
            lines.append(f"Shape pattern: {pattern}.")

        lines.append(self.general_idea(zone, pattern))

        if local["density"] == 0:
            lines.append("Why this can be good here: the area is open, so the move is mainly about development, direction, and claiming future potential before contact starts.")
        elif local["friendly_wide"] > local["enemy_wide"]:
            lines.append("Why this can be good here: you have nearby support, so the move is more likely to build from strength instead of becoming isolated.")
        elif local["enemy_wide"] > local["friendly_wide"]:
            lines.append("Why this is risky here: there are more enemy stones nearby than friendly stones. It can work as a probe or reduction, but it needs a clear escape route or forcing sequence.")
        else:
            lines.append("Why this is balanced here: both sides have comparable local presence, so the value depends on sente, shape, and the next forcing move.")

        if local["enemy_near"] > 0 and local["friendly_near"] > 0:
            lines.append("Local fighting note: both colors are close to the move, so liberties, cutting points, and connection matter more than abstract territory.")

        if tenuki:
            lines.append("Tenuki note: this move leaves the previous area. That is strong when the old fight is settled, but risky if a weak group or severe cut was left behind.")
        else:
            lines.append("Local-answer note: this move stays near the previous area. That can be disciplined, but make sure you are not just following the opponent around.")

        if top_move:
            if top_move.upper() == review.move.upper():
                lines.append(f"KataGo context: the visible top move matches {review.move}, so the move is good here because it fits the engine's whole-board priority.")
            else:
                lines.append(f"KataGo context: the visible top suggestion is {top_move}. Your move may still be locally logical, but KataGo may see another area as bigger, more urgent, or better timed.")

        if black_wr is not None and white_wr is not None:
            lines.append(f"Evaluation context: Black {black_wr:.1f}% / White {white_wr:.1f}%. Estimated score: {self.score_text(score)}.")

        return zone, pattern, phase, local, top_move, "\n\n".join(lines)

    def build_review(self, review, matrix, stone_count, tenuki):
        zone, pattern, phase, local, top_move, impact = self.why_here(review, matrix, stone_count, tenuki)

        if top_move and top_move.upper() == review.move.upper():
            review.verdict = f"Good here: {zone}"
        elif top_move:
            review.verdict = f"Study this: {zone}"
        else:
            review.verdict = f"{phase.title()} {zone}"

        capture_text = f"\nCaptured stones: {review.captures}" if review.captures else ""

        review.move_text = (
            f"{review.color} {review.move}{capture_text}\n"
            f"Area: {zone}"
            + (f" / Pattern: {pattern}" if pattern else "")
        )

        review.impact_text = impact

        lesson = []

        lesson.append("How to think about this move:")
        lesson.append("")
        lesson.append("1. Separate the general idea from this exact position.")
        lesson.append("A move can be normal in general but wrong here if another group is weak, another area is bigger, or the direction is off.")
        lesson.append("")
        lesson.append("2. Ask what the move does immediately.")
        lesson.append("Does it defend, attack, connect, cut, invade, reduce, expand, or take territory?")
        lesson.append("")
        lesson.append("3. Ask why it is good or questionable here.")

        if local["friendly_wide"] > local["enemy_wide"]:
            lesson.append("Here, nearby friendly support makes the move more reliable. You can build from strength.")
        elif local["enemy_wide"] > local["friendly_wide"]:
            lesson.append("Here, nearby enemy strength makes the move more dangerous. It needs a follow-up plan.")
        elif local["density"] == 0:
            lesson.append("Here, the board is open around this move. The value is direction and future development.")
        else:
            lesson.append("Here, the local balance is close. Look for sente, shape, and the opponent's strongest reply.")

        lesson.append("")
        lesson.append("4. Compare with KataGo.")
        lesson.append("Do not only ask which move has higher winrate. Ask what problem KataGo's move solves first.")
        lesson.append("")
        lesson.append("5. Study question:")
        lesson.append("If you remove this move from the board, what weakness or opportunity appears? That tells you the purpose of the move.")

        review.lesson_text = "\n".join(lesson)
        review.status = "ready"

    def enrich_with_katago(self, review, post):
        top_after = post["moves"][0] if post.get("moves") else None
        extra = []

        if post.get("black_winrate") is not None and post.get("white_winrate") is not None:
            extra.append(f"After move: Black {post['black_winrate']:.1f}% / White {post['white_winrate']:.1f}%")

        extra.append(f"Estimated score: {self.score_text(post.get('score'))}")

        if top_after:
            extra.append(f"KataGo now wants: {top_after['move']}")
            extra.append(f"Suggested continuation: {self.pv_text(top_after)}")

        if extra and "Fresh KataGo reading:" not in review.impact_text:
            review.impact_text += "\n\nFresh KataGo reading:\n" + "\n".join(extra)

        if top_after and "KataGo drill:" not in review.lesson_text:
            review.lesson_text += (
                f"\n\nKataGo drill:\n"
                f"Replay the position once with {review.move}, then once with {top_after['move']}.\n"
                "Look for which version leaves fewer weak groups and clearer direction."
            )

    def update(self, window):
        matrix = self.read_board_matrix(window)
        signature = self.board_signature(matrix)
        stone_count = self.stone_count(matrix)

        snapshot = self.extract_snapshot(window)

        if snapshot is not None and snapshot["signature"] != self.latest_snapshot_signature:
            self.latest_snapshot = snapshot
            self.latest_snapshot_signature = snapshot["signature"]

        if self.previous_signature is None:
            self.previous_signature = signature
            self.previous_matrix = matrix
            return

        if stone_count == 0:
            self.clear()
            self.previous_signature = signature
            self.previous_matrix = matrix
            return

        if (
            self.previous_matrix is not None
            and signature != self.previous_signature
            and self.looks_like_backward_navigation(self.previous_matrix, matrix)
        ):
            self.clear()
            self.previous_signature = signature
            self.previous_matrix = matrix
            return

        if signature != self.previous_signature:
            if self.previous_matrix is not None:
                row, col, color_code, captures = self.detect_move(self.previous_matrix, matrix)
            else:
                row, col, color_code, captures = None, None, "?", 0

            color = "Black" if color_code == "B" else "White" if color_code == "W" else "Unknown"
            move = self.coord_name(row, col, len(matrix))

            tenuki = False

            if row is not None and col is not None and self.previous_focus is not None:
                old_row, old_col = self.previous_focus
                tenuki = abs(row - old_row) + abs(col - old_col) >= 10

            review = CoachReview(
                move_number=len(self.entries) + 1,
                color=color,
                move=move,
                row=row,
                col=col,
                captures=captures,
                pre=self.latest_snapshot,
            )

            self.build_review(review, matrix, stone_count, tenuki)

            self.pending_review = review
            self.entries.append(review)

            self.previous_signature = signature
            self.previous_matrix = matrix

            if row is not None and col is not None:
                self.previous_focus = (row, col)

            self.request_analysis(window)
            self.write_log()
            return

        if self.pending_review is not None and snapshot is not None:
            pre_sig = self.pending_review.pre["signature"] if self.pending_review.pre is not None else None
            post_sig = snapshot["signature"]

            if post_sig != pre_sig and post_sig != self.last_completed_post_signature:
                self.last_completed_post_signature = post_sig
                self.enrich_with_katago(self.pending_review, snapshot)
                self.pending_review = None
                self.write_log()

    def latest_ui(self):
        if not self.entries:
            return {
                "summary": "Review",
                "move": "Waiting for move feedback...",
                "impact": "Waiting for move feedback...",
                "lesson": "Play a move, replay an SGF, or let the AI play itself.",
            }

        entry = self.entries[-1]

        return {
            "summary": entry.verdict,
            "move": entry.move_text,
            "impact": entry.impact_text,
            "lesson": entry.lesson_text,
        }

    def write_log(self):
        lines = []
        lines.append("# Go Sensei Detailed Coach")
        lines.append("")
        lines.append(f"Started: {self.started}")
        lines.append("")
        lines.append("This file records contextual feedback from the board position and KataGo.")
        lines.append("")
        lines.append("---")
        lines.append("")

        if not self.entries:
            lines.append("No moves reviewed yet.")
        else:
            for entry in self.entries:
                lines.append(f"## Move {entry.move_number}: {entry.color} {entry.move}")
                lines.append("")
                lines.append(f"**Verdict:** {entry.verdict}")
                lines.append("")
                lines.append("### Move")
                lines.append(entry.move_text)
                lines.append("")
                lines.append("### Why / Impact")
                lines.append(entry.impact_text)
                lines.append("")
                lines.append("### Lesson")
                lines.append(entry.lesson_text)
                lines.append("")
                lines.append("---")
                lines.append("")

        self.log_path.write_text("\n".join(lines), encoding="utf-8")
