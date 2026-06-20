from app.core.coordinates import GO_COLUMNS, human_to_point
from app.core.stone import Stone


Point = tuple[int, int]


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

    def place_stone(self, coordinate: str, stone: Stone) -> int:
        """Place a stone on the board.

        Returns:
            Number of opponent stones captured.

        Raises:
            ValueError: If the move is illegal.
        """
        row, col = human_to_point(coordinate, self.size)

        if self.grid[row][col] is not None:
            raise ValueError(f"Point {coordinate} is already occupied.")

        self.grid[row][col] = stone

        opponent = self.get_opponent(stone)
        captured_stones: list[tuple[int, int, Stone]] = []
        checked_groups: set[frozenset[Point]] = set()

        for neighbor_row, neighbor_col in self.neighbors(row, col):
            if self.grid[neighbor_row][neighbor_col] != opponent:
                continue

            opponent_group = self.collect_group(neighbor_row, neighbor_col)
            frozen_group = frozenset(opponent_group)

            if frozen_group in checked_groups:
                continue

            checked_groups.add(frozen_group)

            if self.count_liberties(opponent_group) == 0:
                captured_stones.extend(self.remove_group(opponent_group))

        own_group = self.collect_group(row, col)

        if self.count_liberties(own_group) == 0:
            self.grid[row][col] = None

            for captured_row, captured_col, captured_stone in captured_stones:
                self.grid[captured_row][captured_col] = captured_stone

            raise ValueError(f"Illegal move: {coordinate} is suicide.")

        return len(captured_stones)

    def is_legal_move(self, coordinate: str, stone: Stone) -> bool:
        """Return True if the move is legal, otherwise False.

        This checks:
        - valid coordinate
        - empty point
        - not suicide

        Ko is not implemented yet.
        """
        test_board = self.copy()

        try:
            test_board.place_stone(coordinate, stone)
        except ValueError:
            return False

        return True

    def copy(self) -> "Board":
        copied_board = Board(size=self.size)
        copied_board.grid = [row.copy() for row in self.grid]
        return copied_board

    def clear(self) -> None:
        self.grid = [[None for _ in range(self.size)] for _ in range(self.size)]

    def get_opponent(self, stone: Stone) -> Stone:
        if stone == Stone.BLACK:
            return Stone.WHITE

        return Stone.BLACK

    def neighbors(self, row: int, col: int) -> list[Point]:
        possible_neighbors = [
            (row - 1, col),
            (row + 1, col),
            (row, col - 1),
            (row, col + 1),
        ]

        return [
            (neighbor_row, neighbor_col)
            for neighbor_row, neighbor_col in possible_neighbors
            if 0 <= neighbor_row < self.size and 0 <= neighbor_col < self.size
        ]

    def collect_group(self, start_row: int, start_col: int) -> set[Point]:
        stone = self.grid[start_row][start_col]

        if stone is None:
            return set()

        group: set[Point] = set()
        stack = [(start_row, start_col)]

        while stack:
            row, col = stack.pop()

            if (row, col) in group:
                continue

            if self.grid[row][col] != stone:
                continue

            group.add((row, col))

            for neighbor_row, neighbor_col in self.neighbors(row, col):
                if self.grid[neighbor_row][neighbor_col] == stone:
                    stack.append((neighbor_row, neighbor_col))

        return group

    def count_liberties(self, group: set[Point]) -> int:
        liberties: set[Point] = set()

        for row, col in group:
            for neighbor_row, neighbor_col in self.neighbors(row, col):
                if self.grid[neighbor_row][neighbor_col] is None:
                    liberties.add((neighbor_row, neighbor_col))

        return len(liberties)

    def remove_group(self, group: set[Point]) -> list[tuple[int, int, Stone]]:
        removed_stones: list[tuple[int, int, Stone]] = []

        for row, col in group:
            stone = self.grid[row][col]

            if stone is None:
                continue

            removed_stones.append((row, col, stone))
            self.grid[row][col] = None

        return removed_stones

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