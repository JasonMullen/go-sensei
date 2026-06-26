
from __future__ import annotations

from typing import Any


class FreeGoKnowledge:
    def coord_to_row_col(self, coord: str) -> tuple[int, int] | None:
        if not coord:
            return None

        coord = str(coord).upper().strip()
        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

        if coord[0] not in letters:
            return None

        try:
            rank = int(coord[1:])
        except Exception:
            return None

        if not (1 <= rank <= 19):
            return None

        col = letters.index(coord[0])
        row = 19 - rank

        return row, col

    def zone_name(self, row: int | None, col: int | None) -> str:
        if row is None or col is None:
            return "unknown"

        edge = min(row, col, 18 - row, 18 - col)

        if edge <= 4 and ((row <= 6 or row >= 12) and (col <= 6 or col >= 12)):
            return "corner"

        if edge <= 3:
            return "side"

        return "center"

    def corner_pattern(self, row: int | None, col: int | None) -> str | None:
        if row is None or col is None:
            return None

        vertical = min(row + 1, 19 - row)
        horizontal = min(col + 1, 19 - col)

        if vertical > 7 or horizontal > 7:
            return None

        a, b = sorted([vertical, horizontal])
        return f"{a}-{b}"

    def game_phase(self, stone_count: int) -> str:
        if stone_count <= 30:
            return "opening"
        if stone_count <= 120:
            return "middle game"
        return "endgame"

    def pattern_idea(self, pattern: str | None) -> str:
        ideas = {
            "3-3": (
                "The 3-3 point is direct territory. It usually says: take the corner clearly, "
                "even if the opponent gets outside influence."
            ),
            "3-4": (
                "The 3-4 point is flexible. It is not only territory and not only influence; "
                "the main question is direction of play. Which side should this corner face?"
            ),
            "4-4": (
                "The 4-4 point is fast and influence-oriented. It values speed, outside development, "
                "and whole-board coordination more than immediately locking the corner."
            ),
            "3-5": (
                "The 3-5 point is high and ambitious. It often aims to pressure the opponent or build outside shape, "
                "but it can be thin if the rest of the board does not support it."
            ),
            "4-5": (
                "The 4-5 point is a high-pressure corner move. It often invites fighting and asks whether your outside influence "
                "will be useful later."
            ),
            "5-5": (
                "The 5-5 point is very high and framework-oriented. It usually needs support from nearby stones or a clear moyo plan."
            ),
        }

        if pattern is None:
            return "This is not a standard corner point, so its meaning depends more on nearby stones, weak groups, and direction."

        return ideas.get(
            pattern,
            f"This is a {pattern} corner/edge pattern. Treat it as a direction-of-play question, not just a local joseki question."
        )

    def zone_idea(self, zone: str) -> str:
        if zone == "corner":
            return (
                "Corner logic: corners are the most efficient place to make secure territory because two board edges help you."
            )

        if zone == "side":
            return (
                "Side logic: side moves usually expand a framework, reduce the opponent's area, or give a weak group running room."
            )

        if zone == "center":
            return (
                "Center logic: center moves rarely make direct territory immediately. They usually matter because of influence, attack, connection, escape, or whole-board pressure."
            )

        return "The move should be judged by its relationship to nearby groups and the whole-board direction."

    def stage_idea(self, phase: str) -> str:
        if phase == "opening":
            return (
                "Opening lens: do not only ask whether the move is locally good. Ask whether it makes your earlier stones more useful "
                "and whether it chooses the correct direction for future development."
            )

        if phase == "middle game":
            return (
                "Middle-game lens: weak groups, cutting points, sente, and attack-for-profit become more important than simple territory."
            )

        return (
            "Endgame lens: the question becomes sente/gote and point value. A move can be small in territory but big if it keeps initiative."
        )

    def tenuki_idea(self, tenuki: bool) -> str:
        if not tenuki:
            return (
                "Local-continuation check: since this move stays near the previous area, ask whether you are playing because it is truly urgent "
                "or because you feel emotionally pulled into the fight."
            )

        return (
            "Tenuki/global-shift check: this move leaves the previous local area. That can be strong if the old fight is not urgent, "
            "but dangerous if a weak group or cutting point needed immediate attention."
        )

    def kata_go_idea(self, played: str, top_move: str | None, score_text: str, black_wr: float | None, white_wr: float | None) -> str:
        if top_move and top_move.upper() != played.upper():
            return (
                f"KataGo prefers {top_move} next. Do not read that as simply 'your move is bad.' "
                f"Read it as a priority signal: KataGo thinks {top_move} is more urgent, bigger, or better timed in the whole-board position."
            )

        if top_move and top_move.upper() == played.upper():
            return (
                "KataGo's visible top move matches the played move. Study the follow-up: the value is not only the point itself, "
                "but the continuation it prepares."
            )

        if black_wr is not None and white_wr is not None:
            return (
                f"Current evaluation: Black {black_wr:.1f}% / White {white_wr:.1f}%, score {score_text}. "
                "Use winrate to judge who is likely to win; use score to judge the margin."
            )

        return (
            "KataGo has not exposed a clear top move yet. Use the concept lesson first, then compare with the engine once the right panel updates."
        )

    def shape_questions(self, zone: str, pattern: str | None, phase: str) -> str:
        questions = []

        questions.append("Does this move make one of your weak groups safer, or does it make the opponent's group heavier?")

        if zone == "corner":
            questions.append("Is the move choosing territory, influence, or attack direction?")
            questions.append("If this is joseki-like, does the joseki fit the rest of the board, or are you memorizing a local pattern?")
        elif zone == "side":
            questions.append("Is this an extension, reduction, invasion, or running move?")
            questions.append("Does it face your strength, or is it playing into the opponent's strength?")
        elif zone == "center":
            questions.append("Is this move connecting, cutting, attacking, escaping, or building influence?")

        if phase == "middle game":
            questions.append("What is the most severe opponent reply if you tenuki?")
            questions.append("Are there cutting points or forcing moves that should be handled first?")

        if pattern in {"3-4", "4-4", "3-5", "4-5"}:
            questions.append("Which direction should this stone develop toward: side extension, enclosure, pincer, or outside influence?")

        return "\n".join(f"- {q}" for q in questions)

    def nuanced_lesson(
        self,
        played: str,
        color: str,
        stone_count: int,
        tenuki: bool,
        top_move: str | None,
        score_text: str,
        black_wr: float | None,
        white_wr: float | None,
    ) -> dict[str, str]:
        rc = self.coord_to_row_col(played)

        if rc is None:
            return {
                "summary": "Concept review",
                "impact": "This move could not be mapped to a normal coordinate.",
                "lesson": "Use KataGo's suggested continuation and compare the move to nearby weaknesses."
            }

        row, col = rc
        zone = self.zone_name(row, col)
        pattern = self.corner_pattern(row, col)
        phase = self.game_phase(stone_count)

        summary = f"{phase.title()} {zone}"
        if pattern:
            summary += f" / {pattern}"

        impact_parts = [
            self.zone_idea(zone),
            self.pattern_idea(pattern),
            self.stage_idea(phase),
            self.tenuki_idea(tenuki),
            self.kata_go_idea(played, top_move, score_text, black_wr, white_wr),
        ]

        lesson_parts = [
            "Think about this move through layers, not just as one local point:",
            self.shape_questions(zone, pattern, phase),
        ]

        if color == "Black":
            lesson_parts.append(
                "Because Black moved, ask whether Black is increasing pressure while keeping sente, or simply adding another local stone."
            )
        elif color == "White":
            lesson_parts.append(
                "Because White moved, ask whether White is reducing Black's potential, stabilizing a group, or taking the initiative elsewhere."
            )

        if top_move and top_move.upper() != played.upper():
            lesson_parts.append(
                f"Comparison drill: replay the position once with {played}, then once with KataGo's {top_move}. "
                "Look for which version leaves fewer weak groups and better future forcing moves."
            )
        else:
            lesson_parts.append(
                "Continuation drill: do not stop at this move. Ask what the next forcing move, extension, or attack target should be."
            )

        return {
            "summary": summary,
            "impact": "\n\n".join(impact_parts),
            "lesson": "\n\n".join(lesson_parts),
        }
