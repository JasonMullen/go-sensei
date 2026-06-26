
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


class EliteGameKnowledge:
    """
    Lightweight local knowledge layer.

    It scans your downloaded SGF/elite/pro game files and gives pattern feedback.
    This does NOT retrain KataGo. It gives Go Sensei Coach a study-library voice:
    "Have strong games used this kind of move, and what idea is usually behind it?"
    """

    def __init__(self) -> None:
        self.loaded = False
        self.coord_counter: Counter[str] = Counter()
        self.corner_pattern_counter: Counter[str] = Counter()
        self.zone_counter: Counter[str] = Counter()
        self.followups: dict[str, Counter[str]] = defaultdict(Counter)
        self.total_moves = 0
        self.files_scanned = 0
        self.max_files = 2500

    def ensure_loaded(self) -> None:
        if self.loaded:
            return

        self.loaded = True

        roots = [
            Path("data"),
            Path("app/data"),
            Path("analysis_logs"),
            Path("Go Sensei Game"),
            Path("."),
        ]

        seen: set[Path] = set()

        for root in roots:
            if not root.exists():
                continue

            for path in root.rglob("*"):
                if self.files_scanned >= self.max_files:
                    return

                if not path.is_file():
                    continue

                if path in seen:
                    continue

                seen.add(path)

                lower = str(path).lower()

                if any(skip in lower for skip in [".venv", "__pycache__", ".git", "engines"]):
                    continue

                if path.suffix.lower() == ".sgf":
                    self.scan_sgf(path)
                elif path.suffix.lower() in {".csv", ".json", ".txt"}:
                    self.scan_text_like_file(path)

    def scan_text_like_file(self, path: Path) -> None:
        # Many imported game files still contain SGF fragments or coordinates.
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        if len(text) > 2_000_000:
            text = text[:2_000_000]

        if ";B[" in text or ";W[" in text:
            self.scan_sgf_text(text)
            self.files_scanned += 1
            return

        if path.suffix.lower() == ".csv":
            self.scan_csv_coordinates(path)
            return

        if path.suffix.lower() == ".json":
            self.scan_json_coordinates(text)
            return

    def scan_sgf(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        self.scan_sgf_text(text)
        self.files_scanned += 1

    def scan_sgf_text(self, text: str) -> None:
        moves: list[str] = []

        for color, raw in re.findall(r";([BW])\[([a-s]{0,2})\]", text, flags=re.IGNORECASE):
            if not raw or len(raw) != 2:
                continue

            coord = self.sgf_to_go_coord(raw)

            if coord is None:
                continue

            moves.append(coord)
            self.add_move(coord)

        for a, b in zip(moves, moves[1:]):
            self.followups[a][b] += 1

    def scan_csv_coordinates(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key, value in row.items():
                        if key is None or value is None:
                            continue

                        lower_key = key.lower()
                        if any(token in lower_key for token in ["move", "coord", "point"]):
                            coord = self.clean_coord(value)
                            if coord:
                                self.add_move(coord)
        except Exception:
            return

        self.files_scanned += 1

    def scan_json_coordinates(self, text: str) -> None:
        try:
            data = json.loads(text)
        except Exception:
            return

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    lower_key = str(key).lower()
                    if any(token in lower_key for token in ["move", "coord", "point"]):
                        coord = self.clean_coord(value)
                        if coord:
                            self.add_move(coord)
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        self.files_scanned += 1

    def sgf_to_go_coord(self, raw: str) -> str | None:
        raw = raw.lower().strip()

        if len(raw) != 2:
            return None

        col = ord(raw[0]) - ord("a")
        row = ord(raw[1]) - ord("a")

        if not (0 <= col < 19 and 0 <= row < 19):
            return None

        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        return f"{letters[col]}{19 - row}"

    def clean_coord(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).upper().strip()

        match = re.search(r"\b([A-HJ-T])\s*(1[0-9]|[1-9])\b", text)
        if not match:
            return None

        file_label = match.group(1)
        rank = int(match.group(2))

        if not (1 <= rank <= 19):
            return None

        return f"{file_label}{rank}"

    def coord_to_row_col(self, coord: str) -> tuple[int, int] | None:
        coord = self.clean_coord(coord) or ""

        if len(coord) < 2:
            return None

        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

        file_label = coord[0]
        if file_label not in letters:
            return None

        try:
            rank = int(coord[1:])
        except Exception:
            return None

        col = letters.index(file_label)
        row = 19 - rank

        if not (0 <= row < 19 and 0 <= col < 19):
            return None

        return row, col

    def zone_name(self, row: int, col: int) -> str:
        edge = min(row, col, 18 - row, 18 - col)

        if edge <= 4 and ((row <= 6 or row >= 12) and (col <= 6 or col >= 12)):
            return "corner"

        if edge <= 3:
            return "side"

        return "center"

    def corner_pattern(self, row: int, col: int) -> str | None:
        # Normalize to nearest corner line distances.
        vertical = min(row + 1, 19 - row)
        horizontal = min(col + 1, 19 - col)

        if vertical > 7 or horizontal > 7:
            return None

        a, b = sorted([vertical, horizontal])
        return f"{a}-{b}"

    def add_move(self, coord: str) -> None:
        coord = self.clean_coord(coord)
        if not coord:
            return

        rc = self.coord_to_row_col(coord)
        if rc is None:
            return

        row, col = rc

        self.total_moves += 1
        self.coord_counter[coord] += 1

        zone = self.zone_name(row, col)
        self.zone_counter[zone] += 1

        pattern = self.corner_pattern(row, col)
        if pattern:
            self.corner_pattern_counter[pattern] += 1

    def idea_for_corner_pattern(self, pattern: str | None) -> str:
        if pattern is None:
            return ""

        ideas = {
            "3-3": "The 3-3 point is direct territory. It usually says: secure the corner now, accept less outside influence.",
            "3-4": "The 3-4 point balances territory and outside development. It keeps direction flexible.",
            "4-4": "The 4-4 point values speed, influence, and whole-board development more than immediate secure territory.",
            "3-5": "The 3-5 point is higher and more influence-oriented. It often aims at outside pressure rather than simple corner profit.",
            "4-5": "The 4-5 point is a high-pressure corner move. It often invites fighting or large-scale development.",
            "5-5": "The 5-5 point is very high and framework-oriented. It usually needs whole-board support.",
        }

        return ideas.get(
            pattern,
            f"This is a {pattern} style corner move. Its meaning depends heavily on direction and nearby stones.",
        )

    def idea_for_zone(self, zone: str) -> str:
        if zone == "corner":
            return "Corner moves are efficient because two board edges help make territory quickly."
        if zone == "side":
            return "Side moves usually expand frameworks, reduce the opponent, or give weak groups running room."
        if zone == "center":
            return "Center moves are usually about influence, connection, attack, escape, or whole-board pressure."
        return "This move needs to be understood by its relationship to nearby groups."

    def explain_move(self, coord: str, color: str = "") -> dict[str, str]:
        self.ensure_loaded()

        coord = self.clean_coord(coord) or coord
        rc = self.coord_to_row_col(coord)

        if rc is None:
            return {
                "summary": "Elite pattern unavailable",
                "detail": "I could not map this move to a normal board coordinate.",
                "lesson": "Use KataGo's continuation and the current board position to study this move.",
            }

        row, col = rc
        zone = self.zone_name(row, col)
        pattern = self.corner_pattern(row, col)

        coord_hits = self.coord_counter.get(coord, 0)
        pattern_hits = self.corner_pattern_counter.get(pattern, 0) if pattern else 0

        top_followups = self.followups.get(coord, Counter()).most_common(3)

        lines: list[str] = []

        lines.append(self.idea_for_zone(zone))

        if pattern:
            lines.append(self.idea_for_corner_pattern(pattern))

        if coord_hits > 0:
            lines.append(
                f"In the downloaded elite-game library, the exact point {coord} appears {coord_hits} time(s)."
            )
        else:
            lines.append(
                f"I do not see the exact point {coord} often in the downloaded elite-game library."
            )

        if pattern and pattern_hits > 0:
            lines.append(
                f"The broader {pattern} corner pattern appears {pattern_hits} time(s), so the idea itself is recognizable."
            )

        if top_followups:
            followup_text = ", ".join(f"{move} ({count})" for move, count in top_followups)
            lines.append(f"Common next moves after {coord} in the library: {followup_text}.")
        else:
            lines.append(
                "No common exact follow-up was found, so the explanation should rely more on shape, direction, and KataGo."
            )

        if self.files_scanned == 0:
            lines.append(
                "I did not find SGF/elite-game files yet. Put SGF files in data/ or app/data/ for stronger elite-game feedback."
            )
        else:
            lines.append(
                f"Elite library scanned: {self.files_scanned} file(s), {self.total_moves} move records."
            )

        if zone == "corner":
            study = "Ask: is this move choosing territory, influence, or attack direction?"
        elif zone == "side":
            study = "Ask: is this move expanding your framework, reducing theirs, or helping a weak group move out?"
        else:
            study = "Ask: is this move connecting, attacking, escaping, or increasing whole-board pressure?"

        return {
            "summary": f"Elite pattern: {pattern or zone}",
            "detail": "\n".join(lines),
            "lesson": study,
        }
