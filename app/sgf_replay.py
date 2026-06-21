import sys
from pathlib import Path

from app.core.sgf import load_sgf_file, replay_sgf_game


def main() -> None:
    if len(sys.argv) > 1:
        sgf_path = Path(sys.argv[1])
    else:
        sgf_path = Path("data/sgf/sample_game.sgf")

    game = load_sgf_file(sgf_path)
    result = replay_sgf_game(game)

    print()
    print("Go Sensei SGF Replay")
    print("=" * 30)
    print(f"File: {sgf_path}")
    print(f"Board size: {game.board_size}x{game.board_size}")
    print(f"Black: {game.black_player or 'Unknown'}")
    print(f"White: {game.white_player or 'Unknown'}")
    print(f"Komi: {game.komi or 'Unknown'}")
    print(f"Result: {game.result or 'Unknown'}")
    print(f"Moves replayed: {result.moves_played}")
    print(f"Black captures: {result.black_captures}")
    print(f"White captures: {result.white_captures}")
    print()
    print(result.board.to_text())
    print()


if __name__ == "__main__":
    main()
