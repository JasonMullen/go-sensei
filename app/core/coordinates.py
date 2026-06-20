GO_COLUMNS = "ABCDEFGHJKLMNOPQRST"


def human_to_point(coordinate: str, board_size: int = 19) -> tuple[int, int]:
    """Convert a Go coordinate like 'D4' into an internal board point.

    Human Go coordinates:
    - A1 is the bottom-left corner.
    - T19 is the top-right corner on a 19x19 board.
    - The letter I is skipped.

    Internal board coordinates:
    - row 0 is the top row.
    - col 0 is the left column.
    """
    coordinate = coordinate.strip().upper()

    if len(coordinate) < 2:
        raise ValueError(f"Invalid coordinate: {coordinate}")

    column_letter = coordinate[0]
    row_text = coordinate[1:]

    if column_letter not in GO_COLUMNS[:board_size]:
        raise ValueError(f"Invalid column: {column_letter}")

    if not row_text.isdigit():
        raise ValueError(f"Invalid row: {row_text}")

    human_row = int(row_text)

    if human_row < 1 or human_row > board_size:
        raise ValueError(f"Row must be between 1 and {board_size}: {human_row}")

    col = GO_COLUMNS.index(column_letter)
    row = board_size - human_row

    return row, col


def point_to_human(row: int, col: int, board_size: int = 19) -> str:
    """Convert an internal board point into a Go coordinate like 'D4'."""
    if row < 0 or row >= board_size:
        raise ValueError(f"Invalid row: {row}")

    if col < 0 or col >= board_size:
        raise ValueError(f"Invalid column: {col}")

    column_letter = GO_COLUMNS[col]
    human_row = board_size - row

    return f"{column_letter}{human_row}"