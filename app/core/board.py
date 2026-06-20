from app.core.coordinates import GO_COLUMNS, human_to_point
from app.core.stone import Stone


class Board:
    def __init__(self, size: int = 19) -> None:
        if size not in {9, 13, 19}:
            raise ValueError("Board size must be 9, 13, or 19.")

        self.size = size
        self.grid: list[list[Stone | None]] = [
            [None for _ in range(size)] for _ in range(size)
        ]

    def get(self, coordinate: str) -> Stone | None:
        row, col = human_to_point(coordinate, self.size)
        return self.grid[row][col]

    def place_stone(self, coordinate: str, stone: Stone) -> None:
        row, col = human_to_point(coordinate, self.size)

        if self.grid[row][col] is not None:
            raise ValueError(f"Point {coordinate} is already occupied.")

        self.grid[row][col] = stone

    def clear(self) -> None:
        self.grid = [[None for _ in range(self.size)] for _ in range(self.size)]

    def to_text(self) -> str:
        lines: list[str] = []

        for row_index, row in enumerate(self.grid):
            human_row = self.size - row_index
            row_values = []

            for point in row:
                if point is None:
                    row_values.append(".")
                else:
                    row_values.append(point.symbol)

            lines.append(f"{human_row:>2} " + " ".join(row_values))

        columns = "   " + " ".join(GO_COLUMNS[: self.size])
        lines.append(columns)

        return "\n".join(lines)

    def print_board(self) -> None:
        print(self.to_text())