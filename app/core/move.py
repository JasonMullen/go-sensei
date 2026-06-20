from dataclasses import dataclass

from app.core.stone import Stone


@dataclass(frozen=True)
class Move:
    color: Stone
    coordinate: str | None

    @property
    def is_pass(self) -> bool:
        return self.coordinate is None