from dataclasses import dataclass
from pathlib import Path

from app.core.board import Board
from app.core.coordinates import human_to_point, point_to_human
from app.core.stone import Stone


Point = tuple[int, int]


@dataclass(frozen=True)
class SgfMove:
    move_number: int
    color: Stone
    coordinate: str | None
    raw_point: str


@dataclass(frozen=True)
class SgfSetupStone:
    color: Stone
    coordinate: str
    raw_point: str


@dataclass(frozen=True)
class SgfGame:
    board_size: int
    moves: list[SgfMove]
    setup_stones: list[SgfSetupStone]
    black_player: str | None = None
    white_player: str | None = None
    komi: str | None = None
    result: str | None = None


@dataclass(frozen=True)
class ReplayPosition:
    board: Board
    move_index: int
    last_move: tuple[int, int] | None
    black_captures: int
    white_captures: int
    skipped_moves: int
    errors: list[str]


@dataclass(frozen=True)
class ReplayResult:
    board: Board
    moves_played: int
    black_captures: int
    white_captures: int
    skipped_moves: int = 0
    errors: list[str] | None = None


def load_sgf_file(path: str | Path) -> SgfGame:
    sgf_path = Path(path)
    sgf_text = sgf_path.read_text(encoding="utf-8")
    return parse_sgf(sgf_text)


def parse_sgf(sgf_text: str) -> SgfGame:
    nodes = extract_main_line_nodes(sgf_text)

    if not nodes:
        raise ValueError("SGF does not contain a playable game tree.")

    root_properties = parse_node_properties(nodes[0])
    board_size = get_board_size(root_properties)

    setup_stones = get_setup_stones(root_properties, board_size)
    moves: list[SgfMove] = []

    for node in nodes[1:]:
        properties = parse_node_properties(node)

        if "B" in properties:
            raw_point = properties["B"][0]
            moves.append(
                SgfMove(
                    move_number=len(moves) + 1,
                    color=Stone.BLACK,
                    coordinate=sgf_point_to_human(raw_point, board_size),
                    raw_point=raw_point,
                )
            )

        elif "W" in properties:
            raw_point = properties["W"][0]
            moves.append(
                SgfMove(
                    move_number=len(moves) + 1,
                    color=Stone.WHITE,
                    coordinate=sgf_point_to_human(raw_point, board_size),
                    raw_point=raw_point,
                )
            )

    return SgfGame(
        board_size=board_size,
        moves=moves,
        setup_stones=setup_stones,
        black_player=get_first_property(root_properties, "PB"),
        white_player=get_first_property(root_properties, "PW"),
        komi=get_first_property(root_properties, "KM"),
        result=get_first_property(root_properties, "RE"),
    )


def extract_main_line_nodes(sgf_text: str) -> list[str]:
    start_index = sgf_text.find("(")

    if start_index == -1:
        return []

    nodes, _ = parse_game_tree(sgf_text, start_index)
    return [node for node in nodes if node]


def parse_game_tree(sgf_text: str, index: int) -> tuple[list[str], int]:
    if sgf_text[index] != "(":
        raise ValueError("SGF game tree must start with '('.")

    index += 1
    nodes: list[str] = []

    while index < len(sgf_text):
        index = skip_whitespace(sgf_text, index)

        if index >= len(sgf_text):
            break

        char = sgf_text[index]

        if char == ";":
            node, index = read_node(sgf_text, index + 1)
            nodes.append(node)
            continue

        if char == "(":
            variation_nodes, index = parse_game_tree(sgf_text, index)
            nodes.extend(variation_nodes)

            while True:
                index = skip_whitespace(sgf_text, index)

                if index < len(sgf_text) and sgf_text[index] == "(":
                    _, index = parse_game_tree(sgf_text, index)
                else:
                    break

            continue

        if char == ")":
            return nodes, index + 1

        index += 1

    return nodes, index


def read_node(sgf_text: str, index: int) -> tuple[str, int]:
    node_chars: list[str] = []
    inside_value = False
    escaping = False

    while index < len(sgf_text):
        char = sgf_text[index]

        if inside_value:
            node_chars.append(char)

            if escaping:
                escaping = False
            elif char == "\\":
                escaping = True
            elif char == "]":
                inside_value = False

            index += 1
            continue

        if char == "[":
            inside_value = True
            node_chars.append(char)
            index += 1
            continue

        if char in ";()":
            break

        node_chars.append(char)
        index += 1

    return "".join(node_chars).strip(), index


def skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1

    return index


