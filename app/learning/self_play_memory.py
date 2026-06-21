from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_MEMORY_PATH = Path(
    os.getenv(
        "GO_SENSEI_SELF_PLAY_MEMORY",
        r"C:\Users\jason\OneDrive\Attachments\Desktop\Go Sensei Game\database\self_play_memory.json",
    )
)


class SelfPlayMemory:
    """Simple persistent memory for AI-vs-AI games.

    This does NOT retrain KataGo. It stores patterns from self-play and lets
    Go Sensei prefer learned moves when KataGo also thinks they are reasonable.
    """

    def __init__(self, path: Path = DEFAULT_MEMORY_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": 1,
                "total_moves": 0,
                "positions": {},
            }

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "version": 1,
                "total_moves": 0,
                "positions": {},
            }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def total_moves(self) -> int:
        return int(self.data.get("total_moves", 0))

    def phase_for_move_number(self, move_number: int) -> str:
        if move_number <= 40:
            return "opening"
        if move_number <= 120:
            return "middle"
        return "endgame"

    def player_name(self, player: Any) -> str:
        return getattr(player, "name", str(player)).upper()

    def make_key(self, board_size: int, player: Any, move_number: int) -> str:
        phase = self.phase_for_move_number(move_number)
        color = self.player_name(player)
        return f"{board_size}|{color}|{phase}"

    def record_move(
        self,
        board_size: int,
        player: Any,
        move_number: int,
        move: str,
        chosen_rank: int | None = None,
        visits: int | None = None,
        prior: float | None = None,
        winrate: float | None = None,
        score_lead: float | None = None,
    ) -> None:
        key = self.make_key(board_size, player, move_number)

        positions = self.data.setdefault("positions", {})
        bucket = positions.setdefault(key, {})
        stats = bucket.setdefault(
            move,
            {
                "count": 0,
                "rank_total": 0,
                "rank_count": 0,
                "visits_total": 0,
                "prior_total": 0.0,
                "prior_count": 0,
                "winrate_total": 0.0,
                "winrate_count": 0,
                "score_total": 0.0,
                "score_count": 0,
            },
        )

        stats["count"] += 1

        if chosen_rank is not None:
            stats["rank_total"] += int(chosen_rank)
            stats["rank_count"] += 1

        if visits is not None:
            stats["visits_total"] += int(visits)

        if prior is not None:
            stats["prior_total"] += float(prior)
            stats["prior_count"] += 1

        if winrate is not None:
            stats["winrate_total"] += float(winrate)
            stats["winrate_count"] += 1

        if score_lead is not None:
            stats["score_total"] += float(score_lead)
            stats["score_count"] += 1

        self.data["total_moves"] = int(self.data.get("total_moves", 0)) + 1
        self.save()

    def get_recommendations(
        self,
        board_size: int,
        player: Any,
        move_number: int,
        limit: int = 8,
    ) -> list[str]:
        key = self.make_key(board_size, player, move_number)
        bucket = self.data.get("positions", {}).get(key, {})

        scored: list[tuple[float, str]] = []

        for move, stats in bucket.items():
            count = float(stats.get("count", 0))
            rank_count = float(stats.get("rank_count", 0))
            rank_total = float(stats.get("rank_total", 0))

            avg_rank_bonus = 0.0
            if rank_count > 0:
                avg_rank = rank_total / rank_count
                avg_rank_bonus = max(0.0, 10.0 - avg_rank)

            visits_bonus = min(float(stats.get("visits_total", 0)) / 1000.0, 5.0)

            score = count * 3.0 + avg_rank_bonus + visits_bonus
            scored.append((score, move))

        scored.sort(reverse=True)

        return [move for _, move in scored[:limit]]
