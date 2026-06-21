from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.analysis.katago_client import KataGoAnalysisResult, KataGoClient, KataGoMoveInfo, KataGoSettings
from app.core.board import Board
from app.core.sgf import SgfGame, build_board_at_move, load_sgf_file
from app.core.stone import Stone
from app.review.concepts import MoveConceptExplanation, explain_move_conceptually


@dataclass(frozen=True)
class ReviewedMove:
    move_number: int
    player: Stone
    played_move: str
    best_move: str | None
    player_winrate_before: float | None
    player_winrate_after: float | None
    winrate_loss: float | None
    score_loss: float | None
    visits: int | None
    concept: MoveConceptExplanation
    pv: list[str]


@dataclass(frozen=True)
class GameReview:
    sgf_path: Path
    moves_reviewed: int
    visits_per_position: int
    reviewed_moves: list[ReviewedMove]

    @property
    def biggest_mistakes(self) -> list[ReviewedMove]:
        return sorted(
            self.reviewed_moves,
            key=lambda move: move.winrate_loss if move.winrate_loss is not None else -1,
            reverse=True,
        )


class GameReviewer:
    def __init__(self, settings: KataGoSettings | None = None, visits: int = 8) -> None:
        base_settings = settings or KataGoSettings.from_environment()

        from dataclasses import replace

        self.settings = replace(base_settings, max_visits=visits)
        self.visits = visits

    def review_sgf(
        self,
        sgf_path: str | Path,
        limit: int | None = None,
    ) -> GameReview:
        path = Path(sgf_path)
        game = load_sgf_file(path)

        reviewed_moves: list[ReviewedMove] = []

        total_moves = len(game.moves)

        if limit is not None:
            total_moves = min(total_moves, limit)

        missing_files = self.settings.missing_files()

        if missing_files:
            missing_text = ", ".join(str(path) for path in missing_files)
            raise RuntimeError(f"KataGo missing files: {missing_text}")

        with KataGoClient(self.settings) as client:
            for move_index in range(total_moves):
                move = game.moves[move_index]

                if move.coordinate is None:
                    continue

                move_number = move_index + 1
                print(
                    f"[Game Review] Analyzing move {move_number}/{total_moves}: "
                    f"{move.color.name} {move.coordinate}",
                    flush=True,
                )

                before_position = build_board_at_move(game, move_index)
                before_board = before_position.board

                before_result = client.analyze_board(
                    board=before_board,
                    current_player=move.color,
                )

                after_position = build_board_at_move(game, move_index + 1)
                after_board = after_position.board

                next_player = get_next_player(game, move_index, move.color)

                after_result = client.analyze_board(
                    board=after_board,
                    current_player=next_player,
                )

                reviewed_move = self.build_reviewed_move(
                    move_number=move_number,
                    player=move.color,
                    played_move=move.coordinate,
                    before_board=before_board,
                    before_result=before_result,
                    after_result=after_result,
                    next_player=next_player,
                )

                reviewed_moves.append(reviewed_move)

        return GameReview(
            sgf_path=path,
            moves_reviewed=len(reviewed_moves),
            visits_per_position=self.visits,
            reviewed_moves=reviewed_moves,
        )

    def build_reviewed_move(
        self,
        move_number: int,
        player: Stone,
        played_move: str,
        before_board: Board,
        before_result: KataGoAnalysisResult,
        after_result: KataGoAnalysisResult,
        next_player: Stone,
    ) -> ReviewedMove:
        best_move_info = get_best_move(before_result)

        best_move = best_move_info.move if best_move_info is not None else None
        best_winrate = before_result.root_winrate_percent
        player_winrate_after = convert_after_result_to_player_winrate(
            after_result=after_result,
            player=player,
            next_player=next_player,
        )

        winrate_loss = None

        if best_winrate is not None and player_winrate_after is not None:
            winrate_loss = max(0.0, best_winrate - player_winrate_after)

        best_score = before_result.root_score_lead
        played_score = convert_after_result_to_player_score(
            after_result=after_result,
            player=player,
            next_player=next_player,
        )

        score_loss = None

        if best_score is not None and played_score is not None:
            score_loss = max(0.0, best_score - played_score)

        concept = explain_move_conceptually(
            board=before_board,
            played_move=played_move,
            best_move=best_move,
            player=player,
            winrate_loss=winrate_loss,
            score_loss=score_loss,
            move_number=move_number,
        )

        pv = best_move_info.pv if best_move_info is not None else []

        return ReviewedMove(
            move_number=move_number,
            player=player,
            played_move=played_move,
            best_move=best_move,
            player_winrate_before=best_winrate,
            player_winrate_after=player_winrate_after,
            winrate_loss=winrate_loss,
            score_loss=score_loss,
            visits=before_result.root_visits,
            concept=concept,
            pv=pv,
        )