def parse_node_properties(node_text: str) -> dict[str, list[str]]:
    properties: dict[str, list[str]] = {}
    index = 0

    while index < len(node_text):
        while index < len(node_text) and node_text[index].isspace():
            index += 1

        property_start = index

        while index < len(node_text) and node_text[index].isalpha():
            index += 1

        if property_start == index:
            index += 1
            continue

        property_name = node_text[property_start:index].upper()
        values: list[str] = []

        while index < len(node_text) and node_text[index] == "[":
            value, index = read_property_value(node_text, index)
            values.append(value)

        if values:
            properties[property_name] = values

    return properties


def read_property_value(node_text: str, start_index: int) -> tuple[str, int]:
    if node_text[start_index] != "[":
        raise ValueError("SGF property value must start with '['.")

    index = start_index + 1
    value_chars: list[str] = []
    escaping = False

    while index < len(node_text):
        char = node_text[index]

        if escaping:
            value_chars.append(char)
            escaping = False
        elif char == "\\":
            escaping = True
        elif char == "]":
            return "".join(value_chars), index + 1
        else:
            value_chars.append(char)

        index += 1

    raise ValueError("SGF property value is missing closing ']'.")


def get_board_size(root_properties: dict[str, list[str]]) -> int:
    size_text = get_first_property(root_properties, "SZ")

    if size_text is None:
        return 19

    try:
        board_size = int(size_text)
    except ValueError as error:
        raise ValueError(f"Invalid SGF board size: {size_text}") from error

    if board_size not in {9, 13, 19}:
        raise ValueError("Only 9x9, 13x13, and 19x19 boards are supported.")

    return board_size


def get_setup_stones(
    root_properties: dict[str, list[str]],
    board_size: int,
) -> list[SgfSetupStone]:
    setup_stones: list[SgfSetupStone] = []

    for raw_point in root_properties.get("AB", []):
        coordinate = sgf_point_to_human(raw_point, board_size)

        if coordinate is not None:
            setup_stones.append(
                SgfSetupStone(
                    color=Stone.BLACK,
                    coordinate=coordinate,
                    raw_point=raw_point,
                )
            )

    for raw_point in root_properties.get("AW", []):
        coordinate = sgf_point_to_human(raw_point, board_size)

        if coordinate is not None:
            setup_stones.append(
                SgfSetupStone(
                    color=Stone.WHITE,
                    coordinate=coordinate,
                    raw_point=raw_point,
                )
            )

    return setup_stones


def get_first_property(
    properties: dict[str, list[str]],
    property_name: str,
) -> str | None:
    values = properties.get(property_name)

    if not values:
        return None

    return values[0]


def sgf_point_to_human(raw_point: str, board_size: int) -> str | None:
    if raw_point == "":
        return None

    if len(raw_point) != 2:
        raise ValueError(f"Invalid SGF point: {raw_point}")

    col = ord(raw_point[0].lower()) - ord("a")
    row = ord(raw_point[1].lower()) - ord("a")

    if not 0 <= row < board_size or not 0 <= col < board_size:
        raise ValueError(
            f"SGF point {raw_point} is outside a {board_size}x{board_size} board."
        )

    return point_to_human(row, col, board_size)


def build_board_at_move(game: SgfGame, requested_move_index: int) -> ReplayPosition:
    target_index = max(0, min(requested_move_index, len(game.moves)))

    board = Board(size=game.board_size)
    black_captures = 0
    white_captures = 0
    skipped_moves = 0
    errors: list[str] = []
    last_move: tuple[int, int] | None = None

    apply_setup_stones(board, game.setup_stones)

    for move in game.moves[:target_index]:
        if move.coordinate is None:
            continue

        try:
            captured_count = board.place_stone(move.coordinate, move.color)
        except ValueError as error:
            skipped_moves += 1
            errors.append(f"Move {move.move_number}: {error}")
            continue

        if move.color == Stone.BLACK:
            black_captures += captured_count
        else:
            white_captures += captured_count

        last_move = human_to_point(move.coordinate, board.size)

    return ReplayPosition(
        board=board,
        move_index=target_index,
        last_move=last_move,
        black_captures=black_captures,
        white_captures=white_captures,
        skipped_moves=skipped_moves,
        errors=errors,
    )


def apply_setup_stones(board: Board, setup_stones: list[SgfSetupStone]) -> None:
    for setup_stone in setup_stones:
        row, col = human_to_point(setup_stone.coordinate, board.size)

        if board.grid[row][col] is not None:
            raise ValueError(f"Setup point {setup_stone.coordinate} is occupied.")

        board.grid[row][col] = setup_stone.color


def replay_sgf_game(game: SgfGame) -> ReplayResult:
    position = build_board_at_move(game, len(game.moves))

    return ReplayResult(
        board=position.board,
        moves_played=position.move_index,
        black_captures=position.black_captures,
        white_captures=position.white_captures,
        skipped_moves=position.skipped_moves,
        errors=position.errors,
    )
