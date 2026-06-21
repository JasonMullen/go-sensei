from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.coordinates import point_to_human
from app.core.stone import Stone
from app.data.game_store import GameStore


DEFAULT_ELITE_DIR = Path(
    r"C:\Users\jason\OneDrive\Attachments\Desktop\Go Sensei Game\elite games"
)


@dataclass(frozen=True)
class ImportedGameStats:
    path: Path
    target_color: Stone | None
    imported_moves: int
    skipped_reason: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Study elite SGF games and build a Go Sensei style profile."
    )

    parser.add_argument(
        "elite_dir",
        nargs="?",
        default=str(DEFAULT_ELITE_DIR),
        help="Folder containing elite SGF games.",
    )
    parser.add_argument("--profile", default="Cosmic")
    parser.add_argument("--player", default="Takemiya")
    parser.add_argument("--max-moves", type=int, default=120)
    parser.add_argument("--reset", action="store_true")

    args = parser.parse_args()

    elite_dir = Path(args.elite_dir)
    store = GameStore()

    if args.reset:
        reset_profile(store, args.profile)

    stats = import_elite_folder(
        store=store,
        elite_dir=elite_dir,
        profile_name=args.profile,
        player_name=args.player,
        max_moves=args.max_moves,
    )

    imported_games = [item for item in stats if item.imported_moves > 0]
    imported_moves = sum(item.imported_moves for item in stats)

    print()
    print("Go Sensei Elite Style Import Complete")
    print("=" * 48)
    print(f"Folder: {elite_dir}")
    print(f"Profile: {args.profile}")
    print(f"Target player: {args.player}")
    print(f"Games studied: {len(imported_games)}")
    print(f"Moves studied: {imported_moves}")
    print()

    preferences = store.get_style_preferences(
        board_size=19,
        profile_name=args.profile,
    )

    print("Top learned style preferences:")
    print("-" * 48)

    if not preferences:
        print("No preferences learned yet.")
    else:
        for region, line_type, count in preferences:
            print(f"{region:<10} {line_type:<15} {count}")


def import_elite_folder(
    store: GameStore,
    elite_dir: Path,
    profile_name: str,
    player_name: str,
    max_moves: int,
) -> list[ImportedGameStats]:
    if not elite_dir.exists():
        raise FileNotFoundError(f"Elite games folder not found: {elite_dir}")

    stats: list[ImportedGameStats] = []

    for path in sorted(elite_dir.rglob("*")):
        if not path.is_file():
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as error:
            stats.append(
                ImportedGameStats(
                    path=path,
                    target_color=None,
                    imported_moves=0,
                    skipped_reason=f"Could not read file: {error}",
                )
            )
            continue

        if "(;" not in text or (";B[" not in text and ";W[" not in text):
            stats.append(
                ImportedGameStats(
                    path=path,
                    target_color=None,
                    imported_moves=0,
                    skipped_reason="Not recognized as SGF text",
                )
            )
            continue

        board_size = extract_board_size(text)
        target_color = detect_player_color(
            sgf_text=text,
            path=path,
            player_name=player_name,
        )

        if target_color is None:
            stats.append(
                ImportedGameStats(
                    path=path,
                    target_color=None,
                    imported_moves=0,
                    skipped_reason=f"Could not detect {player_name}'s color",
                )
            )
            continue

        imported_count = 0

        for move_number, color, coordinate in extract_sgf_moves(text, board_size):
            if move_number > max_moves:
                break

            if color != target_color:
                continue

            store.update_style_profile(
                player=color,
                coordinate=coordinate,
                board_size=board_size,
                profile_name=profile_name,
            )

            imported_count += 1

        stats.append(
            ImportedGameStats(
                path=path,
                target_color=target_color,
                imported_moves=imported_count,
                skipped_reason=None if imported_count > 0 else "No target-player moves found",
            )
        )

    return stats


def reset_profile(store: GameStore, profile_name: str) -> None:
    with store.connect() as connection:
        connection.execute(
            "DELETE FROM style_profile WHERE profile_name = ?",
            (profile_name,),
        )

    print(f"[Go Sensei Database] Reset style profile: {profile_name}", flush=True)


def extract_board_size(text: str) -> int:
    match = re.search(r"SZ\[(\d+)\]", text)

    if not match:
        return 19

    return int(match.group(1))


def detect_player_color(
    sgf_text: str,
    path: Path,
    player_name: str,
) -> Stone | None:
    target = normalize(player_name)

    black_player = extract_property(sgf_text, "PB")
    white_player = extract_property(sgf_text, "PW")

    if target in normalize(black_player):
        return Stone.BLACK

    if target in normalize(white_player):
        return Stone.WHITE

    name = path.stem
    parts = [part.strip() for part in name.split(" - ")]

    if len(parts) >= 2:
        black_name = parts[0]
        white_name = parts[1]

        if target in normalize(black_name):
            return Stone.BLACK

        if target in normalize(white_name):
            return Stone.WHITE

    return None


def extract_property(text: str, property_name: str) -> str:
    match = re.search(rf"{property_name}\[((?:\\.|[^\]])*)\]", text)

    if not match:
        return ""

    return match.group(1).replace("\\]", "]").replace("\\\\", "\\")


def extract_sgf_moves(
    text: str,
    board_size: int,
) -> list[tuple[int, Stone, str]]:
    output: list[tuple[int, Stone, str]] = []

    for index, match in enumerate(re.finditer(r";([BW])\[([a-z]{0,2})\]", text), start=1):
        color_text = match.group(1)
        sgf_coordinate = match.group(2)

        if len(sgf_coordinate) != 2:
            continue

        color = Stone.BLACK if color_text == "B" else Stone.WHITE

        try:
            coordinate = sgf_to_human_coordinate(sgf_coordinate, board_size)
        except ValueError:
            continue

        output.append((index, color, coordinate))

    return output


def sgf_to_human_coordinate(
    sgf_coordinate: str,
    board_size: int,
) -> str:
    col = ord(sgf_coordinate[0]) - ord("a")
    row = ord(sgf_coordinate[1]) - ord("a")

    if not (0 <= row < board_size and 0 <= col < board_size):
        raise ValueError(f"Invalid SGF coordinate: {sgf_coordinate}")

    return point_to_human(row, col, board_size)


def normalize(value: str) -> str:
    return value.lower().replace(" ", "").replace("-", "").replace("_", "")


if __name__ == "__main__":
    main()
