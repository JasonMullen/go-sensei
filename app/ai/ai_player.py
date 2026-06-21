from __future__ import annotations

from app.analysis.katago_client import KataGoAnalysisResult
from app.core.board import Board
from app.core.stone import Stone


def choose_ai_move(
    board: Board,
    player: Stone,
    result: KataGoAnalysisResult | None,
) -> str | None:
    if result is None:
        return None

    for move_info in result.best_moves:
        move = move_info.move

        if move.lower() == "pass":
            continue

        try:
            test_board = board.copy()
            test_board.place_stone(move, player)
        except Exception:
            continue

        return move

    return None
