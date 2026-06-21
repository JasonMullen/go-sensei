from __future__ import annotations

from dataclasses import dataclass

from app.analysis.katago_client import KataGoAnalysisResult, KataGoMoveInfo
from app.core.stone import Stone


@dataclass(frozen=True)
class LiveMoveCoaching:
    title: str
    lines: list[str]
    severity: str


@dataclass(frozen=True)
class MoveJudgment:
    severity: str
    verdict: str
    played_rank: int | None
    best_move: str | None
    engine_winrate_loss: float | None
    engine_score_loss: float | None
    actual_winrate_swing: float | None
    actual_score_swing: float | None


def make_live_move_coaching(
    played_move: str | None,
    player: Stone | None,
    before_result: KataGoAnalysisResult | None,
    after_result: KataGoAnalysisResult | None,
    board_size: int,
) -> LiveMoveCoaching:
    if played_move is None or player is None:
        return LiveMoveCoaching(
            title="Coach: Waiting",
            severity="waiting",
            lines=[
                "Verdict: Waiting",
                "Your move: No move selected yet.",
                "Engine idea: Click ANALYZE, wait for Ready, then make a move.",
                "Main lesson: I need a move before I can coach it.",
            ],
        )

    if after_result is None:
        return LiveMoveCoaching(
            title="Coach: Thinking",
            severity="waiting",
            lines=[
                "Verdict: Thinking",
                f"Your move: {player.name.title()} {played_move}",
                "Engine idea: Waiting for KataGo after-move analysis.",
                "Main lesson: I am checking what changed after your move.",
            ],
        )

    judgment = judge_move(
        played_move=played_move,
        player=player,
        before_result=before_result,
        after_result=after_result,
    )

    title = f"Coach: {judgment.verdict}"

    lines: list[str] = []
    lines.append(f"Verdict: {judgment.verdict}")
    lines.append(f"Your move: {player.name.title()} {played_move}")

    if judgment.best_move is None:
        lines.append("Engine idea: No pre-move KataGo comparison was ready.")
        lines.append("Judged by: after-move board evaluation only.")
    elif judgment.played_rank == 1:
        lines.append(f"Engine idea: You played KataGo's #1 move: {played_move}.")
        lines.append("Judged by: KataGo move ranking.")
    elif judgment.played_rank is not None:
        lines.append(
            f"Engine idea: KataGo preferred {judgment.best_move}. Your move ranked #{judgment.played_rank}."
        )
        lines.append("Judged by: KataGo move ranking and engine loss.")
    else:
        lines.append(
            f"Engine idea: KataGo preferred {judgment.best_move}. Your move was outside the shown recommendations."
        )
        lines.append("Judged by: after-move swing because the move was not in KataGo's displayed candidates.")

    if judgment.engine_winrate_loss is not None:
        lines.append(f"Engine gap: {judgment.engine_winrate_loss:.1f}% worse than KataGo's best shown move.")

    if judgment.engine_score_loss is not None:
        lines.append(f"Point gap: {judgment.engine_score_loss:.2f} points worse than KataGo's best shown move.")

    if judgment.actual_winrate_swing is not None:
        sign = "+" if judgment.actual_winrate_swing >= 0 else ""
        lines.append(f"After-move swing: {sign}{judgment.actual_winrate_swing:.1f}% for {player.name.title()}.")

    if judgment.actual_score_swing is not None:
        sign = "+" if judgment.actual_score_swing >= 0 else ""
        lines.append(f"Score swing: {sign}{judgment.actual_score_swing:.2f} for {player.name.title()}.")

    concept = choose_main_concept(
        severity=judgment.severity,
        played_rank=judgment.played_rank,
        best_move=judgment.best_move,
    )

    lines.append(f"Main lesson: {concept['lesson']}")
    lines.append(f"Why it matters: {concept['why']}")
    lines.append(f"Ask yourself: {concept['question']}")

    if before_result is not None and before_result.best_moves:
        pv = before_result.best_moves[0].pv
        if pv:
            lines.append("Engine line: " + " → ".join(pv[:5]))

    return LiveMoveCoaching(
        title=title,
        lines=lines,
        severity=judgment.severity,
    )


def judge_move(
    played_move: str,
    player: Stone,
    before_result: KataGoAnalysisResult | None,
    after_result: KataGoAnalysisResult | None,
) -> MoveJudgment:
    best_info: KataGoMoveInfo | None = None
    played_info: KataGoMoveInfo | None = None
    played_rank: int | None = None

    if before_result is not None and before_result.best_moves:
        best_info = before_result.best_moves[0]

        for index, move in enumerate(before_result.best_moves, start=1):
            if normalize_move(move.move) == normalize_move(played_move):
                played_info = move
                played_rank = index
                break

    best_move = best_info.move if best_info is not None else None

    engine_winrate_loss = None
    engine_score_loss = None

    # This is the safest comparison because both values come from the SAME pre-move KataGo result.
    if best_info is not None and played_info is not None:
        engine_winrate_loss = safe_loss(best_info.winrate_percent, played_info.winrate_percent)
        engine_score_loss = safe_loss(best_info.score_lead, played_info.score_lead)

    before_wr = player_winrate_from_position(before_result, player)
    after_wr = player_winrate_from_position(after_result, player)

    actual_winrate_swing = None
    if before_wr is not None and after_wr is not None:
        actual_winrate_swing = after_wr - before_wr

    before_score = player_score_from_position(before_result, player)
    after_score = player_score_from_position(after_result, player)

    actual_score_swing = None
    if before_score is not None and after_score is not None:
        actual_score_swing = after_score - before_score

    severity = classify_move(
        played_rank=played_rank,
        best_info=best_info,
        engine_winrate_loss=engine_winrate_loss,
        engine_score_loss=engine_score_loss,
        actual_winrate_swing=actual_winrate_swing,
        actual_score_swing=actual_score_swing,
    )

    return MoveJudgment(
        severity=severity,
        verdict=friendly_verdict(severity),
        played_rank=played_rank,
        best_move=best_move,
        engine_winrate_loss=engine_winrate_loss,
        engine_score_loss=engine_score_loss,
        actual_winrate_swing=actual_winrate_swing,
        actual_score_swing=actual_score_swing,
    )


