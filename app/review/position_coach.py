
from __future__ import annotations

from pathlib import Path


class PositionCoach:
    def __init__(self) -> None:
        self.previous_signature = None
        self.previous_matrix = None
        self.content = {
            "summary": "Review",
            "move": "Waiting for move feedback...",
            "impact": "Play a move, replay an SGF, or let the AI play itself.",
            "lesson": "The coach will explain the whole-board position, the purpose of the move, and what to study next.",
        }

    def clear(self) -> None:
        self.previous_signature = None
        self.previous_matrix = None
        self.content = {
            "summary": "Review",
            "move": "Waiting for move feedback...",
            "impact": "Play a move, replay an SGF, or let the AI play itself.",
            "lesson": "The coach will explain the whole-board position, the purpose of the move, and what to study next.",
        }

    def norm_stone(self, value):
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

        return self.norm_stone(value)

    def matrix(self, window):
        board = getattr(window, "board", None)
        size = int(getattr(board, "size", 19) or 19)

        result = []

        for row in range(size):
            row_values = []

            for col in range(size):
                row_values.append(self.read_cell(board, row, col))

            result.append(row_values)

        return result

    def signature(self, matrix):
        return tuple("".join(cell or "." for cell in row) for row in matrix)

    def stone_count(self, matrix):
        return sum(1 for row in matrix for cell in row if cell is not None)

    def coord(self, row, col, size=19):
        if row is None or col is None:
            return "Current position"

        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        return f"{letters[col]}{size - row}"

    def phase(self, stone_count):
        if stone_count <= 30:
            return "opening"

        if stone_count <= 120:
            return "middle game"

        return "endgame"

    def neighbors(self, row, col, size):
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr = row + dr
            cc = col + dc

            if 0 <= rr < size and 0 <= cc < size:
                yield rr, cc

    def groups(self, matrix):
        size = len(matrix)
        seen = set()
        groups = []

        for row in range(size):
            for col in range(size):
                color = matrix[row][col]

                if color is None or (row, col) in seen:
                    continue

                stack = [(row, col)]
                stones = set()
                liberties = set()

                while stack:
                    r, c = stack.pop()

                    if (r, c) in seen:
                        continue

                    if matrix[r][c] != color:
                        continue

                    seen.add((r, c))
                    stones.add((r, c))

                    for nr, nc in self.neighbors(r, c, size):
                        if matrix[nr][nc] is None:
                            liberties.add((nr, nc))
                        elif matrix[nr][nc] == color and (nr, nc) not in seen:
                            stack.append((nr, nc))

                groups.append(
                    {
                        "color": color,
                        "stones": stones,
                        "liberties": liberties,
                        "liberty_count": len(liberties),
                        "size": len(stones),
                        "center": (
                            sum(r for r, c in stones) / max(1, len(stones)),
                            sum(c for r, c in stones) / max(1, len(stones)),
                        ),
                    }
                )

        return groups

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

        return None, None, None, removed

    def zone_pattern(self, row, col):
        if row is None or col is None:
            return "whole board", None

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

    def pattern_meaning(self, zone, pattern):
        if pattern == "3-3":
            return "The 3-3 point is direct territory. It secures the corner but usually gives the opponent outside influence."

        if pattern == "3-4":
            return "The 3-4 point is flexible. It balances territory and outside development, so direction of play matters."

        if pattern == "4-4":
            return "The 4-4 point is fast and influence-based. It values speed, outside strength, and whole-board development."

        if pattern == "3-5":
            return "The 3-5 point is high and ambitious. It can pressure the opponent, but it can also become thin."

        if pattern == "4-5":
            return "The 4-5 point is a high-pressure move. It often aims at fighting, influence, or a large framework."

        if zone == "corner":
            return "Corner moves are efficient because two board edges help make territory."

        if zone == "side":
            return "Side moves usually expand, reduce, invade, or help a weak group run."

        if zone == "center":
            return "Center moves usually matter through attack, escape, connection, influence, or whole-board pressure."

        return "This position should be judged by weak groups, sente, big areas, and whole-board direction."

    def group_label(self, group):
        if group is None:
            return "none"

        row = int(group["center"][0])
        col = int(group["center"][1])
        color = "Black" if group["color"] == "B" else "White"

        return f"{color} group near {self.coord(row, col)}, {group['size']} stones, {group['liberty_count']} liberties"

    def group_containing(self, groups, row, col):
        if row is None or col is None:
            return None

        for group in groups:
            if (row, col) in group["stones"]:
                return group

        return None

    def local_context(self, groups, row, col, color):
        enemy = "W" if color == "B" else "B"

        context = {
            "friendly_wide": 0,
            "enemy_wide": 0,
            "near_weak_friend": None,
            "near_weak_enemy": None,
        }

        if row is None or col is None or color not in ("B", "W"):
            return context

        for group in groups:
            dist = min(abs(row - r) + abs(col - c) for r, c in group["stones"])

            if group["color"] == color:
                if dist <= 5:
                    context["friendly_wide"] += group["size"]

                if dist <= 5 and group["liberty_count"] <= 3:
                    if context["near_weak_friend"] is None or group["liberty_count"] < context["near_weak_friend"]["liberty_count"]:
                        context["near_weak_friend"] = group

            elif group["color"] == enemy:
                if dist <= 5:
                    context["enemy_wide"] += group["size"]

                if dist <= 5 and group["liberty_count"] <= 3:
                    if context["near_weak_enemy"] is None or group["liberty_count"] < context["near_weak_enemy"]["liberty_count"]:
                        context["near_weak_enemy"] = group

        return context

    def get_value(self, obj, *names):
        for name in names:
            if obj is None:
                continue

            if isinstance(obj, dict) and name in obj:
                return obj[name]

            if hasattr(obj, name):
                return getattr(obj, name)

        return None

    def percent(self, value):
        if value is None:
            return None

        try:
            number = float(value)
        except Exception:
            return None

        if 0.0 <= number <= 1.0:
            number *= 100.0

        return max(0.0, min(100.0, number))

    def katago(self, window):
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
        ):
            container = getattr(window, container_name, None)

            if container is None:
                continue

            candidates.append(container)

            for name in names + ("result", "current_result", "latest_result"):
                value = getattr(container, name, None)

                if value:
                    candidates.append(value)

        best_move = None
        black_wr = None
        score = None
        top_moves = []

        for result in candidates:
            root = self.get_value(result, "rootInfo", "root_info", "root") or result

            if black_wr is None:
                black_wr = self.get_value(
                    root,
                    "black_winrate_percent",
                    "root_winrate_percent",
                    "blackWinrate",
                    "black_winrate",
                    "winrate",
                )

            if score is None:
                score = self.get_value(
                    root,
                    "scoreLead",
                    "score_lead",
                    "root_score_lead",
                    "scoreMean",
                    "score_mean",
                )

            raw_moves = self.get_value(
                result,
                "moveInfos",
                "move_infos",
                "best_moves",
                "top_moves",
                "recommendations",
                "moves",
            )

            if raw_moves is None:
                raw_moves = self.get_value(
                    root,
                    "moveInfos",
                    "move_infos",
                    "best_moves",
                    "top_moves",
                    "recommendations",
                    "moves",
                )

            if isinstance(raw_moves, list) and raw_moves:
                for info in raw_moves[:5]:
                    move = self.get_value(info, "move", "coord", "coordinate", "point")

                    if move:
                        top_moves.append(str(move).upper())

                if best_move is None and top_moves:
                    best_move = top_moves[0]

        black_wr = self.percent(black_wr)

        try:
            score = float(score)
        except Exception:
            score = None

        return {
            "best_move": best_move,
            "top_moves": top_moves,
            "black_wr": black_wr,
            "white_wr": 100.0 - black_wr if black_wr is not None else None,
            "score": score,
        }

    def score_text(self, score):
        if score is None:
            return "No score estimate yet"

        if score > 0:
            return f"Black by {score:.2f}"

        if score < 0:
            return f"White by {abs(score):.2f}"

        return "Even"

    def build_position_plan(self, window, matrix):
        groups = self.groups(matrix)
        stone_count = self.stone_count(matrix)
        phase = self.phase(stone_count)
        katago = self.katago(window)

        black_groups = [g for g in groups if g["color"] == "B"]
        white_groups = [g for g in groups if g["color"] == "W"]

        black_weak = sorted([g for g in black_groups if g["liberty_count"] <= 3], key=lambda g: g["liberty_count"])
        white_weak = sorted([g for g in white_groups if g["liberty_count"] <= 3], key=lambda g: g["liberty_count"])

        summary = f"{phase.title()} position plan"
        move_text = f"Whole-board review\nStones: {stone_count} | Black groups: {len(black_groups)} | White groups: {len(white_groups)}"

        impact = []

        impact.append(f"This is a {phase} position, so the coach is looking at the whole board first.")
        impact.append("Before judging any move, find the urgent thing: weak groups, big open areas, sente, and the largest framework.")

        if black_weak:
            impact.append(f"Black's clearest weakness: {self.group_label(black_weak[0])}.")
        else:
            impact.append("Black has no obvious emergency group with 3 or fewer liberties.")

        if white_weak:
            impact.append(f"White's clearest weakness: {self.group_label(white_weak[0])}.")
        else:
            impact.append("White has no obvious emergency group with 3 or fewer liberties.")

        if katago["best_move"]:
            impact.append(f"KataGo's visible priority is {katago['best_move']}. The coaching question is: what problem does that move solve first?")

        if katago["black_wr"] is not None and katago["white_wr"] is not None:
            impact.append(f"Engine context: Black {katago['black_wr']:.1f}% / White {katago['white_wr']:.1f}. Score: {self.score_text(katago['score'])}.")

        lesson = []

        lesson.append("Coach's plan:")
        lesson.append("")
        lesson.append("1. Do not start by asking 'what is the best move?'")
        lesson.append("Start by asking 'what is urgent?'")
        lesson.append("")
        lesson.append("2. Check weak groups first.")
        lesson.append("A big move is not big if one of your groups is about to be attacked or cut.")
        lesson.append("")
        lesson.append("3. Then check direction.")
        lesson.append("Which side of the board has the most future value? Which move makes your earlier stones more useful?")
        lesson.append("")
        lesson.append("4. Compare with KataGo.")

        if katago["best_move"]:
            lesson.append(f"KataGo points to {katago['best_move']}. Ask why that move is urgent or efficient here.")
        else:
            lesson.append("When KataGo shows top moves, compare the purpose of those moves instead of only comparing numbers.")

        self.content = {
            "summary": summary,
            "move": move_text,
            "impact": "\n\n".join(impact),
            "lesson": "\n".join(lesson),
        }

    def build_move_review(self, window, matrix, row, col, color, captures):
        groups = self.groups(matrix)
        stone_count = self.stone_count(matrix)
        phase = self.phase(stone_count)
        zone, pattern = self.zone_pattern(row, col)
        katago = self.katago(window)
        local = self.local_context(groups, row, col, color)

        move_name = self.coord(row, col)
        color_name = "Black" if color == "B" else "White"

        move_group = self.group_containing(groups, row, col)
        best_move = katago["best_move"]

        if best_move and best_move.upper() == move_name.upper():
            summary = f"Strong move: {move_name}"
        elif best_move:
            summary = f"Coach review: {move_name}"
        else:
            summary = f"{phase.title()} {zone}: {move_name}"

        capture_text = f"\nCaptured stones: {captures}" if captures else ""
        move_text = f"{color_name} {move_name}{capture_text}\nArea: {zone}" + (f" | Pattern: {pattern}" if pattern else "")

        impact = []

        impact.append(f"{color_name} {move_name} is a {phase} move in the {zone}.")
        impact.append(self.pattern_meaning(zone, pattern))

        if move_group is not None:
            impact.append(f"The played stone belongs to: {self.group_label(move_group)}.")

        if local["near_weak_friend"] is not None:
            impact.append(f"Real purpose here: this move is near a friendly weak group: {self.group_label(local['near_weak_friend'])}. That makes it a stabilizing or shape-improving move.")
        elif local["near_weak_enemy"] is not None:
            impact.append(f"Real purpose here: this move is near an enemy weak group: {self.group_label(local['near_weak_enemy'])}. That makes it an attacking or pressure move.")
        elif local["friendly_wide"] > local["enemy_wide"]:
            impact.append("Real purpose here: friendly support is nearby, so the move is building from strength. It can expand influence, support an attack, or prepare a larger framework.")
        elif local["enemy_wide"] > local["friendly_wide"]:
            impact.append("Real purpose here: more enemy stones are nearby than friendly stones. This can be a reduction or probe, but it needs a clear escape route or forcing follow-up.")
        elif local["friendly_wide"] == 0 and local["enemy_wide"] == 0:
            impact.append("Real purpose here: this is an open-area move. It is about direction, development, and claiming future potential before contact starts.")
        else:
            impact.append("Real purpose here: the local balance is even, so the move must be judged by sente, shape, and the opponent's strongest reply.")

        if best_move:
            if best_move.upper() == move_name.upper():
                impact.append("KataGo agrees with this move. That means it likely fits the whole-board priority, not just local shape.")
            else:
                impact.append(f"KataGo prefers {best_move}. Your move may be logical locally, but KataGo is saying another problem is bigger, more urgent, or better timed.")

        if katago["black_wr"] is not None and katago["white_wr"] is not None:
            impact.append(f"Engine context: Black {katago['black_wr']:.1f}% / White {katago['white_wr']:.1f}. Score: {self.score_text(katago['score'])}.")

        lesson = []

        lesson.append("Coach's read:")
        lesson.append("")
        lesson.append("1. Name the purpose of the move.")
        lesson.append("Is it defending, attacking, connecting, cutting, expanding, reducing, invading, or taking territory?")
        lesson.append("")
        lesson.append("2. Ask if that purpose matches this position.")

        if local["near_weak_friend"] is not None:
            lesson.append("Here, defense or shape may be correct because a friendly group nearby needs care.")
        elif local["near_weak_enemy"] is not None:
            lesson.append("Here, pressure may be correct because an enemy group nearby can be attacked.")
        elif local["friendly_wide"] > local["enemy_wide"]:
            lesson.append("Here, the move has support, so building from strength is reasonable.")
        elif local["enemy_wide"] > local["friendly_wide"]:
            lesson.append("Here, the move is more dangerous because enemy stones are nearby. Look for the escape route.")
        else:
            lesson.append("Here, the board is not forcing one obvious local answer, so whole-board direction matters.")

        lesson.append("")
        lesson.append("3. Ask the most important practical question:")
        lesson.append("If I ignore this area, what is the opponent's most painful move?")
        lesson.append("")
        lesson.append("4. Compare with KataGo's priority.")

        if best_move:
            lesson.append(f"KataGo points to {best_move}. Ask what that move fixes or threatens that this move does not.")
        else:
            lesson.append("When KataGo gives a top move, study the purpose of that move instead of only the winrate.")

        self.content = {
            "summary": summary,
            "move": move_text,
            "impact": "\n\n".join(impact),
            "lesson": "\n".join(lesson),
        }

    def write_log(self):
        try:
            Path("analysis_logs").mkdir(parents=True, exist_ok=True)
            Path("analysis_logs/go_sensei_detailed_coach.md").write_text(
                "# Go Sensei Coach\n\n"
                f"## {self.content['summary']}\n\n"
                f"### Move\n{self.content['move']}\n\n"
                f"### Whole-board and Move Context\n{self.content['impact']}\n\n"
                f"### Coaching Plan\n{self.content['lesson']}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def update(self, window):
        matrix = self.matrix(window)
        signature = self.signature(matrix)
        stone_count = self.stone_count(matrix)

        if stone_count == 0:
            self.clear()
            self.previous_signature = signature
            self.previous_matrix = matrix
            return

        if self.previous_signature is None:
            self.previous_signature = signature
            self.previous_matrix = matrix
            self.build_position_plan(window, matrix)
            self.write_log()
            return

        if signature != self.previous_signature:
            old_matrix = self.previous_matrix

            row, col, color, captures = self.detect_move(old_matrix, matrix)

            self.previous_signature = signature
            self.previous_matrix = matrix

            if row is not None and col is not None and color is not None:
                self.build_move_review(window, matrix, row, col, color, captures)
            else:
                self.build_position_plan(window, matrix)

            self.write_log()
            return

        if self.content["move"] == "Waiting for move feedback...":
            self.build_position_plan(window, matrix)
            self.write_log()

    def latest_ui(self):
        return self.content
