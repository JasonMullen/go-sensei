from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.coordinates import human_to_point
from app.core.stone import Stone


DEFAULT_GAME_LIBRARY_ROOT = Path(
    os.environ.get(
        "GO_SENSEI_GAME_DIR",
        r"C:\Users\jason\OneDrive\Attachments\Desktop\Go Sensei Game",
    )
)


@dataclass(frozen=True)
class SavedGamePaths:
    root: Path
    my_games: Path
    elite_games: Path
    database_dir: Path
    analysis_cache: Path
    autosaves: Path
    database_path: Path


class GameStore:
    def __init__(self, root: Path | None = None) -> None:
        self.paths = build_game_paths(root or DEFAULT_GAME_LIBRARY_ROOT)
        ensure_game_library(self.paths)
        self.initialize_database()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize_database(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    board_size INTEGER NOT NULL,
                    black_player TEXT,
                    white_player TEXT,
                    sgf_path TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS moves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL,
                    move_number INTEGER NOT NULL,
                    player TEXT NOT NULL,
                    coordinate TEXT NOT NULL,
                    captured_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(game_id) REFERENCES games(id)
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER,
                    move_number INTEGER,
                    player TEXT,
                    coordinate TEXT,
                    black_winrate REAL,
                    white_winrate REAL,
                    black_score_lead REAL,
                    best_move TEXT,
                    visits INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(game_id) REFERENCES games(id)
                );

                CREATE TABLE IF NOT EXISTS mistakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER,
                    move_number INTEGER,
                    player TEXT,
                    coordinate TEXT,
                    severity TEXT,
                    best_move TEXT,
                    winrate_loss REAL,
                    score_loss REAL,
                    concept TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(game_id) REFERENCES games(id)
                );

                CREATE TABLE IF NOT EXISTS analysis_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    board_key TEXT NOT NULL UNIQUE,
                    current_player TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS style_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_name TEXT NOT NULL,
                    board_size INTEGER NOT NULL,
                    region TEXT NOT NULL,
                    line_type TEXT NOT NULL,
                    move_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(profile_name, board_size, region, line_type)
                );
                """
            )

    def start_game(
        self,
        board_size: int,
        source: str = "manual",
        black_player: str = "Jason",
        white_player: str = "Opponent",
        sgf_path: Path | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO games (
                    source, board_size, black_player, white_player, sgf_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    board_size,
                    black_player,
                    white_player,
                    str(sgf_path) if sgf_path else None,
                    now_text(),
                ),
            )

            return int(cursor.lastrowid)

    def record_move(
        self,
        game_id: int,
        move_number: int,
        player: Stone,
        coordinate: str,
        captured_count: int = 0,
        board_size: int = 19,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO moves (
                    game_id, move_number, player, coordinate, captured_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    move_number,
                    player.name,
                    coordinate,
                    captured_count,
                    now_text(),
                ),
            )

        self.update_style_profile(
            player=player,
            coordinate=coordinate,
            board_size=board_size,
        )

    def update_style_profile(
        self,
        player: Stone,
        coordinate: str,
        board_size: int,
        profile_name: str = "Jason",
    ) -> None:
        region = classify_region(coordinate, board_size)
        line_type = classify_line_type(coordinate, board_size)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO style_profile (
                    profile_name, board_size, region, line_type, move_count, updated_at
                )
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(profile_name, board_size, region, line_type)
                DO UPDATE SET
                    move_count = move_count + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_name,
                    board_size,
                    region,
                    line_type,
                    now_text(),
                ),
            )

    def get_style_preferences(
        self,
        board_size: int,
        profile_name: str = "Jason",
    ) -> list[tuple[str, str, int]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT region, line_type, move_count
                FROM style_profile
                WHERE profile_name = ? AND board_size = ?
                ORDER BY move_count DESC
                LIMIT 10
                """,
                (
                    profile_name,
                    board_size,
                ),
            ).fetchall()

        return [(str(region), str(line_type), int(count)) for region, line_type, count in rows]

    def write_autosave_sgf(
        self,
        moves: list[tuple[str, Stone]],
        board_size: int,
        game_id: int | None = None,
    ) -> Path:
        last_move_at = datetime.now()
        timestamp = last_move_at.strftime("%Y-%m-%d_%H-%M-%S")
        display_time = last_move_at.strftime("%A, %B %d, %Y at %I:%M:%S %p")

        sgf_text = moves_to_sgf(
            moves=moves,
            board_size=board_size,
            black_player="Jason",
            white_player="Opponent",
            game_name=f"Go Sensei Game - Last move {display_time}",
            last_move_at=last_move_at,
        )

        # Always keep one easy-to-find current autosave.
        current_path = self.paths.autosaves / "current_manual_game.sgf"
        current_path.write_text(sgf_text, encoding="utf-8")

        # Also keep one dated SGF in My games, named by the last move time.
        if game_id is None:
            game_id = 0

        if game_id:
            filename_prefix = f"go_sensei_game_{game_id:04d}_last_move_"

            # Remove the older dated copy for this same game so the folder does not fill
            # with a new file after every single move.
            for old_path in self.paths.my_games.glob(f"{filename_prefix}*.sgf"):
                old_path.unlink(missing_ok=True)
        else:
            filename_prefix = "go_sensei_game_last_move_"

        dated_path = self.paths.my_games / f"{filename_prefix}{timestamp}.sgf"
        dated_path.write_text(sgf_text, encoding="utf-8")

        return dated_path

    def save_manual_game_sgf(
        self,
        moves: list[tuple[str, Stone]],
        board_size: int,
        name: str | None = None,
    ) -> Path:
        last_move_at = datetime.now()
        timestamp = last_move_at.strftime("%Y-%m-%d_%H-%M-%S")
        display_time = last_move_at.strftime("%A, %B %d, %Y at %I:%M:%S %p")

        safe_name = sanitize_filename(name or "go_sensei_game")
        path = self.paths.my_games / f"{safe_name}_last_move_{timestamp}.sgf"

        sgf_text = moves_to_sgf(
            moves=moves,
            board_size=board_size,
            black_player="Jason",
            white_player="Opponent",
            game_name=f"{safe_name} - Last move {display_time}",
            last_move_at=last_move_at,
        )

        path.write_text(sgf_text, encoding="utf-8")
        return path

