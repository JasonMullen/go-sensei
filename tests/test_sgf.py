from app.core.sgf import (
    parse_sgf,
    replay_sgf_game,
    sgf_point_to_human,
)
from app.core.stone import Stone


def test_sgf_point_to_human_19x19() -> None:
    assert sgf_point_to_human("dd", 19) == "D16"
    assert sgf_point_to_human("pd", 19) == "Q16"
    assert sgf_point_to_human("", 19) is None


def test_parse_sgf_board_size_and_players() -> None:
    sgf_text = "(;GM[1]FF[4]SZ[13]PB[Black]PW[White];B[dd];W[jj])"

    game = parse_sgf(sgf_text)

    assert game.board_size == 13
    assert game.black_player == "Black"
    assert game.white_player == "White"
    assert len(game.moves) == 2


def test_parse_sgf_moves() -> None:
    sgf_text = "(;GM[1]FF[4]SZ[19];B[pd];W[dd];B[])"

    game = parse_sgf(sgf_text)

    assert game.moves[0].color == Stone.BLACK
    assert game.moves[0].coordinate == "Q16"

    assert game.moves[1].color == Stone.WHITE
    assert game.moves[1].coordinate == "D16"

    assert game.moves[2].color == Stone.BLACK
    assert game.moves[2].coordinate is None


def test_replay_sgf_game_places_stones() -> None:
    sgf_text = "(;GM[1]FF[4]SZ[19];B[pd];W[dd];B[qp])"

    game = parse_sgf(sgf_text)
    result = replay_sgf_game(game)

    assert result.moves_played == 3
    assert result.board.get("Q16") == Stone.BLACK
    assert result.board.get("D16") == Stone.WHITE
    assert result.board.get("R4") == Stone.BLACK


def test_replay_sgf_game_uses_capture_logic() -> None:
    sgf_text = "(;GM[1]FF[4]SZ[19];B[dp];W[cp];W[ep];W[dq];W[do])"

    game = parse_sgf(sgf_text)
    result = replay_sgf_game(game)

    assert result.white_captures == 1
    assert result.board.get("D4") is None
