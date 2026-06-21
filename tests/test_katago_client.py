from app.analysis.katago_client import (
    KataGoSettings,
    board_to_initial_stones,
    build_analysis_query,
    parse_analysis_response,
)
from app.core.board import Board
from app.core.stone import Stone


def test_board_to_initial_stones() -> None:
    board = Board(size=19)
    board.place_stone("D4", Stone.BLACK)
    board.place_stone("Q16", Stone.WHITE)

    initial_stones = board_to_initial_stones(board)

    assert ["B", "D4"] in initial_stones
    assert ["W", "Q16"] in initial_stones


def test_build_analysis_query_from_board() -> None:
    board = Board(size=19)
    board.place_stone("D4", Stone.BLACK)

    settings = KataGoSettings(
        executable_path="katago",
        model_path="model.bin.gz",
        config_path="analysis.cfg",
        max_visits=50,
        analysis_pv_len=8,
    )

    query = build_analysis_query(
        board=board,
        current_player=Stone.WHITE,
        settings=settings,
        query_id="test-query",
    )

    assert query["id"] == "test-query"
    assert query["initialPlayer"] == "W"
    assert query["boardXSize"] == 19
    assert query["boardYSize"] == 19
    assert query["rules"] == "tromp-taylor"
    assert query["komi"] == 7.5
    assert query["maxVisits"] == 50
    assert query["analysisPVLen"] == 8
    assert query["initialStones"] == [["B", "D4"]]
    assert query["moves"] == []
    assert query["analyzeTurns"] == [0]


def test_parse_analysis_response() -> None:
    response = {
        "id": "test-query",
        "isDuringSearch": False,
        "turnNumber": 0,
        "rootInfo": {
            "currentPlayer": "B",
            "winrate": 0.62,
            "scoreLead": 4.5,
            "visits": 100,
        },
        "moveInfos": [
            {
                "move": "Q16",
                "order": 0,
                "winrate": 0.64,
                "visits": 60,
                "scoreLead": 5.1,
                "prior": 0.2,
                "pv": ["Q16", "D4"],
            },
            {
                "move": "D16",
                "order": 1,
                "winrate": 0.61,
                "visits": 40,
                "scoreLead": 4.4,
                "prior": 0.15,
                "pv": ["D16", "Q4"],
            },
        ],
    }

    result = parse_analysis_response(response, board_size=19)

    assert result.query_id == "test-query"
    assert result.current_player == Stone.BLACK
    assert result.root_winrate_percent == 62.0
    assert result.root_score_lead == 4.5
    assert result.root_visits == 100

    assert len(result.best_moves) == 2
    assert result.best_moves[0].move == "Q16"
    assert result.best_moves[0].winrate_percent == 64.0
    assert result.best_moves[0].visits == 60
    assert result.best_moves[0].pv == ["Q16", "D4"]