def build_game_paths(root: Path) -> SavedGamePaths:
    return SavedGamePaths(
        root=root,
        my_games=root / "My games",
        elite_games=root / "elite games",
        database_dir=root / "database",
        analysis_cache=root / "analysis cache",
        autosaves=root / "My games" / "autosaves",
        database_path=root / "database" / "go_sensei.db",
    )


def ensure_game_library(paths: SavedGamePaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.my_games.mkdir(parents=True, exist_ok=True)
    paths.elite_games.mkdir(parents=True, exist_ok=True)
    paths.database_dir.mkdir(parents=True, exist_ok=True)
    paths.analysis_cache.mkdir(parents=True, exist_ok=True)
    paths.autosaves.mkdir(parents=True, exist_ok=True)


def moves_to_sgf(
    moves: list[tuple[str, Stone]],
    board_size: int,
    black_player: str,
    white_player: str,
    game_name: str,
    last_move_at: datetime | None = None,
) -> str:
    if last_move_at is None:
        last_move_at = datetime.now()

    last_move_date = last_move_at.strftime("%Y-%m-%d")
    last_move_display = last_move_at.strftime("%A, %B %d, %Y at %I:%M:%S %p")

    properties = [
        "(;GM[1]",
        "FF[4]",
        f"SZ[{board_size}]",
        f"GN[{escape_sgf(game_name)}]",
        f"PB[{escape_sgf(black_player)}]",
        f"PW[{escape_sgf(white_player)}]",
        f"DT[{last_move_date}]",
        f"GC[Last move played: {escape_sgf(last_move_display)}]",
        "AP[Go Sensei]",
    ]

    sgf = "".join(properties)

    for coordinate, stone in moves:
        color = "B" if stone == Stone.BLACK else "W"
        sgf_coordinate = human_to_sgf_coordinate(coordinate, board_size)
        sgf += f";{color}[{sgf_coordinate}]"

    sgf += ")\n"
    return sgf

def human_to_sgf_coordinate(coordinate: str, board_size: int) -> str:
    row, col = human_to_point(coordinate, board_size)

    # SGF uses lowercase zero-based letters and does NOT skip I.
    return chr(ord("a") + col) + chr(ord("a") + row)


def classify_region(coordinate: str, board_size: int) -> str:
    try:
        row, col = human_to_point(coordinate, board_size)
    except ValueError:
        return "unknown"

    edge = min(row, col, board_size - 1 - row, board_size - 1 - col)

    in_corner_zone = (
        (row <= 5 or row >= board_size - 6)
        and (col <= 5 or col >= board_size - 6)
    )

    if edge <= 3 and in_corner_zone:
        return "corner"

    if edge <= 3:
        return "side"

    return "center"


def classify_line_type(coordinate: str, board_size: int) -> str:
    try:
        row, col = human_to_point(coordinate, board_size)
    except ValueError:
        return "unknown"

    line_from_edge = min(row, col, board_size - 1 - row, board_size - 1 - col) + 1

    if line_from_edge <= 2:
        return "low"
    if line_from_edge == 3:
        return "territory"
    if line_from_edge == 4:
        return "influence"

    return "cosmic_center"


def escape_sgf(value: str) -> str:
    return value.replace("\\", "\\\\").replace("]", "\\]")


def sanitize_filename(value: str) -> str:
    invalid = '<>:"/\\|?*'
    output = "".join("_" if character in invalid else character for character in value)
    return output.strip() or "go_sensei_game"


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")
