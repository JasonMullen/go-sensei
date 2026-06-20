import pytest

from app.core.board import Board
from app.core.stone import Stone


def test_board_starts_empty() -> None:
    board = Board()

    assert board.get("D4") is None


def test_place_black_stone() -> None:
    board = Board()

    board.place_stone("D4", Stone.BLACK)

    assert board.get("D4") == Stone.BLACK


def test_place_white_stone() -> None:
    board = Board()

    board.place_stone("Q16", Stone.WHITE)

    assert board.get("Q16") == Stone.WHITE


def test_cannot_place_on_occupied_point() -> None:
    board = Board()

    board.place_stone("D4", Stone.BLACK)

    with pytest.raises(ValueError):
        board.place_stone("D4", Stone.WHITE)


def test_board_rejects_invalid_size() -> None:
    with pytest.raises(ValueError):
        Board(size=20)


def test_board_text_contains_stones() -> None:
    board = Board()

    board.place_stone("D4", Stone.BLACK)
    board.place_stone("Q16", Stone.WHITE)

    board_text = board.to_text()

    assert "X" in board_text
    assert "O" in board_text