def get_next_player(game: SgfGame, move_index: int, current_player: Stone) -> Stone:
    if move_index + 1 < len(game.moves):
        return game.moves[move_index + 1].color

    return Stone.WHITE if current_player == Stone.BLACK else Stone.BLACK


def get_best_move(result: KataGoAnalysisResult) -> KataGoMoveInfo | None:
    if not result.best_moves:
        return None

    return result.best_moves[0]


def convert_after_result_to_player_winrate(
    after_result: KataGoAnalysisResult,
    player: Stone,
    next_player: Stone,
) -> float | None:
    if after_result.root_winrate_percent is None:
        return None

    if next_player == player:
        return after_result.root_winrate_percent

    return 100.0 - after_result.root_winrate_percent


def convert_after_result_to_player_score(
    after_result: KataGoAnalysisResult,
    player: Stone,
    next_player: Stone,
) -> float | None:
    if after_result.root_score_lead is None:
        return None

    if next_player == player:
        return after_result.root_score_lead

    return -after_result.root_score_lead


def write_markdown_review(
    review: GameReview,
    output_path: str | Path,
    top_n: int = 15,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    biggest = review.biggest_mistakes[:top_n]

    lines: list[str] = []

    lines.append("# Go Sensei Full Game Review")
    lines.append("")
    lines.append(f"**SGF:** `{review.sgf_path}`")
    lines.append(f"**Moves reviewed:** {review.moves_reviewed}")
    lines.append(f"**KataGo visits per position:** {review.visits_per_position}")
    lines.append("")
    lines.append("## Biggest mistakes")
    lines.append("")
    lines.append("| Move | Player | Played | Engine preferred | Winrate loss | Point loss | Severity | Concepts |")
    lines.append("|---:|---|---|---|---:|---:|---|---|")

    for move in biggest:
        lines.append(
            "| "
            f"{move.move_number} | "
            f"{move.player.name.title()} | "
            f"{move.played_move} | "
            f"{move.best_move or 'N/A'} | "
            f"{format_optional(move.winrate_loss, suffix='%')} | "
            f"{format_optional(move.score_loss)} | "
            f"{move.concept.severity} | "
            f"{', '.join(move.concept.tags)} |"
        )

    lines.append("")
    lines.append("## Conceptual review notes")
    lines.append("")

    for move in biggest:
        lines.append(f"### Move {move.move_number}: {move.player.name.title()} played {move.played_move}")
        lines.append("")
        lines.append(f"**Severity:** {move.concept.severity}")
        lines.append("")
        lines.append(f"**Engine preferred:** {move.best_move or 'N/A'}")
        lines.append("")
        lines.append(f"**Winrate loss:** {format_optional(move.winrate_loss, suffix='%')}")
        lines.append("")
        lines.append(f"**Point loss:** {format_optional(move.score_loss)}")
        lines.append("")
        lines.append(f"**Concepts:** {', '.join(move.concept.tags)}")
        lines.append("")
        lines.append(f"**What happened:** {move.concept.summary}")
        lines.append("")
        lines.append(f"**Why the engine move is better:** {move.concept.why_better}")
        lines.append("")

        if move.pv:
            lines.append(f"**Possible continuation:** {' → '.join(move.pv[:10])}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def format_optional(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "N/A"

    return f"{value:.2f}{suffix}"
