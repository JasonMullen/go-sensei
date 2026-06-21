from pathlib import Path

from app.analysis.katago_client import KataGoClient, KataGoSettings
from app.core.board import Board
from app.core.sgf import build_board_at_move, load_sgf_file
from app.core.stone import Stone


def main() -> None:
    settings = KataGoSettings.from_environment()

    missing_files = settings.missing_files()

    if missing_files:
        print()
        print("KataGo is not configured yet.")
        print("Missing files:")

        for path in missing_files:
            print(f"- {path}")

        print()
        print("You need a KataGo executable, model file, and analysis config.")
        print("Default expected locations:")
        print("- engines/katago/katago.exe")
        print("- engines/katago/model.bin.gz")
        print("- engines/katago/analysis.cfg")
        print()
        print("Or set these environment variables:")
        print("- KATAGO_EXECUTABLE")
        print("- KATAGO_MODEL")
        print("- KATAGO_CONFIG")
        print()
        return

    board, current_player = get_position_to_analyze()

    with KataGoClient(settings) as client:
        result = client.analyze_board(
            board=board,
            current_player=current_player,
        )

    print()
    print("Go Sensei KataGo Analysis")
    print("=" * 34)
    print(f"Board size: {result.board_size}x{result.board_size}")
    print(f"Current player: {result.current_player.name}")

    if result.root_winrate_percent is not None:
        print(f"Root winrate: {result.root_winrate_percent:.2f}%")

    if result.root_score_lead is not None:
        print(f"Score lead: {result.root_score_lead:.2f}")

    if result.root_visits is not None:
        print(f"Root visits: {result.root_visits}")

    print()
    print("Best moves:")
    print("-" * 34)

    for index, move in enumerate(result.best_moves[:10], start=1):
        pv_text = " ".join(move.pv[:8])

        print(
            f"{index:>2}. {move.move:<4} "
            f"winrate={move.winrate_percent:>6.2f}% "
            f"visits={move.visits:<5} "
            f"scoreLead={move.score_lead if move.score_lead is not None else 'N/A'} "
            f"pv={pv_text}"
        )

    print()


def get_position_to_analyze() -> tuple[Board, Stone]:
    import sys

    if len(sys.argv) >= 2:
        sgf_path = Path(sys.argv[1])
        move_index = int(sys.argv[2]) if len(sys.argv) >= 3 else 0

        game = load_sgf_file(sgf_path)
        position = build_board_at_move(game, move_index)

        if move_index < len(game.moves):
            current_player = game.moves[move_index].color
        else:
            current_player = Stone.BLACK

        return position.board, current_player

    board = Board(size=19)
    board.place_stone("Q16", Stone.BLACK)
    board.place_stone("D16", Stone.WHITE)
    board.place_stone("Q4", Stone.BLACK)
    board.place_stone("D4", Stone.WHITE)

    return board, Stone.BLACK


if __name__ == "__main__":
    main()
