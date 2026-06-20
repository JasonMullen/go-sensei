from app.core.board import Board
from app.core.stone import Stone


def main() -> None:
    board = Board(size=19)
    board.place_stone("D4", Stone.BLACK)
    board.place_stone("Q16", Stone.WHITE)
    board.print_board()

if __name__ == "__main__":
    main()
