from enum import StrEnum


class Stone(StrEnum):
    BLACK = "B"
    WHITE = "W"

    @property
    def symbol(self) -> str:
        if self == Stone.BLACK:
            return "X"
        return "O"