def classify_move(
    played_rank: int | None,
    best_info: KataGoMoveInfo | None,
    engine_winrate_loss: float | None,
    engine_score_loss: float | None,
    actual_winrate_swing: float | None,
    actual_score_swing: float | None,
) -> str:
    engine_wr_loss = engine_winrate_loss or 0.0
    engine_pt_loss = engine_score_loss or 0.0

    actual_wr_loss = max(0.0, -(actual_winrate_swing or 0.0))
    actual_pt_loss = max(0.0, -(actual_score_swing or 0.0))

    # Most important rule:
    # If KataGo explicitly says you played its top move, do NOT call it a blunder
    # because of a possibly noisy before/after perspective swing.
    if best_info is not None and played_rank == 1:
        if engine_wr_loss <= 1.0 and engine_pt_loss <= 0.5:
            return "excellent"

        return "good"

    if best_info is not None and played_rank in (2, 3):
        if engine_wr_loss < 2.5 and engine_pt_loss < 1.0:
            return "good"

        if engine_wr_loss < 6.0 and engine_pt_loss < 2.5:
            return "inaccuracy"

        return "mistake"

    if best_info is not None and played_rank is not None:
        if engine_wr_loss >= 12.0 or engine_pt_loss >= 5.0:
            return "mistake"

        if engine_wr_loss >= 5.0 or engine_pt_loss >= 2.0:
            return "inaccuracy"

        return "questionable"

    # If your move was not even in the shown recommendations, use the actual swing.
    # This catches real disasters like 50/50 -> 99% for the opponent.
    if actual_wr_loss >= 20.0 or actual_pt_loss >= 8.0:
        return "blunder"

    if actual_wr_loss >= 10.0 or actual_pt_loss >= 4.0:
        return "mistake"

    if actual_wr_loss >= 5.0 or actual_pt_loss >= 2.0:
        return "inaccuracy"

    if best_info is not None and played_rank is None:
        return "questionable"

    return "review"


def player_winrate_from_position(
    result: KataGoAnalysisResult | None,
    player: Stone,
) -> float | None:
    if result is None or result.root_winrate_percent is None:
        return None

    # Match the right-side panel: root winrate belongs to result.current_player.
    if result.current_player == player:
        return result.root_winrate_percent

    return 100.0 - result.root_winrate_percent


def player_score_from_position(
    result: KataGoAnalysisResult | None,
    player: Stone,
) -> float | None:
    if result is None or result.root_score_lead is None:
        return None

    # Match the right-side panel: positive score belongs to result.current_player.
    if result.current_player == player:
        return result.root_score_lead

    return -result.root_score_lead


def safe_loss(best_value: float | None, played_value: float | None) -> float | None:
    if best_value is None or played_value is None:
        return None

    return max(0.0, best_value - played_value)


def normalize_move(move: str | None) -> str:
    if move is None:
        return ""

    return move.strip().upper()


def friendly_verdict(severity: str) -> str:
    if severity == "excellent":
        return "Excellent move"
    if severity == "good":
        return "Good move"
    if severity == "questionable":
        return "Questionable move"
    if severity == "inaccuracy":
        return "Inaccuracy"
    if severity == "mistake":
        return "Mistake"
    if severity == "blunder":
        return "Serious mistake"

    return "Review"


def choose_main_concept(
    severity: str,
    played_rank: int | None,
    best_move: str | None,
) -> dict[str, str]:
    if played_rank == 1:
        return {
            "lesson": "Your move matched KataGo's main idea.",
            "why": "When your move is the engine's top choice, the important work is understanding the follow-up.",
            "question": "What continuation does this move prepare?",
        }

    if played_rank in (2, 3):
        return {
            "lesson": "Your move was playable, but KataGo preferred a slightly cleaner choice.",
            "why": "Top candidate moves are often close, but the best one usually handles direction, shape, or sente more efficiently.",
            "question": f"Why is {best_move} a little more efficient?",
        }

    if severity == "blunder":
        return {
            "lesson": "The move caused a major swing in the position.",
            "why": "Big swings usually happen when a move ignores an urgent fight, weak group, capture race, or huge sente point.",
            "question": "What urgent problem did I leave unanswered?",
        }

    if severity == "mistake":
        return {
            "lesson": "Your move missed an important priority.",
            "why": "A useful-looking move can still be wrong if the board demanded defense, attack, or a bigger point elsewhere.",
            "question": "What was more urgent than my move?",
        }

    if severity == "inaccuracy":
        return {
            "lesson": "Your idea may be playable, but the timing or direction was not ideal.",
            "why": "Small losses often come from playing the right kind of move in the wrong order.",
            "question": "Does KataGo's move do the same job with better timing?",
        }

    if severity == "questionable":
        return {
            "lesson": "Your move was not in KataGo's main displayed recommendations.",
            "why": "That does not automatically mean disaster, but it means the move deserves review.",
            "question": f"Why did KataGo prefer {best_move}?",
        }

    return {
        "lesson": "The coach needs a clearer engine comparison.",
        "why": "If the move was not in the displayed candidates and the swing was small, the judgment should stay cautious.",
        "question": "Should I increase visits or show more candidate moves?",
    }
