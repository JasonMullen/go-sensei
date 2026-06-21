from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.board import Board
from app.core.coordinates import human_to_point
from app.core.stone import Stone


@dataclass(frozen=True)
class MoveConceptExplanation:
    severity: str
    tags: list[str]
    summary: str
    why_better: str


def explain_move_conceptually(
    board: Board,
    played_move: str,
    best_move: str | None,
    player: Stone,
    winrate_loss: float | None,
    score_loss: float | None,
    move_number: int,
) -> MoveConceptExplanation:
    severity = classify_severity(winrate_loss)
    tags: list[str] = []

    played_region = classify_region(board, played_move)
    best_region = classify_region(board, best_move) if best_move else "unknown"

    if played_region != "unknown":
        tags.append(played_region)

    if best_region != "unknown" and best_region != played_region:
        tags.append(f"engine preferred {best_region}")

    if best_move:
        distance = move_distance(board, played_move, best_move)

        if distance is not None:
            if distance <= 3:
                tags.append("local fight")
            elif distance >= 8:
                tags.append("global priority / tenuki")

    neighbor_info = local_neighbor_profile(board, played_move, player)

    if neighbor_info["enemy_neighbors"] >= 2:
        tags.append("contact fight")

    if neighbor_info["own_neighbors"] >= 2:
        tags.append("shape / connection")

    if move_number <= 30:
        tags.append("opening direction")
    elif move_number <= 120:
        tags.append("middle game judgment")
    else:
        tags.append("endgame value")

    if winrate_loss is None:
        summary = (
            f"{played_move} was played by {player.name.title()}, but the engine did not "
            "give enough comparison data to measure the exact loss."
        )
    elif winrate_loss < 2:
        summary = (
            f"{played_move} was close to acceptable. The engine did not see a major loss, "
            "so the move is probably playable even if it was not the top choice."
        )
    elif winrate_loss < 5:
        summary = (
            f"{played_move} looks like a small inaccuracy. The move may be locally reasonable, "
            "but KataGo preferred a move with slightly better whole-board value."
        )
    elif winrate_loss < 10:
        summary = (
            f"{played_move} looks like a real mistake. The issue is probably not just tactics; "
            "it likely misjudged the biggest area of the board."
        )
    else:
        summary = (
            f"{played_move} looks like a major mistake. KataGo thinks this move gave up a large "
            "amount of winning chances, usually because a more urgent fight, defense, or big point existed."
        )

    if best_move:
        why_better = build_better_move_reason(
            board=board,
            played_move=played_move,
            best_move=best_move,
            played_region=played_region,
            best_region=best_region,
            winrate_loss=winrate_loss,
            score_loss=score_loss,
        )
    else:
        why_better = "No clear better move was available from the engine output."

    return MoveConceptExplanation(
        severity=severity,
        tags=dedupe(tags),
        summary=summary,
        why_better=why_better,
    )


def classify_severity(winrate_loss: float | None) -> str:
    if winrate_loss is None:
        return "unclear"

    if winrate_loss < 2:
        return "okay"
    if winrate_loss < 5:
        return "inaccuracy"
    if winrate_loss < 10:
        return "mistake"

    return "blunder"


def classify_region(board: Board, move: str | None) -> str:
    if move is None or move.lower() == "pass":
        return "unknown"

    try:
        row, col = human_to_point(move, board.size)
    except ValueError:
        return "unknown"

    edge_distance = min(row, col, board.size - 1 - row, board.size - 1 - col)

    if edge_distance <= 3:
        if (row <= 5 or row >= board.size - 6) and (col <= 5 or col >= board.size - 6):
            return "corner"
        return "side"

    return "center / influence"


def move_distance(board: Board, move_a: str, move_b: str) -> float | None:
    try:
        row_a, col_a = human_to_point(move_a, board.size)
        row_b, col_b = human_to_point(move_b, board.size)
    except ValueError:
        return None

    return math.dist((row_a, col_a), (row_b, col_b))


def local_neighbor_profile(board: Board, move: str, player: Stone) -> dict[str, int]:
    try:
        row, col = human_to_point(move, board.size)
    except ValueError:
        return {"own_neighbors": 0, "enemy_neighbors": 0, "empty_neighbors": 0}

    opponent = Stone.WHITE if player == Stone.BLACK else Stone.BLACK

    own_neighbors = 0
    enemy_neighbors = 0
    empty_neighbors = 0

    for next_row, next_col in [
        (row - 1, col),
        (row + 1, col),
        (row, col - 1),
        (row, col + 1),
    ]:
        if not (0 <= next_row < board.size and 0 <= next_col < board.size):
            continue

        coordinate = board_coordinate(board, next_row, next_col)
        stone = board.get(coordinate)

        if stone == player:
            own_neighbors += 1
        elif stone == opponent:
            enemy_neighbors += 1
        else:
            empty_neighbors += 1

    return {
        "own_neighbors": own_neighbors,
        "enemy_neighbors": enemy_neighbors,
        "empty_neighbors": empty_neighbors,
    }


def board_coordinate(board: Board, row: int, col: int) -> str:
    from app.core.coordinates import point_to_human

    return point_to_human(row, col, board.size)


def build_better_move_reason(
    board: Board,
    played_move: str,
    best_move: str,
    played_region: str,
    best_region: str,
    winrate_loss: float | None,
    score_loss: float | None,
) -> str:
    reason_parts: list[str] = []

    if played_region != best_region:
        reason_parts.append(
            f"KataGo preferred {best_move} in the {best_region} instead of {played_move} in the {played_region}."
        )
    else:
        reason_parts.append(
            f"KataGo preferred {best_move}, which is in the same general area as the played move."
        )

    distance = move_distance(board, played_move, best_move)

    if distance is not None:
        if distance <= 3:
            reason_parts.append(
                "Because the better move is nearby, the mistake is probably about local shape, liberties, cutting points, or defense."
            )
        elif distance >= 8:
            reason_parts.append(
                "Because the better move is far away, the mistake is probably about whole-board priority: the played move was too small or too slow."
            )
        else:
            reason_parts.append(
                "The better move is moderately far away, which suggests a balance between local fighting and whole-board value."
            )

    if winrate_loss is not None:
        reason_parts.append(f"The engine estimated about {winrate_loss:.1f}% winrate loss.")

    if score_loss is not None:
        reason_parts.append(f"The estimated point loss was about {score_loss:.2f} points.")

    return " ".join(reason_parts)


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []

    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)

    return output
