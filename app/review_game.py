from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.review.game_reviewer import GameReviewer, write_markdown_review


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review a full SGF game with KataGo and Go Sensei concept explanations."
    )

    parser.add_argument("sgf_path", help="Path to the SGF file to review.")
    parser.add_argument(
        "--visits",
        type=int,
        default=4,
        help="KataGo visits per analysis. Use 4 for fast CPU review, 20+ for deeper review.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of moves to review. Omit this to review the whole game.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of biggest mistakes to include in the report.",
    )

    args = parser.parse_args()

    sgf_path = Path(args.sgf_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path("analysis_logs") / f"{sgf_path.stem}_review_{timestamp}.md"

    reviewer = GameReviewer(visits=args.visits)
    review = reviewer.review_sgf(
        sgf_path=sgf_path,
        limit=args.limit,
    )

    report_path = write_markdown_review(
        review=review,
        output_path=output_path,
        top_n=args.top,
    )

    print()
    print("Go Sensei Full Game Review Complete")
    print("=" * 42)
    print(f"Moves reviewed: {review.moves_reviewed}")
    print(f"Report saved to: {report_path}")
    print()
    print("Biggest mistakes:")
    print("-" * 42)

    for move in review.biggest_mistakes[: args.top]:
        loss = "N/A" if move.winrate_loss is None else f"{move.winrate_loss:.2f}%"
        print(
            f"Move {move.move_number:>3} "
            f"{move.player.name:<5} "
            f"played {move.played_move:<4} "
            f"best {move.best_move or 'N/A':<4} "
            f"loss {loss:<8} "
            f"{move.concept.severity}"
        )

    print()


if __name__ == "__main__":
    main()
