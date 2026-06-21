from __future__ import annotations

from typing import Iterable

from app.analysis.katago_client import KataGoAnalysisResult, KataGoMoveInfo
from app.core.board import Board
from app.core.stone import Stone


def _is_legal_move(board: Board, player: Stone, move: str) -> bool:
    if move.lower() == "pass":
        return True

    try:
        test_board = board.copy()
        test_board.place_stone(move, player)
        return True
    except Exception:
        return False


def _same_move(left: str, right: str) -> bool:
    return left.strip().upper() == right.strip().upper()


def choose_ai_move(
    board: Board,
    player: Stone,
    result: KataGoAnalysisResult | None,
    learned_moves: Iterable[str] | None = None,
    max_learned_rank: int = 8,
    max_winrate_loss: float = 3.0,
    max_score_loss: float = 4.0,
) -> str | None:
    """Choose an AI move.

    Default behavior: play KataGo's best legal move.

    If learned_moves are supplied, Go Sensei may choose one of those learned
    self-play moves only if it is still close to KataGo's top move.
    """

    if result is None:
        return None

    legal_candidates: list[KataGoMoveInfo] = []

    for move_info in result.best_moves:
        move = move_info.move

        if not move:
            continue

        if move.lower() == "pass":
            continue

        if not _is_legal_move(board, player, move):
            continue

        legal_candidates.append(move_info)

    if not legal_candidates:
        return None

    best = legal_candidates[0]
    best_winrate = best.winrate_percent
    best_score = best.score_lead

    learned_list = list(learned_moves or [])

    if learned_list:
        for learned_move in learned_list:
            for candidate in legal_candidates[:max_learned_rank]:
                if not _same_move(candidate.move, learned_move):
                    continue

                winrate_ok = True
                score_ok = True

                if best_winrate is not None and candidate.winrate_percent is not None:
                    winrate_loss = max(0.0, best_winrate - candidate.winrate_percent)
                    winrate_ok = winrate_loss <= max_winrate_loss

                if best_score is not None and candidate.score_lead is not None:
                    score_loss = abs(best_score - candidate.score_lead)
                    score_ok = score_loss <= max_score_loss

                if winrate_ok and score_ok:
                    return candidate.move

    return best.move
