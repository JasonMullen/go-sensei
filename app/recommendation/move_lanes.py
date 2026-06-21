from __future__ import annotations

from dataclasses import dataclass

from app.analysis.katago_client import KataGoAnalysisResult
from app.core.coordinates import human_to_point


@dataclass(frozen=True)
class DisplayMoveLane:
    move: str
    lane: str
    label: str
    color: tuple[int, int, int]
    reason: str


BLUE = (65, 145, 255)
GREEN = (70, 220, 130)
ORANGE = (255, 165, 60)


def build_display_move_lanes(
    result: KataGoAnalysisResult | None,
    board_size: int,
    style_preferences: list[tuple[str, str, int]] | None = None,
    cosmic_preferences: list[tuple[str, str, int]] | None = None,
) -> list[DisplayMoveLane]:
    if result is None or not result.best_moves:
        return []

    lanes: list[DisplayMoveLane] = []
    used: set[str] = set()

    for index, move in enumerate(result.best_moves[:3], start=1):
        if move.move in used:
            continue

        lanes.append(
            DisplayMoveLane(
                move=move.move,
                lane="engine",
                label=f"B{index}",
                color=BLUE,
                reason="KataGo optimal candidate",
            )
        )
        used.add(move.move)

    jason_moves = select_profile_moves(
        result=result,
        board_size=board_size,
        preferences=style_preferences or [],
        used=used,
    )

    for index, move in enumerate(jason_moves[:2], start=1):
        lanes.append(
            DisplayMoveLane(
                move=move,
                lane="jason_style",
                label=f"G{index}",
                color=GREEN,
                reason="Similar to your current playing style",
            )
        )
        used.add(move)

    cosmic_moves = select_profile_moves(
        result=result,
        board_size=board_size,
        preferences=cosmic_preferences or [],
        used=used,
    )

    if not cosmic_moves:
        cosmic_moves = select_cosmic_fallback_moves(
            result=result,
            board_size=board_size,
            used=used,
        )

    for index, move in enumerate(cosmic_moves[:2], start=1):
        lanes.append(
            DisplayMoveLane(
                move=move,
                lane="cosmic",
                label=f"C{index}",
                color=ORANGE,
                reason="Cosmic Go / influence-style candidate",
            )
        )
        used.add(move)

    return lanes


def select_profile_moves(
    result: KataGoAnalysisResult,
    board_size: int,
    preferences: list[tuple[str, str, int]],
    used: set[str],
) -> list[str]:
    if not preferences:
        return []

    scored: list[tuple[int, str]] = []

    for move_info in result.best_moves:
        move = move_info.move

        if move in used:
            continue

        region = classify_region(move, board_size)
        line_type = classify_line_type(move, board_size)

        score = 0

        for preferred_region, preferred_line_type, count in preferences:
            if region == preferred_region:
                score += 3 * count

            if line_type == preferred_line_type:
                score += 2 * count

        if score > 0:
            scored.append((score, move))

    scored.sort(reverse=True)
    return [move for _score, move in scored]


def select_cosmic_fallback_moves(
    result: KataGoAnalysisResult,
    board_size: int,
    used: set[str],
) -> list[str]:
    scored: list[tuple[float, str]] = []

    for move_info in result.best_moves:
        move = move_info.move

        if move in used:
            continue

        score = cosmic_score(move, board_size)

        if score > 0:
            scored.append((score, move))

    scored.sort(reverse=True)
    return [move for _score, move in scored]


def cosmic_score(move: str, board_size: int) -> float:
    try:
        row, col = human_to_point(move, board_size)
    except ValueError:
        return 0.0

    edge = min(row, col, board_size - 1 - row, board_size - 1 - col)
    center = (board_size - 1) / 2
    distance_from_center = abs(row - center) + abs(col - center)

    score = 0.0
    score += max(0.0, 12.0 - distance_from_center)

    if edge >= 3:
        score += 4.0

    if edge >= 4:
        score += 3.0

    if edge <= 1:
        score -= 8.0

    return score


def classify_region(move: str, board_size: int) -> str:
    try:
        row, col = human_to_point(move, board_size)
    except ValueError:
        return "unknown"

    edge = min(row, col, board_size - 1 - row, board_size - 1 - col)

    in_corner_zone = (
        (row <= 5 or row >= board_size - 6)
        and (col <= 5 or col >= board_size - 6)
    )

    if edge <= 3 and in_corner_zone:
        return "corner"

    if edge <= 3:
        return "side"

    return "center"


def classify_line_type(move: str, board_size: int) -> str:
    try:
        row, col = human_to_point(move, board_size)
    except ValueError:
        return "unknown"

    line_from_edge = min(row, col, board_size - 1 - row, board_size - 1 - col) + 1

    if line_from_edge <= 2:
        return "low"
    if line_from_edge == 3:
        return "territory"
    if line_from_edge == 4:
        return "influence"

    return "cosmic_center"
