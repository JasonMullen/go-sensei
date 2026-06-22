import math
import random
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import pygame

from app.core.board import Board
from app.core.coordinates import GO_COLUMNS, human_to_point, point_to_human
from app.core.sgf import SgfGame, build_board_at_move, load_sgf_file
from app.core.stone import Stone
from app.analysis.live_analyzer import LiveAnalysisService, LiveAnalysisState
from app.ai.ai_player import choose_ai_move
from app.data.game_store import GameStore
from app.recommendation.move_lanes import build_display_move_lanes
from app.review.live_move_coach import make_live_move_coaching


class GoBoardWindow:
    def __init__(self, board_size: int = 19) -> None:
        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move: tuple[int, int] | None = None
        self.status_message = ""

        self.analysis_enabled = False
        self.analysis_service = LiveAnalysisService(max_visits=4)
        self.analysis_state = LiveAnalysisState()
        self.ai_enabled = False
        self.ai_player = Stone.WHITE
        self.ai_pending_request_id = None
        self.ai_is_thinking = False
        self.ai_last_move = None
        self.game_store = GameStore()
        self.current_database_game_id = self.game_store.start_game(board_size=self.board.size)
        self.last_autosave_path = None
        self.coach_title = "Coach Read"
        self.coach_lines = ["Click ANALYZE, wait for Ready, then make a move."]
        self.pending_coach_review = None

        self.loaded_game: SgfGame | None = None
        self.loaded_sgf_path: Path | None = None
        self.move_index = 0
        self.black_captures = 0
        self.white_captures = 0
        self.manual_move_history: list[tuple[str, Stone]] = []
        self.manual_move_index = 0
        self.skipped_moves = 0

        self.is_playing = False
        self.playback_speed = 1.5
        self.min_playback_speed = 0.25
        self.max_playback_speed = 6.0
        self.last_auto_step_ms = 0
        self.dragging_speed_slider = False

        pygame.init()
        self.stone_sound = self.load_stone_sound()
        pygame.display.set_caption("Go Sensei Board")

        self.window_width = 800
        self.window_height = 832
        self.min_window_width = 720
        self.min_window_height = 760
        self.max_board_pixels = 675
        self.min_board_pixels = 420

        self.screen = pygame.display.set_mode(
            (self.window_width, self.window_height),
            pygame.RESIZABLE,
        )
        self.clock = pygame.time.Clock()

        self.coord_font = pygame.font.SysFont("arial", 21, bold=True)
        self.status_font = pygame.font.SysFont("arial", 16, bold=True)
        self.ui_font = pygame.font.SysFont("arial", 17, bold=True)
        self.small_ui_font = pygame.font.SysFont("arial", 14, bold=True)

        self.outer_bg = (224, 182, 87)
        self.board_base = (211, 170, 78)
        self.line_color = (46, 34, 18)
        self.star_color = (15, 12, 8)
        self.text_color = (8, 8, 8)

        self.control_bar_color = (47, 47, 47)
        self.button_fill = (78, 78, 78)
        self.button_hover = (96, 96, 96)
        self.button_disabled = (60, 60, 60)
        self.button_text = (210, 210, 210)

        self.black_core = (36, 36, 38)
        self.black_edge = (14, 14, 16)
        self.black_highlight = (92, 92, 94)

        self.white_edge = (170, 170, 170)
        self.white_highlight = (255, 255, 255)

        self.board_left = 0
        self.board_top = 0
        self.board_pixels = 0
        self.board_right = 0
        self.board_bottom = 0
        self.cell_size = 0.0
        self.stone_radius = 0

        self.board_surface: pygame.Surface | None = None
        self.cached_board_key: tuple[int, int] | None = None

        self.dropdown_open = False
        self.dropdown_rect = pygame.Rect(0, 0, 0, 0)
        self.dropdown_option_rects: list[tuple[int, pygame.Rect]] = []

        self.control_bar_rect = pygame.Rect(0, 0, 0, 0)
        self.button_rects: dict[str, pygame.Rect] = {}
        self.speed_slider_rect = pygame.Rect(0, 0, 0, 0)
        self.speed_slider_hit_rect = pygame.Rect(0, 0, 0, 0)

        self.recalculate_layout()

    def load_stone_sound(self) -> pygame.mixer.Sound | None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()

            sound_path = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "sounds"
                / "stone_place.wav"
            )

            if not sound_path.exists():
                return None

            return pygame.mixer.Sound(str(sound_path))
        except pygame.error:
            return None

    def play_stone_sound(self) -> None:
        if self.stone_sound is not None:
            self.stone_sound.play()

    def recalculate_layout(self) -> None:
        header_height = 53
        bottom_ui_height = 104
        side_padding = 60

        available_width = self.window_width - (side_padding * 2)
        available_height = self.window_height - header_height - bottom_ui_height

        self.board_pixels = int(
            min(
                available_width,
                available_height,
                self.max_board_pixels,
            )
        )
        self.board_pixels = max(self.min_board_pixels, self.board_pixels)

        self.board_left = (self.window_width - self.board_pixels) // 2
        self.board_top = header_height
        self.board_right = self.board_left + self.board_pixels
        self.board_bottom = self.board_top + self.board_pixels

        self.cell_size = self.board_pixels / (self.board.size - 1)
        self.stone_radius = int(self.cell_size * 0.43)

        self.dropdown_rect = pygame.Rect(
            self.window_width - 150,
            8,
            110,
            30,
        )

        self.dropdown_option_rects = []
        option_top = self.dropdown_rect.bottom + 3

        for index, size in enumerate([19, 13, 9]):
            option_rect = pygame.Rect(
                self.dropdown_rect.left,
                option_top + (index * 30),
                self.dropdown_rect.width,
                30,
            )
            self.dropdown_option_rects.append((size, option_rect))

        self.recalculate_control_layout()
        self.rebuild_board_surface_if_needed()

    def recalculate_control_layout(self) -> None:
        self.control_bar_rect = pygame.Rect(
            0,
            self.window_height - 47,
            self.window_width,
            47,
        )

        button_names = [
            "load",
            "analysis",
            "beginning",
            "back",
            "play_pause",
            "forward",
            "end",
        ]

        gap = 6
        side_margin = 8
        button_width = (
            self.window_width
            - (side_margin * 2)
            - (gap * (len(button_names) - 1))
        ) // len(button_names)

        x = side_margin
        y = self.control_bar_rect.top + 5

        self.button_rects = {}

        for name in button_names:
            self.button_rects[name] = pygame.Rect(x, y, button_width, 38)
            x += button_width + gap

        slider_width = 250
        slider_left = self.board_right - slider_width
        slider_top = self.control_bar_rect.top - 20

        self.speed_slider_rect = pygame.Rect(
            slider_left,
            slider_top,
            slider_width,
            6,
        )
        self.speed_slider_hit_rect = self.speed_slider_rect.inflate(0, 26)

    def draw_wood_grain(self, surface: pygame.Surface, rng) -> None:
        """Draw a simple wood-grain background for the Go board surface."""
        width, height = surface.get_size()

        base_color = (219, 174, 74)
        surface.fill(base_color)

        # Light vertical grain
        for x in range(0, width, 3):
            shade = rng.randint(-12, 12)
            color = (
                max(0, min(255, base_color[0] + shade)),
                max(0, min(255, base_color[1] + shade)),
                max(0, min(255, base_color[2] + shade)),
            )
            pygame.draw.line(surface, color, (x, 0), (x, height), 1)

        # A few darker natural grain streaks
        for _ in range(38):
            x = rng.randint(0, max(1, width - 1))
            shade = rng.randint(18, 38)
            color = (
                max(0, base_color[0] - shade),
                max(0, base_color[1] - shade),
                max(0, base_color[2] - shade),
            )
            pygame.draw.line(surface, color, (x, 0), (x, height), 1)

        # Soft horizontal variation
        for _ in range(18):
            y = rng.randint(0, max(1, height - 1))
            shade = rng.randint(-8, 8)
            color = (
                max(0, min(255, base_color[0] + shade)),
                max(0, min(255, base_color[1] + shade)),
                max(0, min(255, base_color[2] + shade)),
            )
            pygame.draw.line(surface, color, (0, y), (width, y), 1)


    def rebuild_board_surface_if_needed(self) -> None:
        board_key = (self.board.size, self.board_pixels)

        if self.cached_board_key == board_key and self.board_surface is not None:
            return

        self.board_surface = self.build_board_surface()
        self.cached_board_key = board_key

    def build_board_surface(self) -> pygame.Surface:
        surface = pygame.Surface((self.board_pixels, self.board_pixels))
        surface.fill(self.board_base)

        rng = random.Random(11)
        self.draw_wood_grain(surface, rng)
        self.draw_grid(surface)
        self.draw_star_points(surface)

        return surface

    def draw(self) -> None:
        # Full safe redraw. This prevents the window from staying black.
        self.screen.fill((224, 184, 86))

        # Board wood background
        board_padding = max(12, self.cell_size // 2)
        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )
        pygame.draw.rect(self.screen, (219, 174, 74), board_rect)

        # Subtle board border
        pygame.draw.rect(self.screen, (110, 78, 28), board_rect, 2)

        # Grid lines
        for row in range(self.board.size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, self.board.size - 1)
            pygame.draw.line(self.screen, (65, 45, 20), (start_x, y), (end_x, y), 1)

        for col in range(self.board.size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(self.board.size - 1, col)
            pygame.draw.line(self.screen, (65, 45, 20), (x, start_y), (x, end_y), 1)

        # Star points
        if self.board.size == 19:
            star_points = [3, 9, 15]
        elif self.board.size == 13:
            star_points = [3, 6, 9]
        elif self.board.size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, (35, 25, 12), (x, y), 4)

        # Coordinates
        if hasattr(self, "draw_coordinates"):
            self.draw_coordinates()

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(self.board.size):
            for col in range(self.board.size):
                coordinate = point_to_human(row, col, self.board.size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                if stone == Stone.BLACK:
                    x, y = self.point_to_pixels(row, col)
                    pygame.draw.circle(self.screen, (22, 22, 25), (x, y), stone_radius)
                    pygame.draw.circle(self.screen, (65, 65, 70), (x - 5, y - 5), max(3, stone_radius // 4))
                elif stone == Stone.WHITE:
                    x, y = self.point_to_pixels(row, col)
                    pygame.draw.circle(self.screen, (235, 235, 230), (x, y), stone_radius)
                    pygame.draw.circle(self.screen, (160, 160, 160), (x, y), stone_radius, 2)
                    pygame.draw.circle(self.screen, (255, 255, 255), (x - 5, y - 5), max(3, stone_radius // 4))

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (80, 150, 255), (x, y), max(6, stone_radius // 3), 3)

        # Analysis markers: blue/green/orange move suggestions
        if hasattr(self, "draw_analysis_markers"):
            self.draw_analysis_markers()

        # Left and right panels
        if hasattr(self, "draw_coach_panel"):
            self.draw_coach_panel()

        if hasattr(self, "draw_analysis_panel"):
            self.draw_analysis_panel()

        # Optional UI pieces from the existing app
        for method_name in [
            "draw_size_selector",
            "draw_speed_slider",
            "draw_bottom_controls",
            "draw_replay_controls",
            "draw_controls",
            "draw_status",
            "draw_status_bar",
            "draw_ai_status_badge",
        ]:
            method = getattr(self, method_name, None)
            if callable(method):
                method()

        pygame.display.flip()

    def draw_grid(self, surface: pygame.Surface) -> None:
        for index in range(self.board.size):
            x = round(index * self.cell_size)
            y = round(index * self.cell_size)

            pygame.draw.line(
                surface,
                self.line_color,
                (0, y),
                (self.board_pixels, y),
                1,
            )

            pygame.draw.line(
                surface,
                self.line_color,
                (x, 0),
                (x, self.board_pixels),
                1,
            )

    def draw_star_points(self, surface: pygame.Surface) -> None:
        star_radius = max(3, int(self.cell_size * 0.075))

        for row, col in self.get_star_points():
            x = round(col * self.cell_size)
            y = round(row * self.cell_size)

            pygame.draw.circle(surface, self.star_color, (x, y), star_radius)

    def get_star_points(self) -> list[tuple[int, int]]:
        if self.board.size == 19:
            indices = [3, 9, 15]
        elif self.board.size == 13:
            indices = [3, 6, 9]
        else:
            indices = [2, 4, 6]

        return [(row, col) for row in indices for col in indices]

    def run(self) -> None:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if hasattr(self, "shutdown"):
                        self.shutdown()

                    pygame.quit()
                    raise SystemExit

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.dragging_speed_slider = False

                if event.type == pygame.MOUSEMOTION and self.dragging_speed_slider:
                    self.update_speed_from_mouse(event.pos[0])

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_i:
                        if hasattr(self, "toggle_ai_opponent"):
                            self.toggle_ai_opponent()
                        continue

                    if event.key == pygame.K_r:
                        self.reset_board()
                        continue

                    if event.key == pygame.K_a:
                        self.toggle_live_analysis()
                        continue

            self.update_auto_replay()
            self.analysis_state = self.analysis_service.get_state()

            if hasattr(self, "update_ai_move"):
                self.update_ai_move()

            if hasattr(self, "update_live_move_coaching"):
                self.update_live_move_coaching()

            self.draw()
            self.clock.tick(60)

    def shutdown(self) -> None:
        self.analysis_service.stop()

    def handle_resize(self, width: int, height: int) -> None:
        self.window_width = max(width, self.min_window_width)
        self.window_height = max(height, self.min_window_height)

        self.screen = pygame.display.set_mode(
            (self.window_width, self.window_height),
            pygame.RESIZABLE,
        )

        self.cached_board_key = None
        self.recalculate_layout()

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        # 1. Top-right board-size button
        size_rect = getattr(self, "size_selector_rect", None)

        if size_rect is not None and size_rect.collidepoint(mouse_pos):
            self.cycle_board_size()
            return

        # 2. Bottom buttons
        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                self.handle_button_click(button_name)
                return

        # 3. Speed slider, if available
        speed_rect = getattr(self, "speed_slider_rect", None)

        if speed_rect is not None and speed_rect.collidepoint(mouse_pos):
            self.dragging_speed_slider = True

            if hasattr(self, "update_speed_from_mouse"):
                self.update_speed_from_mouse(mouse_pos[0])

            return

        # 4. Board placement
        self.handle_board_click(mouse_pos)

    def handle_button_click(self, button_name: str) -> None:
        if button_name == "load":
            self.load_sgf_from_dialog()
            return

        if button_name == "analysis":
            self.toggle_live_analysis()
            return

        if button_name == "ai":
            self.toggle_ai_opponent()
            return

        if self.loaded_game is None:
            if button_name == "beginning":
                self.go_to_manual_beginning()
            elif button_name == "back":
                self.step_manual_back()
            elif button_name == "forward":
                self.step_manual_forward()
            elif button_name == "end":
                self.go_to_manual_end()
            elif button_name == "play_pause":
                self.status_message = "Manual mode: use << and >> for undo/redo"
            return

        if button_name == "beginning":
            self.go_to_beginning()
        elif button_name == "back":
            self.step_back()
        elif button_name == "play_pause":
            self.toggle_playback()
        elif button_name == "forward":
            self.step_forward(play_sound=True)
        elif button_name == "end":
            self.go_to_end()

    def load_sgf_from_dialog(self) -> None:
        self.is_playing = False

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        try:
            selected_path = filedialog.askopenfilename(
                parent=root,
                title="Load SGF file",
                filetypes=[
                    ("SGF files", "*.sgf"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()

        if not selected_path:
            return

        try:
            game = load_sgf_file(selected_path)
        except Exception as error:
            self.status_message = f"Could not load SGF: {error}"
            return

        self.clear_manual_history()

        self.loaded_game = game
        self.loaded_sgf_path = Path(selected_path)
        self.is_playing = False
        self.move_index = 0
        self.black_captures = 0
        self.white_captures = 0
        self.skipped_moves = 0
        self.status_message = f"Loaded {self.loaded_sgf_path.name}"

        self.board = Board(size=game.board_size)
        self.current_player = Stone.BLACK
        self.last_move = None

        self.cached_board_key = None
        self.recalculate_layout()
        self.set_replay_position(0)

    def update_auto_replay(self) -> None:
        if self.loaded_game is None or not self.is_playing:
            return

        if self.move_index >= len(self.loaded_game.moves):
            self.is_playing = False
            return

        now_ms = pygame.time.get_ticks()
        interval_ms = max(80, int(1000 / self.playback_speed))

        if now_ms - self.last_auto_step_ms >= interval_ms:
            self.step_forward(play_sound=True)
            self.last_auto_step_ms = now_ms

    def toggle_playback(self) -> None:
        if self.loaded_game is None:
            return

        if self.move_index >= len(self.loaded_game.moves):
            self.set_replay_position(0)

        self.is_playing = not self.is_playing
        self.last_auto_step_ms = 0

    def go_to_beginning(self) -> None:
        if self.loaded_game is None:
            return

        self.is_playing = False
        self.set_replay_position(0)

    def go_to_end(self) -> None:
        if self.loaded_game is None:
            return

        self.is_playing = False
        self.set_replay_position(len(self.loaded_game.moves))

    def step_back(self) -> None:
        if self.loaded_game is None:
            return

        self.is_playing = False
        self.set_replay_position(self.move_index - 1)

    def step_forward(self, play_sound: bool = False) -> None:
        if self.loaded_game is None:
            return

        if self.move_index >= len(self.loaded_game.moves):
            self.is_playing = False
            return

        self.set_replay_position(self.move_index + 1, play_sound=play_sound)

    def set_replay_position(
        self,
        requested_move_index: int,
        play_sound: bool = False,
    ) -> None:
        if self.loaded_game is None:
            return

        position = build_board_at_move(self.loaded_game, requested_move_index)

        self.board = position.board
        self.move_index = position.move_index
        self.black_captures = position.black_captures
        self.white_captures = position.white_captures
        self.skipped_moves = position.skipped_moves
        self.last_move = position.last_move

        if play_sound and self.last_move is not None:
            self.play_stone_sound()

        self.update_current_player_from_replay()
        self.status_message = self.get_replay_status_text()

        if self.analysis_enabled:
            self.request_live_analysis_from_replay()

    def update_current_player_from_replay(self) -> None:
        if self.loaded_game is None:
            self.current_player = Stone.BLACK
            return

        if self.move_index < len(self.loaded_game.moves):
            self.current_player = self.loaded_game.moves[self.move_index].color
        else:
            self.current_player = Stone.BLACK

    def get_replay_status_text(self) -> str:
        if self.loaded_game is None:
            return ""

        total_moves = len(self.loaded_game.moves)

        if self.skipped_moves > 0:
            return f"Move {self.move_index}/{total_moves} — skipped {self.skipped_moves}"

        return f"Move {self.move_index}/{total_moves}"

    def update_speed_from_mouse(self, mouse_x: int) -> None:
        left = self.speed_slider_rect.left
        right = self.speed_slider_rect.right

        clamped_x = max(left, min(mouse_x, right))
        fraction = (clamped_x - left) / self.speed_slider_rect.width

        speed_range = self.max_playback_speed - self.min_playback_speed
        self.playback_speed = self.min_playback_speed + (fraction * speed_range)
        self.playback_speed = round(self.playback_speed, 2)

    def change_board_size(self, board_size: int) -> None:
        if board_size == self.board.size and self.loaded_game is None:
            return

        self.loaded_game = None
        self.loaded_sgf_path = None
        self.is_playing = False
        self.clear_manual_history()
        self.move_index = 0
        self.black_captures = 0
        self.white_captures = 0
        self.skipped_moves = 0

        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move = None
        self.status_message = f"New {board_size}x{board_size} board"

        self.cached_board_key = None
        self.recalculate_layout()

    def reset_board(self) -> None:
        self.is_playing = False
        self.loaded_game = None
        self.loaded_sgf_path = None
        self.clear_manual_history()
        self.move_index = 0
        self.black_captures = 0
        self.white_captures = 0
        self.skipped_moves = 0

        self.board.clear()
        self.current_player = Stone.BLACK
        self.last_move = None
        self.status_message = ""

    def switch_turn(self) -> None:
        if self.current_player == Stone.BLACK:
            self.current_player = Stone.WHITE
        else:
            self.current_player = Stone.BLACK

    def handle_board_click(self, mouse_pos: tuple[int, int]) -> None:
        if self.loaded_game is not None:
            self.status_message = "Replay mode: use the SGF controls"
            return

        if self.ai_enabled and self.current_player == self.ai_player:
            self.status_message = "AI is thinking..."
            return

        point = self.mouse_to_point(mouse_pos)

        if point is None:
            return

        row, col = point
        coordinate = point_to_human(row, col, self.board.size)
        played_stone = self.current_player

        baseline_completed_request_id = self.analysis_state.completed_request_id
        pre_move_result = None

        if self.analysis_enabled and not self.analysis_state.is_thinking:
            pre_move_result = self.analysis_state.latest_result

        if hasattr(self, "manual_move_history") and self.manual_move_index < len(self.manual_move_history):
            next_coordinate, next_stone = self.manual_move_history[self.manual_move_index]

            if next_coordinate == coordinate and next_stone == played_stone:
                self.step_manual_forward(play_sound=True)
                return

            self.manual_move_history = self.manual_move_history[: self.manual_move_index]

        try:
            captured_count = self.board.place_stone(coordinate, played_stone)
        except ValueError:
            self.status_message = f"Illegal move: {coordinate}"
            return

        if hasattr(self, "manual_move_history"):
            self.manual_move_history.append((coordinate, played_stone))
            self.manual_move_index += 1

        if hasattr(self, "record_current_move_to_database"):
            self.record_current_move_to_database(
                coordinate=coordinate,
                player=played_stone,
                captured_count=captured_count,
            )

        if hasattr(self, "autosave_current_manual_game"):
            self.autosave_current_manual_game()

        if played_stone == Stone.BLACK:
            self.black_captures += captured_count
        else:
            self.white_captures += captured_count

        self.play_stone_sound()
        self.last_move = (row, col)

        if captured_count == 1:
            self.status_message = "Captured 1 stone"
        elif captured_count > 1:
            self.status_message = f"Captured {captured_count} stones"
        elif hasattr(self, "get_manual_status_text"):
            self.status_message = self.get_manual_status_text()
        else:
            self.status_message = ""

        self.switch_turn()

        if self.analysis_enabled and hasattr(self, "start_move_coaching"):
            self.start_move_coaching(
                played_move=coordinate,
                player=played_stone,
                before_result=pre_move_result,
                baseline_completed_request_id=baseline_completed_request_id,
            )

        if self.analysis_enabled:
            self.request_live_analysis()

        self.maybe_request_ai_move()

    def clear_manual_history(self) -> None:
        self.manual_move_history = []
        self.manual_move_index = 0

    def get_manual_status_text(self) -> str:
        total = len(self.manual_move_history)

        if total == 0:
            return ""

        if self.manual_move_index < total:
            return f"Manual move {self.manual_move_index}/{total} — redo available"

        return f"Manual move {self.manual_move_index}/{total}"

    def go_to_manual_beginning(self) -> None:
        if not self.manual_move_history:
            self.status_message = "No manual moves to undo"
            return

        self.set_manual_position(0)

    def go_to_manual_end(self) -> None:
        if not self.manual_move_history:
            self.status_message = "No manual moves yet"
            return

        self.set_manual_position(len(self.manual_move_history), play_sound=True)

    def step_manual_back(self) -> None:
        if self.manual_move_index <= 0:
            self.status_message = "Already at the beginning"
            return

        self.set_manual_position(self.manual_move_index - 1)

    def step_manual_forward(self, play_sound: bool = True) -> None:
        if self.manual_move_index >= len(self.manual_move_history):
            self.status_message = "No future move to replay"
            return

        self.set_manual_position(self.manual_move_index + 1, play_sound=play_sound)

    def set_manual_position(
        self,
        target_index: int,
        play_sound: bool = False,
    ) -> None:
        target_index = max(0, min(target_index, len(self.manual_move_history)))

        board_size = self.board.size
        self.board = Board(size=board_size)
        self.black_captures = 0
        self.white_captures = 0
        self.last_move = None

        last_coordinate: str | None = None

        for coordinate, stone in self.manual_move_history[:target_index]:
            captured_count = self.board.place_stone(coordinate, stone)

            if stone == Stone.BLACK:
                self.black_captures += captured_count
            else:
                self.white_captures += captured_count

            last_coordinate = coordinate

        self.manual_move_index = target_index

        if last_coordinate is not None:
            self.last_move = human_to_point(last_coordinate, self.board.size)

            if play_sound:
                self.play_stone_sound()

        if self.manual_move_index < len(self.manual_move_history):
            self.current_player = self.manual_move_history[self.manual_move_index][1]
        elif self.manual_move_index > 0:
            last_stone = self.manual_move_history[self.manual_move_index - 1][1]
            self.current_player = Stone.WHITE if last_stone == Stone.BLACK else Stone.BLACK
        else:
            self.current_player = Stone.BLACK

        self.status_message = self.get_manual_status_text()

        if self.analysis_enabled:
            self.request_live_analysis()


    def mouse_to_point(
        self,
        mouse_pos: tuple[int, int],
    ) -> tuple[int, int] | None:
        mouse_x, mouse_y = mouse_pos
        closest_point: tuple[int, int] | None = None
        closest_distance = float("inf")

        for row in range(self.board.size):
            for col in range(self.board.size):
                px, py = self.point_to_pixels(row, col)
                distance = math.dist((mouse_x, mouse_y), (px, py))

                if distance < closest_distance:
                    closest_distance = distance
                    closest_point = (row, col)

        if closest_distance <= self.cell_size * 0.42:
            return closest_point

        return None

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        x = self.board_left + (col * self.cell_size)
        y = self.board_top + (row * self.cell_size)
        return round(x), round(y)

    def draw(self) -> None:
        self.screen.fill(self.outer_bg)

        if self.board_surface is not None:
            self.screen.blit(self.board_surface, (self.board_left, self.board_top))

        self.draw_coordinates()
        self.draw_hover_preview()
        self.draw_stones()
        self.draw_analysis_markers()
        self.draw_dropdown()
        self.draw_speed_slider()
        self.draw_status_text()
        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_control_bar()

    def draw_coordinates(self) -> None:
        columns = GO_COLUMNS[: self.board.size]

        # Column letters stay aligned directly above and below the board.
        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(
                top,
                (x - top.get_width() // 2, self.board_top - 44),
            )
            self.screen.blit(
                bottom,
                (x - bottom.get_width() // 2, self.board_bottom + 28),
            )

        # Row numbers now sit right next to the board edges.
        number_gap = 10

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            left_x = self.board_left - number_gap - left.get_width()
            right_x = self.board_right + number_gap

            self.screen.blit(
                left,
                (left_x, y - left.get_height() // 2),
            )
            self.screen.blit(
                right,
                (right_x, y - right.get_height() // 2),
            )

    def draw_hover_preview(self) -> None:
        if self.loaded_game is not None:
            return

        hover_point = self.mouse_to_point(pygame.mouse.get_pos())

        if hover_point is None:
            return

        row, col = hover_point
        coordinate = point_to_human(row, col, self.board.size)

        if self.board.get(coordinate) is not None:
            return

        x, y = self.point_to_pixels(row, col)

        preview = pygame.Surface(
            (self.stone_radius * 3, self.stone_radius * 3),
            pygame.SRCALPHA,
        )
        cx = preview.get_width() // 2
        cy = preview.get_height() // 2

        if self.current_player == Stone.BLACK:
            color = (30, 30, 30, 80)
        else:
            color = (250, 250, 250, 125)

        pygame.draw.circle(preview, color, (cx, cy), self.stone_radius)
        self.screen.blit(
            preview,
            (
                x - preview.get_width() // 2,
                y - preview.get_height() // 2,
            ),
        )

    def draw_stones(self) -> None:
        for row in range(self.board.size):
            for col in range(self.board.size):
                stone = self.board.grid[row][col]

                if stone is None:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK:
                    self.draw_black_stone(x, y)
                else:
                    self.draw_white_stone(x, y)

                if self.last_move == (row, col):
                    self.draw_last_move_marker(x, y, stone)

    def draw_shadow(self, x: int, y: int) -> None:
        shadow = pygame.Surface(
            (self.stone_radius * 4, self.stone_radius * 4),
            pygame.SRCALPHA,
        )
        cx = shadow.get_width() // 2
        cy = shadow.get_height() // 2

        pygame.draw.circle(
            shadow,
            (0, 0, 0, 50),
            (cx + 4, cy + 5),
            self.stone_radius + 1,
        )

        self.screen.blit(
            shadow,
            (
                x - shadow.get_width() // 2,
                y - shadow.get_height() // 2,
            ),
        )

    def draw_black_stone(self, x: int, y: int) -> None:
        self.draw_shadow(x, y)

        for radius in range(self.stone_radius, 0, -1):
            t = radius / self.stone_radius
            shade = int(
                self.black_core[0]
                + (70 - self.black_core[0]) * (1 - t) * 0.35
            )

            pygame.draw.circle(
                self.screen,
                (shade, shade, shade + 2),
                (x, y),
                radius,
            )

        pygame.draw.circle(self.screen, self.black_edge, (x, y), self.stone_radius, 2)

        highlight_x = x - int(self.stone_radius * 0.30)
        highlight_y = y - int(self.stone_radius * 0.32)

        pygame.draw.circle(
            self.screen,
            self.black_highlight,
            (highlight_x, highlight_y),
            max(4, int(self.stone_radius * 0.17)),
        )

    def draw_white_stone(self, x: int, y: int) -> None:
        self.draw_shadow(x, y)

        for radius in range(self.stone_radius, 0, -1):
            t = radius / self.stone_radius
            shade = int(225 + (22 * (1 - t)))

            pygame.draw.circle(
                self.screen,
                (shade, shade, shade),
                (x, y),
                radius,
            )

        pygame.draw.circle(self.screen, self.white_edge, (x, y), self.stone_radius, 2)

        highlight_x = x - int(self.stone_radius * 0.25)
        highlight_y = y - int(self.stone_radius * 0.28)

        pygame.draw.circle(
            self.screen,
            self.white_highlight,
            (highlight_x, highlight_y),
            max(4, int(self.stone_radius * 0.15)),
        )

    def draw_last_move_marker(self, x: int, y: int, stone: Stone) -> None:
        marker_radius = max(5, int(self.stone_radius * 0.34))

        if stone == Stone.BLACK:
            color = (245, 245, 245)
        else:
            color = (25, 25, 25)

        pygame.draw.circle(self.screen, color, (x, y), marker_radius, 3)

    def draw_dropdown(self) -> None:
        mouse_pos = pygame.mouse.get_pos()

        if self.dropdown_rect.collidepoint(mouse_pos):
            fill = self.button_hover
        else:
            fill = self.button_fill

        pygame.draw.rect(self.screen, fill, self.dropdown_rect, border_radius=6)

        label = f"{self.board.size} x {self.board.size}"
        label_surface = self.small_ui_font.render(label, True, self.button_text)

        self.screen.blit(
            label_surface,
            (
                self.dropdown_rect.centerx - label_surface.get_width() // 2,
                self.dropdown_rect.centery - label_surface.get_height() // 2,
            ),
        )

        if not self.dropdown_open:
            return

        for size, rect in self.dropdown_option_rects:
            if rect.collidepoint(mouse_pos):
                option_fill = self.button_hover
            else:
                option_fill = self.button_fill

            pygame.draw.rect(self.screen, option_fill, rect, border_radius=5)

            option_label = f"{size} x {size}"
            option_surface = self.small_ui_font.render(
                option_label,
                True,
                self.button_text,
            )

            self.screen.blit(
                option_surface,
                (
                    rect.centerx - option_surface.get_width() // 2,
                    rect.centery - option_surface.get_height() // 2,
                ),
            )

    def draw_speed_slider(self) -> None:
        label = f"{self.playback_speed:.2f}x"
        label_surface = self.small_ui_font.render(label, True, self.text_color)

        self.screen.blit(
            label_surface,
            (
                self.speed_slider_rect.left - label_surface.get_width() - 8,
                self.speed_slider_rect.centery - label_surface.get_height() // 2,
            ),
        )

        pygame.draw.rect(
            self.screen,
            self.line_color,
            self.speed_slider_rect,
            border_radius=5,
        )

        fraction = (
            (self.playback_speed - self.min_playback_speed)
            / (self.max_playback_speed - self.min_playback_speed)
        )

        knob_x = self.speed_slider_rect.left + int(
            fraction * self.speed_slider_rect.width
        )
        knob_y = self.speed_slider_rect.centery

        pygame.draw.circle(self.screen, self.button_fill, (knob_x, knob_y), 10)
        pygame.draw.circle(self.screen, self.line_color, (knob_x, knob_y), 10, 2)

    def draw_status_text(self) -> None:
        if self.loaded_game is not None:
            text = self.get_replay_status_text()
        elif self.status_message:
            text = self.status_message
        elif self.current_player == Stone.BLACK:
            text = "Black to move"
        else:
            text = "White to move"

        text_surface = self.small_ui_font.render(text, True, self.text_color)

        self.screen.blit(
            text_surface,
            (
                self.board_left,
                self.control_bar_rect.top - 23,
            ),
        )

    def draw_control_bar(self) -> None:
        pygame.draw.rect(self.screen, self.control_bar_color, self.control_bar_rect)

        labels = {
            "load": "SGF",
            "analysis": "ANALYZE ON" if self.analysis_enabled else "ANALYZE",
            "ai": "AI ON" if self.ai_enabled else "AI OFF",
            "beginning": "|<",
            "back": "<<",
            "play_pause": "PAUSE" if self.is_playing else "PLAY",
            "forward": ">>",
            "end": ">|",
        }

        for button_name, rect in self.button_rects.items():
            enabled = button_name in ("load", "analysis", "ai", "beginning", "back", "forward", "end", "play_pause") or self.loaded_game is not None
            self.draw_button(rect, labels[button_name], enabled)

    def draw_button(
        self,
        rect: pygame.Rect,
        label: str,
        enabled: bool,
    ) -> None:
        mouse_pos = pygame.mouse.get_pos()

        if not enabled:
            fill = self.button_disabled
        elif rect.collidepoint(mouse_pos):
            fill = self.button_hover
        else:
            fill = self.button_fill

        pygame.draw.rect(self.screen, fill, rect, border_radius=5)

        text = self.ui_font.render(label, True, self.button_text)

        self.screen.blit(
            text,
            (
                rect.centerx - text.get_width() // 2,
                rect.centery - text.get_height() // 2,
            ),
        )




    def toggle_live_analysis(self) -> None:
        self.analysis_enabled = not self.analysis_enabled

        if self.analysis_enabled:
            self.status_message = "Live KataGo analysis ON"
            print("[Go Sensei Board] Analysis button ON", flush=True)
            self.request_live_analysis()
        else:
            self.status_message = "Live KataGo analysis OFF"
            print("[Go Sensei Board] Analysis button OFF", flush=True)
            self.analysis_service.clear()
            self.analysis_state = LiveAnalysisState()

    def disable_live_analysis(self) -> None:
        self.analysis_enabled = False
        self.analysis_service.clear()
        self.analysis_state = LiveAnalysisState()

    def request_live_analysis(self) -> int | None:
        print(
            f"[Go Sensei Board] Sending current board to KataGo for {self.current_player.name}...",
            flush=True,
        )
        return self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.current_player,
        )

    def request_live_analysis_from_replay(self) -> None:
        print(
            f"[Go Sensei Board] Sending SGF replay position {self.move_index} to KataGo for {self.current_player.name}...",
            flush=True,
        )
        self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.current_player,
        )

    def get_stable_black_white_winrates(self) -> tuple[float | None, float | None]:
        result = self.analysis_state.latest_result

        if result is None or result.root_winrate_percent is None:
            return None, None

        # Anchor the display to Black/White only.
        # Do not flip this based on whose turn it is.
        black_winrate = result.root_winrate_percent
        white_winrate = 100.0 - black_winrate

        return black_winrate, white_winrate

    def get_stable_black_score_lead(self) -> float | None:
        result = self.analysis_state.latest_result

        if result is None or result.root_score_lead is None:
            return None

        # Anchor the display to Black/White only.
        # Positive = Black ahead. Negative = White ahead.
        return result.root_score_lead

    def get_analysis_recommendations(self, limit: int = 5):
        if not self.analysis_enabled:
            return []

        result = self.analysis_state.latest_result

        if result is None:
            return []

        recommendations = []

        for move in result.best_moves[:limit]:
            move_text = move.move

            if move_text.lower() == "pass":
                continue

            try:
                row, col = human_to_point(move_text, self.board.size)
            except ValueError:
                continue

            coordinate = point_to_human(row, col, self.board.size)

            if self.board.get(coordinate) is not None:
                continue

            recommendations.append((row, col, move))

        return recommendations

    def draw_analysis_markers(self) -> None:
        if not self.analysis_enabled:
            return

        result = self.analysis_state.latest_result

        if result is None:
            return

        try:
            jason_preferences = self.game_store.get_style_preferences(
                board_size=self.board.size,
                profile_name="Jason",
            )
        except Exception:
            jason_preferences = []

        try:
            cosmic_preferences = self.game_store.get_style_preferences(
                board_size=self.board.size,
                profile_name="Cosmic",
            )
        except Exception:
            cosmic_preferences = []

        lanes = build_display_move_lanes(
            result=result,
            board_size=self.board.size,
            style_preferences=jason_preferences,
            cosmic_preferences=cosmic_preferences,
        )

        for lane in lanes:
            try:
                row, col = human_to_point(lane.move, self.board.size)
            except ValueError:
                continue

            x, y = self.point_to_pixels(row, col)

            pygame.draw.circle(
                self.screen,
                lane.color,
                (x, y),
                max(13, self.cell_size // 3),
                4,
            )

            label_surface = self.small_ui_font.render(lane.label, True, (255, 255, 255))
            label_rect = label_surface.get_rect(center=(x, y))
            self.screen.blit(label_surface, label_rect)

    def draw_recommendation_marker(self, x: int, y: int, index: int) -> None:
        radius = max(13, int(self.stone_radius * 0.42))

        marker_surface = pygame.Surface(
            (radius * 3, radius * 3),
            pygame.SRCALPHA,
        )
        cx = marker_surface.get_width() // 2
        cy = marker_surface.get_height() // 2

        pygame.draw.circle(marker_surface, (38, 119, 255, 220), (cx, cy), radius)
        pygame.draw.circle(marker_surface, (255, 255, 255, 240), (cx, cy), radius, 2)

        label = self.small_ui_font.render(str(index), True, (255, 255, 255))
        marker_surface.blit(
            label,
            (
                cx - label.get_width() // 2,
                cy - label.get_height() // 2,
            ),
        )

        self.screen.blit(
            marker_surface,
            (
                x - marker_surface.get_width() // 2,
                y - marker_surface.get_height() // 2,
            ),
        )

    def draw_analysis_panel(self) -> None:
        panel_width = 390
        panel_height = 620

        panel_left = self.window_width - panel_width - 18
        panel_top = 80

        panel_rect = pygame.Rect(panel_left, panel_top, panel_width, panel_height)

        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill((22, 20, 18, 238))
        self.screen.blit(panel_surface, panel_rect.topleft)

        pygame.draw.rect(self.screen, (238, 205, 125), panel_rect, 2, border_radius=14)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        def add_text(value: str, font=None, color=(240, 240, 240), gap: int = 23) -> None:
            nonlocal y

            selected_font = font or self.small_ui_font
            surface = selected_font.render(value, True, color)
            self.screen.blit(surface, (x, y))
            y += gap

        def draw_card(title: str, height: int) -> pygame.Rect:
            nonlocal y

            card_rect = pygame.Rect(x - 5, y, panel_width - 28, height)
            card_surface = pygame.Surface((card_rect.width, card_rect.height), pygame.SRCALPHA)
            card_surface.fill((255, 255, 255, 24))
            self.screen.blit(card_surface, card_rect.topleft)

            pygame.draw.rect(self.screen, (255, 255, 255, 48), card_rect, 1, border_radius=10)

            title_surface = self.small_ui_font.render(title, True, (255, 225, 150))
            self.screen.blit(title_surface, (card_rect.left + 12, card_rect.top + 10))

            y = card_rect.top + 38
            return card_rect

        def end_card(card: pygame.Rect) -> None:
            nonlocal y
            y = card.bottom + 14

        title_surface = self.status_font.render("KataGo Analysis", True, (255, 225, 150))
        self.screen.blit(title_surface, (x, y))
        y += 34

        engine_color = (90, 235, 145) if self.analysis_enabled else (255, 120, 120)
        add_text("Engine: ON" if self.analysis_enabled else "Engine: OFF", color=engine_color)
        y += 4

        result = self.analysis_state.latest_result

        # Status card
        card = draw_card("Status", 94)

        if self.analysis_state.is_thinking:
            add_text("Thinking...", color=(90, 190, 255), gap=22)
        elif self.analysis_state.latest_error:
            add_text("Error", color=(255, 120, 120), gap=22)
        elif result is not None:
            add_text("Ready", color=(90, 235, 145), gap=22)
        else:
            add_text("Waiting for analysis", color=(220, 220, 220), gap=22)

        if self.analysis_state.latest_elapsed_seconds is not None:
            add_text(f"Last run: {self.analysis_state.latest_elapsed_seconds:.2f}s", color=(205, 205, 210), gap=22)
        else:
            add_text("Click ANALYZE to begin", color=(205, 205, 210), gap=22)

        end_card(card)

        # Winrate card
        card = draw_card("Black / White winrate", 128)

        black_winrate = None
        white_winrate = None

        if result is not None and result.root_winrate_percent is not None:
            if result.current_player == Stone.BLACK:
                black_winrate = result.root_winrate_percent
            else:
                black_winrate = 100.0 - result.root_winrate_percent

            white_winrate = 100.0 - black_winrate

        if black_winrate is None or white_winrate is None:
            add_text("No result yet", color=(215, 215, 215), gap=22)

            bar_rect = pygame.Rect(x, y + 8, panel_width - 42, 18)
            pygame.draw.rect(self.screen, (95, 95, 105), bar_rect, border_radius=9)
        else:
            add_text(f"Black: {black_winrate:.1f}%", gap=22)
            add_text(f"White: {white_winrate:.1f}%", gap=22)

            bar_rect = pygame.Rect(x, y + 4, panel_width - 42, 18)
            pygame.draw.rect(self.screen, (235, 235, 235), bar_rect, border_radius=9)

            black_width = int(bar_rect.width * (black_winrate / 100.0))
            black_rect = pygame.Rect(bar_rect.left, bar_rect.top, black_width, bar_rect.height)
            pygame.draw.rect(self.screen, (35, 35, 38), black_rect, border_radius=9)

            pygame.draw.rect(self.screen, (255, 230, 150), bar_rect, 1, border_radius=9)

        end_card(card)

        # Score card
        card = draw_card("Point estimate", 116)

        black_score = None

        if result is not None and result.root_score_lead is not None:
            if result.current_player == Stone.BLACK:
                black_score = result.root_score_lead
            else:
                black_score = -result.root_score_lead

        if black_score is None:
            add_text("Waiting for score estimate", color=(215, 215, 215), gap=22)
        else:
            add_text(f"Black: {black_score:+.2f} pts", gap=22)
            add_text(f"White: {-black_score:+.2f} pts", gap=22)

            if black_score > 0:
                add_text(f"Leader: Black by {abs(black_score):.2f}", color=(90, 235, 145), gap=22)
            elif black_score < 0:
                add_text(f"Leader: White by {abs(black_score):.2f}", color=(90, 235, 145), gap=22)
            else:
                add_text("Leader: Even", color=(90, 235, 145), gap=22)

        end_card(card)

        # Captures card
        card = draw_card("Captures", 116)

        add_text(f"Black captured: {self.black_captures}", gap=22)
        add_text(f"White captured: {self.white_captures}", gap=22)
        add_text(
            f"Stones removed — B:{self.white_captures} W:{self.black_captures}",
            color=(210, 210, 215),
            gap=22,
        )

        end_card(card)

    def start_move_coaching(
        self,
        played_move: str,
        player: Stone,
        before_result,
        baseline_completed_request_id: int,
    ) -> None:
        self.pending_coach_review = {
            "played_move": played_move,
            "player": player,
            "before_result": before_result,
            "baseline_completed_request_id": baseline_completed_request_id,
        }

        self.coach_title = "Coach Read"
        self.coach_lines = [
            f"Reviewing {player.name.title()} {played_move}...",
            "KataGo is comparing your move with the engine recommendation.",
        ]

        print("", flush=True)
        print(f"[Go Sensei Coach] Reviewing {player.name.title()} {played_move}...", flush=True)
        print("[Go Sensei Coach] Waiting for KataGo after-move analysis...", flush=True)
        print("", flush=True)

    def update_live_move_coaching(self) -> None:
        if self.pending_coach_review is None:
            return

        if self.analysis_state.latest_result is None:
            return

        baseline = self.pending_coach_review["baseline_completed_request_id"]

        if self.analysis_state.completed_request_id <= baseline:
            return

        coaching = make_live_move_coaching(
            played_move=self.pending_coach_review["played_move"],
            player=self.pending_coach_review["player"],
            before_result=self.pending_coach_review["before_result"],
            after_result=self.analysis_state.latest_result,
            board_size=self.board.size,
        )

        self.coach_title = coaching.title
        self.coach_lines = coaching.lines

        print("", flush=True)
        print(f"[Go Sensei Coach] {self.coach_title}", flush=True)
        for line in self.coach_lines:
            print(f"[Go Sensei Coach] {line}", flush=True)
        print("", flush=True)

        self.pending_coach_review = None


    def draw_coach_panel(self) -> None:
        panel_width = 390
        panel_height = 620

        # Match the left coach gap to the right KataGo gap.
        right_panel_width = 390
        right_panel_left = self.window_width - right_panel_width - 18
        side_gap = right_panel_left - self.board_right

        # Keep a healthy visual gap, close to your requested 5 cm.
        side_gap = max(95, side_gap)

        panel_left = self.board_left - panel_width - side_gap
        panel_top = 80

        # If it would go off-screen, keep it visible.
        if panel_left < 12:
            panel_left = 12

        panel_rect = pygame.Rect(panel_left, panel_top, panel_width, panel_height)

        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill((17, 22, 30, 242))
        self.screen.blit(panel_surface, panel_rect.topleft)

        pygame.draw.rect(self.screen, (115, 180, 255), panel_rect, 2, border_radius=16)

        x = panel_rect.left + 16
        y = panel_rect.top + 14

        title = getattr(self, "coach_title", "Go Sensei Coach")
        lines = getattr(
            self,
            "coach_lines",
            ["Click ANALYZE, wait for Ready, then make a move."],
        )

        header = self.status_font.render("Go Sensei Coach", True, (150, 200, 255))
        self.screen.blit(header, (x, y))
        y += 30

        subheader = self.small_ui_font.render("Clear feedback for your last move", True, (205, 215, 230))
        self.screen.blit(subheader, (x, y))
        y += 30

        y = self.draw_coach_card(
            title=title,
            lines=self.get_coach_lines_by_label(lines, "Verdict"),
            left=x,
            top=y,
            width=panel_width - 32,
            min_height=76,
            accent=(130, 210, 160),
        )

        y += 10

        y = self.draw_coach_card(
            title="Move",
            lines=self.get_coach_lines_by_label(lines, "Your move", "Engine idea"),
            left=x,
            top=y,
            width=panel_width - 32,
            min_height=100,
            accent=(150, 200, 255),
        )

        y += 10

        y = self.draw_coach_card(
            title="Impact",
            lines=self.get_coach_lines_by_label(lines, "Impact", "Engine gap", "Point gap", "Winrate", "Score", "After-move swing", "Score swing"),
            left=x,
            top=y,
            width=panel_width - 32,
            min_height=100,
            accent=(255, 210, 125),
        )

        y += 10

        remaining_height = panel_rect.bottom - y - 16

        if remaining_height > 110:
            lesson_lines = self.get_coach_lines_by_label(
                lines,
                "Main lesson",
                "Why it matters",
                "Ask yourself",
                "Engine line",
            )

            self.draw_coach_card(
                title="Lesson",
                lines=lesson_lines,
                left=x,
                top=y,
                width=panel_width - 32,
                min_height=remaining_height,
                accent=(190, 160, 255),
            )

    def draw_coach_wrapped_lines(
        self,
        lines: list[str],
        rect: pygame.Rect,
        font,
        color: tuple[int, int, int],
        line_gap: int = 20,
    ) -> None:
        y = rect.top

        for line in lines:
            if line == "":
                y += line_gap // 2
                continue

            words = line.split()
            current = ""

            for word in words:
                test = word if not current else current + " " + word

                if font.size(test)[0] <= rect.width:
                    current = test
                else:
                    if current:
                        surface = font.render(current, True, color)
                        self.screen.blit(surface, (rect.left, y))
                        y += line_gap

                        if y > rect.bottom - line_gap:
                            return

                    current = word

            if current:
                surface = font.render(current, True, color)
                self.screen.blit(surface, (rect.left, y))
                y += line_gap

                if y > rect.bottom - line_gap:
                    return

            y += 4

    def draw_coach_card(
        self,
        title: str,
        lines: list[str],
        left: int,
        top: int,
        width: int,
        min_height: int,
        accent: tuple[int, int, int],
    ) -> int:
        if not lines:
            lines = ["Waiting for move feedback..."]

        card_rect = pygame.Rect(left, top, width, min_height)

        card_surface = pygame.Surface((card_rect.width, card_rect.height), pygame.SRCALPHA)
        card_surface.fill((255, 255, 255, 24))
        self.screen.blit(card_surface, card_rect.topleft)

        pygame.draw.rect(self.screen, (255, 255, 255, 45), card_rect, 1, border_radius=12)
        pygame.draw.line(
            self.screen,
            accent,
            (card_rect.left + 10, card_rect.top + 10),
            (card_rect.left + 10, card_rect.bottom - 10),
            3,
        )

        title_surface = self.small_ui_font.render(title, True, accent)
        self.screen.blit(title_surface, (card_rect.left + 20, card_rect.top + 10))

        body_rect = pygame.Rect(
            card_rect.left + 20,
            card_rect.top + 36,
            card_rect.width - 34,
            card_rect.height - 44,
        )

        self.draw_coach_wrapped_lines(
            lines=lines,
            rect=body_rect,
            font=self.small_ui_font,
            color=(235, 238, 242),
            line_gap=20,
        )

        return card_rect.bottom

    def get_coach_lines_by_label(self, lines: list[str], *labels: str) -> list[str]:
        selected: list[str] = []

        for line in lines:
            for label in labels:
                prefix = f"{label}:"

                if line.startswith(prefix):
                    selected.append(line.replace(prefix, "").strip())
                    break

        return selected

    def record_current_move_to_database(
        self,
        coordinate: str,
        player: Stone,
        captured_count: int,
    ) -> None:
        try:
            move_number = getattr(self, "manual_move_index", 0)

            self.game_store.record_move(
                game_id=self.current_database_game_id,
                move_number=move_number,
                player=player,
                coordinate=coordinate,
                captured_count=captured_count,
                board_size=self.board.size,
            )

            print(
                f"[Go Sensei Database] Saved move {move_number}: {player.name} {coordinate}",
                flush=True,
            )
        except Exception as error:
            print(f"[Go Sensei Database] Could not save move: {error}", flush=True)

    def autosave_current_manual_game(self) -> None:
        try:
            if not hasattr(self, "manual_move_history"):
                return

            if not self.manual_move_history:
                return

            self.last_autosave_path = self.game_store.write_autosave_sgf(
                moves=self.manual_move_history,
                board_size=self.board.size,
                game_id=self.current_database_game_id,
            )

            print(
                f"[Go Sensei SGF] Autosaved current game to {self.last_autosave_path}",
                flush=True,
            )
        except Exception as error:
            print(f"[Go Sensei SGF] Could not autosave SGF: {error}", flush=True)

    def toggle_ai_opponent(self) -> None:
        self.ai_enabled = not self.ai_enabled
        self.ai_player = Stone.WHITE

        if self.ai_enabled:
            self.status_message = "AI opponent ON — You are Black, AI is White"
            print("[Go Sensei AI] AI opponent ON. Human: BLACK. AI: WHITE.", flush=True)
            self.maybe_request_ai_move()
        else:
            self.status_message = "AI opponent OFF"
            self.ai_pending_request_id = None
            self.ai_is_thinking = False
            print("[Go Sensei AI] AI opponent OFF.", flush=True)

    def maybe_request_ai_move(self) -> None:
        if not self.ai_enabled:
            return

        if self.loaded_game is not None:
            return

        if self.current_player != self.ai_player:
            return

        if self.ai_pending_request_id is not None:
            return

        print(
            f"[Go Sensei AI] Asking KataGo for {self.ai_player.name}'s move...",
            flush=True,
        )

        self.ai_is_thinking = True
        self.status_message = "AI is thinking..."

        self.ai_pending_request_id = self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.ai_player,
        )

    def update_ai_move(self) -> None:
        if not self.ai_enabled:
            return

        if self.ai_pending_request_id is None:
            return

        if self.analysis_state.latest_result is None:
            return

        if self.analysis_state.completed_request_id < self.ai_pending_request_id:
            return

        result = self.analysis_state.latest_result
        ai_move = choose_ai_move(
            board=self.board,
            player=self.ai_player,
            result=result,
        )

        self.ai_pending_request_id = None
        self.ai_is_thinking = False

        if ai_move is None:
            self.status_message = "AI could not find a legal move"
            print("[Go Sensei AI] Could not find a legal move.", flush=True)
            return

        self.play_ai_move(ai_move)

    def play_ai_move(self, coordinate: str) -> None:
        ai_stone = self.ai_player

        try:
            captured_count = self.board.place_stone(coordinate, ai_stone)
        except ValueError:
            self.status_message = f"AI tried illegal move: {coordinate}"
            print(f"[Go Sensei AI] Illegal AI move skipped: {coordinate}", flush=True)
            return

        if hasattr(self, "manual_move_history"):
            if self.manual_move_index < len(self.manual_move_history):
                self.manual_move_history = self.manual_move_history[: self.manual_move_index]

            self.manual_move_history.append((coordinate, ai_stone))
            self.manual_move_index += 1

        if hasattr(self, "record_current_move_to_database"):
            self.record_current_move_to_database(
                coordinate=coordinate,
                player=ai_stone,
                captured_count=captured_count,
            )

        if hasattr(self, "autosave_current_manual_game"):
            self.autosave_current_manual_game()

        if ai_stone == Stone.BLACK:
            self.black_captures += captured_count
        else:
            self.white_captures += captured_count

        try:
            row, col = human_to_point(coordinate, self.board.size)
            self.last_move = (row, col)
        except ValueError:
            self.last_move = None

        self.play_stone_sound()
        self.ai_last_move = coordinate
        self.status_message = f"AI played {coordinate}"

        print(f"[Go Sensei AI] AI played {ai_stone.name} {coordinate}", flush=True)

        self.switch_turn()

        if self.analysis_enabled:
            self.request_live_analysis()

    def draw_ai_status_badge(self) -> None:
        badge_width = 210
        badge_height = 34
        badge_left = self.board_left
        badge_top = self.window_height - 82

        badge_rect = pygame.Rect(badge_left, badge_top, badge_width, badge_height)

        badge_surface = pygame.Surface((badge_width, badge_height), pygame.SRCALPHA)

        if self.ai_enabled:
            badge_surface.fill((20, 80, 45, 220))
            label = "AI ON — You: Black"
            color = (170, 255, 200)
        else:
            badge_surface.fill((45, 45, 50, 210))
            label = "AI OFF — Press I"
            color = (230, 230, 235)

        self.screen.blit(badge_surface, badge_rect.topleft)
        pygame.draw.rect(self.screen, (240, 240, 240), badge_rect, 1, border_radius=8)

        label_surface = self.small_ui_font.render(label, True, color)
        self.screen.blit(
            label_surface,
            (
                badge_rect.left + 12,
                badge_rect.centery - label_surface.get_height() // 2,
            ),
        )


    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        try:
            screen_width = self.screen.get_width()
            screen_height = self.screen.get_height()

            self.screen.fill((224, 184, 86))

            board_size = self.board.size

            # Rebuild a safe centered board layout.
            panel_width = 390
            side_gap = 95
            top_margin = 65
            bottom_margin = 125

            available_width = screen_width - (panel_width * 2) - (side_gap * 2) - 80
            available_height = screen_height - top_margin - bottom_margin

            board_pixel_size = min(available_width, available_height)

            if board_pixel_size < 360:
                board_pixel_size = min(screen_width - 80, screen_height - 150)

            board_pixel_size = int(board_pixel_size)
            board_left = int((screen_width - board_pixel_size) / 2)
            board_top = top_margin
            board_right = board_left + board_pixel_size
            board_bottom = board_top + board_pixel_size

            cell_size = board_pixel_size / (board_size - 1)

            self.board_left = board_left
            self.board_top = board_top
            self.board_right = board_right
            self.board_bottom = board_bottom
            self.cell_size = cell_size

            def point_to_pixels(row: int, col: int) -> tuple[int, int]:
                return (
                    int(board_left + col * cell_size),
                    int(board_top + row * cell_size),
                )

            # Board background
            board_padding = 24
            board_rect = pygame.Rect(
                board_left - board_padding,
                board_top - board_padding,
                board_pixel_size + board_padding * 2,
                board_pixel_size + board_padding * 2,
            )

            pygame.draw.rect(self.screen, (219, 174, 74), board_rect)
            pygame.draw.rect(self.screen, (110, 78, 28), board_rect, 2)

            # Grid
            grid_color = (65, 45, 20)

            for row in range(board_size):
                start_x, y = point_to_pixels(row, 0)
                end_x, _ = point_to_pixels(row, board_size - 1)
                pygame.draw.line(self.screen, grid_color, (start_x, y), (end_x, y), 1)

            for col in range(board_size):
                x, start_y = point_to_pixels(0, col)
                _, end_y = point_to_pixels(board_size - 1, col)
                pygame.draw.line(self.screen, grid_color, (x, start_y), (x, end_y), 1)

            # Star points
            if board_size == 19:
                star_points = [3, 9, 15]
            elif board_size == 13:
                star_points = [3, 6, 9]
            elif board_size == 9:
                star_points = [2, 4, 6]
            else:
                star_points = []

            for row in star_points:
                for col in star_points:
                    x, y = point_to_pixels(row, col)
                    pygame.draw.circle(self.screen, (30, 20, 10), (x, y), 4)

            # Fonts
            coord_font = getattr(self, "coord_font", pygame.font.SysFont("arial", 22, bold=True))
            small_font = getattr(self, "small_ui_font", pygame.font.SysFont("arial", 15, bold=True))
            text_color = getattr(self, "text_color", (20, 20, 20))

            # Coordinates
            letters = "ABCDEFGHJKLMNOPQRST"[:board_size]

            for col, label in enumerate(letters):
                x, _ = point_to_pixels(0, col)

                top = coord_font.render(label, True, text_color)
                bottom = coord_font.render(label, True, text_color)

                self.screen.blit(top, (x - top.get_width() // 2, board_top - 42))
                self.screen.blit(bottom, (x - bottom.get_width() // 2, board_bottom + 28))

            for row in range(board_size):
                label = str(board_size - row)
                _, y = point_to_pixels(row, 0)

                left = coord_font.render(label, True, text_color)
                right = coord_font.render(label, True, text_color)

                self.screen.blit(left, (board_left - 10 - left.get_width(), y - left.get_height() // 2))
                self.screen.blit(right, (board_right + 10, y - right.get_height() // 2))

            # Stones
            stone_radius = max(10, int(cell_size * 0.42))

            for row in range(board_size):
                for col in range(board_size):
                    coordinate = point_to_human(row, col, board_size)

                    try:
                        stone = self.board.get(coordinate)
                    except Exception:
                        stone = None

                    if stone is None:
                        continue

                    stone_name = getattr(stone, "name", str(stone)).upper()

                    if "EMPTY" in stone_name:
                        continue

                    x, y = point_to_pixels(row, col)

                    if stone == Stone.BLACK or "BLACK" in stone_name:
                        pygame.draw.circle(self.screen, (22, 22, 25), (x, y), stone_radius)
                        pygame.draw.circle(self.screen, (65, 65, 70), (x - 5, y - 5), max(3, stone_radius // 4))
                    elif stone == Stone.WHITE or "WHITE" in stone_name:
                        pygame.draw.circle(self.screen, (235, 235, 230), (x, y), stone_radius)
                        pygame.draw.circle(self.screen, (150, 150, 150), (x, y), stone_radius, 2)
                        pygame.draw.circle(self.screen, (255, 255, 255), (x - 5, y - 5), max(3, stone_radius // 4))

            # Last move marker
            if getattr(self, "last_move", None) is not None:
                row, col = self.last_move
                x, y = point_to_pixels(row, col)
                pygame.draw.circle(self.screen, (80, 150, 255), (x, y), max(6, stone_radius // 3), 3)

            # Analysis markers
            self.point_to_pixels = point_to_pixels

            for method_name in [
                "draw_analysis_markers",
                "draw_coach_panel",
                "draw_analysis_panel",
                "draw_size_selector",
                "draw_speed_slider",
                "draw_bottom_controls",
                "draw_replay_controls",
                "draw_controls",
                "draw_status",
                "draw_status_bar",
                "draw_ai_status_badge",
            ]:
                method = getattr(self, method_name, None)

                if callable(method):
                    try:
                        method()
                    except Exception as error:
                        print(f"[Go Sensei Draw] Skipped {method_name}: {error}", flush=True)

            pygame.display.flip()

        except Exception as error:
            self.screen.fill((40, 0, 0))

            font = pygame.font.SysFont("arial", 20, bold=True)
            message = f"Draw error: {error}"
            surface = font.render(message, True, (255, 220, 220))
            self.screen.blit(surface, (30, 30))

            pygame.display.flip()
            print(f"[Go Sensei Draw Error] {error}", flush=True)


    def run(self) -> None:
        import pygame

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if hasattr(self, "shutdown"):
                        self.shutdown()

                    pygame.quit()
                    raise SystemExit

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.dragging_speed_slider = False

                if event.type == pygame.MOUSEMOTION and getattr(self, "dragging_speed_slider", False):
                    self.update_speed_from_mouse(event.pos[0])

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_i:
                        if hasattr(self, "toggle_ai_opponent"):
                            self.toggle_ai_opponent()
                        continue

                    if event.key == pygame.K_r:
                        self.reset_board()
                        continue

                    if event.key == pygame.K_a:
                        self.toggle_live_analysis()
                        continue

            if hasattr(self, "update_auto_replay"):
                self.update_auto_replay()

            if hasattr(self, "analysis_service"):
                self.analysis_state = self.analysis_service.get_state()

            if hasattr(self, "update_ai_move"):
                self.update_ai_move()

            if hasattr(self, "update_live_move_coaching"):
                self.update_live_move_coaching()

            self.draw()
            self.clock.tick(60)

    def recalculate_safe_layout(self) -> None:
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()

        self.safe_panel_width = 360
        self.safe_panel_margin = 24
        self.safe_panel_gap = 38
        self.safe_panel_top = 78
        self.safe_panel_height = min(620, screen_height - 160)

        self.safe_left_panel_left = self.safe_panel_margin
        self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

        board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
        board_area_right = self.safe_right_panel_left - self.safe_panel_gap
        board_area_width = board_area_right - board_area_left

        top_margin = 58
        bottom_margin = 138
        board_area_height = screen_height - top_margin - bottom_margin

        board_pixel_size = min(board_area_width, board_area_height)

        if board_pixel_size < 360:
            # If the window is too narrow, shrink panels slightly and keep everything visible.
            self.safe_panel_width = 300
            self.safe_panel_gap = 24
            self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin
            board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
            board_area_right = self.safe_right_panel_left - self.safe_panel_gap
            board_area_width = board_area_right - board_area_left
            board_pixel_size = min(board_area_width, board_area_height)

        board_pixel_size = max(300, int(board_pixel_size))

        self.board_left = int(board_area_left + (board_area_width - board_pixel_size) / 2)
        self.board_top = top_margin
        self.board_right = self.board_left + board_pixel_size
        self.board_bottom = self.board_top + board_pixel_size
        self.cell_size = board_pixel_size / (self.board.size - 1)

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        return (
            int(self.board_left + col * self.cell_size),
            int(self.board_top + row * self.cell_size),
        )

    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        self.recalculate_safe_layout()
        self.screen.fill((224, 184, 86))

        board_size = self.board.size

        # Board background
        board_padding = 24
        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )
        pygame.draw.rect(self.screen, (219, 174, 74), board_rect)
        pygame.draw.rect(self.screen, (110, 78, 28), board_rect, 2)

        # Grid
        grid_color = (65, 45, 20)

        for row in range(board_size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, board_size - 1)
            pygame.draw.line(self.screen, grid_color, (start_x, y), (end_x, y), 1)

        for col in range(board_size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(board_size - 1, col)
            pygame.draw.line(self.screen, grid_color, (x, start_y), (x, end_y), 1)

        # Star points
        if board_size == 19:
            star_points = [3, 9, 15]
        elif board_size == 13:
            star_points = [3, 6, 9]
        elif board_size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, (30, 20, 10), (x, y), 4)

        # Coordinates
        self.draw_coordinates()

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(board_size):
            for col in range(board_size):
                coordinate = point_to_human(row, col, board_size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                stone_name = getattr(stone, "name", str(stone)).upper()

                if "EMPTY" in stone_name:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK or "BLACK" in stone_name:
                    pygame.draw.circle(self.screen, (22, 22, 25), (x, y), stone_radius)
                    pygame.draw.circle(self.screen, (65, 65, 70), (x - 5, y - 5), max(3, stone_radius // 4))
                elif stone == Stone.WHITE or "WHITE" in stone_name:
                    pygame.draw.circle(self.screen, (235, 235, 230), (x, y), stone_radius)
                    pygame.draw.circle(self.screen, (150, 150, 150), (x, y), stone_radius, 2)
                    pygame.draw.circle(self.screen, (255, 255, 255), (x - 5, y - 5), max(3, stone_radius // 4))

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (80, 150, 255), (x, y), max(6, stone_radius // 3), 3)

        # Analysis colored markers
        if hasattr(self, "draw_analysis_markers"):
            try:
                self.draw_analysis_markers()
            except Exception as error:
                print(f"[Go Sensei Draw] Analysis markers skipped: {error}", flush=True)

        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_bottom_controls()
        self.draw_size_selector()

        pygame.display.flip()

    def draw_coordinates(self) -> None:
        import pygame

        columns = "ABCDEFGHJKLMNOPQRST"[: self.board.size]
        number_gap = 10

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, self.board_top - 42))
            self.screen.blit(bottom, (x - bottom.get_width() // 2, self.board_bottom + 28))

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (self.board_left - number_gap - left.get_width(), y - left.get_height() // 2))
            self.screen.blit(right, (self.board_right + number_gap, y - right.get_height() // 2))

    def draw_coach_panel(self) -> None:
        import pygame

        panel_width = self.safe_panel_width
        panel_height = self.safe_panel_height
        panel_left = self.safe_left_panel_left
        panel_top = self.safe_panel_top

        panel_rect = pygame.Rect(panel_left, panel_top, panel_width, panel_height)

        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill((17, 22, 30, 242))
        self.screen.blit(panel_surface, panel_rect.topleft)

        pygame.draw.rect(self.screen, (115, 180, 255), panel_rect, 2, border_radius=16)

        x = panel_rect.left + 16
        y = panel_rect.top + 14

        title = getattr(self, "coach_title", "Coach Read")
        lines = getattr(self, "coach_lines", ["Waiting for move feedback..."])

        header = self.status_font.render("Go Sensei Coach", True, (150, 200, 255))
        self.screen.blit(header, (x, y))
        y += 30

        subheader = self.small_ui_font.render("Clear feedback for your last move", True, (205, 215, 230))
        self.screen.blit(subheader, (x, y))
        y += 30

        y = self.draw_coach_card(title, self.get_coach_lines_by_label(lines, "Verdict"), x, y, panel_width - 32, 76, (130, 210, 160))
        y += 10
        y = self.draw_coach_card("Move", self.get_coach_lines_by_label(lines, "Your move", "Engine idea"), x, y, panel_width - 32, 100, (150, 200, 255))
        y += 10
        y = self.draw_coach_card("Impact", self.get_coach_lines_by_label(lines, "Impact", "Engine gap", "Point gap", "Winrate", "Score", "After-move swing", "Score swing"), x, y, panel_width - 32, 100, (255, 210, 125))
        y += 10

        remaining_height = panel_rect.bottom - y - 16

        if remaining_height > 110:
            lesson_lines = self.get_coach_lines_by_label(lines, "Main lesson", "Why it matters", "Ask yourself", "Engine line")
            self.draw_coach_card("Lesson", lesson_lines, x, y, panel_width - 32, remaining_height, (190, 160, 255))

    def draw_analysis_panel(self) -> None:
        import pygame
        from app.core.stone import Stone

        panel_width = self.safe_panel_width
        panel_height = self.safe_panel_height
        panel_left = self.safe_right_panel_left
        panel_top = self.safe_panel_top

        panel_rect = pygame.Rect(panel_left, panel_top, panel_width, panel_height)

        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill((22, 20, 18, 238))
        self.screen.blit(panel_surface, panel_rect.topleft)

        pygame.draw.rect(self.screen, (238, 205, 125), panel_rect, 2, border_radius=14)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        def add_text(value: str, color=(240, 240, 240), gap: int = 23) -> None:
            nonlocal y
            surface = self.small_ui_font.render(value, True, color)
            self.screen.blit(surface, (x, y))
            y += gap

        def draw_card(title: str, height: int) -> pygame.Rect:
            nonlocal y
            card_rect = pygame.Rect(x - 5, y, panel_width - 28, height)
            card_surface = pygame.Surface((card_rect.width, card_rect.height), pygame.SRCALPHA)
            card_surface.fill((255, 255, 255, 24))
            self.screen.blit(card_surface, card_rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 48), card_rect, 1, border_radius=10)

            title_surface = self.small_ui_font.render(title, True, (255, 225, 150))
            self.screen.blit(title_surface, (card_rect.left + 12, card_rect.top + 10))

            y = card_rect.top + 38
            return card_rect

        def end_card(card: pygame.Rect) -> None:
            nonlocal y
            y = card.bottom + 14

        title_surface = self.status_font.render("KataGo Analysis", True, (255, 225, 150))
        self.screen.blit(title_surface, (x, y))
        y += 34

        engine_color = (90, 235, 145) if getattr(self, "analysis_enabled", False) else (255, 120, 120)
        add_text("Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF", color=engine_color)
        y += 4

        result = self.analysis_state.latest_result

        card = draw_card("Status", 94)

        if self.analysis_state.is_thinking:
            add_text("Thinking...", color=(90, 190, 255))
        elif self.analysis_state.latest_error:
            add_text("Error", color=(255, 120, 120))
        elif result is not None:
            add_text("Ready", color=(90, 235, 145))
        else:
            add_text("Waiting for analysis", color=(220, 220, 220))

        if self.analysis_state.latest_elapsed_seconds is not None:
            add_text(f"Last run: {self.analysis_state.latest_elapsed_seconds:.2f}s", color=(205, 205, 210))
        else:
            add_text("Click ANALYZE to begin", color=(205, 205, 210))

        end_card(card)

        card = draw_card("Black / White winrate", 128)

        black_winrate = None
        white_winrate = None

        if result is not None and result.root_winrate_percent is not None:
            if result.current_player == Stone.BLACK:
                black_winrate = result.root_winrate_percent
            else:
                black_winrate = 100.0 - result.root_winrate_percent

            white_winrate = 100.0 - black_winrate

        if black_winrate is None:
            add_text("No result yet", color=(215, 215, 215))
            bar_rect = pygame.Rect(x, y + 8, panel_width - 42, 18)
            pygame.draw.rect(self.screen, (95, 95, 105), bar_rect, border_radius=9)
        else:
            add_text(f"Black: {black_winrate:.1f}%")
            add_text(f"White: {white_winrate:.1f}%")

            bar_rect = pygame.Rect(x, y + 4, panel_width - 42, 18)
            pygame.draw.rect(self.screen, (235, 235, 235), bar_rect, border_radius=9)

            black_width = int(bar_rect.width * (black_winrate / 100.0))
            black_rect = pygame.Rect(bar_rect.left, bar_rect.top, black_width, bar_rect.height)
            pygame.draw.rect(self.screen, (35, 35, 38), black_rect, border_radius=9)
            pygame.draw.rect(self.screen, (255, 230, 150), bar_rect, 1, border_radius=9)

        end_card(card)

        card = draw_card("Point estimate", 116)

        black_score = None

        if result is not None and result.root_score_lead is not None:
            if result.current_player == Stone.BLACK:
                black_score = result.root_score_lead
            else:
                black_score = -result.root_score_lead

        if black_score is None:
            add_text("Waiting for score estimate", color=(215, 215, 215))
        else:
            add_text(f"Black: {black_score:+.2f} pts")
            add_text(f"White: {-black_score:+.2f} pts")

            if black_score > 0:
                add_text(f"Leader: Black by {abs(black_score):.2f}", color=(90, 235, 145))
            elif black_score < 0:
                add_text(f"Leader: White by {abs(black_score):.2f}", color=(90, 235, 145))
            else:
                add_text("Leader: Even", color=(90, 235, 145))

        end_card(card)

        card = draw_card("Captures", 116)
        add_text(f"Black captured: {getattr(self, 'black_captures', 0)}")
        add_text(f"White captured: {getattr(self, 'white_captures', 0)}")
        add_text(f"Stones removed — B:{getattr(self, 'white_captures', 0)} W:{getattr(self, 'black_captures', 0)}", color=(210, 210, 215))
        end_card(card)

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 52
        h = 38
        gap = 6

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", "AI ON" if getattr(self, "ai_enabled", False) else "AI OFF"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 20 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 10

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            color = (72, 72, 76)

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                color = (70, 105, 85)

            if name == "ai" and getattr(self, "ai_enabled", False):
                color = (75, 110, 75)

            pygame.draw.rect(self.screen, color, rect, border_radius=6)
            pygame.draw.rect(self.screen, (125, 125, 130), rect, 1, border_radius=6)

            text_surface = self.status_font.render(label, True, (235, 235, 235))
            self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

            x += w + gap

    def draw_size_selector(self) -> None:
        import pygame

        # Top-right board-size button
        rect = pygame.Rect(self.screen.get_width() - 118, 12, 96, 36)
        self.size_selector_rect = rect

        pygame.draw.rect(self.screen, (70, 70, 74), rect, border_radius=7)
        pygame.draw.rect(self.screen, (135, 135, 140), rect, 1, border_radius=7)

        label = f"{self.board.size} x {self.board.size}"
        surface = self.small_ui_font.render(label, True, (240, 240, 240))
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        # 1. Board-size selector
        size_rect = getattr(self, "size_selector_rect", None)

        if size_rect is not None and size_rect.collidepoint(mouse_pos):
            self.cycle_board_size()
            return

        # 2. Bottom buttons
        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                self.handle_button_click(button_name)
                return

        # 3. Speed slider, if the old app still has it
        speed_rect = getattr(self, "speed_slider_rect", None)

        if speed_rect is not None and speed_rect.collidepoint(mouse_pos):
            self.dragging_speed_slider = True

            if hasattr(self, "update_speed_from_mouse"):
                self.update_speed_from_mouse(mouse_pos[0])

            return

        # 4. Board click
        self.handle_board_click(mouse_pos)

    def handle_button_click(self, button_name: str) -> None:
        print(f"[Go Sensei UI] Button clicked: {button_name}", flush=True)

        if button_name == "load":
            self.load_sgf_from_dialog()
            return

        if button_name == "analysis":
            self.toggle_live_analysis()
            return

        if button_name == "ai":
            if hasattr(self, "toggle_ai_opponent"):
                self.toggle_ai_opponent()
            else:
                print("[Go Sensei UI] AI opponent is not installed yet.", flush=True)
            return

        # Manual mode: undo/redo through move history
        if getattr(self, "loaded_game", None) is None:
            if button_name == "beginning":
                if hasattr(self, "go_to_manual_beginning"):
                    self.go_to_manual_beginning()
                else:
                    self.set_manual_position_safe(0)
                return

            if button_name == "back":
                if hasattr(self, "step_manual_back"):
                    self.step_manual_back()
                else:
                    self.set_manual_position_safe(max(0, getattr(self, "manual_move_index", 0) - 1))
                return

            if button_name == "play_pause":
                self.status_message = "Manual mode: use << and >> for undo/redo"
                return

            if button_name == "forward":
                if hasattr(self, "step_manual_forward"):
                    self.step_manual_forward(play_sound=True)
                else:
                    self.set_manual_position_safe(getattr(self, "manual_move_index", 0) + 1)
                return

            if button_name == "end":
                if hasattr(self, "go_to_manual_end"):
                    self.go_to_manual_end()
                else:
                    self.set_manual_position_safe(len(getattr(self, "manual_move_history", [])))
                return

        # SGF replay mode
        if button_name == "beginning":
            if hasattr(self, "go_to_beginning"):
                self.go_to_beginning()
            else:
                self.set_replay_position_safe(0)
            return

        if button_name == "back":
            if hasattr(self, "step_back"):
                self.step_back()
            else:
                self.set_replay_position_safe(max(0, getattr(self, "move_index", 0) - 1))
            return

        if button_name == "play_pause":
            if hasattr(self, "toggle_playback"):
                self.toggle_playback()
            else:
                self.is_playing = not getattr(self, "is_playing", False)
            return

        if button_name == "forward":
            if hasattr(self, "step_forward"):
                self.step_forward(play_sound=True)
            else:
                self.set_replay_position_safe(getattr(self, "move_index", 0) + 1)
            return

        if button_name == "end":
            if hasattr(self, "go_to_end"):
                self.go_to_end()
            else:
                loaded_game = getattr(self, "loaded_game", None)
                if loaded_game is not None:
                    self.set_replay_position_safe(len(loaded_game.moves))
            return

    def cycle_board_size(self) -> None:
        current_size = self.board.size

        if current_size == 19:
            new_size = 13
        elif current_size == 13:
            new_size = 9
        else:
            new_size = 19

        self.change_board_size_safe(new_size)

    def change_board_size_safe(self, new_size: int) -> None:
        from app.core.board import Board
        from app.core.stone import Stone

        print(f"[Go Sensei UI] Changing board size to {new_size}x{new_size}", flush=True)

        self.board = Board(size=new_size)
        self.current_player = Stone.BLACK

        self.loaded_game = None
        self.loaded_sgf_path = None
        self.move_index = 0
        self.is_playing = False

        self.black_captures = 0
        self.white_captures = 0
        self.last_move = None

        self.manual_move_history = []
        self.manual_move_index = 0

        if hasattr(self, "game_store"):
            try:
                self.current_database_game_id = self.game_store.start_game(board_size=new_size)
            except Exception as error:
                print(f"[Go Sensei Database] Could not start new game: {error}", flush=True)

        self.status_message = f"Board changed to {new_size}x{new_size}"

        # Clear pending AI request when board changes.
        if hasattr(self, "ai_pending_request_id"):
            self.ai_pending_request_id = None

        if hasattr(self, "ai_is_thinking"):
            self.ai_is_thinking = False

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def toggle_live_analysis(self) -> None:
        self.analysis_enabled = not getattr(self, "analysis_enabled", False)

        if self.analysis_enabled:
            print("[Go Sensei Board] Analysis button ON", flush=True)
            self.status_message = "Analysis ON"
            self.request_live_analysis()
        else:
            print("[Go Sensei Board] Analysis button OFF", flush=True)
            self.status_message = "Analysis OFF"

    def request_live_analysis(self) -> int | None:
        print(
            f"[Go Sensei Board] Sending current board to KataGo for {self.current_player.name}...",
            flush=True,
        )

        return self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.current_player,
        )

    def load_sgf_from_dialog(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog

            from app.core.sgf import load_sgf_file

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            path = filedialog.askopenfilename(
                title="Open SGF file",
                filetypes=[
                    ("SGF files", "*.sgf"),
                    ("All files", "*.*"),
                ],
            )

            root.destroy()

            if not path:
                self.status_message = "SGF load cancelled"
                return

            game = load_sgf_file(path)

            self.loaded_game = game
            self.loaded_sgf_path = path
            self.move_index = 0
            self.is_playing = False
            self.manual_move_history = []
            self.manual_move_index = 0

            if hasattr(self, "set_replay_position"):
                self.set_replay_position(0)
            else:
                self.set_replay_position_safe(0)

            self.status_message = f"Loaded SGF: {path}"
            print(f"[Go Sensei SGF] Loaded {path}", flush=True)

        except Exception as error:
            self.status_message = f"Could not load SGF: {error}"
            print(f"[Go Sensei SGF] Could not load SGF: {error}", flush=True)

    def set_replay_position_safe(self, target_index: int) -> None:
        from app.core.sgf import build_board_at_move
        from app.core.stone import Stone

        game = getattr(self, "loaded_game", None)

        if game is None:
            return

        target_index = max(0, min(target_index, len(game.moves)))

        position = build_board_at_move(game, target_index)

        self.board = position.board
        self.move_index = target_index
        self.black_captures = getattr(position, "black_captures", 0)
        self.white_captures = getattr(position, "white_captures", 0)

        if target_index > 0:
            last_move = game.moves[target_index - 1]

            if last_move.coordinate is not None:
                try:
                    from app.core.coordinates import human_to_point
                    self.last_move = human_to_point(last_move.coordinate, self.board.size)
                except Exception:
                    self.last_move = None
        else:
            self.last_move = None

        if target_index < len(game.moves):
            self.current_player = game.moves[target_index].color
        elif target_index > 0:
            last_color = game.moves[target_index - 1].color
            self.current_player = Stone.WHITE if last_color == Stone.BLACK else Stone.BLACK
        else:
            self.current_player = Stone.BLACK

        self.status_message = f"SGF move {target_index}/{len(game.moves)}"

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def set_manual_position_safe(self, target_index: int) -> None:
        from app.core.board import Board
        from app.core.coordinates import human_to_point
        from app.core.stone import Stone

        history = getattr(self, "manual_move_history", [])
        target_index = max(0, min(target_index, len(history)))

        board_size = self.board.size
        self.board = Board(size=board_size)
        self.black_captures = 0
        self.white_captures = 0
        self.last_move = None

        for coordinate, stone in history[:target_index]:
            captured_count = self.board.place_stone(coordinate, stone)

            if stone == Stone.BLACK:
                self.black_captures += captured_count
            else:
                self.white_captures += captured_count

            try:
                self.last_move = human_to_point(coordinate, board_size)
            except Exception:
                self.last_move = None

        self.manual_move_index = target_index

        if target_index < len(history):
            self.current_player = history[target_index][1]
        elif target_index > 0:
            last_stone = history[target_index - 1][1]
            self.current_player = Stone.WHITE if last_stone == Stone.BLACK else Stone.BLACK
        else:
            self.current_player = Stone.BLACK

        self.status_message = f"Manual move {target_index}/{len(history)}"

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def draw_size_selector(self) -> None:
        import pygame

        rect = pygame.Rect(self.screen.get_width() - 110, 12, 82, 34)
        pygame.draw.rect(self.screen, (70, 70, 74), rect, border_radius=6)

        label = f"{self.board.size} x {self.board.size}"
        surface = self.small_ui_font.render(label, True, (235, 235, 235))
        self.screen.blit(surface, surface.get_rect(center=rect.center))


    def get_size_selector_rect(self):
        import pygame

        return pygame.Rect(
            self.screen.get_width() - 118,
            12,
            96,
            36,
        )

    def draw_size_selector(self) -> None:
        import pygame

        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect

        pygame.draw.rect(self.screen, (64, 64, 68), rect, border_radius=7)
        pygame.draw.rect(self.screen, (150, 150, 155), rect, 1, border_radius=7)

        label = f"{self.board.size} x {self.board.size}"
        surface = self.small_ui_font.render(label, True, (245, 245, 245))
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        # Top-right board-size button.
        # This does not depend on an old stored rect. It calculates the button live.
        size_rect = self.get_size_selector_rect()

        if size_rect.collidepoint(mouse_pos):
            print("[Go Sensei UI] Size button clicked", flush=True)
            self.cycle_board_size()
            return

        # Bottom buttons.
        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                print(f"[Go Sensei UI] Bottom button clicked: {button_name}", flush=True)
                self.handle_button_click(button_name)
                return

        # Speed slider, if present.
        speed_rect = getattr(self, "speed_slider_rect", None)

        if speed_rect is not None and speed_rect.collidepoint(mouse_pos):
            self.dragging_speed_slider = True

            if hasattr(self, "update_speed_from_mouse"):
                self.update_speed_from_mouse(mouse_pos[0])

            return

        # Board placement.
        self.handle_board_click(mouse_pos)

    def cycle_board_size(self) -> None:
        current_size = self.board.size

        if current_size == 19:
            new_size = 13
        elif current_size == 13:
            new_size = 9
        else:
            new_size = 19

        print(f"[Go Sensei UI] Cycling board size: {current_size} -> {new_size}", flush=True)
        self.change_board_size_safe(new_size)

    def change_board_size_safe(self, new_size: int) -> None:
        from app.core.board import Board
        from app.core.stone import Stone

        print(f"[Go Sensei UI] Changing board size to {new_size}x{new_size}", flush=True)

        self.board = Board(size=new_size)
        self.current_player = Stone.BLACK

        self.loaded_game = None
        self.loaded_sgf_path = None
        self.move_index = 0
        self.is_playing = False

        self.black_captures = 0
        self.white_captures = 0
        self.last_move = None

        self.manual_move_history = []
        self.manual_move_index = 0

        self.status_message = f"Board changed to {new_size}x{new_size}"

        if hasattr(self, "ai_pending_request_id"):
            self.ai_pending_request_id = None

        if hasattr(self, "ai_is_thinking"):
            self.ai_is_thinking = False

        if hasattr(self, "game_store"):
            try:
                self.current_database_game_id = self.game_store.start_game(board_size=new_size)
            except Exception as error:
                print(f"[Go Sensei Database] Could not start new game: {error}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()


    def get_size_selector_rect(self):
        import pygame

        return pygame.Rect(
            self.screen.get_width() - 118,
            12,
            96,
            36,
        )

    def draw_size_selector(self) -> None:
        import pygame

        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect

        pygame.draw.rect(self.screen, (64, 64, 70), rect, border_radius=7)
        pygame.draw.rect(self.screen, (150, 150, 155), rect, 1, border_radius=7)

        label = f"{self.board.size} x {self.board.size}"
        surface = self.small_ui_font.render(label, True, (245, 245, 245))
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 52
        h = 38
        gap = 6

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", "AI ON" if getattr(self, "ai_enabled", False) else "AI OFF"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 20 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 10

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            color = (70, 70, 76)

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                color = (70, 105, 85)

            if name == "ai" and getattr(self, "ai_enabled", False):
                color = (75, 110, 75)

            pygame.draw.rect(self.screen, color, rect, border_radius=6)
            pygame.draw.rect(self.screen, (128, 128, 135), rect, 1, border_radius=6)

            text_surface = self.status_font.render(label, True, (235, 235, 235))
            self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

            x += w + gap

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        print(f"[Go Sensei UI] Mouse down at {mouse_pos}", flush=True)

        # Top-right board-size button
        size_rect = self.get_size_selector_rect()

        if size_rect.collidepoint(mouse_pos):
            print("[Go Sensei UI] Size button clicked", flush=True)
            self.cycle_board_size()
            return

        # Bottom buttons
        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                print(f"[Go Sensei UI] Bottom button clicked: {button_name}", flush=True)
                self.handle_button_click(button_name)
                return

        # Board placement
        self.handle_board_click(mouse_pos)

    def handle_button_click(self, button_name: str) -> None:
        if button_name == "load":
            self.load_sgf_from_dialog()
            return

        if button_name == "analysis":
            self.toggle_live_analysis()
            return

        if button_name == "ai":
            if hasattr(self, "toggle_ai_opponent"):
                self.toggle_ai_opponent()
            else:
                self.status_message = "AI opponent is not installed yet"
                print("[Go Sensei UI] AI opponent is not installed yet.", flush=True)
            return

        # Manual board mode: replay buttons become undo/redo
        if getattr(self, "loaded_game", None) is None:
            if button_name == "beginning":
                if hasattr(self, "go_to_manual_beginning"):
                    self.go_to_manual_beginning()
                return

            if button_name == "back":
                if hasattr(self, "step_manual_back"):
                    self.step_manual_back()
                return

            if button_name == "play_pause":
                self.status_message = "Manual mode: use << and >> for undo/redo"
                return

            if button_name == "forward":
                if hasattr(self, "step_manual_forward"):
                    self.step_manual_forward(play_sound=True)
                return

            if button_name == "end":
                if hasattr(self, "go_to_manual_end"):
                    self.go_to_manual_end()
                return

        # SGF replay mode
        if button_name == "beginning":
            if hasattr(self, "go_to_beginning"):
                self.go_to_beginning()
            return

        if button_name == "back":
            if hasattr(self, "step_back"):
                self.step_back()
            return

        if button_name == "play_pause":
            if hasattr(self, "toggle_playback"):
                self.toggle_playback()
            else:
                self.is_playing = not getattr(self, "is_playing", False)
            return

        if button_name == "forward":
            if hasattr(self, "step_forward"):
                self.step_forward(play_sound=True)
            return

        if button_name == "end":
            if hasattr(self, "go_to_end"):
                self.go_to_end()
            return

    def cycle_board_size(self) -> None:
        current_size = self.board.size

        if current_size == 19:
            new_size = 13
        elif current_size == 13:
            new_size = 9
        else:
            new_size = 19

        print(f"[Go Sensei UI] Cycling board size: {current_size} -> {new_size}", flush=True)
        self.change_board_size_safe(new_size)

    def change_board_size_safe(self, new_size: int) -> None:
        from app.core.board import Board
        from app.core.stone import Stone

        print(f"[Go Sensei UI] Changing board size to {new_size}x{new_size}", flush=True)

        self.board = Board(size=new_size)
        self.current_player = Stone.BLACK

        self.loaded_game = None
        self.loaded_sgf_path = None
        self.move_index = 0
        self.is_playing = False

        self.black_captures = 0
        self.white_captures = 0
        self.last_move = None

        self.manual_move_history = []
        self.manual_move_index = 0

        self.status_message = f"Board changed to {new_size}x{new_size}"

        if hasattr(self, "ai_pending_request_id"):
            self.ai_pending_request_id = None

        if hasattr(self, "ai_is_thinking"):
            self.ai_is_thinking = False

        if hasattr(self, "game_store"):
            try:
                self.current_database_game_id = self.game_store.start_game(board_size=new_size)
            except Exception as error:
                print(f"[Go Sensei Database] Could not start new game: {error}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def toggle_live_analysis(self) -> None:
        self.analysis_enabled = not getattr(self, "analysis_enabled", False)

        if self.analysis_enabled:
            self.status_message = "Analysis ON — Chinese rules, komi 7.5"
            print("[Go Sensei Board] Analysis ON — Chinese rules, komi 7.5", flush=True)
            self.request_live_analysis()
        else:
            self.status_message = "Analysis OFF"
            print("[Go Sensei Board] Analysis OFF", flush=True)

    def request_live_analysis(self) -> int | None:
        if not hasattr(self, "analysis_service"):
            print("[Go Sensei Board] No analysis service available.", flush=True)
            return None

        print(
            f"[Go Sensei Board] Sending board to KataGo: player={self.current_player.name}, rules=chinese, komi=7.5",
            flush=True,
        )

        return self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.current_player,
        )

    def load_sgf_from_dialog(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog

            from app.core.sgf import load_sgf_file

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            sgf_path = filedialog.askopenfilename(
                title="Open SGF file",
                filetypes=[
                    ("SGF files", "*.sgf"),
                    ("All files", "*.*"),
                ],
            )

            root.destroy()

            if not sgf_path:
                self.status_message = "SGF load cancelled"
                return

            game = load_sgf_file(sgf_path)

            self.loaded_game = game
            self.loaded_sgf_path = sgf_path
            self.move_index = 0
            self.is_playing = False
            self.manual_move_history = []
            self.manual_move_index = 0

            if hasattr(self, "set_replay_position"):
                self.set_replay_position(0)

            self.status_message = f"Loaded SGF"
            print(f"[Go Sensei SGF] Loaded {sgf_path}", flush=True)

            if getattr(self, "analysis_enabled", False):
                self.request_live_analysis()

        except Exception as error:
            self.status_message = f"Could not load SGF: {error}"
            print(f"[Go Sensei SGF] Could not load SGF: {error}", flush=True)

    def run(self) -> None:
        import pygame

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if hasattr(self, "shutdown"):
                        self.shutdown()

                    pygame.quit()
                    raise SystemExit

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.dragging_speed_slider = False

                if event.type == pygame.MOUSEMOTION and getattr(self, "dragging_speed_slider", False):
                    if hasattr(self, "update_speed_from_mouse"):
                        self.update_speed_from_mouse(event.pos[0])

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.reset_board()
                        continue

                    if event.key == pygame.K_a:
                        self.toggle_live_analysis()
                        continue

                    if event.key == pygame.K_i:
                        if hasattr(self, "toggle_ai_opponent"):
                            self.toggle_ai_opponent()
                        continue

            if hasattr(self, "update_auto_replay"):
                self.update_auto_replay()

            if hasattr(self, "analysis_service"):
                self.analysis_state = self.analysis_service.get_state()

            if hasattr(self, "update_ai_move"):
                self.update_ai_move()

            if hasattr(self, "update_live_move_coaching"):
                self.update_live_move_coaching()

            self.draw()
            self.clock.tick(60)


    def get_ai_button_label(self) -> str:
        if not getattr(self, "ai_enabled", False):
            return "AI OFF"

        from app.core.stone import Stone

        human_player = getattr(self, "human_player", Stone.BLACK)

        if human_player == Stone.BLACK:
            return "YOU BLACK"

        return "YOU WHITE"

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 52
        h = 38
        gap = 6

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label()),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 20 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 10

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            color = (70, 70, 76)

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                color = (70, 105, 85)

            if name == "ai" and getattr(self, "ai_enabled", False):
                color = (75, 110, 75)

            pygame.draw.rect(self.screen, color, rect, border_radius=6)
            pygame.draw.rect(self.screen, (128, 128, 135), rect, 1, border_radius=6)

            text_surface = self.status_font.render(label, True, (235, 235, 235))
            self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

            x += w + gap

    def toggle_ai_opponent(self) -> None:
        from app.core.stone import Stone

        # Cycle:
        # AI OFF -> human black / AI white
        # human black -> human white / AI black
        # human white -> AI OFF
        if not getattr(self, "ai_enabled", False):
            self.ai_enabled = True
            self.human_player = Stone.BLACK
            self.ai_player = Stone.WHITE
            self.ai_pending_request_id = None
            self.ai_is_thinking = False
            self.status_message = "AI ON: You play Black. AI plays White."
            print("[Go Sensei AI] ON: human=Black, ai=White", flush=True)
            self.maybe_request_ai_move()
            return

        if getattr(self, "human_player", Stone.BLACK) == Stone.BLACK:
            self.ai_enabled = True
            self.human_player = Stone.WHITE
            self.ai_player = Stone.BLACK
            self.ai_pending_request_id = None
            self.ai_is_thinking = False
            self.status_message = "AI ON: You play White. AI plays Black."
            print("[Go Sensei AI] ON: human=White, ai=Black", flush=True)
            self.maybe_request_ai_move()
            return

        self.ai_enabled = False
        self.ai_pending_request_id = None
        self.ai_is_thinking = False
        self.status_message = "AI OFF"
        print("[Go Sensei AI] OFF", flush=True)

    def maybe_request_ai_move(self) -> None:
        from app.core.stone import Stone

        if not getattr(self, "ai_enabled", False):
            return

        ai_player = getattr(self, "ai_player", Stone.WHITE)

        if self.current_player != ai_player:
            return

        if getattr(self, "ai_pending_request_id", None) is not None:
            return

        if not hasattr(self, "analysis_service"):
            self.status_message = "AI needs KataGo analysis service"
            print("[Go Sensei AI] No analysis service available.", flush=True)
            return

        print(f"[Go Sensei AI] Requesting move for {ai_player.name}", flush=True)

        self.ai_is_thinking = True
        self.status_message = f"AI thinking as {ai_player.name}..."

        self.ai_pending_request_id = self.analysis_service.request_analysis(
            board=self.board,
            current_player=ai_player,
        )

    def update_ai_move(self) -> None:
        if not getattr(self, "ai_enabled", False):
            return

        self.maybe_request_ai_move()

        pending_id = getattr(self, "ai_pending_request_id", None)

        if pending_id is None:
            return

        if not hasattr(self, "analysis_service"):
            return

        state = self.analysis_service.get_state()

        if state.latest_error:
            self.ai_is_thinking = False
            self.ai_pending_request_id = None
            self.status_message = f"AI error: {state.latest_error}"
            print(f"[Go Sensei AI] Error: {state.latest_error}", flush=True)
            return

        completed_id = getattr(state, "completed_request_id", None)

        if completed_id != pending_id:
            return

        result = state.latest_result

        if result is None:
            return

        self.play_ai_move(result)

    def play_ai_move(self, result) -> None:
        from app.ai.ai_player import choose_ai_move
        from app.core.coordinates import human_to_point
        from app.core.stone import Stone

        ai_player = getattr(self, "ai_player", Stone.WHITE)

        move = choose_ai_move(self.board, ai_player, result)

        self.ai_pending_request_id = None
        self.ai_is_thinking = False

        if move is None:
            self.status_message = "AI could not find a legal move"
            print("[Go Sensei AI] No legal move found.", flush=True)
            return

        if move.lower() == "pass":
            self.status_message = f"AI {ai_player.name} passed"
            print(f"[Go Sensei AI] {ai_player.name} passed.", flush=True)
            self.current_player = Stone.WHITE if ai_player == Stone.BLACK else Stone.BLACK
            return

        try:
            captured_count = self.board.place_stone(move, ai_player)
        except Exception as error:
            self.status_message = f"AI illegal move: {move}"
            print(f"[Go Sensei AI] Illegal move {move}: {error}", flush=True)
            return

        if ai_player == Stone.BLACK:
            self.black_captures += captured_count
            self.current_player = Stone.WHITE
        else:
            self.white_captures += captured_count
            self.current_player = Stone.BLACK

        try:
            self.last_move = human_to_point(move, self.board.size)
        except Exception:
            self.last_move = None

        if not hasattr(self, "manual_move_history"):
            self.manual_move_history = []
            self.manual_move_index = 0

        # If you undo then AI plays, remove future branch.
        self.manual_move_history = self.manual_move_history[: self.manual_move_index]
        self.manual_move_history.append((move, ai_player))
        self.manual_move_index = len(self.manual_move_history)

        if hasattr(self, "record_current_move_to_database"):
            try:
                self.record_current_move_to_database(move, ai_player)
            except Exception as error:
                print(f"[Go Sensei Database] AI move not recorded: {error}", flush=True)

        if hasattr(self, "autosave_current_manual_game"):
            try:
                self.autosave_current_manual_game()
            except Exception as error:
                print(f"[Go Sensei Autosave] AI move not autosaved: {error}", flush=True)

        self.status_message = f"AI played {ai_player.name}: {move}"
        print(f"[Go Sensei AI] Played {ai_player.name}: {move}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()


    def get_ai_mode(self) -> str:
        return getattr(self, "ai_mode", "off")

    def get_ai_button_label(self) -> str:
        mode = self.get_ai_mode()

        if mode == "human_black":
            return "YOU BLACK"

        if mode == "human_white":
            return "YOU WHITE"

        if mode == "self_play":
            return "AI VS AI"

        return "AI OFF"

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 52
        h = 38
        gap = 6

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label()),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 20 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 10

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            color = (70, 70, 76)

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                color = (70, 105, 85)

            if name == "ai":
                mode = self.get_ai_mode()

                if mode == "human_black":
                    color = (75, 110, 75)
                elif mode == "human_white":
                    color = (80, 95, 125)
                elif mode == "self_play":
                    color = (120, 85, 135)

            pygame.draw.rect(self.screen, color, rect, border_radius=6)
            pygame.draw.rect(self.screen, (128, 128, 135), rect, 1, border_radius=6)

            text_surface = self.status_font.render(label, True, (235, 235, 235))
            self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

            x += w + gap

    def toggle_ai_opponent(self) -> None:
        from app.core.stone import Stone

        mode = self.get_ai_mode()

        self.ai_pending_request_id = None
        self.ai_pending_player = None
        self.ai_is_thinking = False

        if mode == "off":
            self.ai_mode = "human_black"
            self.ai_enabled = True
            self.human_player = Stone.BLACK
            self.ai_player = Stone.WHITE
            self.status_message = "AI ON: You play Black. AI plays White."
            print("[Go Sensei AI] Mode: human=Black, ai=White", flush=True)
            self.maybe_request_ai_move()
            return

        if mode == "human_black":
            self.ai_mode = "human_white"
            self.ai_enabled = True
            self.human_player = Stone.WHITE
            self.ai_player = Stone.BLACK
            self.status_message = "AI ON: You play White. AI plays Black."
            print("[Go Sensei AI] Mode: human=White, ai=Black", flush=True)
            self.maybe_request_ai_move()
            return

        if mode == "human_white":
            self.ai_mode = "self_play"
            self.ai_enabled = True
            self.human_player = None
            self.ai_player = None
            self.self_play_last_move_time_ms = 0
            self.self_play_delay_ms = 650
            self.status_message = "AI VS AI: KataGo plays both sides."
            print("[Go Sensei AI] Mode: AI vs AI", flush=True)
            self.maybe_request_ai_move()
            return

        self.ai_mode = "off"
        self.ai_enabled = False
        self.human_player = Stone.BLACK
        self.ai_player = Stone.WHITE
        self.status_message = "AI OFF"
        print("[Go Sensei AI] Mode: OFF", flush=True)

    def get_ai_player_to_move(self):
        from app.core.stone import Stone

        mode = self.get_ai_mode()

        if mode == "off":
            return None

        if mode == "self_play":
            return self.current_player

        ai_player = getattr(self, "ai_player", Stone.WHITE)

        if self.current_player == ai_player:
            return ai_player

        return None

    def maybe_request_ai_move(self) -> None:
        import pygame

        if not getattr(self, "ai_enabled", False):
            return

        ai_player = self.get_ai_player_to_move()

        if ai_player is None:
            return

        if getattr(self, "ai_pending_request_id", None) is not None:
            return

        if not hasattr(self, "analysis_service"):
            self.status_message = "AI needs KataGo analysis service"
            print("[Go Sensei AI] No analysis service available.", flush=True)
            return

        if self.get_ai_mode() == "self_play":
            now_ms = pygame.time.get_ticks()
            last_ms = getattr(self, "self_play_last_move_time_ms", 0)
            delay_ms = getattr(self, "self_play_delay_ms", 650)

            if now_ms - last_ms < delay_ms:
                return

        print(f"[Go Sensei AI] Requesting move for {ai_player.name}", flush=True)

        self.ai_is_thinking = True

        if self.get_ai_mode() == "self_play":
            self.status_message = f"AI vs AI: {ai_player.name} thinking..."
        else:
            self.status_message = f"AI thinking as {ai_player.name}..."

        self.ai_pending_player = ai_player
        self.ai_pending_request_id = self.analysis_service.request_analysis(
            board=self.board,
            current_player=ai_player,
        )

    def update_ai_move(self) -> None:
        if not getattr(self, "ai_enabled", False):
            return

        self.maybe_request_ai_move()

        pending_id = getattr(self, "ai_pending_request_id", None)

        if pending_id is None:
            return

        if not hasattr(self, "analysis_service"):
            return

        state = self.analysis_service.get_state()

        if state.latest_error:
            self.ai_is_thinking = False
            self.ai_pending_request_id = None
            self.ai_pending_player = None
            self.status_message = f"AI error: {state.latest_error}"
            print(f"[Go Sensei AI] Error: {state.latest_error}", flush=True)
            return

        completed_id = getattr(state, "completed_request_id", None)

        if completed_id != pending_id:
            return

        result = state.latest_result

        if result is None:
            return

        ai_player = getattr(self, "ai_pending_player", None)

        self.ai_pending_request_id = None
        self.ai_pending_player = None
        self.ai_is_thinking = False

        if ai_player is None:
            ai_player = self.current_player

        self.play_ai_move(result, ai_player)

    def play_ai_move(self, result, ai_player=None) -> None:
        import pygame

        from app.ai.ai_player import choose_ai_move
        from app.core.coordinates import human_to_point
        from app.core.stone import Stone

        if ai_player is None:
            ai_player = self.current_player

        move = choose_ai_move(self.board, ai_player, result)

        if move is None:
            self.status_message = "AI could not find a legal move"
            print("[Go Sensei AI] No legal move found.", flush=True)
            return

        if move.lower() == "pass":
            self.status_message = f"AI {ai_player.name} passed"
            print(f"[Go Sensei AI] {ai_player.name} passed.", flush=True)
            self.current_player = Stone.WHITE if ai_player == Stone.BLACK else Stone.BLACK
            self.self_play_last_move_time_ms = pygame.time.get_ticks()
            return

        try:
            captured_count = self.board.place_stone(move, ai_player)
        except Exception as error:
            self.status_message = f"AI illegal move: {move}"
            print(f"[Go Sensei AI] Illegal move {move}: {error}", flush=True)
            return

        if ai_player == Stone.BLACK:
            self.black_captures += captured_count
            self.current_player = Stone.WHITE
        else:
            self.white_captures += captured_count
            self.current_player = Stone.BLACK

        try:
            self.last_move = human_to_point(move, self.board.size)
        except Exception:
            self.last_move = None

        if not hasattr(self, "manual_move_history"):
            self.manual_move_history = []
            self.manual_move_index = 0

        self.manual_move_history = self.manual_move_history[: self.manual_move_index]
        self.manual_move_history.append((move, ai_player))
        self.manual_move_index = len(self.manual_move_history)

        if hasattr(self, "record_current_move_to_database"):
            try:
                self.record_current_move_to_database(move, ai_player)
            except Exception as error:
                print(f"[Go Sensei Database] AI move not recorded: {error}", flush=True)

        if hasattr(self, "autosave_current_manual_game"):
            try:
                self.autosave_current_manual_game()
            except Exception as error:
                print(f"[Go Sensei Autosave] AI move not autosaved: {error}", flush=True)

        self.self_play_last_move_time_ms = pygame.time.get_ticks()

        if self.get_ai_mode() == "self_play":
            self.status_message = f"AI vs AI: {ai_player.name} played {move}"
        else:
            self.status_message = f"AI played {ai_player.name}: {move}"

        print(f"[Go Sensei AI] Played {ai_player.name}: {move}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()


    def ui_theme(self) -> dict:
        return {
            "background_top": (232, 191, 94),
            "background_bottom": (184, 124, 45),
            "board_light": (232, 188, 94),
            "board_mid": (214, 161, 68),
            "board_dark": (111, 74, 28),
            "grid": (62, 42, 18),
            "text": (26, 24, 22),
            "muted_text": (210, 215, 224),
            "panel": (18, 22, 30, 238),
            "panel_warm": (26, 22, 18, 238),
            "panel_border_blue": (105, 170, 255),
            "panel_border_gold": (245, 205, 125),
            "button": (58, 60, 68),
            "button_hover": (78, 82, 92),
            "button_border": (132, 135, 145),
            "green": (90, 230, 145),
            "red": (255, 115, 115),
            "gold": (255, 222, 145),
            "blue": (110, 178, 255),
            "purple": (190, 145, 255),
        }

    def draw_vertical_gradient(self, surface, top_color, bottom_color) -> None:
        import pygame

        width, height = surface.get_size()

        for y in range(height):
            t = y / max(1, height - 1)
            color = (
                int(top_color[0] * (1 - t) + bottom_color[0] * t),
                int(top_color[1] * (1 - t) + bottom_color[1] * t),
                int(top_color[2] * (1 - t) + bottom_color[2] * t),
            )
            pygame.draw.line(surface, color, (0, y), (width, y))

    def draw_soft_shadow_rect(self, rect, radius: int = 18, strength: int = 55) -> None:
        import pygame

        shadow = pygame.Surface((rect.width + 28, rect.height + 28), pygame.SRCALPHA)

        for i in range(7):
            alpha = max(0, strength - i * 7)
            shadow_rect = pygame.Rect(14 - i, 14 - i, rect.width + i * 2, rect.height + i * 2)
            pygame.draw.rect(shadow, (0, 0, 0, alpha), shadow_rect, border_radius=radius + i)

        self.screen.blit(shadow, (rect.left - 14, rect.top - 10))

    def draw_panel(self, rect, fill_color, border_color, radius: int = 18) -> None:
        import pygame

        self.draw_soft_shadow_rect(rect, radius=radius)

        panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(panel_surface, fill_color, panel_surface.get_rect(), border_radius=radius)
        self.screen.blit(panel_surface, rect.topleft)

        pygame.draw.rect(self.screen, border_color, rect, 2, border_radius=radius)

    def draw_button(self, rect, label: str, active: bool = False, accent=None) -> None:
        import pygame

        theme = self.ui_theme()
        mouse_pos = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mouse_pos)

        color = theme["button_hover"] if hovered else theme["button"]

        if active:
            color = accent or (75, 110, 85)

        self.draw_soft_shadow_rect(rect, radius=9, strength=25)
        pygame.draw.rect(self.screen, color, rect, border_radius=8)
        pygame.draw.rect(self.screen, theme["button_border"], rect, 1, border_radius=8)

        font = getattr(self, "status_font", pygame.font.SysFont("arial", 17, bold=True))
        text_surface = font.render(label, True, (245, 245, 245))
        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def make_hd_stone(self, stone_color: str, radius: int):
        import pygame

        scale = 3
        size = radius * 2 + 18
        big_size = size * scale
        big_radius = radius * scale

        surface = pygame.Surface((big_size, big_size), pygame.SRCALPHA)
        center = (big_size // 2, big_size // 2)

        # Shadow
        pygame.draw.circle(
            surface,
            (0, 0, 0, 85),
            (center[0] + 5 * scale, center[1] + 6 * scale),
            big_radius,
        )

        if stone_color == "black":
            base = (20, 21, 24)
            rim = (70, 72, 78)
            highlight = (92, 94, 104)

            pygame.draw.circle(surface, base, center, big_radius)
            pygame.draw.circle(surface, rim, center, big_radius, max(2, scale * 2))
            pygame.draw.circle(
                surface,
                highlight,
                (center[0] - 6 * scale, center[1] - 7 * scale),
                max(3 * scale, big_radius // 4),
            )

        else:
            base = (238, 238, 232)
            rim = (155, 155, 155)
            highlight = (255, 255, 255)
            lowlight = (205, 205, 198)

            pygame.draw.circle(surface, base, center, big_radius)
            pygame.draw.circle(surface, rim, center, big_radius, max(2, scale * 2))
            pygame.draw.circle(
                surface,
                highlight,
                (center[0] - 6 * scale, center[1] - 8 * scale),
                max(4 * scale, big_radius // 4),
            )
            pygame.draw.circle(
                surface,
                lowlight,
                (center[0] + 5 * scale, center[1] + 6 * scale),
                max(3 * scale, big_radius // 5),
            )

        return pygame.transform.smoothscale(surface, (size, size))

    def draw_hd_stone(self, x: int, y: int, stone_color: str, radius: int) -> None:
        cache_name = "_hd_stone_cache"

        if not hasattr(self, cache_name):
            self._hd_stone_cache = {}

        key = (stone_color, radius)

        if key not in self._hd_stone_cache:
            self._hd_stone_cache[key] = self.make_hd_stone(stone_color, radius)

        stone_surface = self._hd_stone_cache[key]
        rect = stone_surface.get_rect(center=(x, y))
        self.screen.blit(stone_surface, rect)

    def draw_board_texture(self, board_rect) -> None:
        import math
        import pygame

        theme = self.ui_theme()

        self.draw_soft_shadow_rect(board_rect, radius=14, strength=65)

        board_surface = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)

        # Base vertical wood gradient
        for y in range(board_rect.height):
            t = y / max(1, board_rect.height - 1)
            color = (
                int(theme["board_light"][0] * (1 - t) + theme["board_mid"][0] * t),
                int(theme["board_light"][1] * (1 - t) + theme["board_mid"][1] * t),
                int(theme["board_light"][2] * (1 - t) + theme["board_mid"][2] * t),
            )
            pygame.draw.line(board_surface, color, (0, y), (board_rect.width, y))

        # Soft wood grain
        for x in range(0, board_rect.width, 5):
            wave = math.sin(x * 0.025) * 10 + math.sin(x * 0.071) * 5
            shade = int(wave)
            color = (
                max(0, min(255, theme["board_mid"][0] + shade)),
                max(0, min(255, theme["board_mid"][1] + shade)),
                max(0, min(255, theme["board_mid"][2] + shade)),
                55,
            )
            pygame.draw.line(board_surface, color, (x, 0), (x, board_rect.height), 1)

        # Rounded board
        rounded = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)
        pygame.draw.rect(rounded, (255, 255, 255, 255), rounded.get_rect(), border_radius=14)
        board_surface.blit(rounded, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        self.screen.blit(board_surface, board_rect.topleft)
        pygame.draw.rect(self.screen, theme["board_dark"], board_rect, 3, border_radius=14)

    def recalculate_safe_layout(self) -> None:
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()

        self.safe_panel_width = 372
        self.safe_panel_margin = 22
        self.safe_panel_gap = 34
        self.safe_panel_top = 72
        self.safe_panel_height = min(635, screen_height - 158)

        self.safe_left_panel_left = self.safe_panel_margin
        self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

        board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
        board_area_right = self.safe_right_panel_left - self.safe_panel_gap
        board_area_width = board_area_right - board_area_left

        top_margin = 64
        bottom_margin = 135
        board_area_height = screen_height - top_margin - bottom_margin

        board_pixel_size = min(board_area_width, board_area_height)

        if board_pixel_size < 380:
            self.safe_panel_width = 320
            self.safe_panel_gap = 24
            self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

            board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
            board_area_right = self.safe_right_panel_left - self.safe_panel_gap
            board_area_width = board_area_right - board_area_left
            board_pixel_size = min(board_area_width, board_area_height)

        board_pixel_size = max(320, int(board_pixel_size))

        self.board_left = int(board_area_left + (board_area_width - board_pixel_size) / 2)
        self.board_top = top_margin
        self.board_right = self.board_left + board_pixel_size
        self.board_bottom = self.board_top + board_pixel_size
        self.cell_size = board_pixel_size / (self.board.size - 1)

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        return (
            int(self.board_left + col * self.cell_size),
            int(self.board_top + row * self.cell_size),
        )

    def draw_coordinates(self) -> None:
        columns = "ABCDEFGHJKLMNOPQRST"[: self.board.size]
        number_gap = 11

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, self.board_top - 42))
            self.screen.blit(bottom, (x - bottom.get_width() // 2, self.board_bottom + 27))

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (self.board_left - number_gap - left.get_width(), y - left.get_height() // 2))
            self.screen.blit(right, (self.board_right + number_gap, y - right.get_height() // 2))

    def draw_size_selector(self) -> None:
        import pygame

        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect

        self.draw_button(rect, f"{self.board.size} x {self.board.size}", active=False)

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 54
        h = 40
        gap = 7

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 24 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 12

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = None

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                active = True
                accent = (58, 112, 84)

            if name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = (62, 116, 82)
                elif mode == "human_white":
                    active = True
                    accent = (64, 88, 130)
                elif mode == "self_play":
                    active = True
                    accent = (118, 78, 142)

            self.draw_button(rect, label, active=active, accent=accent)

            x += w + gap

    def draw_coach_panel(self) -> None:
        import pygame

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_left_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel"], theme["panel_border_blue"], radius=18)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        title_surface = self.status_font.render("Go Sensei Coach", True, theme["blue"])
        self.screen.blit(title_surface, (x, y))
        y += 30

        subtitle = self.small_ui_font.render("Move feedback, ideas, and lessons", True, theme["muted_text"])
        self.screen.blit(subtitle, (x, y))
        y += 30

        lines = getattr(self, "coach_lines", ["Waiting for move feedback..."])
        title = getattr(self, "coach_title", "Coach Read")

        y = self.draw_coach_card(title, self.get_coach_lines_by_label(lines, "Verdict"), x, y, panel_rect.width - 36, 78, theme["green"])
        y += 10
        y = self.draw_coach_card("Move", self.get_coach_lines_by_label(lines, "Your move", "Engine idea"), x, y, panel_rect.width - 36, 104, theme["blue"])
        y += 10
        y = self.draw_coach_card("Impact", self.get_coach_lines_by_label(lines, "Impact", "Engine gap", "Point gap", "Winrate", "Score", "After-move swing", "Score swing"), x, y, panel_rect.width - 36, 104, theme["gold"])
        y += 10

        remaining = panel_rect.bottom - y - 16

        if remaining > 110:
            self.draw_coach_card("Lesson", self.get_coach_lines_by_label(lines, "Main lesson", "Why it matters", "Ask yourself", "Engine line"), x, y, panel_rect.width - 36, remaining, theme["purple"])

    def draw_analysis_panel(self) -> None:
        import pygame
        from app.core.stone import Stone

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_right_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel_warm"], theme["panel_border_gold"], radius=18)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        title_surface = self.status_font.render("KataGo Analysis", True, theme["gold"])
        self.screen.blit(title_surface, (x, y))
        y += 32

        rule_surface = self.small_ui_font.render("Rules: Chinese   Komi: 7.5", True, (235, 220, 180))
        self.screen.blit(rule_surface, (x, y))
        y += 28

        engine_color = theme["green"] if getattr(self, "analysis_enabled", False) else theme["red"]
        engine_text = "Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF"
        engine_surface = self.small_ui_font.render(engine_text, True, engine_color)
        self.screen.blit(engine_surface, (x, y))
        y += 32

        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        def card(title: str, height: int):
            nonlocal y
            rect = pygame.Rect(x - 4, y, panel_rect.width - 28, height)
            card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(card_surface, (255, 255, 255, 24), card_surface.get_rect(), border_radius=12)
            self.screen.blit(card_surface, rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 52), rect, 1, border_radius=12)

            title_surface = self.small_ui_font.render(title, True, theme["gold"])
            self.screen.blit(title_surface, (rect.left + 12, rect.top + 10))

            y = rect.top + 38
            return rect

        def add(value: str, color=(240, 240, 240), gap=23):
            nonlocal y
            surface = self.small_ui_font.render(value, True, color)
            self.screen.blit(surface, (x + 8, y))
            y += gap

        def finish(rect):
            nonlocal y
            y = rect.bottom + 14

        status_card = card("Status", 92)

        if state is not None and getattr(state, "is_thinking", False):
            add("Thinking...", theme["blue"])
        elif state is not None and getattr(state, "latest_error", None):
            add("Error", theme["red"])
        elif result is not None:
            add("Ready", theme["green"])
        else:
            add("Waiting for analysis", (220, 220, 220))

        elapsed = getattr(state, "latest_elapsed_seconds", None) if state is not None else None
        if elapsed is not None:
            add(f"Last run: {elapsed:.2f}s", (210, 210, 215))
        else:
            add("Click ANALYZE to begin", (210, 210, 215))

        finish(status_card)

        win_card = card("Winrate", 132)

        black_winrate = None
        white_winrate = None

        if result is not None and result.root_winrate_percent is not None:
            if result.current_player == Stone.BLACK:
                black_winrate = result.root_winrate_percent
            else:
                black_winrate = 100.0 - result.root_winrate_percent

            white_winrate = 100.0 - black_winrate

        if black_winrate is None:
            add("No result yet", (220, 220, 220))
        else:
            add(f"Black: {black_winrate:.1f}%")
            add(f"White: {white_winrate:.1f}%")

            bar = pygame.Rect(x + 8, y + 4, panel_rect.width - 52, 20)
            pygame.draw.rect(self.screen, (235, 235, 230), bar, border_radius=10)

            black_width = int(bar.width * (black_winrate / 100.0))
            black_rect = pygame.Rect(bar.left, bar.top, black_width, bar.height)
            pygame.draw.rect(self.screen, (28, 28, 32), black_rect, border_radius=10)
            pygame.draw.rect(self.screen, theme["gold"], bar, 1, border_radius=10)

        finish(win_card)

        score_card = card("Score estimate", 118)

        black_score = None

        if result is not None and result.root_score_lead is not None:
            if result.current_player == Stone.BLACK:
                black_score = result.root_score_lead
            else:
                black_score = -result.root_score_lead

        if black_score is None:
            add("Waiting for score estimate", (220, 220, 220))
        else:
            add(f"Black: {black_score:+.2f} pts")
            add(f"White: {-black_score:+.2f} pts")

            if black_score > 0:
                add(f"Leader: Black by {abs(black_score):.2f}", theme["green"])
            elif black_score < 0:
                add(f"Leader: White by {abs(black_score):.2f}", theme["green"])
            else:
                add("Leader: Even", theme["green"])

        finish(score_card)

        captures_card = card("Captures", 108)
        add(f"Black captured: {getattr(self, 'black_captures', 0)}")
        add(f"White captured: {getattr(self, 'white_captures', 0)}")

        learning_count = 0
        if hasattr(self, "get_self_play_memory_count"):
            try:
                learning_count = self.get_self_play_memory_count()
            except Exception:
                learning_count = 0

        finish(captures_card)

        if panel_rect.bottom - y > 72:
            learn_card = card("Learning", 72)
            add(f"Self-play memory: {learning_count} moves", theme["purple"])
            finish(learn_card)

    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        theme = self.ui_theme()
        self.recalculate_safe_layout()

        self.draw_vertical_gradient(self.screen, theme["background_top"], theme["background_bottom"])

        board_size = self.board.size
        board_padding = 26

        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )

        self.draw_board_texture(board_rect)

        # Grid
        for row in range(board_size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, board_size - 1)
            pygame.draw.line(self.screen, theme["grid"], (start_x, y), (end_x, y), 1)

        for col in range(board_size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(board_size - 1, col)
            pygame.draw.line(self.screen, theme["grid"], (x, start_y), (x, end_y), 1)

        # Star points
        if board_size == 19:
            star_points = [3, 9, 15]
        elif board_size == 13:
            star_points = [3, 6, 9]
        elif board_size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, (34, 23, 12), (x, y), max(3, int(self.cell_size * 0.08)))

        self.draw_coordinates()

        # Analysis markers under stones
        if hasattr(self, "draw_analysis_markers"):
            try:
                self.draw_analysis_markers()
            except Exception as error:
                print(f"[Go Sensei Draw] Analysis markers skipped: {error}", flush=True)

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(board_size):
            for col in range(board_size):
                coordinate = point_to_human(row, col, board_size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                stone_name = getattr(stone, "name", str(stone)).upper()

                if "EMPTY" in stone_name:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK or "BLACK" in stone_name:
                    self.draw_hd_stone(x, y, "black", stone_radius)
                elif stone == Stone.WHITE or "WHITE" in stone_name:
                    self.draw_hd_stone(x, y, "white", stone_radius)

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (85, 165, 255), (x, y), max(7, stone_radius // 3), 3)
            pygame.draw.circle(self.screen, (255, 255, 255), (x, y), max(3, stone_radius // 7))

        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_bottom_controls()
        self.draw_size_selector()

        pygame.display.flip()


    def ui_theme(self) -> dict:
        return {
            "background_top": (229, 184, 86),
            "background_bottom": (170, 103, 38),

            "board_light": (235, 193, 101),
            "board_mid": (218, 166, 72),
            "board_warm": (204, 142, 52),
            "board_dark": (98, 66, 27),

            "grid": (58, 39, 17),
            "grid_soft": (88, 58, 22),
            "text": (24, 22, 20),

            "panel": (17, 20, 27, 236),
            "panel_warm": (26, 22, 17, 238),
            "card": (255, 255, 255, 26),

            "panel_border_blue": (92, 166, 255),
            "panel_border_gold": (238, 198, 112),

            "button": (50, 53, 61),
            "button_hover": (68, 72, 83),
            "button_border": (115, 120, 132),

            "green": (94, 232, 150),
            "red": (255, 116, 116),
            "gold": (255, 220, 140),
            "blue": (110, 180, 255),
            "purple": (190, 150, 255),
            "muted": (205, 210, 220),
            "white": (244, 244, 240),
        }

    def draw_vertical_gradient(self, surface, top_color, bottom_color) -> None:
        import pygame

        width, height = surface.get_size()

        for y in range(height):
            t = y / max(1, height - 1)
            color = (
                int(top_color[0] * (1 - t) + bottom_color[0] * t),
                int(top_color[1] * (1 - t) + bottom_color[1] * t),
                int(top_color[2] * (1 - t) + bottom_color[2] * t),
            )
            pygame.draw.line(surface, color, (0, y), (width, y))

    def draw_background_vignette(self) -> None:
        import pygame

        width = self.screen.get_width()
        height = self.screen.get_height()

        overlay = pygame.Surface((width, height), pygame.SRCALPHA)

        # Soft side darkening so the center board feels important.
        for i in range(120):
            alpha = int(70 * (i / 120))
            pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(0, 0, i, height))
            pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(width - i, 0, i, height))

        # Subtle bottom warmth.
        pygame.draw.rect(overlay, (80, 35, 10, 34), pygame.Rect(0, height - 95, width, 95))

        self.screen.blit(overlay, (0, 0))

    def draw_soft_shadow_rect(self, rect, radius: int = 18, strength: int = 48) -> None:
        import pygame

        shadow = pygame.Surface((rect.width + 34, rect.height + 34), pygame.SRCALPHA)

        for i in range(9):
            alpha = max(0, strength - i * 5)
            shadow_rect = pygame.Rect(17 - i, 17 - i, rect.width + i * 2, rect.height + i * 2)
            pygame.draw.rect(shadow, (0, 0, 0, alpha), shadow_rect, border_radius=radius + i)

        self.screen.blit(shadow, (rect.left - 17, rect.top - 12))

    def draw_panel(self, rect, fill_color, border_color, radius: int = 20) -> None:
        import pygame

        self.draw_soft_shadow_rect(rect, radius=radius, strength=58)

        panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(panel_surface, fill_color, panel_surface.get_rect(), border_radius=radius)

        # Soft top highlight
        pygame.draw.rect(panel_surface, (255, 255, 255, 18), pygame.Rect(0, 0, rect.width, 42), border_radius=radius)

        self.screen.blit(panel_surface, rect.topleft)

        pygame.draw.rect(self.screen, border_color, rect, 2, border_radius=radius)
        pygame.draw.rect(self.screen, (255, 255, 255, 32), rect.inflate(-6, -6), 1, border_radius=radius - 3)

    def draw_button(self, rect, label: str, active: bool = False, accent=None) -> None:
        import pygame

        theme = self.ui_theme()
        mouse_pos = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mouse_pos)

        color = theme["button_hover"] if hovered else theme["button"]

        if active:
            color = accent or (72, 112, 86)

        self.draw_soft_shadow_rect(rect, radius=10, strength=22)

        pygame.draw.rect(self.screen, color, rect, border_radius=9)
        pygame.draw.rect(self.screen, theme["button_border"], rect, 1, border_radius=9)

        # Small highlight line
        pygame.draw.line(
            self.screen,
            (255, 255, 255, 38),
            (rect.left + 10, rect.top + 6),
            (rect.right - 10, rect.top + 6),
            1,
        )

        font = getattr(self, "status_font", pygame.font.SysFont("arial", 17, bold=True))
        text_surface = font.render(label, True, (242, 242, 242))
        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def make_hd_stone(self, stone_color: str, radius: int):
        import pygame

        scale = 4
        size = radius * 2 + 20
        big_size = size * scale
        big_radius = radius * scale

        surface = pygame.Surface((big_size, big_size), pygame.SRCALPHA)
        center = (big_size // 2, big_size // 2)

        # Drop shadow
        pygame.draw.circle(
            surface,
            (0, 0, 0, 80),
            (center[0] + 5 * scale, center[1] + 7 * scale),
            big_radius,
        )

        if stone_color == "black":
            # Layered black stone, less flat.
            layers = [
                ((14, 15, 18), 1.00),
                ((22, 23, 27), 0.88),
                ((34, 35, 42), 0.66),
                ((48, 50, 58), 0.42),
            ]

            for color, factor in layers:
                pygame.draw.circle(surface, color, center, int(big_radius * factor))

            pygame.draw.circle(surface, (5, 5, 7), center, big_radius, max(2, scale * 2))
            pygame.draw.circle(
                surface,
                (100, 104, 118, 165),
                (center[0] - 7 * scale, center[1] - 8 * scale),
                max(4 * scale, big_radius // 5),
            )

        else:
            # Layered white stone with warm porcelain feel.
            layers = [
                ((228, 226, 216), 1.00),
                ((240, 239, 232), 0.86),
                ((250, 250, 246), 0.62),
                ((255, 255, 255), 0.34),
            ]

            for color, factor in layers:
                pygame.draw.circle(surface, color, center, int(big_radius * factor))

            pygame.draw.circle(surface, (145, 143, 135), center, big_radius, max(2, scale * 2))
            pygame.draw.circle(
                surface,
                (255, 255, 255, 210),
                (center[0] - 7 * scale, center[1] - 9 * scale),
                max(5 * scale, big_radius // 4),
            )
            pygame.draw.circle(
                surface,
                (190, 188, 178, 90),
                (center[0] + 7 * scale, center[1] + 8 * scale),
                max(4 * scale, big_radius // 5),
            )

        return pygame.transform.smoothscale(surface, (size, size))

    def draw_hd_stone(self, x: int, y: int, stone_color: str, radius: int) -> None:
        if not hasattr(self, "_hd_stone_cache"):
            self._hd_stone_cache = {}

        key = (stone_color, radius)

        if key not in self._hd_stone_cache:
            self._hd_stone_cache[key] = self.make_hd_stone(stone_color, radius)

        stone_surface = self._hd_stone_cache[key]
        rect = stone_surface.get_rect(center=(x, y))
        self.screen.blit(stone_surface, rect)

    def draw_board_texture(self, board_rect) -> None:
        import math
        import pygame

        theme = self.ui_theme()

        self.draw_soft_shadow_rect(board_rect, radius=18, strength=70)

        board_surface = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)

        # Smooth base gradient
        for y in range(board_rect.height):
            t = y / max(1, board_rect.height - 1)
            color = (
                int(theme["board_light"][0] * (1 - t) + theme["board_mid"][0] * t),
                int(theme["board_light"][1] * (1 - t) + theme["board_mid"][1] * t),
                int(theme["board_light"][2] * (1 - t) + theme["board_mid"][2] * t),
            )
            pygame.draw.line(board_surface, color, (0, y), (board_rect.width, y))

        # Broad wood planks instead of noisy stripes
        plank_count = 8
        plank_width = board_rect.width / plank_count

        for i in range(plank_count):
            x = int(i * plank_width)
            shade = -10 if i % 2 else 6
            plank_color = (
                max(0, min(255, theme["board_mid"][0] + shade)),
                max(0, min(255, theme["board_mid"][1] + shade)),
                max(0, min(255, theme["board_mid"][2] + shade)),
                34,
            )
            pygame.draw.rect(board_surface, plank_color, pygame.Rect(x, 0, int(plank_width), board_rect.height))

            # plank seam
            pygame.draw.line(board_surface, (95, 58, 18, 45), (x, 0), (x, board_rect.height), 1)

        # Very subtle organic grain
        for x in range(0, board_rect.width, 18):
            wave = math.sin(x * 0.023) * 8 + math.sin(x * 0.061) * 4
            shade = int(wave)
            color = (
                max(0, min(255, theme["board_warm"][0] + shade)),
                max(0, min(255, theme["board_warm"][1] + shade)),
                max(0, min(255, theme["board_warm"][2] + shade)),
                42,
            )
            pygame.draw.line(board_surface, color, (x, 0), (x + 8, board_rect.height), 1)

        # Rounded clipping mask
        mask = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=18)
        board_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        self.screen.blit(board_surface, board_rect.topleft)

        # Board border
        pygame.draw.rect(self.screen, theme["board_dark"], board_rect, 3, border_radius=18)
        pygame.draw.rect(self.screen, (255, 235, 170, 42), board_rect.inflate(-8, -8), 1, border_radius=14)

    def recalculate_safe_layout(self) -> None:
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()

        self.safe_panel_width = 370
        self.safe_panel_margin = 22
        self.safe_panel_gap = 38
        self.safe_panel_top = 76
        self.safe_panel_height = min(620, screen_height - 168)

        self.safe_left_panel_left = self.safe_panel_margin
        self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

        board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
        board_area_right = self.safe_right_panel_left - self.safe_panel_gap
        board_area_width = board_area_right - board_area_left

        top_margin = 64
        bottom_margin = 136
        board_area_height = screen_height - top_margin - bottom_margin

        board_pixel_size = min(board_area_width, board_area_height)

        if board_pixel_size < 380:
            self.safe_panel_width = 318
            self.safe_panel_gap = 24
            self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

            board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
            board_area_right = self.safe_right_panel_left - self.safe_panel_gap
            board_area_width = board_area_right - board_area_left
            board_pixel_size = min(board_area_width, board_area_height)

        board_pixel_size = max(320, int(board_pixel_size))

        self.board_left = int(board_area_left + (board_area_width - board_pixel_size) / 2)
        self.board_top = top_margin
        self.board_right = self.board_left + board_pixel_size
        self.board_bottom = self.board_top + board_pixel_size
        self.cell_size = board_pixel_size / (self.board.size - 1)

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        return (
            int(self.board_left + col * self.cell_size),
            int(self.board_top + row * self.cell_size),
        )

    def draw_coordinates(self) -> None:
        columns = "ABCDEFGHJKLMNOPQRST"[: self.board.size]
        number_gap = 12

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, self.board_top - 41))
            self.screen.blit(bottom, (x - bottom.get_width() // 2, self.board_bottom + 26))

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (self.board_left - number_gap - left.get_width(), y - left.get_height() // 2))
            self.screen.blit(right, (self.board_right + number_gap, y - right.get_height() // 2))

    def draw_size_selector(self) -> None:
        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect
        self.draw_button(rect, f"{self.board.size} x {self.board.size}", active=False)

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 55
        h = 41
        gap = 7

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 24 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 12

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = None

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                active = True
                accent = (58, 112, 84)

            if name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = (62, 116, 82)
                elif mode == "human_white":
                    active = True
                    accent = (64, 88, 130)
                elif mode == "self_play":
                    active = True
                    accent = (118, 78, 142)

            self.draw_button(rect, label, active=active, accent=accent)

            x += w + gap

    def draw_coach_panel(self) -> None:
        import pygame

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_left_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel"], theme["panel_border_blue"], radius=20)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        title_surface = self.status_font.render("Go Sensei Coach", True, theme["blue"])
        self.screen.blit(title_surface, (x, y))
        y += 30

        subtitle = self.small_ui_font.render("Move feedback, ideas, and lessons", True, theme["muted"])
        self.screen.blit(subtitle, (x, y))
        y += 30

        lines = getattr(self, "coach_lines", ["Waiting for move feedback..."])
        title = getattr(self, "coach_title", "Coach Read")

        y = self.draw_coach_card(title, self.get_coach_lines_by_label(lines, "Verdict"), x, y, panel_rect.width - 36, 78, theme["green"])
        y += 10
        y = self.draw_coach_card("Move", self.get_coach_lines_by_label(lines, "Your move", "Engine idea"), x, y, panel_rect.width - 36, 104, theme["blue"])
        y += 10
        y = self.draw_coach_card("Impact", self.get_coach_lines_by_label(lines, "Impact", "Engine gap", "Point gap", "Winrate", "Score", "After-move swing", "Score swing"), x, y, panel_rect.width - 36, 104, theme["gold"])
        y += 10

        remaining = panel_rect.bottom - y - 16

        if remaining > 110:
            self.draw_coach_card("Lesson", self.get_coach_lines_by_label(lines, "Main lesson", "Why it matters", "Ask yourself", "Engine line"), x, y, panel_rect.width - 36, remaining, theme["purple"])

    def draw_analysis_panel(self) -> None:
        import pygame
        from app.core.stone import Stone

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_right_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel_warm"], theme["panel_border_gold"], radius=20)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        title_surface = self.status_font.render("KataGo Analysis", True, theme["gold"])
        self.screen.blit(title_surface, (x, y))
        y += 32

        rule_surface = self.small_ui_font.render("Rules: Chinese   Komi: 7.5", True, (235, 220, 180))
        self.screen.blit(rule_surface, (x, y))
        y += 27

        engine_color = theme["green"] if getattr(self, "analysis_enabled", False) else theme["red"]
        engine_text = "Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF"
        engine_surface = self.small_ui_font.render(engine_text, True, engine_color)
        self.screen.blit(engine_surface, (x, y))
        y += 31

        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        def card(title: str, height: int):
            nonlocal y
            rect = pygame.Rect(x - 4, y, panel_rect.width - 28, height)
            card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(card_surface, theme["card"], card_surface.get_rect(), border_radius=13)
            pygame.draw.rect(card_surface, (255, 255, 255, 14), pygame.Rect(0, 0, rect.width, 30), border_radius=13)
            self.screen.blit(card_surface, rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 55), rect, 1, border_radius=13)

            title_surface = self.small_ui_font.render(title, True, theme["gold"])
            self.screen.blit(title_surface, (rect.left + 12, rect.top + 10))

            y = rect.top + 38
            return rect

        def add(value: str, color=(240, 240, 240), gap=23):
            nonlocal y
            surface = self.small_ui_font.render(value, True, color)
            self.screen.blit(surface, (x + 8, y))
            y += gap

        def finish(rect):
            nonlocal y
            y = rect.bottom + 14

        status_card = card("Status", 92)

        if state is not None and getattr(state, "is_thinking", False):
            add("Thinking...", theme["blue"])
        elif state is not None and getattr(state, "latest_error", None):
            add("Error", theme["red"])
        elif result is not None:
            add("Ready", theme["green"])
        else:
            add("Waiting for analysis", (220, 220, 220))

        elapsed = getattr(state, "latest_elapsed_seconds", None) if state is not None else None
        if elapsed is not None:
            add(f"Last run: {elapsed:.2f}s", (210, 210, 215))
        else:
            add("Click ANALYZE to begin", (210, 210, 215))

        finish(status_card)

        win_card = card("Winrate", 132)

        black_winrate = None
        white_winrate = None

        if result is not None and result.root_winrate_percent is not None:
            if result.current_player == Stone.BLACK:
                black_winrate = result.root_winrate_percent
            else:
                black_winrate = 100.0 - result.root_winrate_percent

            white_winrate = 100.0 - black_winrate

        if black_winrate is None:
            add("No result yet", (220, 220, 220))
        else:
            add(f"Black: {black_winrate:.1f}%")
            add(f"White: {white_winrate:.1f}%")

            bar = pygame.Rect(x + 8, y + 4, panel_rect.width - 52, 20)
            pygame.draw.rect(self.screen, (235, 235, 230), bar, border_radius=10)

            black_width = int(bar.width * (black_winrate / 100.0))
            black_rect = pygame.Rect(bar.left, bar.top, black_width, bar.height)
            pygame.draw.rect(self.screen, (24, 24, 28), black_rect, border_radius=10)
            pygame.draw.rect(self.screen, theme["gold"], bar, 1, border_radius=10)

        finish(win_card)

        score_card = card("Score estimate", 118)

        black_score = None

        if result is not None and result.root_score_lead is not None:
            if result.current_player == Stone.BLACK:
                black_score = result.root_score_lead
            else:
                black_score = -result.root_score_lead

        if black_score is None:
            add("Waiting for score estimate", (220, 220, 220))
        else:
            add(f"Black: {black_score:+.2f} pts")
            add(f"White: {-black_score:+.2f} pts")

            if black_score > 0:
                add(f"Leader: Black by {abs(black_score):.2f}", theme["green"])
            elif black_score < 0:
                add(f"Leader: White by {abs(black_score):.2f}", theme["green"])
            else:
                add("Leader: Even", theme["green"])

        finish(score_card)

        captures_card = card("Captures", 108)
        add(f"Black captured: {getattr(self, 'black_captures', 0)}")
        add(f"White captured: {getattr(self, 'white_captures', 0)}")
        finish(captures_card)

        learning_count = 0
        if hasattr(self, "get_self_play_memory_count"):
            try:
                learning_count = self.get_self_play_memory_count()
            except Exception:
                learning_count = 0

        if panel_rect.bottom - y > 72:
            learn_card = card("Learning", 72)
            add(f"Self-play memory: {learning_count} moves", theme["purple"])
            finish(learn_card)

    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        theme = self.ui_theme()
        self.recalculate_safe_layout()

        self.draw_vertical_gradient(self.screen, theme["background_top"], theme["background_bottom"])
        self.draw_background_vignette()

        board_size = self.board.size
        board_padding = 27

        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )

        self.draw_board_texture(board_rect)

        # Grid
        for row in range(board_size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, board_size - 1)
            width = 2 if row in [0, board_size - 1] else 1
            pygame.draw.line(self.screen, theme["grid"], (start_x, y), (end_x, y), width)

        for col in range(board_size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(board_size - 1, col)
            width = 2 if col in [0, board_size - 1] else 1
            pygame.draw.line(self.screen, theme["grid"], (x, start_y), (x, end_y), width)

        # Star points
        if board_size == 19:
            star_points = [3, 9, 15]
        elif board_size == 13:
            star_points = [3, 6, 9]
        elif board_size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, (30, 20, 10), (x, y), max(3, int(self.cell_size * 0.08)))

        self.draw_coordinates()

        if hasattr(self, "draw_analysis_markers"):
            try:
                self.draw_analysis_markers()
            except Exception as error:
                print(f"[Go Sensei Draw] Analysis markers skipped: {error}", flush=True)

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(board_size):
            for col in range(board_size):
                coordinate = point_to_human(row, col, board_size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                stone_name = getattr(stone, "name", str(stone)).upper()

                if "EMPTY" in stone_name:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK or "BLACK" in stone_name:
                    self.draw_hd_stone(x, y, "black", stone_radius)
                elif stone == Stone.WHITE or "WHITE" in stone_name:
                    self.draw_hd_stone(x, y, "white", stone_radius)

        # Hover preview
        try:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if self.board_left <= mouse_x <= self.board_right and self.board_top <= mouse_y <= self.board_bottom:
                col = round((mouse_x - self.board_left) / self.cell_size)
                row = round((mouse_y - self.board_top) / self.cell_size)

                if 0 <= row < board_size and 0 <= col < board_size:
                    coordinate = point_to_human(row, col, board_size)
                    if self.board.get(coordinate) is None:
                        x, y = self.point_to_pixels(row, col)
                        preview = pygame.Surface((stone_radius * 2 + 4, stone_radius * 2 + 4), pygame.SRCALPHA)
                        color = (20, 20, 24, 70) if self.current_player == Stone.BLACK else (255, 255, 255, 90)
                        pygame.draw.circle(preview, color, preview.get_rect().center, stone_radius)
                        self.screen.blit(preview, preview.get_rect(center=(x, y)))
        except Exception:
            pass

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (85, 165, 255), (x, y), max(7, stone_radius // 3), 3)
            pygame.draw.circle(self.screen, (255, 255, 255), (x, y), max(3, stone_radius // 7))

        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_bottom_controls()
        self.draw_size_selector()

        pygame.display.flip()


    def ui_theme(self) -> dict:
        return {
            # Flat, clean app background
            "background": (210, 154, 62),

            # Crystal-clear board colors: no grain/noise
            "board": (226, 177, 82),
            "board_edge": (96, 63, 25),
            "board_inner_highlight": (245, 205, 118),

            # Crisp grid
            "grid": (62, 43, 19),
            "grid_outer": (42, 29, 12),
            "star": (25, 18, 9),

            # Text
            "text": (22, 20, 18),
            "muted": (205, 210, 220),
            "white": (245, 245, 242),

            # Panels
            "panel": (17, 21, 28, 245),
            "panel_warm": (25, 22, 17, 245),
            "card": (44, 47, 53, 248),

            # Borders
            "panel_border_blue": (78, 158, 255),
            "panel_border_gold": (236, 195, 104),

            # Buttons
            "button": (54, 57, 66),
            "button_hover": (70, 75, 86),
            "button_border": (120, 125, 138),

            # Accents
            "green": (92, 232, 150),
            "red": (255, 116, 116),
            "gold": (255, 220, 135),
            "blue": (100, 174, 255),
            "purple": (190, 150, 255),
        }

    def draw_vertical_gradient(self, surface, top_color, bottom_color) -> None:
        # Crystal mode: no gradient noise, just a clean solid background.
        surface.fill(self.ui_theme()["background"])

    def draw_background_vignette(self) -> None:
        # Crystal mode: no vignette. Keep the screen clean.
        return

    def draw_soft_shadow_rect(self, rect, radius: int = 16, strength: int = 28) -> None:
        import pygame

        # Very soft shadow only; avoids fuzzy/grainy appearance.
        shadow = pygame.Surface((rect.width + 16, rect.height + 16), pygame.SRCALPHA)
        pygame.draw.rect(
            shadow,
            (0, 0, 0, strength),
            pygame.Rect(8, 8, rect.width, rect.height),
            border_radius=radius,
        )
        self.screen.blit(shadow, (rect.left - 4, rect.top - 2))

    def draw_panel(self, rect, fill_color, border_color, radius: int = 18) -> None:
        import pygame

        self.draw_soft_shadow_rect(rect, radius=radius, strength=36)

        panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(panel_surface, fill_color, panel_surface.get_rect(), border_radius=radius)
        self.screen.blit(panel_surface, rect.topleft)

        pygame.draw.rect(self.screen, border_color, rect, 2, border_radius=radius)

    def draw_button(self, rect, label: str, active: bool = False, accent=None) -> None:
        import pygame

        theme = self.ui_theme()
        hovered = rect.collidepoint(pygame.mouse.get_pos())

        color = theme["button_hover"] if hovered else theme["button"]

        if active:
            color = accent or (70, 110, 86)

        pygame.draw.rect(self.screen, color, rect, border_radius=8)
        pygame.draw.rect(self.screen, theme["button_border"], rect, 1, border_radius=8)

        font = getattr(self, "status_font", pygame.font.SysFont("arial", 17, bold=True))
        text_surface = font.render(label, True, theme["white"])
        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def make_hd_stone(self, stone_color: str, radius: int):
        import pygame

        # High-res antialiased stones, but clean and not textured.
        scale = 4
        size = radius * 2 + 16
        big_size = size * scale
        big_radius = radius * scale

        surface = pygame.Surface((big_size, big_size), pygame.SRCALPHA)
        center = (big_size // 2, big_size // 2)

        # Clean shadow
        pygame.draw.circle(
            surface,
            (0, 0, 0, 80),
            (center[0] + 4 * scale, center[1] + 5 * scale),
            big_radius,
        )

        if stone_color == "black":
            pygame.draw.circle(surface, (18, 19, 23), center, big_radius)
            pygame.draw.circle(surface, (50, 52, 60), center, int(big_radius * 0.72))
            pygame.draw.circle(
                surface,
                (92, 95, 108, 150),
                (center[0] - 7 * scale, center[1] - 8 * scale),
                max(4 * scale, big_radius // 5),
            )
            pygame.draw.circle(surface, (5, 5, 7), center, big_radius, max(2, scale * 2))

        else:
            pygame.draw.circle(surface, (230, 229, 222), center, big_radius)
            pygame.draw.circle(surface, (248, 248, 244), center, int(big_radius * 0.72))
            pygame.draw.circle(
                surface,
                (255, 255, 255, 220),
                (center[0] - 7 * scale, center[1] - 8 * scale),
                max(5 * scale, big_radius // 4),
            )
            pygame.draw.circle(surface, (142, 142, 136), center, big_radius, max(2, scale * 2))

        return pygame.transform.smoothscale(surface, (size, size))

    def draw_hd_stone(self, x: int, y: int, stone_color: str, radius: int) -> None:
        if not hasattr(self, "_hd_stone_cache"):
            self._hd_stone_cache = {}

        key = (stone_color, radius)

        if key not in self._hd_stone_cache:
            self._hd_stone_cache[key] = self.make_hd_stone(stone_color, radius)

        stone_surface = self._hd_stone_cache[key]
        self.screen.blit(stone_surface, stone_surface.get_rect(center=(x, y)))

    def draw_board_texture(self, board_rect) -> None:
        import pygame

        theme = self.ui_theme()

        # Clean, flat, high-definition board. No fake wood grain.
        self.draw_soft_shadow_rect(board_rect, radius=16, strength=45)

        pygame.draw.rect(self.screen, theme["board"], board_rect, border_radius=16)

        # Clean border and subtle inner highlight
        pygame.draw.rect(self.screen, theme["board_edge"], board_rect, 3, border_radius=16)
        pygame.draw.rect(self.screen, theme["board_inner_highlight"], board_rect.inflate(-10, -10), 1, border_radius=12)

    def recalculate_safe_layout(self) -> None:
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()

        self.safe_panel_width = 370
        self.safe_panel_margin = 22
        self.safe_panel_gap = 40
        self.safe_panel_top = 76
        self.safe_panel_height = min(620, screen_height - 168)

        self.safe_left_panel_left = self.safe_panel_margin
        self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

        board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
        board_area_right = self.safe_right_panel_left - self.safe_panel_gap
        board_area_width = board_area_right - board_area_left

        top_margin = 64
        bottom_margin = 136
        board_area_height = screen_height - top_margin - bottom_margin

        board_pixel_size = min(board_area_width, board_area_height)

        if board_pixel_size < 380:
            self.safe_panel_width = 318
            self.safe_panel_gap = 26
            self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

            board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
            board_area_right = self.safe_right_panel_left - self.safe_panel_gap
            board_area_width = board_area_right - board_area_left
            board_pixel_size = min(board_area_width, board_area_height)

        board_pixel_size = max(320, int(board_pixel_size))

        self.board_left = int(board_area_left + (board_area_width - board_pixel_size) / 2)
        self.board_top = top_margin
        self.board_right = self.board_left + board_pixel_size
        self.board_bottom = self.board_top + board_pixel_size
        self.cell_size = board_pixel_size / (self.board.size - 1)

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        return (
            int(self.board_left + col * self.cell_size),
            int(self.board_top + row * self.cell_size),
        )

    def draw_coordinates(self) -> None:
        columns = "ABCDEFGHJKLMNOPQRST"[: self.board.size]
        number_gap = 12

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, self.board_top - 41))
            self.screen.blit(bottom, (x - bottom.get_width() // 2, self.board_bottom + 26))

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (self.board_left - number_gap - left.get_width(), y - left.get_height() // 2))
            self.screen.blit(right, (self.board_right + number_gap, y - right.get_height() // 2))

    def draw_size_selector(self) -> None:
        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect
        self.draw_button(rect, f"{self.board.size} x {self.board.size}", active=False)

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 55
        h = 41
        gap = 7

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 24 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 12

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = None

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                active = True
                accent = (58, 112, 84)

            if name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = (62, 116, 82)
                elif mode == "human_white":
                    active = True
                    accent = (64, 88, 130)
                elif mode == "self_play":
                    active = True
                    accent = (118, 78, 142)

            self.draw_button(rect, label, active=active, accent=accent)

            x += w + gap

    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        theme = self.ui_theme()
        self.recalculate_safe_layout()

        # Clean solid background
        self.screen.fill(theme["background"])

        board_size = self.board.size
        board_padding = 27

        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )

        self.draw_board_texture(board_rect)

        # Crisp grid lines
        for row in range(board_size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, board_size - 1)

            width = 2 if row in [0, board_size - 1] else 1
            color = theme["grid_outer"] if row in [0, board_size - 1] else theme["grid"]

            pygame.draw.line(self.screen, color, (start_x, y), (end_x, y), width)

        for col in range(board_size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(board_size - 1, col)

            width = 2 if col in [0, board_size - 1] else 1
            color = theme["grid_outer"] if col in [0, board_size - 1] else theme["grid"]

            pygame.draw.line(self.screen, color, (x, start_y), (x, end_y), width)

        # Star points
        if board_size == 19:
            star_points = [3, 9, 15]
        elif board_size == 13:
            star_points = [3, 6, 9]
        elif board_size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, theme["star"], (x, y), max(3, int(self.cell_size * 0.08)))

        self.draw_coordinates()

        if hasattr(self, "draw_analysis_markers"):
            try:
                self.draw_analysis_markers()
            except Exception as error:
                print(f"[Go Sensei Draw] Analysis markers skipped: {error}", flush=True)

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(board_size):
            for col in range(board_size):
                coordinate = point_to_human(row, col, board_size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                stone_name = getattr(stone, "name", str(stone)).upper()

                if "EMPTY" in stone_name:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK or "BLACK" in stone_name:
                    self.draw_hd_stone(x, y, "black", stone_radius)
                elif stone == Stone.WHITE or "WHITE" in stone_name:
                    self.draw_hd_stone(x, y, "white", stone_radius)

        # Hover preview
        try:
            mouse_x, mouse_y = pygame.mouse.get_pos()

            if self.board_left <= mouse_x <= self.board_right and self.board_top <= mouse_y <= self.board_bottom:
                col = round((mouse_x - self.board_left) / self.cell_size)
                row = round((mouse_y - self.board_top) / self.cell_size)

                if 0 <= row < board_size and 0 <= col < board_size:
                    coordinate = point_to_human(row, col, board_size)

                    if self.board.get(coordinate) is None:
                        x, y = self.point_to_pixels(row, col)
                        preview = pygame.Surface((stone_radius * 2 + 4, stone_radius * 2 + 4), pygame.SRCALPHA)

                        color = (20, 20, 24, 60) if self.current_player == Stone.BLACK else (255, 255, 255, 90)
                        pygame.draw.circle(preview, color, preview.get_rect().center, stone_radius)

                        self.screen.blit(preview, preview.get_rect(center=(x, y)))
        except Exception:
            pass

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (80, 160, 255), (x, y), max(7, stone_radius // 3), 3)
            pygame.draw.circle(self.screen, (255, 255, 255), (x, y), max(3, stone_radius // 7))

        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_bottom_controls()
        self.draw_size_selector()

        pygame.display.flip()


    def ui_theme(self) -> dict:
        return {
            "background_top": (229, 184, 86),
            "background_bottom": (170, 103, 38),

            "board_light": (235, 193, 101),
            "board_mid": (218, 166, 72),
            "board_warm": (204, 142, 52),
            "board_dark": (98, 66, 27),

            "grid": (58, 39, 17),
            "grid_soft": (88, 58, 22),
            "text": (24, 22, 20),

            "panel": (17, 20, 27, 236),
            "panel_warm": (26, 22, 17, 238),
            "card": (255, 255, 255, 26),

            "panel_border_blue": (92, 166, 255),
            "panel_border_gold": (238, 198, 112),

            "button": (50, 53, 61),
            "button_hover": (68, 72, 83),
            "button_border": (115, 120, 132),

            "green": (94, 232, 150),
            "red": (255, 116, 116),
            "gold": (255, 220, 140),
            "blue": (110, 180, 255),
            "purple": (190, 150, 255),
            "muted": (205, 210, 220),
            "white": (244, 244, 240),
        }

    def draw_vertical_gradient(self, surface, top_color, bottom_color) -> None:
        import pygame

        width, height = surface.get_size()

        for y in range(height):
            t = y / max(1, height - 1)
            color = (
                int(top_color[0] * (1 - t) + bottom_color[0] * t),
                int(top_color[1] * (1 - t) + bottom_color[1] * t),
                int(top_color[2] * (1 - t) + bottom_color[2] * t),
            )
            pygame.draw.line(surface, color, (0, y), (width, y))

    def draw_background_vignette(self) -> None:
        import pygame

        width = self.screen.get_width()
        height = self.screen.get_height()

        overlay = pygame.Surface((width, height), pygame.SRCALPHA)

        # Soft side darkening so the center board feels important.
        for i in range(120):
            alpha = int(70 * (i / 120))
            pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(0, 0, i, height))
            pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(width - i, 0, i, height))

        # Subtle bottom warmth.
        pygame.draw.rect(overlay, (80, 35, 10, 34), pygame.Rect(0, height - 95, width, 95))

        self.screen.blit(overlay, (0, 0))

    def draw_soft_shadow_rect(self, rect, radius: int = 18, strength: int = 48) -> None:
        import pygame

        shadow = pygame.Surface((rect.width + 34, rect.height + 34), pygame.SRCALPHA)

        for i in range(9):
            alpha = max(0, strength - i * 5)
            shadow_rect = pygame.Rect(17 - i, 17 - i, rect.width + i * 2, rect.height + i * 2)
            pygame.draw.rect(shadow, (0, 0, 0, alpha), shadow_rect, border_radius=radius + i)

        self.screen.blit(shadow, (rect.left - 17, rect.top - 12))

    def draw_panel(self, rect, fill_color, border_color, radius: int = 20) -> None:
        import pygame

        self.draw_soft_shadow_rect(rect, radius=radius, strength=58)

        panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(panel_surface, fill_color, panel_surface.get_rect(), border_radius=radius)

        # Soft top highlight
        pygame.draw.rect(panel_surface, (255, 255, 255, 18), pygame.Rect(0, 0, rect.width, 42), border_radius=radius)

        self.screen.blit(panel_surface, rect.topleft)

        pygame.draw.rect(self.screen, border_color, rect, 2, border_radius=radius)
        pygame.draw.rect(self.screen, (255, 255, 255, 32), rect.inflate(-6, -6), 1, border_radius=radius - 3)

    def draw_button(self, rect, label: str, active: bool = False, accent=None) -> None:
        import pygame

        theme = self.ui_theme()
        mouse_pos = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mouse_pos)

        color = theme["button_hover"] if hovered else theme["button"]

        if active:
            color = accent or (72, 112, 86)

        self.draw_soft_shadow_rect(rect, radius=10, strength=22)

        pygame.draw.rect(self.screen, color, rect, border_radius=9)
        pygame.draw.rect(self.screen, theme["button_border"], rect, 1, border_radius=9)

        # Small highlight line
        pygame.draw.line(
            self.screen,
            (255, 255, 255, 38),
            (rect.left + 10, rect.top + 6),
            (rect.right - 10, rect.top + 6),
            1,
        )

        font = getattr(self, "status_font", pygame.font.SysFont("arial", 17, bold=True))
        text_surface = font.render(label, True, (242, 242, 242))
        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def make_hd_stone(self, stone_color: str, radius: int):
        import pygame

        scale = 4
        size = radius * 2 + 20
        big_size = size * scale
        big_radius = radius * scale

        surface = pygame.Surface((big_size, big_size), pygame.SRCALPHA)
        center = (big_size // 2, big_size // 2)

        # Drop shadow
        pygame.draw.circle(
            surface,
            (0, 0, 0, 80),
            (center[0] + 5 * scale, center[1] + 7 * scale),
            big_radius,
        )

        if stone_color == "black":
            # Layered black stone, less flat.
            layers = [
                ((14, 15, 18), 1.00),
                ((22, 23, 27), 0.88),
                ((34, 35, 42), 0.66),
                ((48, 50, 58), 0.42),
            ]

            for color, factor in layers:
                pygame.draw.circle(surface, color, center, int(big_radius * factor))

            pygame.draw.circle(surface, (5, 5, 7), center, big_radius, max(2, scale * 2))
            pygame.draw.circle(
                surface,
                (100, 104, 118, 165),
                (center[0] - 7 * scale, center[1] - 8 * scale),
                max(4 * scale, big_radius // 5),
            )

        else:
            # Layered white stone with warm porcelain feel.
            layers = [
                ((228, 226, 216), 1.00),
                ((240, 239, 232), 0.86),
                ((250, 250, 246), 0.62),
                ((255, 255, 255), 0.34),
            ]

            for color, factor in layers:
                pygame.draw.circle(surface, color, center, int(big_radius * factor))

            pygame.draw.circle(surface, (145, 143, 135), center, big_radius, max(2, scale * 2))
            pygame.draw.circle(
                surface,
                (255, 255, 255, 210),
                (center[0] - 7 * scale, center[1] - 9 * scale),
                max(5 * scale, big_radius // 4),
            )
            pygame.draw.circle(
                surface,
                (190, 188, 178, 90),
                (center[0] + 7 * scale, center[1] + 8 * scale),
                max(4 * scale, big_radius // 5),
            )

        return pygame.transform.smoothscale(surface, (size, size))

    def draw_hd_stone(self, x: int, y: int, stone_color: str, radius: int) -> None:
        if not hasattr(self, "_hd_stone_cache"):
            self._hd_stone_cache = {}

        key = (stone_color, radius)

        if key not in self._hd_stone_cache:
            self._hd_stone_cache[key] = self.make_hd_stone(stone_color, radius)

        stone_surface = self._hd_stone_cache[key]
        rect = stone_surface.get_rect(center=(x, y))
        self.screen.blit(stone_surface, rect)

    def draw_board_texture(self, board_rect) -> None:
        import math
        import pygame

        theme = self.ui_theme()

        self.draw_soft_shadow_rect(board_rect, radius=18, strength=70)

        board_surface = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)

        # Smooth base gradient
        for y in range(board_rect.height):
            t = y / max(1, board_rect.height - 1)
            color = (
                int(theme["board_light"][0] * (1 - t) + theme["board_mid"][0] * t),
                int(theme["board_light"][1] * (1 - t) + theme["board_mid"][1] * t),
                int(theme["board_light"][2] * (1 - t) + theme["board_mid"][2] * t),
            )
            pygame.draw.line(board_surface, color, (0, y), (board_rect.width, y))

        # Broad wood planks instead of noisy stripes
        plank_count = 8
        plank_width = board_rect.width / plank_count

        for i in range(plank_count):
            x = int(i * plank_width)
            shade = -10 if i % 2 else 6
            plank_color = (
                max(0, min(255, theme["board_mid"][0] + shade)),
                max(0, min(255, theme["board_mid"][1] + shade)),
                max(0, min(255, theme["board_mid"][2] + shade)),
                34,
            )
            pygame.draw.rect(board_surface, plank_color, pygame.Rect(x, 0, int(plank_width), board_rect.height))

            # plank seam
            pygame.draw.line(board_surface, (95, 58, 18, 45), (x, 0), (x, board_rect.height), 1)

        # Very subtle organic grain
        for x in range(0, board_rect.width, 18):
            wave = math.sin(x * 0.023) * 8 + math.sin(x * 0.061) * 4
            shade = int(wave)
            color = (
                max(0, min(255, theme["board_warm"][0] + shade)),
                max(0, min(255, theme["board_warm"][1] + shade)),
                max(0, min(255, theme["board_warm"][2] + shade)),
                42,
            )
            pygame.draw.line(board_surface, color, (x, 0), (x + 8, board_rect.height), 1)

        # Rounded clipping mask
        mask = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=18)
        board_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        self.screen.blit(board_surface, board_rect.topleft)

        # Board border
        pygame.draw.rect(self.screen, theme["board_dark"], board_rect, 3, border_radius=18)
        pygame.draw.rect(self.screen, (255, 235, 170, 42), board_rect.inflate(-8, -8), 1, border_radius=14)

    def recalculate_safe_layout(self) -> None:
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()

        self.safe_panel_width = 370
        self.safe_panel_margin = 22
        self.safe_panel_gap = 38
        self.safe_panel_top = 76
        self.safe_panel_height = min(620, screen_height - 168)

        self.safe_left_panel_left = self.safe_panel_margin
        self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

        board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
        board_area_right = self.safe_right_panel_left - self.safe_panel_gap
        board_area_width = board_area_right - board_area_left

        top_margin = 64
        bottom_margin = 136
        board_area_height = screen_height - top_margin - bottom_margin

        board_pixel_size = min(board_area_width, board_area_height)

        if board_pixel_size < 380:
            self.safe_panel_width = 318
            self.safe_panel_gap = 24
            self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

            board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
            board_area_right = self.safe_right_panel_left - self.safe_panel_gap
            board_area_width = board_area_right - board_area_left
            board_pixel_size = min(board_area_width, board_area_height)

        board_pixel_size = max(320, int(board_pixel_size))

        self.board_left = int(board_area_left + (board_area_width - board_pixel_size) / 2)
        self.board_top = top_margin
        self.board_right = self.board_left + board_pixel_size
        self.board_bottom = self.board_top + board_pixel_size
        self.cell_size = board_pixel_size / (self.board.size - 1)

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        return (
            int(self.board_left + col * self.cell_size),
            int(self.board_top + row * self.cell_size),
        )

    def draw_coordinates(self) -> None:
        columns = "ABCDEFGHJKLMNOPQRST"[: self.board.size]
        number_gap = 12

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, self.board_top - 41))
            self.screen.blit(bottom, (x - bottom.get_width() // 2, self.board_bottom + 26))

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (self.board_left - number_gap - left.get_width(), y - left.get_height() // 2))
            self.screen.blit(right, (self.board_right + number_gap, y - right.get_height() // 2))

    def draw_size_selector(self) -> None:
        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect
        self.draw_button(rect, f"{self.board.size} x {self.board.size}", active=False)

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 55
        h = 41
        gap = 7

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 24 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 12

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = None

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                active = True
                accent = (58, 112, 84)

            if name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = (62, 116, 82)
                elif mode == "human_white":
                    active = True
                    accent = (64, 88, 130)
                elif mode == "self_play":
                    active = True
                    accent = (118, 78, 142)

            self.draw_button(rect, label, active=active, accent=accent)

            x += w + gap

    def draw_coach_panel(self) -> None:
        import pygame

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_left_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel"], theme["panel_border_blue"], radius=20)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        title_surface = self.status_font.render("Go Sensei Coach", True, theme["blue"])
        self.screen.blit(title_surface, (x, y))
        y += 30

        subtitle = self.small_ui_font.render("Move feedback, ideas, and lessons", True, theme["muted"])
        self.screen.blit(subtitle, (x, y))
        y += 30

        lines = getattr(self, "coach_lines", ["Waiting for move feedback..."])
        title = getattr(self, "coach_title", "Coach Read")

        y = self.draw_coach_card(title, self.get_coach_lines_by_label(lines, "Verdict"), x, y, panel_rect.width - 36, 78, theme["green"])
        y += 10
        y = self.draw_coach_card("Move", self.get_coach_lines_by_label(lines, "Your move", "Engine idea"), x, y, panel_rect.width - 36, 104, theme["blue"])
        y += 10
        y = self.draw_coach_card("Impact", self.get_coach_lines_by_label(lines, "Impact", "Engine gap", "Point gap", "Winrate", "Score", "After-move swing", "Score swing"), x, y, panel_rect.width - 36, 104, theme["gold"])
        y += 10

        remaining = panel_rect.bottom - y - 16

        if remaining > 110:
            self.draw_coach_card("Lesson", self.get_coach_lines_by_label(lines, "Main lesson", "Why it matters", "Ask yourself", "Engine line"), x, y, panel_rect.width - 36, remaining, theme["purple"])

    def draw_analysis_panel(self) -> None:
        import pygame
        from app.core.stone import Stone

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_right_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel_warm"], theme["panel_border_gold"], radius=20)

        x = panel_rect.left + 18
        y = panel_rect.top + 16

        title_surface = self.status_font.render("KataGo Analysis", True, theme["gold"])
        self.screen.blit(title_surface, (x, y))
        y += 32

        rule_surface = self.small_ui_font.render("Rules: Chinese   Komi: 7.5", True, (235, 220, 180))
        self.screen.blit(rule_surface, (x, y))
        y += 27

        engine_color = theme["green"] if getattr(self, "analysis_enabled", False) else theme["red"]
        engine_text = "Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF"
        engine_surface = self.small_ui_font.render(engine_text, True, engine_color)
        self.screen.blit(engine_surface, (x, y))
        y += 31

        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        def card(title: str, height: int):
            nonlocal y
            rect = pygame.Rect(x - 4, y, panel_rect.width - 28, height)
            card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(card_surface, theme["card"], card_surface.get_rect(), border_radius=13)
            pygame.draw.rect(card_surface, (255, 255, 255, 14), pygame.Rect(0, 0, rect.width, 30), border_radius=13)
            self.screen.blit(card_surface, rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 55), rect, 1, border_radius=13)

            title_surface = self.small_ui_font.render(title, True, theme["gold"])
            self.screen.blit(title_surface, (rect.left + 12, rect.top + 10))

            y = rect.top + 38
            return rect

        def add(value: str, color=(240, 240, 240), gap=23):
            nonlocal y
            surface = self.small_ui_font.render(value, True, color)
            self.screen.blit(surface, (x + 8, y))
            y += gap

        def finish(rect):
            nonlocal y
            y = rect.bottom + 14

        status_card = card("Status", 92)

        if state is not None and getattr(state, "is_thinking", False):
            add("Thinking...", theme["blue"])
        elif state is not None and getattr(state, "latest_error", None):
            add("Error", theme["red"])
        elif result is not None:
            add("Ready", theme["green"])
        else:
            add("Waiting for analysis", (220, 220, 220))

        elapsed = getattr(state, "latest_elapsed_seconds", None) if state is not None else None
        if elapsed is not None:
            add(f"Last run: {elapsed:.2f}s", (210, 210, 215))
        else:
            add("Click ANALYZE to begin", (210, 210, 215))

        finish(status_card)

        win_card = card("Winrate", 132)

        black_winrate = None
        white_winrate = None

        if result is not None and result.root_winrate_percent is not None:
            if result.current_player == Stone.BLACK:
                black_winrate = result.root_winrate_percent
            else:
                black_winrate = 100.0 - result.root_winrate_percent

            white_winrate = 100.0 - black_winrate

        if black_winrate is None:
            add("No result yet", (220, 220, 220))
        else:
            add(f"Black: {black_winrate:.1f}%")
            add(f"White: {white_winrate:.1f}%")

            bar = pygame.Rect(x + 8, y + 4, panel_rect.width - 52, 20)
            pygame.draw.rect(self.screen, (235, 235, 230), bar, border_radius=10)

            black_width = int(bar.width * (black_winrate / 100.0))
            black_rect = pygame.Rect(bar.left, bar.top, black_width, bar.height)
            pygame.draw.rect(self.screen, (24, 24, 28), black_rect, border_radius=10)
            pygame.draw.rect(self.screen, theme["gold"], bar, 1, border_radius=10)

        finish(win_card)

        score_card = card("Score estimate", 118)

        black_score = None

        if result is not None and result.root_score_lead is not None:
            if result.current_player == Stone.BLACK:
                black_score = result.root_score_lead
            else:
                black_score = -result.root_score_lead

        if black_score is None:
            add("Waiting for score estimate", (220, 220, 220))
        else:
            add(f"Black: {black_score:+.2f} pts")
            add(f"White: {-black_score:+.2f} pts")

            if black_score > 0:
                add(f"Leader: Black by {abs(black_score):.2f}", theme["green"])
            elif black_score < 0:
                add(f"Leader: White by {abs(black_score):.2f}", theme["green"])
            else:
                add("Leader: Even", theme["green"])

        finish(score_card)

        captures_card = card("Captures", 108)
        add(f"Black captured: {getattr(self, 'black_captures', 0)}")
        add(f"White captured: {getattr(self, 'white_captures', 0)}")
        finish(captures_card)

        learning_count = 0
        if hasattr(self, "get_self_play_memory_count"):
            try:
                learning_count = self.get_self_play_memory_count()
            except Exception:
                learning_count = 0

        if panel_rect.bottom - y > 72:
            learn_card = card("Learning", 72)
            add(f"Self-play memory: {learning_count} moves", theme["purple"])
            finish(learn_card)

    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        theme = self.ui_theme()
        self.recalculate_safe_layout()

        self.draw_vertical_gradient(self.screen, theme["background_top"], theme["background_bottom"])
        self.draw_background_vignette()

        board_size = self.board.size
        board_padding = 27

        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )

        self.draw_board_texture(board_rect)

        # Grid
        for row in range(board_size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, board_size - 1)
            width = 2 if row in [0, board_size - 1] else 1
            pygame.draw.line(self.screen, theme["grid"], (start_x, y), (end_x, y), width)

        for col in range(board_size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(board_size - 1, col)
            width = 2 if col in [0, board_size - 1] else 1
            pygame.draw.line(self.screen, theme["grid"], (x, start_y), (x, end_y), width)

        # Star points
        if board_size == 19:
            star_points = [3, 9, 15]
        elif board_size == 13:
            star_points = [3, 6, 9]
        elif board_size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, (30, 20, 10), (x, y), max(3, int(self.cell_size * 0.08)))

        self.draw_coordinates()

        if hasattr(self, "draw_analysis_markers"):
            try:
                self.draw_analysis_markers()
            except Exception as error:
                print(f"[Go Sensei Draw] Analysis markers skipped: {error}", flush=True)

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(board_size):
            for col in range(board_size):
                coordinate = point_to_human(row, col, board_size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                stone_name = getattr(stone, "name", str(stone)).upper()

                if "EMPTY" in stone_name:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK or "BLACK" in stone_name:
                    self.draw_hd_stone(x, y, "black", stone_radius)
                elif stone == Stone.WHITE or "WHITE" in stone_name:
                    self.draw_hd_stone(x, y, "white", stone_radius)

        # Hover preview
        try:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if self.board_left <= mouse_x <= self.board_right and self.board_top <= mouse_y <= self.board_bottom:
                col = round((mouse_x - self.board_left) / self.cell_size)
                row = round((mouse_y - self.board_top) / self.cell_size)

                if 0 <= row < board_size and 0 <= col < board_size:
                    coordinate = point_to_human(row, col, board_size)
                    if self.board.get(coordinate) is None:
                        x, y = self.point_to_pixels(row, col)
                        preview = pygame.Surface((stone_radius * 2 + 4, stone_radius * 2 + 4), pygame.SRCALPHA)
                        color = (20, 20, 24, 70) if self.current_player == Stone.BLACK else (255, 255, 255, 90)
                        pygame.draw.circle(preview, color, preview.get_rect().center, stone_radius)
                        self.screen.blit(preview, preview.get_rect(center=(x, y)))
        except Exception:
            pass

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (85, 165, 255), (x, y), max(7, stone_radius // 3), 3)
            pygame.draw.circle(self.screen, (255, 255, 255), (x, y), max(3, stone_radius // 7))

        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_bottom_controls()
        self.draw_size_selector()

        pygame.display.flip()


    def ui_theme(self) -> dict:
        return {
            # Flat, clean app background
            "background": (210, 154, 62),

            # Crystal-clear board colors: no grain/noise
            "board": (226, 177, 82),
            "board_edge": (96, 63, 25),
            "board_inner_highlight": (245, 205, 118),

            # Crisp grid
            "grid": (62, 43, 19),
            "grid_outer": (42, 29, 12),
            "star": (25, 18, 9),

            # Text
            "text": (22, 20, 18),
            "muted": (205, 210, 220),
            "white": (245, 245, 242),

            # Panels
            "panel": (17, 21, 28, 245),
            "panel_warm": (25, 22, 17, 245),
            "card": (44, 47, 53, 248),

            # Borders
            "panel_border_blue": (78, 158, 255),
            "panel_border_gold": (236, 195, 104),

            # Buttons
            "button": (54, 57, 66),
            "button_hover": (70, 75, 86),
            "button_border": (120, 125, 138),

            # Accents
            "green": (92, 232, 150),
            "red": (255, 116, 116),
            "gold": (255, 220, 135),
            "blue": (100, 174, 255),
            "purple": (190, 150, 255),
        }

    def draw_vertical_gradient(self, surface, top_color, bottom_color) -> None:
        # Crystal mode: no gradient noise, just a clean solid background.
        surface.fill(self.ui_theme()["background"])

    def draw_background_vignette(self) -> None:
        # Crystal mode: no vignette. Keep the screen clean.
        return

    def draw_soft_shadow_rect(self, rect, radius: int = 16, strength: int = 28) -> None:
        import pygame

        # Very soft shadow only; avoids fuzzy/grainy appearance.
        shadow = pygame.Surface((rect.width + 16, rect.height + 16), pygame.SRCALPHA)
        pygame.draw.rect(
            shadow,
            (0, 0, 0, strength),
            pygame.Rect(8, 8, rect.width, rect.height),
            border_radius=radius,
        )
        self.screen.blit(shadow, (rect.left - 4, rect.top - 2))

    def draw_panel(self, rect, fill_color, border_color, radius: int = 18) -> None:
        import pygame

        self.draw_soft_shadow_rect(rect, radius=radius, strength=36)

        panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(panel_surface, fill_color, panel_surface.get_rect(), border_radius=radius)
        self.screen.blit(panel_surface, rect.topleft)

        pygame.draw.rect(self.screen, border_color, rect, 2, border_radius=radius)

    def draw_button(self, rect, label: str, active: bool = False, accent=None) -> None:
        import pygame

        theme = self.ui_theme()
        hovered = rect.collidepoint(pygame.mouse.get_pos())

        color = theme["button_hover"] if hovered else theme["button"]

        if active:
            color = accent or (70, 110, 86)

        pygame.draw.rect(self.screen, color, rect, border_radius=8)
        pygame.draw.rect(self.screen, theme["button_border"], rect, 1, border_radius=8)

        font = getattr(self, "status_font", pygame.font.SysFont("arial", 17, bold=True))
        text_surface = font.render(label, True, theme["white"])
        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def make_hd_stone(self, stone_color: str, radius: int):
        import pygame

        # High-res antialiased stones, but clean and not textured.
        scale = 4
        size = radius * 2 + 16
        big_size = size * scale
        big_radius = radius * scale

        surface = pygame.Surface((big_size, big_size), pygame.SRCALPHA)
        center = (big_size // 2, big_size // 2)

        # Clean shadow
        pygame.draw.circle(
            surface,
            (0, 0, 0, 80),
            (center[0] + 4 * scale, center[1] + 5 * scale),
            big_radius,
        )

        if stone_color == "black":
            pygame.draw.circle(surface, (18, 19, 23), center, big_radius)
            pygame.draw.circle(surface, (50, 52, 60), center, int(big_radius * 0.72))
            pygame.draw.circle(
                surface,
                (92, 95, 108, 150),
                (center[0] - 7 * scale, center[1] - 8 * scale),
                max(4 * scale, big_radius // 5),
            )
            pygame.draw.circle(surface, (5, 5, 7), center, big_radius, max(2, scale * 2))

        else:
            pygame.draw.circle(surface, (230, 229, 222), center, big_radius)
            pygame.draw.circle(surface, (248, 248, 244), center, int(big_radius * 0.72))
            pygame.draw.circle(
                surface,
                (255, 255, 255, 220),
                (center[0] - 7 * scale, center[1] - 8 * scale),
                max(5 * scale, big_radius // 4),
            )
            pygame.draw.circle(surface, (142, 142, 136), center, big_radius, max(2, scale * 2))

        return pygame.transform.smoothscale(surface, (size, size))

    def draw_hd_stone(self, x: int, y: int, stone_color: str, radius: int) -> None:
        if not hasattr(self, "_hd_stone_cache"):
            self._hd_stone_cache = {}

        key = (stone_color, radius)

        if key not in self._hd_stone_cache:
            self._hd_stone_cache[key] = self.make_hd_stone(stone_color, radius)

        stone_surface = self._hd_stone_cache[key]
        self.screen.blit(stone_surface, stone_surface.get_rect(center=(x, y)))

    def draw_board_texture(self, board_rect) -> None:
        import pygame

        theme = self.ui_theme()

        # Clean, flat, high-definition board. No fake wood grain.
        self.draw_soft_shadow_rect(board_rect, radius=16, strength=45)

        pygame.draw.rect(self.screen, theme["board"], board_rect, border_radius=16)

        # Clean border and subtle inner highlight
        pygame.draw.rect(self.screen, theme["board_edge"], board_rect, 3, border_radius=16)
        pygame.draw.rect(self.screen, theme["board_inner_highlight"], board_rect.inflate(-10, -10), 1, border_radius=12)

    def recalculate_safe_layout(self) -> None:
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()

        self.safe_panel_width = 370
        self.safe_panel_margin = 22
        self.safe_panel_gap = 40
        self.safe_panel_top = 76
        self.safe_panel_height = min(620, screen_height - 168)

        self.safe_left_panel_left = self.safe_panel_margin
        self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

        board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
        board_area_right = self.safe_right_panel_left - self.safe_panel_gap
        board_area_width = board_area_right - board_area_left

        top_margin = 64
        bottom_margin = 136
        board_area_height = screen_height - top_margin - bottom_margin

        board_pixel_size = min(board_area_width, board_area_height)

        if board_pixel_size < 380:
            self.safe_panel_width = 318
            self.safe_panel_gap = 26
            self.safe_right_panel_left = screen_width - self.safe_panel_width - self.safe_panel_margin

            board_area_left = self.safe_left_panel_left + self.safe_panel_width + self.safe_panel_gap
            board_area_right = self.safe_right_panel_left - self.safe_panel_gap
            board_area_width = board_area_right - board_area_left
            board_pixel_size = min(board_area_width, board_area_height)

        board_pixel_size = max(320, int(board_pixel_size))

        self.board_left = int(board_area_left + (board_area_width - board_pixel_size) / 2)
        self.board_top = top_margin
        self.board_right = self.board_left + board_pixel_size
        self.board_bottom = self.board_top + board_pixel_size
        self.cell_size = board_pixel_size / (self.board.size - 1)

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        return (
            int(self.board_left + col * self.cell_size),
            int(self.board_top + row * self.cell_size),
        )

    def draw_coordinates(self) -> None:
        columns = "ABCDEFGHJKLMNOPQRST"[: self.board.size]
        number_gap = 12

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, self.board_top - 41))
            self.screen.blit(bottom, (x - bottom.get_width() // 2, self.board_bottom + 26))

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (self.board_left - number_gap - left.get_width(), y - left.get_height() // 2))
            self.screen.blit(right, (self.board_right + number_gap, y - right.get_height() // 2))

    def draw_size_selector(self) -> None:
        rect = self.get_size_selector_rect()
        self.size_selector_rect = rect
        self.draw_button(rect, f"{self.board.size} x {self.board.size}", active=False)

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 55
        h = 41
        gap = 7

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 24 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 12

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = None

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                active = True
                accent = (58, 112, 84)

            if name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = (62, 116, 82)
                elif mode == "human_white":
                    active = True
                    accent = (64, 88, 130)
                elif mode == "self_play":
                    active = True
                    accent = (118, 78, 142)

            self.draw_button(rect, label, active=active, accent=accent)

            x += w + gap

    def draw(self) -> None:
        import pygame
        from app.core.coordinates import point_to_human
        from app.core.stone import Stone

        theme = self.ui_theme()
        self.recalculate_safe_layout()

        # Clean solid background
        self.screen.fill(theme["background"])

        board_size = self.board.size
        board_padding = 27

        board_rect = pygame.Rect(
            self.board_left - board_padding,
            self.board_top - board_padding,
            (self.board_right - self.board_left) + board_padding * 2,
            (self.board_bottom - self.board_top) + board_padding * 2,
        )

        self.draw_board_texture(board_rect)

        # Crisp grid lines
        for row in range(board_size):
            start_x, y = self.point_to_pixels(row, 0)
            end_x, _ = self.point_to_pixels(row, board_size - 1)

            width = 2 if row in [0, board_size - 1] else 1
            color = theme["grid_outer"] if row in [0, board_size - 1] else theme["grid"]

            pygame.draw.line(self.screen, color, (start_x, y), (end_x, y), width)

        for col in range(board_size):
            x, start_y = self.point_to_pixels(0, col)
            _, end_y = self.point_to_pixels(board_size - 1, col)

            width = 2 if col in [0, board_size - 1] else 1
            color = theme["grid_outer"] if col in [0, board_size - 1] else theme["grid"]

            pygame.draw.line(self.screen, color, (x, start_y), (x, end_y), width)

        # Star points
        if board_size == 19:
            star_points = [3, 9, 15]
        elif board_size == 13:
            star_points = [3, 6, 9]
        elif board_size == 9:
            star_points = [2, 4, 6]
        else:
            star_points = []

        for row in star_points:
            for col in star_points:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, theme["star"], (x, y), max(3, int(self.cell_size * 0.08)))

        self.draw_coordinates()

        if hasattr(self, "draw_analysis_markers"):
            try:
                self.draw_analysis_markers()
            except Exception as error:
                print(f"[Go Sensei Draw] Analysis markers skipped: {error}", flush=True)

        # Stones
        stone_radius = max(10, int(self.cell_size * 0.42))

        for row in range(board_size):
            for col in range(board_size):
                coordinate = point_to_human(row, col, board_size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                if stone is None:
                    continue

                stone_name = getattr(stone, "name", str(stone)).upper()

                if "EMPTY" in stone_name:
                    continue

                x, y = self.point_to_pixels(row, col)

                if stone == Stone.BLACK or "BLACK" in stone_name:
                    self.draw_hd_stone(x, y, "black", stone_radius)
                elif stone == Stone.WHITE or "WHITE" in stone_name:
                    self.draw_hd_stone(x, y, "white", stone_radius)

        # Hover preview
        try:
            mouse_x, mouse_y = pygame.mouse.get_pos()

            if self.board_left <= mouse_x <= self.board_right and self.board_top <= mouse_y <= self.board_bottom:
                col = round((mouse_x - self.board_left) / self.cell_size)
                row = round((mouse_y - self.board_top) / self.cell_size)

                if 0 <= row < board_size and 0 <= col < board_size:
                    coordinate = point_to_human(row, col, board_size)

                    if self.board.get(coordinate) is None:
                        x, y = self.point_to_pixels(row, col)
                        preview = pygame.Surface((stone_radius * 2 + 4, stone_radius * 2 + 4), pygame.SRCALPHA)

                        color = (20, 20, 24, 60) if self.current_player == Stone.BLACK else (255, 255, 255, 90)
                        pygame.draw.circle(preview, color, preview.get_rect().center, stone_radius)

                        self.screen.blit(preview, preview.get_rect(center=(x, y)))
        except Exception:
            pass

        # Last move marker
        if getattr(self, "last_move", None) is not None:
            row, col = self.last_move
            x, y = self.point_to_pixels(row, col)
            pygame.draw.circle(self.screen, (80, 160, 255), (x, y), max(7, stone_radius // 3), 3)
            pygame.draw.circle(self.screen, (255, 255, 255), (x, y), max(3, stone_radius // 7))

        self.draw_coach_panel()
        self.draw_analysis_panel()
        self.draw_bottom_controls()
        self.draw_size_selector()

        pygame.display.flip()


    def get_analysis_depth(self) -> int:
        return int(getattr(self, "analysis_depth", 12))

    def set_analysis_depth(self, value: int) -> None:
        value = max(3, min(40, int(value)))
        self.analysis_depth = value
        self.status_message = f"Variation depth set to {value}"

        print(f"[Go Sensei Analysis] PV depth set to {value}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def increase_analysis_depth(self) -> None:
        self.set_analysis_depth(self.get_analysis_depth() + 2)

    def decrease_analysis_depth(self) -> None:
        self.set_analysis_depth(self.get_analysis_depth() - 2)

    def apply_analysis_depth_to_katago(self) -> None:
        depth = self.get_analysis_depth()
        service = getattr(self, "analysis_service", None)

        if service is None:
            return

        candidates = [
            service,
            getattr(service, "client", None),
            getattr(service, "katago_client", None),
            getattr(service, "_client", None),
        ]

        for candidate in candidates:
            if candidate is None:
                continue

            settings = getattr(candidate, "settings", None)

            if settings is not None and hasattr(settings, "analysis_pv_len"):
                settings.analysis_pv_len = depth
                print(f"[Go Sensei Analysis] Applied PV depth {depth}", flush=True)
                return

    def request_live_analysis(self) -> int | None:
        if not hasattr(self, "analysis_service"):
            print("[Go Sensei Board] No analysis service available.", flush=True)
            return None

        self.apply_analysis_depth_to_katago()

        print(
            f"[Go Sensei Board] Sending board to KataGo: player={self.current_player.name}, rules=chinese, komi=7.5, perspective=BLACK, pv_depth={self.get_analysis_depth()}",
            flush=True,
        )

        return self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.current_player,
        )

    def stable_black_winrate(self, result) -> float | None:
        if result is None:
            return None

        value = getattr(result, "root_winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def stable_white_winrate(self, result) -> float | None:
        black = self.stable_black_winrate(result)

        if black is None:
            return None

        return 100.0 - black

    def stable_black_score_lead(self, result) -> float | None:
        if result is None:
            return None

        value = getattr(result, "root_score_lead", None)

        if value is None:
            return None

        return float(value)

    def move_black_winrate(self, move_info) -> float | None:
        value = getattr(move_info, "winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def move_white_winrate(self, move_info) -> float | None:
        black = self.move_black_winrate(move_info)

        if black is None:
            return None

        return 100.0 - black

    def move_black_score_lead(self, move_info) -> float | None:
        value = getattr(move_info, "score_lead", None)

        if value is None:
            return None

        return float(value)

    def get_top_recommended_moves(self, limit: int = 5):
        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        if result is None:
            return []

        moves = []

        for move_info in getattr(result, "best_moves", [])[:limit]:
            move = getattr(move_info, "move", "")

            if not move or move.lower() == "pass":
                continue

            moves.append(move_info)

        return moves

    def format_score_owner(self, black_score: float | None) -> str:
        if black_score is None:
            return "No score yet"

        if black_score > 0:
            return f"Black by {abs(black_score):.2f}"

        if black_score < 0:
            return f"White by {abs(black_score):.2f}"

        return "Even"

    def format_pv_line(self, move_info, max_len: int | None = None) -> str:
        pv = getattr(move_info, "pv", None)

        if not pv:
            return ""

        if max_len is None:
            max_len = self.get_analysis_depth()

        pv = list(pv)[:max_len]

        return " → ".join(str(move) for move in pv)

    def draw_analysis_depth_widget(self, x: int, y: int, width: int) -> int:
        import pygame

        theme = self.ui_theme()

        label = self.small_ui_font.render("Variation Depth", True, theme["gold"])
        self.screen.blit(label, (x, y))
        y += 24

        minus_rect = pygame.Rect(x, y, 34, 30)
        plus_rect = pygame.Rect(x + width - 34, y, 34, 30)
        value_rect = pygame.Rect(x + 42, y, width - 84, 30)

        self.analysis_depth_minus_rect = minus_rect
        self.analysis_depth_plus_rect = plus_rect

        pygame.draw.rect(self.screen, theme["button"], minus_rect, border_radius=7)
        pygame.draw.rect(self.screen, theme["button"], plus_rect, border_radius=7)
        pygame.draw.rect(self.screen, (35, 37, 43), value_rect, border_radius=7)

        pygame.draw.rect(self.screen, theme["button_border"], minus_rect, 1, border_radius=7)
        pygame.draw.rect(self.screen, theme["button_border"], plus_rect, 1, border_radius=7)
        pygame.draw.rect(self.screen, theme["button_border"], value_rect, 1, border_radius=7)

        minus = self.status_font.render("-", True, theme["white"])
        plus = self.status_font.render("+", True, theme["white"])
        value = self.small_ui_font.render(f"{self.get_analysis_depth()} moves", True, theme["white"])

        self.screen.blit(minus, minus.get_rect(center=minus_rect.center))
        self.screen.blit(plus, plus.get_rect(center=plus_rect.center))
        self.screen.blit(value, value.get_rect(center=value_rect.center))

        return y + 42

    def draw_analysis_markers(self) -> None:
        import pygame
        from app.core.coordinates import human_to_point

        top_moves = self.get_top_recommended_moves(limit=5)
        self.recommended_marker_targets = []

        if not top_moves:
            return

        colors = [
            (80, 165, 255),
            (85, 220, 180),
            (255, 210, 110),
            (200, 150, 255),
            (255, 140, 120),
        ]

        for index, move_info in enumerate(top_moves):
            move = getattr(move_info, "move", "")

            try:
                row, col = human_to_point(move, self.board.size)
                x, y = self.point_to_pixels(row, col)
            except Exception:
                continue

            radius = max(11, int(self.cell_size * 0.23))
            color = colors[index % len(colors)]

            marker_surface = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
            center = marker_surface.get_rect().center

            pygame.draw.circle(marker_surface, (*color, 210), center, radius)
            pygame.draw.circle(marker_surface, (255, 255, 255, 235), center, radius, 2)

            label = self.small_ui_font.render(str(index + 1), True, (15, 18, 24))
            marker_surface.blit(label, label.get_rect(center=center))

            self.screen.blit(marker_surface, marker_surface.get_rect(center=(x, y)))

            target_rect = pygame.Rect(x - radius - 6, y - radius - 6, radius * 2 + 12, radius * 2 + 12)
            self.recommended_marker_targets.append((target_rect, index + 1, move_info))

    def get_hovered_recommendation(self):
        import pygame

        mouse_pos = pygame.mouse.get_pos()

        for rect, rank, move_info in getattr(self, "recommended_move_rects", []):
            if rect.collidepoint(mouse_pos):
                return rank, move_info

        for rect, rank, move_info in getattr(self, "recommended_marker_targets", []):
            if rect.collidepoint(mouse_pos):
                return rank, move_info

        return None, None

    def draw_variation_tooltip(self) -> None:
        import pygame

        rank, move_info = self.get_hovered_recommendation()

        if move_info is None:
            return

        mouse_x, mouse_y = pygame.mouse.get_pos()
        width = 380
        height = 158

        x = mouse_x + 18
        y = mouse_y + 18

        if x + width > self.screen.get_width() - 10:
            x = mouse_x - width - 18

        if y + height > self.screen.get_height() - 10:
            y = mouse_y - height - 18

        rect = pygame.Rect(x, y, width, height)

        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(surface, (18, 22, 30, 248), surface.get_rect(), border_radius=12)
        self.screen.blit(surface, rect.topleft)

        pygame.draw.rect(self.screen, (120, 180, 255), rect, 2, border_radius=12)

        tx = rect.left + 14
        ty = rect.top + 12

        move = getattr(move_info, "move", "")
        black = self.move_black_winrate(move_info)
        white = self.move_white_winrate(move_info)
        score = self.move_black_score_lead(move_info)
        visits = getattr(move_info, "visits", None)
        pv = self.format_pv_line(move_info, self.get_analysis_depth())

        title = self.status_font.render(f"#{rank} {move}", True, (120, 185, 255))
        self.screen.blit(title, (tx, ty))
        ty += 28

        if black is not None and white is not None:
            line = self.small_ui_font.render(f"Black {black:.1f}%   White {white:.1f}%", True, (245, 245, 245))
            self.screen.blit(line, (tx, ty))
            ty += 22

        if score is not None:
            line = self.small_ui_font.render(f"Score: {self.format_score_owner(score)}", True, (255, 220, 135))
            self.screen.blit(line, (tx, ty))
            ty += 22

        if visits is not None:
            line = self.small_ui_font.render(f"Visits: {visits}", True, (205, 210, 220))
            self.screen.blit(line, (tx, ty))
            ty += 22

        if pv:
            if len(pv) > 68:
                pv = pv[:65] + "..."

            line = self.small_ui_font.render(f"PV: {pv}", True, (205, 225, 255))
            self.screen.blit(line, (tx, ty))

    def draw_analysis_panel(self) -> None:
        import pygame

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_right_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel_warm"], theme["panel_border_gold"], radius=18)

        x = panel_rect.left + 18
        y = panel_rect.top + 16
        content_width = panel_rect.width - 36

        title_surface = self.status_font.render("KataGo Analysis", True, theme["gold"])
        self.screen.blit(title_surface, (x, y))
        y += 30

        rules = self.small_ui_font.render("Rules: Chinese   Komi: 7.5   Perspective: Black", True, (235, 220, 180))
        self.screen.blit(rules, (x, y))
        y += 28

        y = self.draw_analysis_depth_widget(x, y, content_width)
        y += 4

        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        engine_color = theme["green"] if getattr(self, "analysis_enabled", False) else theme["red"]
        engine_text = "Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF"
        engine_surface = self.small_ui_font.render(engine_text, True, engine_color)
        self.screen.blit(engine_surface, (x, y))
        y += 28

        black_winrate = self.stable_black_winrate(result)
        white_winrate = self.stable_white_winrate(result)
        black_score = self.stable_black_score_lead(result)

        def card(title: str, height: int):
            nonlocal y
            rect = pygame.Rect(x - 4, y, content_width + 8, height)
            card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(card_surface, theme["card"], card_surface.get_rect(), border_radius=12)
            self.screen.blit(card_surface, rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 48), rect, 1, border_radius=12)

            title_surface = self.small_ui_font.render(title, True, theme["gold"])
            self.screen.blit(title_surface, (rect.left + 12, rect.top + 9))

            y = rect.top + 34
            return rect

        def add(text_value: str, color=None, gap=21):
            nonlocal y

            if color is None:
                color = theme["white"]

            surface = self.small_ui_font.render(text_value, True, color)
            self.screen.blit(surface, (x + 8, y))
            y += gap

        def finish(rect):
            nonlocal y
            y = rect.bottom + 12

        state_card = card("Stable game state", 118)

        if result is None:
            if state is not None and getattr(state, "is_thinking", False):
                add("Thinking...", theme["blue"])
            else:
                add("Click ANALYZE to evaluate", theme["muted"])
        else:
            add(f"Black: {black_winrate:.1f}%" if black_winrate is not None else "Black: --")
            add(f"White: {white_winrate:.1f}%" if white_winrate is not None else "White: --")
            add(f"Score: {self.format_score_owner(black_score)}", theme["gold"])

            if black_winrate is not None:
                bar = pygame.Rect(x + 8, y + 2, content_width - 16, 16)
                pygame.draw.rect(self.screen, (235, 235, 230), bar, border_radius=8)

                black_rect = pygame.Rect(bar.left, bar.top, int(bar.width * black_winrate / 100.0), bar.height)
                pygame.draw.rect(self.screen, (24, 24, 28), black_rect, border_radius=8)
                pygame.draw.rect(self.screen, theme["gold"], bar, 1, border_radius=8)

        finish(state_card)

        top_card = card("Top 5 recommended moves", 254)
        self.recommended_move_rects = []

        top_moves = self.get_top_recommended_moves(limit=5)

        if not top_moves:
            add("No recommendations yet", theme["muted"])
        else:
            row_h = 40

            for index, move_info in enumerate(top_moves):
                rank = index + 1
                move = getattr(move_info, "move", "")
                black = self.move_black_winrate(move_info)
                score = self.move_black_score_lead(move_info)
                visits = getattr(move_info, "visits", None)

                row_rect = pygame.Rect(x + 4, y - 3, content_width - 8, row_h - 4)
                hovered = row_rect.collidepoint(pygame.mouse.get_pos())
                row_color = (65, 70, 82, 255) if hovered else (37, 40, 47, 255)

                pygame.draw.rect(self.screen, row_color, row_rect, border_radius=8)

                move_text = f"#{rank} {move}"

                if black is not None:
                    move_text += f"   B {black:.1f}%"

                if score is not None:
                    move_text += f"   {self.format_score_owner(score)}"

                surface = self.small_ui_font.render(move_text, True, theme["white"])
                self.screen.blit(surface, (row_rect.left + 10, row_rect.top + 5))

                if visits is not None:
                    visit_surface = self.small_ui_font.render(f"{visits} visits", True, theme["muted"])
                    self.screen.blit(visit_surface, (row_rect.left + 10, row_rect.top + 22))

                self.recommended_move_rects.append((row_rect, rank, move_info))
                y += row_h

        finish(top_card)

        self.draw_variation_tooltip()

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        minus_rect = getattr(self, "analysis_depth_minus_rect", None)
        plus_rect = getattr(self, "analysis_depth_plus_rect", None)

        if minus_rect is not None and minus_rect.collidepoint(mouse_pos):
            self.decrease_analysis_depth()
            return

        if plus_rect is not None and plus_rect.collidepoint(mouse_pos):
            self.increase_analysis_depth()
            return

        size_rect = self.get_size_selector_rect()

        if size_rect.collidepoint(mouse_pos):
            print("[Go Sensei UI] Size button clicked", flush=True)
            self.cycle_board_size()
            return

        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                print(f"[Go Sensei UI] Bottom button clicked: {button_name}", flush=True)
                self.handle_button_click(button_name)
                return

        self.handle_board_click(mouse_pos)


    def get_analysis_depth(self) -> int:
        return int(getattr(self, "analysis_depth", 12))

    def set_analysis_depth(self, value: int) -> None:
        value = max(3, min(60, int(value)))
        self.analysis_depth = value
        self.status_message = f"Variation depth set to {value} moves"

        print(f"[Go Sensei Analysis] Variation depth set to {value}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def increase_analysis_depth(self) -> None:
        self.set_analysis_depth(self.get_analysis_depth() + 2)

    def decrease_analysis_depth(self) -> None:
        self.set_analysis_depth(self.get_analysis_depth() - 2)

    def apply_analysis_depth_to_katago(self) -> None:
        depth = self.get_analysis_depth()
        service = getattr(self, "analysis_service", None)

        if service is None:
            return

        candidates = [
            service,
            getattr(service, "client", None),
            getattr(service, "katago_client", None),
            getattr(service, "_client", None),
        ]

        for candidate in candidates:
            if candidate is None:
                continue

            settings = getattr(candidate, "settings", None)

            if settings is not None and hasattr(settings, "analysis_pv_len"):
                settings.analysis_pv_len = depth
                print(f"[Go Sensei Analysis] Applied PV depth {depth} to KataGo", flush=True)
                return

    def request_live_analysis(self) -> int | None:
        if not hasattr(self, "analysis_service"):
            print("[Go Sensei Board] No analysis service available.", flush=True)
            return None

        self.apply_analysis_depth_to_katago()

        print(
            f"[Go Sensei Board] Sending board to KataGo: player={self.current_player.name}, rules=chinese, komi=7.5, perspective=BLACK, pv_depth={self.get_analysis_depth()}",
            flush=True,
        )

        return self.analysis_service.request_analysis(
            board=self.board,
            current_player=self.current_player,
        )

    def stable_black_winrate(self, result) -> float | None:
        # Sound-proof display rule:
        # KataGo config is forced to reportAnalysisWinratesAs = BLACK.
        # Therefore root_winrate_percent ALWAYS means Black's win chance.
        if result is None:
            return None

        value = getattr(result, "root_winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def stable_white_winrate(self, result) -> float | None:
        black = self.stable_black_winrate(result)

        if black is None:
            return None

        return 100.0 - black

    def stable_black_score_lead(self, result) -> float | None:
        # Sound-proof display rule:
        # positive scoreLead = Black ahead
        # negative scoreLead = White ahead
        if result is None:
            return None

        value = getattr(result, "root_score_lead", None)

        if value is None:
            return None

        return float(value)

    def move_black_winrate(self, move_info) -> float | None:
        value = getattr(move_info, "winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def move_white_winrate(self, move_info) -> float | None:
        black = self.move_black_winrate(move_info)

        if black is None:
            return None

        return 100.0 - black

    def move_black_score_lead(self, move_info) -> float | None:
        value = getattr(move_info, "score_lead", None)

        if value is None:
            return None

        return float(value)

    def format_score_owner(self, black_score: float | None) -> str:
        if black_score is None:
            return "No score yet"

        if black_score > 0:
            return f"Black by {abs(black_score):.2f}"

        if black_score < 0:
            return f"White by {abs(black_score):.2f}"

        return "Even"

    def get_top_recommended_moves(self, limit: int = 5):
        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        if result is None:
            return []

        moves = []

        for move_info in getattr(result, "best_moves", [])[:limit]:
            move = getattr(move_info, "move", "")

            if not move or move.lower() == "pass":
                continue

            moves.append(move_info)

        return moves

    def format_pv_line(self, move_info, max_len: int | None = None) -> str:
        pv = getattr(move_info, "pv", None)

        if not pv:
            return ""

        if max_len is None:
            max_len = self.get_analysis_depth()

        pv = list(pv)[:max_len]

        return " → ".join(str(move) for move in pv)

    def draw_analysis_depth_widget(self, x: int, y: int, width: int) -> int:
        import pygame

        theme = self.ui_theme()

        label = self.small_ui_font.render("Variation Depth", True, theme["gold"])
        self.screen.blit(label, (x, y))
        y += 24

        minus_rect = pygame.Rect(x, y, 36, 30)
        plus_rect = pygame.Rect(x + width - 36, y, 36, 30)
        value_rect = pygame.Rect(x + 44, y, width - 88, 30)

        self.analysis_depth_minus_rect = minus_rect
        self.analysis_depth_plus_rect = plus_rect

        pygame.draw.rect(self.screen, theme["button"], minus_rect, border_radius=7)
        pygame.draw.rect(self.screen, theme["button"], plus_rect, border_radius=7)
        pygame.draw.rect(self.screen, (35, 37, 43), value_rect, border_radius=7)

        pygame.draw.rect(self.screen, theme["button_border"], minus_rect, 1, border_radius=7)
        pygame.draw.rect(self.screen, theme["button_border"], plus_rect, 1, border_radius=7)
        pygame.draw.rect(self.screen, theme["button_border"], value_rect, 1, border_radius=7)

        minus = self.status_font.render("-", True, theme["white"])
        plus = self.status_font.render("+", True, theme["white"])
        value = self.small_ui_font.render(f"{self.get_analysis_depth()} moves", True, theme["white"])

        self.screen.blit(minus, minus.get_rect(center=minus_rect.center))
        self.screen.blit(plus, plus.get_rect(center=plus_rect.center))
        self.screen.blit(value, value.get_rect(center=value_rect.center))

        return y + 42

    def draw_analysis_markers(self) -> None:
        import pygame
        from app.core.coordinates import human_to_point

        top_moves = self.get_top_recommended_moves(limit=5)
        self.recommended_marker_targets = []

        if not top_moves:
            return

        colors = [
            (80, 165, 255),
            (85, 220, 180),
            (255, 210, 110),
            (200, 150, 255),
            (255, 140, 120),
        ]

        for index, move_info in enumerate(top_moves):
            move = getattr(move_info, "move", "")

            try:
                row, col = human_to_point(move, self.board.size)
                x, y = self.point_to_pixels(row, col)
            except Exception:
                continue

            radius = max(11, int(self.cell_size * 0.23))
            color = colors[index % len(colors)]

            marker_surface = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
            center = marker_surface.get_rect().center

            pygame.draw.circle(marker_surface, (*color, 210), center, radius)
            pygame.draw.circle(marker_surface, (255, 255, 255, 235), center, radius, 2)

            label = self.small_ui_font.render(str(index + 1), True, (15, 18, 24))
            marker_surface.blit(label, label.get_rect(center=center))

            self.screen.blit(marker_surface, marker_surface.get_rect(center=(x, y)))

            target_rect = pygame.Rect(x - radius - 8, y - radius - 8, radius * 2 + 16, radius * 2 + 16)
            self.recommended_marker_targets.append((target_rect, index + 1, move_info))

    def get_hovered_recommendation(self):
        import pygame

        mouse_pos = pygame.mouse.get_pos()

        for rect, rank, move_info in getattr(self, "recommended_move_rects", []):
            if rect.collidepoint(mouse_pos):
                return rank, move_info

        for rect, rank, move_info in getattr(self, "recommended_marker_targets", []):
            if rect.collidepoint(mouse_pos):
                return rank, move_info

        return None, None

    def draw_variation_tooltip(self) -> None:
        import pygame

        rank, move_info = self.get_hovered_recommendation()

        if move_info is None:
            return

        mouse_x, mouse_y = pygame.mouse.get_pos()
        width = 400
        height = 164

        x = mouse_x + 18
        y = mouse_y + 18

        if x + width > self.screen.get_width() - 10:
            x = mouse_x - width - 18

        if y + height > self.screen.get_height() - 10:
            y = mouse_y - height - 18

        rect = pygame.Rect(x, y, width, height)

        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(surface, (18, 22, 30, 250), surface.get_rect(), border_radius=12)
        self.screen.blit(surface, rect.topleft)

        pygame.draw.rect(self.screen, (120, 180, 255), rect, 2, border_radius=12)

        tx = rect.left + 14
        ty = rect.top + 12

        move = getattr(move_info, "move", "")
        black = self.move_black_winrate(move_info)
        white = self.move_white_winrate(move_info)
        score = self.move_black_score_lead(move_info)
        visits = getattr(move_info, "visits", None)
        pv = self.format_pv_line(move_info, self.get_analysis_depth())

        title = self.status_font.render(f"#{rank} candidate: {move}", True, (120, 185, 255))
        self.screen.blit(title, (tx, ty))
        ty += 30

        if black is not None and white is not None:
            line = self.small_ui_font.render(f"If played: Black {black:.1f}%   White {white:.1f}%", True, (245, 245, 245))
            self.screen.blit(line, (tx, ty))
            ty += 23

        if score is not None:
            line = self.small_ui_font.render(f"Expected score: {self.format_score_owner(score)}", True, (255, 220, 135))
            self.screen.blit(line, (tx, ty))
            ty += 23

        if visits is not None:
            line = self.small_ui_font.render(f"Search visits: {visits}", True, (205, 210, 220))
            self.screen.blit(line, (tx, ty))
            ty += 23

        if pv:
            if len(pv) > 72:
                pv = pv[:69] + "..."

            line = self.small_ui_font.render(f"Variation: {pv}", True, (205, 225, 255))
            self.screen.blit(line, (tx, ty))

    def draw_analysis_panel(self) -> None:
        import pygame

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_right_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel_warm"], theme["panel_border_gold"], radius=18)

        x = panel_rect.left + 18
        y = panel_rect.top + 16
        content_width = panel_rect.width - 36

        title_surface = self.status_font.render("KataGo Analysis", True, theme["gold"])
        self.screen.blit(title_surface, (x, y))
        y += 30

        rules = self.small_ui_font.render("Rules: Chinese   Komi: 7.5   Perspective: Black", True, (235, 220, 180))
        self.screen.blit(rules, (x, y))
        y += 28

        y = self.draw_analysis_depth_widget(x, y, content_width)
        y += 4

        state = getattr(self, "analysis_state", None)
        result = getattr(state, "latest_result", None) if state is not None else None

        engine_color = theme["green"] if getattr(self, "analysis_enabled", False) else theme["red"]
        engine_text = "Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF"
        engine_surface = self.small_ui_font.render(engine_text, True, engine_color)
        self.screen.blit(engine_surface, (x, y))
        y += 28

        black_winrate = self.stable_black_winrate(result)
        white_winrate = self.stable_white_winrate(result)
        black_score = self.stable_black_score_lead(result)

        def card(title: str, height: int):
            nonlocal y
            rect = pygame.Rect(x - 4, y, content_width + 8, height)
            card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(card_surface, theme["card"], card_surface.get_rect(), border_radius=12)
            self.screen.blit(card_surface, rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 48), rect, 1, border_radius=12)

            title_surface = self.small_ui_font.render(title, True, theme["gold"])
            self.screen.blit(title_surface, (rect.left + 12, rect.top + 9))

            y = rect.top + 34
            return rect

        def add(text_value: str, color=None, gap=21):
            nonlocal y

            if color is None:
                color = theme["white"]

            surface = self.small_ui_font.render(text_value, True, color)
            self.screen.blit(surface, (x + 8, y))
            y += gap

        def finish(rect):
            nonlocal y
            y = rect.bottom + 12

        state_card = card("Stable game state", 118)

        if result is None:
            if state is not None and getattr(state, "is_thinking", False):
                add("Thinking...", theme["blue"])
            else:
                add("Click ANALYZE to evaluate", theme["muted"])
        else:
            add(f"Black: {black_winrate:.1f}%" if black_winrate is not None else "Black: --")
            add(f"White: {white_winrate:.1f}%" if white_winrate is not None else "White: --")
            add(f"Score: {self.format_score_owner(black_score)}", theme["gold"])

            if black_winrate is not None:
                bar = pygame.Rect(x + 8, y + 2, content_width - 16, 16)
                pygame.draw.rect(self.screen, (235, 235, 230), bar, border_radius=8)

                black_rect = pygame.Rect(bar.left, bar.top, int(bar.width * black_winrate / 100.0), bar.height)
                pygame.draw.rect(self.screen, (24, 24, 28), black_rect, border_radius=8)
                pygame.draw.rect(self.screen, theme["gold"], bar, 1, border_radius=8)

        finish(state_card)

        top_card = card("Top 5 recommended moves", 254)
        self.recommended_move_rects = []

        top_moves = self.get_top_recommended_moves(limit=5)

        if not top_moves:
            add("No recommendations yet", theme["muted"])
        else:
            row_h = 40

            for index, move_info in enumerate(top_moves):
                rank = index + 1
                move = getattr(move_info, "move", "")
                black = self.move_black_winrate(move_info)
                score = self.move_black_score_lead(move_info)
                visits = getattr(move_info, "visits", None)

                row_rect = pygame.Rect(x + 4, y - 3, content_width - 8, row_h - 4)
                hovered = row_rect.collidepoint(pygame.mouse.get_pos())
                row_color = (65, 70, 82, 255) if hovered else (37, 40, 47, 255)

                pygame.draw.rect(self.screen, row_color, row_rect, border_radius=8)

                move_text = f"#{rank} {move}"

                if black is not None:
                    move_text += f"   B {black:.1f}%"

                if score is not None:
                    move_text += f"   {self.format_score_owner(score)}"

                surface = self.small_ui_font.render(move_text, True, theme["white"])
                self.screen.blit(surface, (row_rect.left + 10, row_rect.top + 5))

                if visits is not None:
                    visit_surface = self.small_ui_font.render(f"{visits} visits", True, theme["muted"])
                    self.screen.blit(visit_surface, (row_rect.left + 10, row_rect.top + 22))

                self.recommended_move_rects.append((row_rect, rank, move_info))
                y += row_h

        finish(top_card)

        self.draw_variation_tooltip()

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        minus_rect = getattr(self, "analysis_depth_minus_rect", None)
        plus_rect = getattr(self, "analysis_depth_plus_rect", None)

        if minus_rect is not None and minus_rect.collidepoint(mouse_pos):
            self.decrease_analysis_depth()
            return

        if plus_rect is not None and plus_rect.collidepoint(mouse_pos):
            self.increase_analysis_depth()
            return

        size_rect = self.get_size_selector_rect()

        if size_rect.collidepoint(mouse_pos):
            print("[Go Sensei UI] Size button clicked", flush=True)
            self.cycle_board_size()
            return

        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                print(f"[Go Sensei UI] Bottom button clicked: {button_name}", flush=True)
                self.handle_button_click(button_name)
                return

        self.handle_board_click(mouse_pos)


    def apply_analysis_depth_to_katago(self) -> None:
        from dataclasses import replace

        depth = self.get_analysis_depth() if hasattr(self, "get_analysis_depth") else 12
        service = getattr(self, "analysis_service", None)

        if service is None:
            return

        candidates = [
            service,
            getattr(service, "client", None),
            getattr(service, "katago_client", None),
            getattr(service, "_client", None),
        ]

        for candidate in candidates:
            if candidate is None:
                continue

            settings = getattr(candidate, "settings", None)

            if settings is None:
                continue

            if not hasattr(settings, "analysis_pv_len"):
                continue

            try:
                new_settings = replace(settings, analysis_pv_len=depth)
                candidate.settings = new_settings
                print(f"[Go Sensei Analysis] Applied PV depth {depth} with dataclass replace", flush=True)
                return
            except Exception as error:
                print(f"[Go Sensei Analysis] Could not update PV depth on this object: {error}", flush=True)

        print("[Go Sensei Analysis] PV depth kept as default because settings could not be updated.", flush=True)

    def request_live_analysis(self) -> int | None:
        try:
            if not hasattr(self, "analysis_service"):
                print("[Go Sensei Board] No analysis service available.", flush=True)
                self.status_message = "No analysis service available"
                return None

            if hasattr(self, "apply_analysis_depth_to_katago"):
                self.apply_analysis_depth_to_katago()

            depth = self.get_analysis_depth() if hasattr(self, "get_analysis_depth") else 12

            print(
                f"[Go Sensei Board] Sending board to KataGo: player={self.current_player.name}, rules=chinese, komi=7.5, perspective=BLACK, pv_depth={depth}",
                flush=True,
            )

            return self.analysis_service.request_analysis(
                board=self.board,
                current_player=self.current_player,
            )

        except Exception as error:
            self.status_message = f"Analyze error: {error}"
            print(f"[Go Sensei Analyze Error] {type(error).__name__}: {error}", flush=True)
            return None

    def toggle_live_analysis(self) -> None:
        try:
            self.analysis_enabled = not getattr(self, "analysis_enabled", False)

            if self.analysis_enabled:
                self.status_message = "Analysis ON - Chinese rules, komi 7.5"
                print("[Go Sensei Board] Analysis ON - Chinese rules, komi 7.5", flush=True)
                self.request_live_analysis()
            else:
                self.status_message = "Analysis OFF"
                print("[Go Sensei Board] Analysis OFF", flush=True)

        except Exception as error:
            self.analysis_enabled = False
            self.status_message = f"Analyze error: {error}"
            print(f"[Go Sensei Analyze Toggle Error] {type(error).__name__}: {error}", flush=True)


    def get_analysis_depth(self) -> int:
        return int(getattr(self, "analysis_depth", 18))

    def set_analysis_depth(self, value: int) -> None:
        value = max(3, min(80, int(value)))
        self.analysis_depth = value
        self.status_message = f"Variation depth set to {value} moves"
        print(f"[Go Sensei Analysis] Variation depth set to {value}", flush=True)

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def increase_analysis_depth(self) -> None:
        self.set_analysis_depth(self.get_analysis_depth() + 5)

    def decrease_analysis_depth(self) -> None:
        self.set_analysis_depth(self.get_analysis_depth() - 5)

    def apply_analysis_depth_to_katago(self) -> None:
        from dataclasses import replace

        depth = self.get_analysis_depth()
        service = getattr(self, "analysis_service", None)

        if service is None:
            return

        candidates = [
            service,
            getattr(service, "client", None),
            getattr(service, "katago_client", None),
            getattr(service, "_client", None),
        ]

        for candidate in candidates:
            if candidate is None:
                continue

            settings = getattr(candidate, "settings", None)

            if settings is None or not hasattr(settings, "analysis_pv_len"):
                continue

            try:
                candidate.settings = replace(settings, analysis_pv_len=depth)
                print(f"[Go Sensei Analysis] Applied PV depth {depth}", flush=True)
                return
            except Exception as error:
                print(f"[Go Sensei Analysis] Could not update depth here: {error}", flush=True)

    def request_live_analysis(self) -> int | None:
        try:
            if not hasattr(self, "analysis_service"):
                self.status_message = "No analysis service available"
                print("[Go Sensei Board] No analysis service available.", flush=True)
                return None

            self.apply_analysis_depth_to_katago()

            request_id = self.analysis_service.request_analysis(
                board=self.board,
                current_player=self.current_player,
            )

            self.main_analysis_request_id = request_id

            print(
                f"[Go Sensei Board] Main analysis request #{request_id}: player={self.current_player.name}, rules=chinese, komi=7.5, perspective=BLACK, depth={self.get_analysis_depth()}",
                flush=True,
            )

            return request_id

        except Exception as error:
            self.status_message = f"Analyze error: {error}"
            print(f"[Go Sensei Analyze Error] {type(error).__name__}: {error}", flush=True)
            return None

    def route_analysis_state(self) -> None:
        state = getattr(self, "analysis_state", None)

        if state is None:
            return

        result = getattr(state, "latest_result", None)
        completed_id = getattr(state, "completed_request_id", None)

        if result is None or completed_id is None:
            return

        hover_pending_id = getattr(self, "hover_analysis_pending_id", None)
        main_pending_id = getattr(self, "main_analysis_request_id", None)

        if hover_pending_id is not None and completed_id == hover_pending_id:
            key = getattr(self, "hover_analysis_pending_key", None)

            if key is not None:
                if not hasattr(self, "hover_analysis_cache"):
                    self.hover_analysis_cache = {}

                self.hover_analysis_cache[key] = result
                print(f"[Go Sensei Hover] Cached hover analysis for {key[-1]}", flush=True)

            self.hover_analysis_pending_id = None
            self.hover_analysis_pending_key = None
            return

        if main_pending_id is not None and completed_id == main_pending_id:
            self.position_analysis_result = result
            print(f"[Go Sensei Analysis] Stored stable main result #{completed_id}", flush=True)
            return

        # Fallback: if there is no stored main result yet, keep the latest result as main.
        if not hasattr(self, "position_analysis_result"):
            self.position_analysis_result = result

    def get_current_position_result(self):
        self.route_analysis_state()

        result = getattr(self, "position_analysis_result", None)

        if result is not None:
            return result

        state = getattr(self, "analysis_state", None)
        return getattr(state, "latest_result", None) if state is not None else None

    def stable_black_winrate(self, result) -> float | None:
        if result is None:
            return None

        value = getattr(result, "root_winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def stable_white_winrate(self, result) -> float | None:
        black = self.stable_black_winrate(result)

        if black is None:
            return None

        return 100.0 - black

    def stable_black_score_lead(self, result) -> float | None:
        if result is None:
            return None

        value = getattr(result, "root_score_lead", None)

        if value is None:
            return None

        return float(value)

    def move_black_winrate(self, move_info) -> float | None:
        value = getattr(move_info, "winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def move_white_winrate(self, move_info) -> float | None:
        black = self.move_black_winrate(move_info)

        if black is None:
            return None

        return 100.0 - black

    def move_black_score_lead(self, move_info) -> float | None:
        value = getattr(move_info, "score_lead", None)

        if value is None:
            return None

        return float(value)

    def format_score_owner(self, black_score: float | None) -> str:
        if black_score is None:
            return "No score yet"

        if black_score > 0:
            return f"Black by {abs(black_score):.2f}"

        if black_score < 0:
            return f"White by {abs(black_score):.2f}"

        return "Even"

    def get_top_recommended_moves(self, limit: int = 5):
        result = self.get_current_position_result()

        if result is None:
            return []

        moves = []

        for move_info in getattr(result, "best_moves", [])[:limit]:
            move = getattr(move_info, "move", "")

            if not move or move.lower() == "pass":
                continue

            moves.append(move_info)

        return moves

    def format_pv_line(self, move_info, max_len: int | None = None) -> str:
        pv = getattr(move_info, "pv", None)

        if not pv:
            return ""

        if max_len is None:
            max_len = self.get_analysis_depth()

        pv = list(pv)[:max_len]

        return " → ".join(str(move) for move in pv)

    def make_board_signature(self) -> str:
        from app.core.coordinates import point_to_human

        parts = []

        for row in range(self.board.size):
            for col in range(self.board.size):
                coordinate = point_to_human(row, col, self.board.size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                name = getattr(stone, "name", str(stone)).upper() if stone is not None else "EMPTY"

                if "BLACK" in name:
                    parts.append("B")
                elif "WHITE" in name:
                    parts.append("W")
                else:
                    parts.append(".")

        return "".join(parts)

    def get_hover_board_candidate(self):
        import pygame
        from app.core.coordinates import point_to_human

        mouse_x, mouse_y = pygame.mouse.get_pos()

        if not (self.board_left <= mouse_x <= self.board_right and self.board_top <= mouse_y <= self.board_bottom):
            return None

        col = round((mouse_x - self.board_left) / self.cell_size)
        row = round((mouse_y - self.board_top) / self.cell_size)

        if not (0 <= row < self.board.size and 0 <= col < self.board.size):
            return None

        coordinate = point_to_human(row, col, self.board.size)

        try:
            stone = self.board.get(coordinate)
        except Exception:
            stone = None

        if stone is not None:
            stone_name = getattr(stone, "name", str(stone)).upper()

            if "EMPTY" not in stone_name:
                return {
                    "move": coordinate,
                    "row": row,
                    "col": col,
                    "occupied": True,
                    "legal": False,
                }

        try:
            test_board = self.board.copy()
            test_board.place_stone(coordinate, self.current_player)
        except Exception:
            return {
                "move": coordinate,
                "row": row,
                "col": col,
                "occupied": False,
                "legal": False,
            }

        return {
            "move": coordinate,
            "row": row,
            "col": col,
            "occupied": False,
            "legal": True,
        }

    def make_hover_cache_key(self, move: str):
        return (
            self.board.size,
            self.current_player.name,
            self.get_analysis_depth(),
            self.make_board_signature(),
            move,
        )

    def get_next_player_after_current(self):
        from app.core.stone import Stone

        return Stone.WHITE if self.current_player == Stone.BLACK else Stone.BLACK

    def maybe_request_hover_point_analysis(self, move: str) -> None:
        import pygame

        if not getattr(self, "analysis_enabled", False):
            return

        if not hasattr(self, "analysis_service"):
            return

        if not hasattr(self, "hover_analysis_cache"):
            self.hover_analysis_cache = {}

        key = self.make_hover_cache_key(move)

        if key in self.hover_analysis_cache:
            return

        if getattr(self, "hover_analysis_pending_id", None) is not None:
            return

        now_ms = pygame.time.get_ticks()
        last_move = getattr(self, "hover_candidate_move", None)
        started_ms = getattr(self, "hover_candidate_started_ms", 0)

        if last_move != move:
            self.hover_candidate_move = move
            self.hover_candidate_started_ms = now_ms
            return

        # Wait briefly so moving the mouse around does not spam KataGo.
        if now_ms - started_ms < 450:
            return

        try:
            test_board = self.board.copy()
            test_board.place_stone(move, self.current_player)

            next_player = self.get_next_player_after_current()

            self.apply_analysis_depth_to_katago()

            request_id = self.analysis_service.request_analysis(
                board=test_board,
                current_player=next_player,
            )

            self.hover_analysis_pending_id = request_id
            self.hover_analysis_pending_key = key

            print(
                f"[Go Sensei Hover] Request #{request_id}: if {self.current_player.name} plays {move}",
                flush=True,
            )

        except Exception as error:
            print(f"[Go Sensei Hover] Could not request hover analysis for {move}: {error}", flush=True)

    def get_hover_result_for_move(self, move: str):
        if not hasattr(self, "hover_analysis_cache"):
            self.hover_analysis_cache = {}

        key = self.make_hover_cache_key(move)
        return self.hover_analysis_cache.get(key)

    def draw_analysis_depth_widget(self, x: int, y: int, width: int) -> int:
        import pygame

        theme = self.ui_theme()

        label = self.small_ui_font.render("Variation Depth", True, theme["gold"])
        self.screen.blit(label, (x, y))
        y += 24

        minus_rect = pygame.Rect(x, y, 36, 30)
        plus_rect = pygame.Rect(x + width - 36, y, 36, 30)
        value_rect = pygame.Rect(x + 44, y, width - 88, 30)

        self.analysis_depth_minus_rect = minus_rect
        self.analysis_depth_plus_rect = plus_rect

        pygame.draw.rect(self.screen, theme["button"], minus_rect, border_radius=7)
        pygame.draw.rect(self.screen, theme["button"], plus_rect, border_radius=7)
        pygame.draw.rect(self.screen, (35, 37, 43), value_rect, border_radius=7)

        pygame.draw.rect(self.screen, theme["button_border"], minus_rect, 1, border_radius=7)
        pygame.draw.rect(self.screen, theme["button_border"], plus_rect, 1, border_radius=7)
        pygame.draw.rect(self.screen, theme["button_border"], value_rect, 1, border_radius=7)

        minus = self.status_font.render("-", True, theme["white"])
        plus = self.status_font.render("+", True, theme["white"])
        value = self.small_ui_font.render(f"{self.get_analysis_depth()} moves", True, theme["white"])

        self.screen.blit(minus, minus.get_rect(center=minus_rect.center))
        self.screen.blit(plus, plus.get_rect(center=plus_rect.center))
        self.screen.blit(value, value.get_rect(center=value_rect.center))

        return y + 42

    def draw_analysis_markers(self) -> None:
        import pygame
        from app.core.coordinates import human_to_point

        self.route_analysis_state()

        top_moves = self.get_top_recommended_moves(limit=5)
        self.recommended_marker_targets = []

        if not top_moves:
            return

        colors = [
            (80, 165, 255),
            (85, 220, 180),
            (255, 210, 110),
            (200, 150, 255),
            (255, 140, 120),
        ]

        for index, move_info in enumerate(top_moves):
            move = getattr(move_info, "move", "")

            try:
                row, col = human_to_point(move, self.board.size)
                x, y = self.point_to_pixels(row, col)
            except Exception:
                continue

            radius = max(11, int(self.cell_size * 0.23))
            color = colors[index % len(colors)]

            marker_surface = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
            center = marker_surface.get_rect().center

            pygame.draw.circle(marker_surface, (*color, 210), center, radius)
            pygame.draw.circle(marker_surface, (255, 255, 255, 235), center, radius, 2)

            label = self.small_ui_font.render(str(index + 1), True, (15, 18, 24))
            marker_surface.blit(label, label.get_rect(center=center))

            self.screen.blit(marker_surface, marker_surface.get_rect(center=(x, y)))

            target_rect = pygame.Rect(x - radius - 8, y - radius - 8, radius * 2 + 16, radius * 2 + 16)
            self.recommended_marker_targets.append((target_rect, index + 1, move_info))

    def get_hovered_recommendation(self):
        import pygame

        mouse_pos = pygame.mouse.get_pos()

        for rect, rank, move_info in getattr(self, "recommended_move_rects", []):
            if rect.collidepoint(mouse_pos):
                return rank, move_info

        for rect, rank, move_info in getattr(self, "recommended_marker_targets", []):
            if rect.collidepoint(mouse_pos):
                return rank, move_info

        return None, None

    def draw_variation_tooltip_box(self, title: str, lines: list[str], accent=(120, 180, 255)) -> None:
        import pygame

        mouse_x, mouse_y = pygame.mouse.get_pos()
        width = 430
        height = 40 + len(lines) * 23

        height = max(128, min(220, height))

        x = mouse_x + 18
        y = mouse_y + 18

        if x + width > self.screen.get_width() - 10:
            x = mouse_x - width - 18

        if y + height > self.screen.get_height() - 10:
            y = mouse_y - height - 18

        rect = pygame.Rect(x, y, width, height)

        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(surface, (18, 22, 30, 250), surface.get_rect(), border_radius=12)
        self.screen.blit(surface, rect.topleft)

        pygame.draw.rect(self.screen, accent, rect, 2, border_radius=12)

        tx = rect.left + 14
        ty = rect.top + 12

        title_surface = self.status_font.render(title, True, accent)
        self.screen.blit(title_surface, (tx, ty))
        ty += 30

        for line in lines:
            if len(line) > 82:
                line = line[:79] + "..."

            surface = self.small_ui_font.render(line, True, (235, 240, 245))
            self.screen.blit(surface, (tx, ty))
            ty += 23

            if ty > rect.bottom - 20:
                break

    def draw_variation_tooltip(self) -> None:
        self.route_analysis_state()

        rank, move_info = self.get_hovered_recommendation()

        if move_info is not None:
            move = getattr(move_info, "move", "")
            black = self.move_black_winrate(move_info)
            white = self.move_white_winrate(move_info)
            score = self.move_black_score_lead(move_info)
            visits = getattr(move_info, "visits", None)
            pv = self.format_pv_line(move_info, self.get_analysis_depth())

            lines = []

            if black is not None and white is not None:
                lines.append(f"If played: Black {black:.1f}%   White {white:.1f}%")

            if score is not None:
                lines.append(f"Expected score: {self.format_score_owner(score)}")

            if visits is not None:
                lines.append(f"Search visits: {visits}")

            if pv:
                lines.append(f"Variation: {pv}")

            self.draw_variation_tooltip_box(f"#{rank} engine candidate: {move}", lines)
            return

        candidate = self.get_hover_board_candidate()

        if candidate is None:
            return

        move = candidate["move"]

        if candidate.get("occupied"):
            self.draw_variation_tooltip_box(
                f"{move}",
                ["Occupied point", "No candidate evaluation available here."],
                accent=(255, 180, 120),
            )
            return

        if not candidate.get("legal"):
            self.draw_variation_tooltip_box(
                f"{move}",
                ["Illegal move", "KataGo hover analysis was not requested."],
                accent=(255, 120, 120),
            )
            return

        # Request hover analysis for any legal point, even if it is not engine recommended.
        self.maybe_request_hover_point_analysis(move)
        hover_result = self.get_hover_result_for_move(move)

        if hover_result is None:
            self.draw_variation_tooltip_box(
                f"If {self.current_player.name} plays {move}",
                [
                    "Hover analysis loading...",
                    "Hold your cursor here for a moment.",
                    "This works for any legal point, not just Top 5 moves.",
                ],
                accent=(120, 180, 255),
            )
            return

        black = self.stable_black_winrate(hover_result)
        white = self.stable_white_winrate(hover_result)
        score = self.stable_black_score_lead(hover_result)

        pv_line = ""

        best_moves = getattr(hover_result, "best_moves", [])

        if best_moves:
            best_reply = best_moves[0]
            reply_pv = self.format_pv_line(best_reply, self.get_analysis_depth())

            if reply_pv:
                pv_line = f"{move} → {reply_pv}"
            else:
                pv_line = move

        lines = []

        if black is not None and white is not None:
            lines.append(f"If played: Black {black:.1f}%   White {white:.1f}%")

        if score is not None:
            lines.append(f"Expected score: {self.format_score_owner(score)}")

        if pv_line:
            lines.append(f"Variation: {pv_line}")

        self.draw_variation_tooltip_box(
            f"Point analysis: {move}",
            lines,
            accent=(85, 220, 180),
        )

    def draw_analysis_panel(self) -> None:
        import pygame

        self.route_analysis_state()

        theme = self.ui_theme()

        panel_rect = pygame.Rect(
            self.safe_right_panel_left,
            self.safe_panel_top,
            self.safe_panel_width,
            self.safe_panel_height,
        )

        self.draw_panel(panel_rect, theme["panel_warm"], theme["panel_border_gold"], radius=18)

        x = panel_rect.left + 18
        y = panel_rect.top + 16
        content_width = panel_rect.width - 36

        title_surface = self.status_font.render("KataGo Analysis", True, theme["gold"])
        self.screen.blit(title_surface, (x, y))
        y += 30

        rules = self.small_ui_font.render("Rules: Chinese   Komi: 7.5   Perspective: Black", True, (235, 220, 180))
        self.screen.blit(rules, (x, y))
        y += 28

        y = self.draw_analysis_depth_widget(x, y, content_width)
        y += 4

        state = getattr(self, "analysis_state", None)
        result = self.get_current_position_result()

        engine_color = theme["green"] if getattr(self, "analysis_enabled", False) else theme["red"]
        engine_text = "Engine: ON" if getattr(self, "analysis_enabled", False) else "Engine: OFF"
        engine_surface = self.small_ui_font.render(engine_text, True, engine_color)
        self.screen.blit(engine_surface, (x, y))
        y += 28

        black_winrate = self.stable_black_winrate(result)
        white_winrate = self.stable_white_winrate(result)
        black_score = self.stable_black_score_lead(result)

        def card(title: str, height: int):
            nonlocal y
            rect = pygame.Rect(x - 4, y, content_width + 8, height)
            card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(card_surface, theme["card"], card_surface.get_rect(), border_radius=12)
            self.screen.blit(card_surface, rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255, 48), rect, 1, border_radius=12)

            title_surface = self.small_ui_font.render(title, True, theme["gold"])
            self.screen.blit(title_surface, (rect.left + 12, rect.top + 9))

            y = rect.top + 34
            return rect

        def add(text_value: str, color=None, gap=21):
            nonlocal y

            if color is None:
                color = theme["white"]

            surface = self.small_ui_font.render(text_value, True, color)
            self.screen.blit(surface, (x + 8, y))
            y += gap

        def finish(rect):
            nonlocal y
            y = rect.bottom + 12

        state_card = card("Stable game state", 118)

        if result is None:
            if state is not None and getattr(state, "is_thinking", False):
                add("Thinking...", theme["blue"])
            else:
                add("Click ANALYZE to evaluate", theme["muted"])
        else:
            add(f"Black: {black_winrate:.1f}%" if black_winrate is not None else "Black: --")
            add(f"White: {white_winrate:.1f}%" if white_winrate is not None else "White: --")
            add(f"Score: {self.format_score_owner(black_score)}", theme["gold"])

            if black_winrate is not None:
                bar = pygame.Rect(x + 8, y + 2, content_width - 16, 16)
                pygame.draw.rect(self.screen, (235, 235, 230), bar, border_radius=8)

                black_rect = pygame.Rect(bar.left, bar.top, int(bar.width * black_winrate / 100.0), bar.height)
                pygame.draw.rect(self.screen, (24, 24, 28), black_rect, border_radius=8)
                pygame.draw.rect(self.screen, theme["gold"], bar, 1, border_radius=8)

        finish(state_card)

        top_card = card("Top 5 recommended moves", 254)
        self.recommended_move_rects = []

        top_moves = self.get_top_recommended_moves(limit=5)

        if not top_moves:
            add("No recommendations yet", theme["muted"])
        else:
            row_h = 40

            for index, move_info in enumerate(top_moves):
                rank = index + 1
                move = getattr(move_info, "move", "")
                black = self.move_black_winrate(move_info)
                score = self.move_black_score_lead(move_info)
                visits = getattr(move_info, "visits", None)

                row_rect = pygame.Rect(x + 4, y - 3, content_width - 8, row_h - 4)
                hovered = row_rect.collidepoint(pygame.mouse.get_pos())
                row_color = (65, 70, 82, 255) if hovered else (37, 40, 47, 255)

                pygame.draw.rect(self.screen, row_color, row_rect, border_radius=8)

                move_text = f"#{rank} {move}"

                if black is not None:
                    move_text += f"   B {black:.1f}%"

                if score is not None:
                    move_text += f"   {self.format_score_owner(score)}"

                surface = self.small_ui_font.render(move_text, True, theme["white"])
                self.screen.blit(surface, (row_rect.left + 10, row_rect.top + 5))

                if visits is not None:
                    visit_surface = self.small_ui_font.render(f"{visits} visits", True, theme["muted"])
                    self.screen.blit(visit_surface, (row_rect.left + 10, row_rect.top + 22))

                self.recommended_move_rects.append((row_rect, rank, move_info))
                y += row_h

        finish(top_card)

        self.draw_variation_tooltip()

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        minus_rect = getattr(self, "analysis_depth_minus_rect", None)
        plus_rect = getattr(self, "analysis_depth_plus_rect", None)

        if minus_rect is not None and minus_rect.collidepoint(mouse_pos):
            self.decrease_analysis_depth()
            return

        if plus_rect is not None and plus_rect.collidepoint(mouse_pos):
            self.increase_analysis_depth()
            return

        size_rect = self.get_size_selector_rect()

        if size_rect.collidepoint(mouse_pos):
            print("[Go Sensei UI] Size button clicked", flush=True)
            self.cycle_board_size()
            return

        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                print(f"[Go Sensei UI] Bottom button clicked: {button_name}", flush=True)
                self.handle_button_click(button_name)
                return

        self.handle_board_click(mouse_pos)


    def get_hover_delay_ms(self) -> int:
        return 120

    def get_hover_max_visits(self) -> int:
        # Fast hover search. Increase this later if you want stronger hover analysis.
        return int(getattr(self, "hover_max_visits", 18))

    def get_hover_pv_depth(self) -> int:
        # Keep hover PV useful but fast. Main Top 5 can still use deeper PV.
        return min(self.get_analysis_depth() if hasattr(self, "get_analysis_depth") else 18, 30)

    def get_normal_analysis_visits(self) -> int:
        return int(getattr(self, "normal_analysis_max_visits", 100))

    def iter_katago_setting_targets(self):
        service = getattr(self, "analysis_service", None)

        if service is None:
            return []

        return [
            service,
            getattr(service, "client", None),
            getattr(service, "katago_client", None),
            getattr(service, "_client", None),
        ]

    def set_katago_runtime_settings(self, pv_len: int | None = None, max_visits: int | None = None) -> None:
        from dataclasses import replace

        for target in self.iter_katago_setting_targets():
            if target is None:
                continue

            settings = getattr(target, "settings", None)

            if settings is None:
                continue

            if not hasattr(settings, "analysis_pv_len"):
                continue

            if not hasattr(self, "normal_analysis_max_visits"):
                self.normal_analysis_max_visits = int(getattr(settings, "max_visits", 100))

            kwargs = {}

            if pv_len is not None:
                kwargs["analysis_pv_len"] = int(pv_len)

            if max_visits is not None and hasattr(settings, "max_visits"):
                kwargs["max_visits"] = int(max_visits)

            if not kwargs:
                return

            try:
                target.settings = replace(settings, **kwargs)
                return
            except Exception as error:
                print(f"[Go Sensei Settings] Could not update KataGo settings here: {error}", flush=True)

    def apply_analysis_depth_to_katago(self) -> None:
        # Main analysis = deeper/stronger.
        depth = self.get_analysis_depth() if hasattr(self, "get_analysis_depth") else 18
        visits = self.get_normal_analysis_visits()

        self.set_katago_runtime_settings(
            pv_len=depth,
            max_visits=visits,
        )

        print(f"[Go Sensei Analysis] Main analysis: visits={visits}, pv_depth={depth}", flush=True)

    def apply_hover_settings_to_katago(self) -> None:
        # Hover analysis = fast/shallow.
        visits = self.get_hover_max_visits()
        depth = self.get_hover_pv_depth()

        self.set_katago_runtime_settings(
            pv_len=depth,
            max_visits=visits,
        )

        print(f"[Go Sensei Hover] Fast hover settings: visits={visits}, pv_depth={depth}", flush=True)

    def request_live_analysis(self) -> int | None:
        try:
            if not hasattr(self, "analysis_service"):
                self.status_message = "No analysis service available"
                print("[Go Sensei Board] No analysis service available.", flush=True)
                return None

            self.apply_analysis_depth_to_katago()

            request_id = self.analysis_service.request_analysis(
                board=self.board,
                current_player=self.current_player,
            )

            self.main_analysis_request_id = request_id

            print(
                f"[Go Sensei Board] Main analysis request #{request_id}: player={self.current_player.name}, rules=chinese, komi=7.5, perspective=BLACK, depth={self.get_analysis_depth()}",
                flush=True,
            )

            return request_id

        except Exception as error:
            self.status_message = f"Analyze error: {error}"
            print(f"[Go Sensei Analyze Error] {type(error).__name__}: {error}", flush=True)
            return None

    def route_analysis_state(self) -> None:
        state = getattr(self, "analysis_state", None)

        if state is None:
            return

        result = getattr(state, "latest_result", None)
        completed_id = getattr(state, "completed_request_id", None)

        if result is None or completed_id is None:
            return

        hover_pending_id = getattr(self, "hover_analysis_pending_id", None)
        main_pending_id = getattr(self, "main_analysis_request_id", None)

        if hover_pending_id is not None and completed_id == hover_pending_id:
            key = getattr(self, "hover_analysis_pending_key", None)

            if key is not None:
                if not hasattr(self, "hover_analysis_cache"):
                    self.hover_analysis_cache = {}

                self.hover_analysis_cache[key] = result

                # Keep cache from growing forever.
                if len(self.hover_analysis_cache) > 500:
                    oldest_key = next(iter(self.hover_analysis_cache))
                    del self.hover_analysis_cache[oldest_key]

                print(f"[Go Sensei Hover] Cached fast hover analysis for {key[-1]}", flush=True)

            self.hover_analysis_pending_id = None
            self.hover_analysis_pending_key = None

            # Restore normal settings after a fast hover request.
            self.apply_analysis_depth_to_katago()
            return

        if main_pending_id is not None and completed_id == main_pending_id:
            self.position_analysis_result = result
            print(f"[Go Sensei Analysis] Stored stable main result #{completed_id}", flush=True)
            return

        if not hasattr(self, "position_analysis_result"):
            self.position_analysis_result = result

    def get_current_position_result(self):
        self.route_analysis_state()

        result = getattr(self, "position_analysis_result", None)

        if result is not None:
            return result

        state = getattr(self, "analysis_state", None)
        return getattr(state, "latest_result", None) if state is not None else None

    def find_move_info_in_current_analysis(self, move: str):
        result = self.get_current_position_result()

        if result is None:
            return None

        target = move.strip().upper()

        for move_info in getattr(result, "best_moves", []):
            candidate = getattr(move_info, "move", "").strip().upper()

            if candidate == target:
                return move_info

        return None

    def make_board_signature(self) -> str:
        from app.core.coordinates import point_to_human

        parts = []

        for row in range(self.board.size):
            for col in range(self.board.size):
                coordinate = point_to_human(row, col, self.board.size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                name = getattr(stone, "name", str(stone)).upper() if stone is not None else "EMPTY"

                if "BLACK" in name:
                    parts.append("B")
                elif "WHITE" in name:
                    parts.append("W")
                else:
                    parts.append(".")

        return "".join(parts)

    def make_hover_cache_key(self, move: str):
        return (
            self.board.size,
            self.current_player.name,
            self.get_hover_pv_depth(),
            self.get_hover_max_visits(),
            self.make_board_signature(),
            move,
        )

    def get_next_player_after_current(self):
        from app.core.stone import Stone

        return Stone.WHITE if self.current_player == Stone.BLACK else Stone.BLACK

    def maybe_request_hover_point_analysis(self, move: str) -> None:
        import pygame

        if not getattr(self, "analysis_enabled", False):
            return

        if not hasattr(self, "analysis_service"):
            return

        if not hasattr(self, "hover_analysis_cache"):
            self.hover_analysis_cache = {}

        key = self.make_hover_cache_key(move)

        if key in self.hover_analysis_cache:
            return

        # Only one hover request at a time. This prevents queue spam.
        if getattr(self, "hover_analysis_pending_id", None) is not None:
            return

        now_ms = pygame.time.get_ticks()
        last_move = getattr(self, "hover_candidate_move", None)
        started_ms = getattr(self, "hover_candidate_started_ms", 0)

        if last_move != move:
            self.hover_candidate_move = move
            self.hover_candidate_started_ms = now_ms
            return

        if now_ms - started_ms < self.get_hover_delay_ms():
            return

        try:
            test_board = self.board.copy()
            test_board.place_stone(move, self.current_player)

            next_player = self.get_next_player_after_current()

            self.apply_hover_settings_to_katago()

            request_id = self.analysis_service.request_analysis(
                board=test_board,
                current_player=next_player,
            )

            self.hover_analysis_pending_id = request_id
            self.hover_analysis_pending_key = key

            print(
                f"[Go Sensei Hover] Fast request #{request_id}: if {self.current_player.name} plays {move}",
                flush=True,
            )

        except Exception as error:
            print(f"[Go Sensei Hover] Could not request hover analysis for {move}: {error}", flush=True)

    def get_hover_result_for_move(self, move: str):
        if not hasattr(self, "hover_analysis_cache"):
            self.hover_analysis_cache = {}

        key = self.make_hover_cache_key(move)
        return self.hover_analysis_cache.get(key)

    def get_hover_board_candidate(self):
        import pygame
        from app.core.coordinates import point_to_human

        mouse_x, mouse_y = pygame.mouse.get_pos()

        if not (self.board_left <= mouse_x <= self.board_right and self.board_top <= mouse_y <= self.board_bottom):
            return None

        col = round((mouse_x - self.board_left) / self.cell_size)
        row = round((mouse_y - self.board_top) / self.cell_size)

        if not (0 <= row < self.board.size and 0 <= col < self.board.size):
            return None

        coordinate = point_to_human(row, col, self.board.size)

        try:
            stone = self.board.get(coordinate)
        except Exception:
            stone = None

        if stone is not None:
            stone_name = getattr(stone, "name", str(stone)).upper()

            if "EMPTY" not in stone_name:
                return {
                    "move": coordinate,
                    "row": row,
                    "col": col,
                    "occupied": True,
                    "legal": False,
                }

        try:
            test_board = self.board.copy()
            test_board.place_stone(coordinate, self.current_player)
        except Exception:
            return {
                "move": coordinate,
                "row": row,
                "col": col,
                "occupied": False,
                "legal": False,
            }

        return {
            "move": coordinate,
            "row": row,
            "col": col,
            "occupied": False,
            "legal": True,
        }

    def draw_variation_tooltip_box(self, title: str, lines: list[str], accent=(120, 180, 255)) -> None:
        import pygame

        mouse_x, mouse_y = pygame.mouse.get_pos()
        width = 440
        height = 40 + len(lines) * 23
        height = max(128, min(230, height))

        x = mouse_x + 18
        y = mouse_y + 18

        if x + width > self.screen.get_width() - 10:
            x = mouse_x - width - 18

        if y + height > self.screen.get_height() - 10:
            y = mouse_y - height - 18

        rect = pygame.Rect(x, y, width, height)

        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(surface, (18, 22, 30, 250), surface.get_rect(), border_radius=12)
        self.screen.blit(surface, rect.topleft)

        pygame.draw.rect(self.screen, accent, rect, 2, border_radius=12)

        tx = rect.left + 14
        ty = rect.top + 12

        title_surface = self.status_font.render(title, True, accent)
        self.screen.blit(title_surface, (tx, ty))
        ty += 30

        for line in lines:
            if len(line) > 88:
                line = line[:85] + "..."

            surface = self.small_ui_font.render(line, True, (235, 240, 245))
            self.screen.blit(surface, (tx, ty))
            ty += 23

            if ty > rect.bottom - 20:
                break

    def draw_variation_tooltip(self) -> None:
        self.route_analysis_state()

        rank, move_info = self.get_hovered_recommendation()

        if move_info is not None:
            self.draw_move_info_tooltip(
                title=f"#{rank} engine candidate: {getattr(move_info, 'move', '')}",
                move_info=move_info,
                accent=(120, 180, 255),
                prefix="If played",
            )
            return

        candidate = self.get_hover_board_candidate()

        if candidate is None:
            return

        move = candidate["move"]

        if candidate.get("occupied"):
            self.draw_variation_tooltip_box(
                f"{move}",
                ["Occupied point", "No candidate evaluation available here."],
                accent=(255, 180, 120),
            )
            return

        if not candidate.get("legal"):
            self.draw_variation_tooltip_box(
                f"{move}",
                ["Illegal move", "KataGo hover analysis was not requested."],
                accent=(255, 120, 120),
            )
            return

        # Fast path: if KataGo already has this move in current moveInfos, show instantly.
        instant_move_info = self.find_move_info_in_current_analysis(move)

        if instant_move_info is not None:
            self.draw_move_info_tooltip(
                title=f"Instant analysis: {move}",
                move_info=instant_move_info,
                accent=(85, 220, 180),
                prefix="If played",
            )
            return

        # Slow path, optimized: shallow cached analysis for any legal point.
        self.maybe_request_hover_point_analysis(move)
        hover_result = self.get_hover_result_for_move(move)

        if hover_result is None:
            pending_id = getattr(self, "hover_analysis_pending_id", None)

            if pending_id is not None:
                loading = f"Fast hover request #{pending_id} running..."
            else:
                loading = "Hold cursor briefly to analyze this point..."

            self.draw_variation_tooltip_box(
                f"If {self.current_player.name} plays {move}",
                [
                    loading,
                    f"Fast mode: {self.get_hover_max_visits()} visits",
                    "Cached after first result.",
                ],
                accent=(120, 180, 255),
            )
            return

        black = self.stable_black_winrate(hover_result)
        white = self.stable_white_winrate(hover_result)
        score = self.stable_black_score_lead(hover_result)

        pv_line = ""

        best_moves = getattr(hover_result, "best_moves", [])

        if best_moves:
            best_reply = best_moves[0]
            reply_pv = self.format_pv_line(best_reply, self.get_hover_pv_depth())

            if reply_pv:
                pv_line = f"{move} → {reply_pv}"
            else:
                pv_line = move

        lines = []

        if black is not None and white is not None:
            lines.append(f"If played: Black {black:.1f}%   White {white:.1f}%")

        if score is not None:
            lines.append(f"Expected score: {self.format_score_owner(score)}")

        lines.append(f"Fast hover: {self.get_hover_max_visits()} visits")

        if pv_line:
            lines.append(f"Variation: {pv_line}")

        self.draw_variation_tooltip_box(
            f"Point analysis: {move}",
            lines,
            accent=(85, 220, 180),
        )

    def draw_move_info_tooltip(self, title: str, move_info, accent=(120, 180, 255), prefix: str = "If played") -> None:
        black = self.move_black_winrate(move_info)
        white = self.move_white_winrate(move_info)
        score = self.move_black_score_lead(move_info)
        visits = getattr(move_info, "visits", None)
        pv = self.format_pv_line(move_info, self.get_analysis_depth())

        lines = []

        if black is not None and white is not None:
            lines.append(f"{prefix}: Black {black:.1f}%   White {white:.1f}%")

        if score is not None:
            lines.append(f"Expected score: {self.format_score_owner(score)}")

        if visits is not None:
            lines.append(f"Search visits: {visits}")

        if pv:
            lines.append(f"Variation: {pv}")

        self.draw_variation_tooltip_box(title, lines, accent=accent)


    def get_performance_mode(self) -> str:
        return getattr(self, "performance_mode", "fast")

    def get_target_fps(self) -> int:
        mode = self.get_performance_mode()

        if mode == "quality":
            return 45

        if mode == "balanced":
            return 35

        return 30

    def get_normal_analysis_visits(self) -> int:
        mode = self.get_performance_mode()

        if mode == "quality":
            return 120

        if mode == "balanced":
            return 80

        return 45

    def get_hover_max_visits(self) -> int:
        mode = self.get_performance_mode()

        if mode == "quality":
            return 20

        if mode == "balanced":
            return 12

        return 6

    def get_hover_delay_ms(self) -> int:
        mode = self.get_performance_mode()

        if mode == "quality":
            return 180

        if mode == "balanced":
            return 120

        return 70

    def get_analysis_depth(self) -> int:
        return int(getattr(self, "analysis_depth", 10))

    def get_hover_pv_depth(self) -> int:
        # Hover must stay fast. Main PV can be deeper.
        return min(self.get_analysis_depth(), 16)

    def cycle_performance_mode(self) -> None:
        mode = self.get_performance_mode()

        if mode == "fast":
            self.performance_mode = "balanced"
        elif mode == "balanced":
            self.performance_mode = "quality"
        else:
            self.performance_mode = "fast"

        self.status_message = f"Performance mode: {self.performance_mode.upper()}"
        print(f"[Go Sensei Performance] Mode set to {self.performance_mode.upper()}", flush=True)

        self.clear_fast_analysis_caches()

        if getattr(self, "analysis_enabled", False):
            self.request_live_analysis()

    def clear_fast_analysis_caches(self) -> None:
        self.hover_analysis_cache = {}
        self.hover_analysis_pending_id = None
        self.hover_analysis_pending_key = None
        self.hover_candidate_move = None
        self.hover_candidate_started_ms = 0

        self._cached_board_signature = None
        self._cached_board_signature_key = None

    def set_katago_runtime_settings(self, pv_len: int | None = None, max_visits: int | None = None) -> None:
        from dataclasses import replace

        service = getattr(self, "analysis_service", None)

        if service is None:
            return

        candidates = [
            service,
            getattr(service, "client", None),
            getattr(service, "katago_client", None),
            getattr(service, "_client", None),
        ]

        for target in candidates:
            if target is None:
                continue

            settings = getattr(target, "settings", None)

            if settings is None:
                continue

            kwargs = {}

            if pv_len is not None and hasattr(settings, "analysis_pv_len"):
                kwargs["analysis_pv_len"] = int(pv_len)

            if max_visits is not None and hasattr(settings, "max_visits"):
                kwargs["max_visits"] = int(max_visits)

            if not kwargs:
                continue

            try:
                target.settings = replace(settings, **kwargs)
                return
            except Exception as error:
                print(f"[Go Sensei Performance] Could not update KataGo settings here: {error}", flush=True)

    def apply_analysis_depth_to_katago(self) -> None:
        visits = self.get_normal_analysis_visits()
        depth = self.get_analysis_depth()

        self.set_katago_runtime_settings(
            pv_len=depth,
            max_visits=visits,
        )

        print(
            f"[Go Sensei Performance] Main analysis: mode={self.get_performance_mode()}, visits={visits}, pv_depth={depth}",
            flush=True,
        )

    def apply_hover_settings_to_katago(self) -> None:
        visits = self.get_hover_max_visits()
        depth = self.get_hover_pv_depth()

        self.set_katago_runtime_settings(
            pv_len=depth,
            max_visits=visits,
        )

        print(
            f"[Go Sensei Performance] Hover analysis: mode={self.get_performance_mode()}, visits={visits}, pv_depth={depth}",
            flush=True,
        )

    def make_board_signature(self) -> str:
        # Cached board signature. This avoids scanning all 361 board points
        # every frame while hovering.
        from app.core.coordinates import point_to_human

        key = (
            self.board.size,
            getattr(self.current_player, "name", str(self.current_player)),
            getattr(self, "manual_move_index", 0),
            getattr(self, "move_index", 0),
            getattr(self, "last_move", None),
            getattr(self, "black_captures", 0),
            getattr(self, "white_captures", 0),
            len(getattr(self, "manual_move_history", [])),
            str(getattr(self, "loaded_sgf_path", "")),
        )

        if getattr(self, "_cached_board_signature_key", None) == key:
            cached = getattr(self, "_cached_board_signature", None)

            if cached is not None:
                return cached

        parts = []

        for row in range(self.board.size):
            for col in range(self.board.size):
                coordinate = point_to_human(row, col, self.board.size)

                try:
                    stone = self.board.get(coordinate)
                except Exception:
                    stone = None

                name = getattr(stone, "name", str(stone)).upper() if stone is not None else "EMPTY"

                if "BLACK" in name:
                    parts.append("B")
                elif "WHITE" in name:
                    parts.append("W")
                else:
                    parts.append(".")

        signature = "".join(parts)

        self._cached_board_signature_key = key
        self._cached_board_signature = signature

        return signature

    def make_hover_cache_key(self, move: str):
        return (
            self.board.size,
            getattr(self.current_player, "name", str(self.current_player)),
            self.get_hover_pv_depth(),
            self.get_hover_max_visits(),
            self.make_board_signature(),
            move,
        )

    def maybe_request_hover_point_analysis(self, move: str) -> None:
        import pygame

        if not getattr(self, "analysis_enabled", False):
            return

        if not hasattr(self, "analysis_service"):
            return

        if not hasattr(self, "hover_analysis_cache"):
            self.hover_analysis_cache = {}

        key = self.make_hover_cache_key(move)

        if key in self.hover_analysis_cache:
            return

        # Do not pile up hover requests.
        if getattr(self, "hover_analysis_pending_id", None) is not None:
            return

        now_ms = pygame.time.get_ticks()
        last_move = getattr(self, "hover_candidate_move", None)
        started_ms = getattr(self, "hover_candidate_started_ms", 0)

        if last_move != move:
            self.hover_candidate_move = move
            self.hover_candidate_started_ms = now_ms
            return

        if now_ms - started_ms < self.get_hover_delay_ms():
            return

        try:
            test_board = self.board.copy()
            test_board.place_stone(move, self.current_player)

            next_player = self.get_next_player_after_current()

            self.apply_hover_settings_to_katago()

            request_id = self.analysis_service.request_analysis(
                board=test_board,
                current_player=next_player,
            )

            self.hover_analysis_pending_id = request_id
            self.hover_analysis_pending_key = key

            print(
                f"[Go Sensei Hover] Fast request #{request_id}: if {self.current_player.name} plays {move}",
                flush=True,
            )

        except Exception as error:
            print(f"[Go Sensei Hover] Could not request hover analysis for {move}: {error}", flush=True)

    def request_live_analysis(self) -> int | None:
        try:
            if not hasattr(self, "analysis_service"):
                self.status_message = "No analysis service available"
                print("[Go Sensei Board] No analysis service available.", flush=True)
                return None

            self.apply_analysis_depth_to_katago()

            request_id = self.analysis_service.request_analysis(
                board=self.board,
                current_player=self.current_player,
            )

            self.main_analysis_request_id = request_id

            print(
                f"[Go Sensei Board] Main analysis #{request_id}: mode={self.get_performance_mode()}, visits={self.get_normal_analysis_visits()}, depth={self.get_analysis_depth()}",
                flush=True,
            )

            return request_id

        except Exception as error:
            self.status_message = f"Analyze error: {error}"
            print(f"[Go Sensei Analyze Error] {type(error).__name__}: {error}", flush=True)
            return None

    def route_analysis_state(self) -> None:
        state = getattr(self, "analysis_state", None)

        if state is None:
            return

        result = getattr(state, "latest_result", None)
        completed_id = getattr(state, "completed_request_id", None)

        if result is None or completed_id is None:
            return

        hover_pending_id = getattr(self, "hover_analysis_pending_id", None)
        main_pending_id = getattr(self, "main_analysis_request_id", None)

        if hover_pending_id is not None and completed_id == hover_pending_id:
            key = getattr(self, "hover_analysis_pending_key", None)

            if key is not None:
                if not hasattr(self, "hover_analysis_cache"):
                    self.hover_analysis_cache = {}

                self.hover_analysis_cache[key] = result

                # Keep cache bounded.
                if len(self.hover_analysis_cache) > 250:
                    oldest_key = next(iter(self.hover_analysis_cache))
                    del self.hover_analysis_cache[oldest_key]

                print(f"[Go Sensei Hover] Cached hover result for {key[-1]}", flush=True)

            self.hover_analysis_pending_id = None
            self.hover_analysis_pending_key = None

            # Restore normal settings after hover.
            self.apply_analysis_depth_to_katago()
            return

        if main_pending_id is not None and completed_id == main_pending_id:
            self.position_analysis_result = result
            print(f"[Go Sensei Analysis] Stored main result #{completed_id}", flush=True)
            return

        if not hasattr(self, "position_analysis_result"):
            self.position_analysis_result = result

    def get_current_position_result(self):
        self.route_analysis_state()

        result = getattr(self, "position_analysis_result", None)

        if result is not None:
            return result

        state = getattr(self, "analysis_state", None)
        return getattr(state, "latest_result", None) if state is not None else None

    def find_move_info_in_current_analysis(self, move: str):
        result = self.get_current_position_result()

        if result is None:
            return None

        target = move.strip().upper()

        for move_info in getattr(result, "best_moves", []):
            candidate = getattr(move_info, "move", "").strip().upper()

            if candidate == target:
                return move_info

        return None

    def draw_bottom_controls(self) -> None:
        import pygame

        y = self.screen.get_height() - 55
        h = 41
        gap = 7

        perf_label = self.get_performance_mode().upper()

        specs = [
            ("load", "SGF"),
            ("analysis", "ANALYZE ON" if getattr(self, "analysis_enabled", False) else "ANALYZE"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
            ("performance", perf_label),
            ("back", "<<"),
            ("play_pause", "PLAY"),
            ("forward", ">>"),
            ("end", ">|"),
        ]

        total_gap = gap * (len(specs) - 1)
        w = int((self.screen.get_width() - 24 - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = 12

        for name, label in specs:
            rect = pygame.Rect(x, y, w, h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = None

            if name == "analysis" and getattr(self, "analysis_enabled", False):
                active = True
                accent = (58, 112, 84)

            if name == "performance":
                active = True

                if self.get_performance_mode() == "fast":
                    accent = (68, 118, 82)
                elif self.get_performance_mode() == "balanced":
                    accent = (72, 92, 132)
                else:
                    accent = (125, 90, 145)

            if name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = (62, 116, 82)
                elif mode == "human_white":
                    active = True
                    accent = (64, 88, 130)
                elif mode == "self_play":
                    active = True
                    accent = (118, 78, 142)

            self.draw_button(rect, label, active=active, accent=accent)

            x += w + gap

    def handle_button_click(self, button_name: str) -> None:
        if button_name == "performance":
            self.cycle_performance_mode()
            return

        if button_name == "load":
            self.load_sgf_from_dialog()
            return

        if button_name == "analysis":
            self.toggle_live_analysis()
            return

        if button_name == "ai":
            if hasattr(self, "toggle_ai_opponent"):
                self.toggle_ai_opponent()
            else:
                self.status_message = "AI opponent is not installed yet"
                print("[Go Sensei UI] AI opponent is not installed yet.", flush=True)
            return

        if getattr(self, "loaded_game", None) is None:
            if button_name == "beginning":
                if hasattr(self, "go_to_manual_beginning"):
                    self.go_to_manual_beginning()
                return

            if button_name == "back":
                if hasattr(self, "step_manual_back"):
                    self.step_manual_back()
                return

            if button_name == "play_pause":
                self.status_message = "Manual mode: use << and >> for undo/redo"
                return

            if button_name == "forward":
                if hasattr(self, "step_manual_forward"):
                    self.step_manual_forward(play_sound=True)
                return

            if button_name == "end":
                if hasattr(self, "go_to_manual_end"):
                    self.go_to_manual_end()
                return

        if button_name == "beginning":
            if hasattr(self, "go_to_beginning"):
                self.go_to_beginning()
            return

        if button_name == "back":
            if hasattr(self, "step_back"):
                self.step_back()
            return

        if button_name == "play_pause":
            if hasattr(self, "toggle_playback"):
                self.toggle_playback()
            else:
                self.is_playing = not getattr(self, "is_playing", False)
            return

        if button_name == "forward":
            if hasattr(self, "step_forward"):
                self.step_forward(play_sound=True)
            return

        if button_name == "end":
            if hasattr(self, "go_to_end"):
                self.go_to_end()
            return

    def run(self) -> None:
        import pygame

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if hasattr(self, "shutdown"):
                        self.shutdown()

                    pygame.quit()
                    raise SystemExit

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.dragging_speed_slider = False

                if event.type == pygame.MOUSEMOTION and getattr(self, "dragging_speed_slider", False):
                    if hasattr(self, "update_speed_from_mouse"):
                        self.update_speed_from_mouse(event.pos[0])

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.reset_board()
                        continue

                    if event.key == pygame.K_a:
                        self.toggle_live_analysis()
                        continue

                    if event.key == pygame.K_i:
                        if hasattr(self, "toggle_ai_opponent"):
                            self.toggle_ai_opponent()
                        continue

                    if event.key == pygame.K_p:
                        self.cycle_performance_mode()
                        continue

            if hasattr(self, "update_auto_replay"):
                self.update_auto_replay()

            if hasattr(self, "analysis_service"):
                self.analysis_state = self.analysis_service.get_state()
                self.route_analysis_state()

            if hasattr(self, "update_ai_move"):
                self.update_ai_move()

            if hasattr(self, "update_live_move_coaching"):
                self.update_live_move_coaching()

            self.draw()
            self.clock.tick(self.get_target_fps())


    def is_search_process_overlay_enabled(self) -> bool:
        # Kept for compatibility with older code, but the monitor is now a separate window.
        return False

    def draw_search_process_overlay(self) -> None:
        # Search monitor no longer draws over the board.
        return

    def is_search_monitor_window_enabled(self) -> bool:
        return bool(getattr(self, "search_monitor_window_enabled", True))

    def toggle_search_process_overlay(self) -> None:
        # S now opens/closes the separate monitor window.
        self.search_monitor_window_enabled = not self.is_search_monitor_window_enabled()

        if self.search_monitor_window_enabled:
            self.status_message = "Search Monitor window ON"
            print("[Go Sensei Search Monitor] Window ON", flush=True)
            self.ensure_search_monitor_window()
        else:
            self.status_message = "Search Monitor window OFF"
            print("[Go Sensei Search Monitor] Window OFF", flush=True)
            self.hide_search_monitor_window()

    def ensure_search_monitor_window(self) -> None:
        if not self.is_search_monitor_window_enabled():
            return

        try:
            import tkinter as tk
        except Exception as error:
            print(f"[Go Sensei Search Monitor] Tkinter unavailable: {error}", flush=True)
            return

        root = getattr(self, "search_monitor_root", None)

        try:
            if root is not None and root.winfo_exists():
                root.deiconify()
                return
        except Exception:
            self.search_monitor_root = None
            self.search_monitor_text = None

        root = tk.Tk()
        root.title("Go Sensei — KataGo Search Monitor")
        root.geometry("820x720")
        root.configure(bg="#10141c")

        root.protocol("WM_DELETE_WINDOW", self.hide_search_monitor_window)

        title = tk.Label(
            root,
            text="KataGo Search Monitor",
            font=("Consolas", 18, "bold"),
            fg="#78b8ff",
            bg="#10141c",
        )
        title.pack(anchor="w", padx=14, pady=(12, 4))

        subtitle = tk.Label(
            root,
            text="Under-the-hood analysis: request IDs, visits, winrate, score lead, and candidate variations.",
            font=("Consolas", 10),
            fg="#d0d6e0",
            bg="#10141c",
        )
        subtitle.pack(anchor="w", padx=14, pady=(0, 8))

        text_box = tk.Text(
            root,
            wrap="word",
            font=("Consolas", 10),
            fg="#f2f2f2",
            bg="#151a24",
            insertbackground="#ffffff",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=12,
        )
        text_box.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.search_monitor_root = root
        self.search_monitor_text = text_box

    def hide_search_monitor_window(self) -> None:
        root = getattr(self, "search_monitor_root", None)

        if root is None:
            return

        try:
            root.withdraw()
        except Exception:
            pass

    def search_monitor_black_winrate(self, obj) -> float | None:
        if obj is None:
            return None

        if hasattr(obj, "root_winrate_percent"):
            value = getattr(obj, "root_winrate_percent", None)
        else:
            value = getattr(obj, "winrate_percent", None)

        if value is None:
            return None

        return max(0.0, min(100.0, float(value)))

    def search_monitor_score(self, obj) -> float | None:
        if obj is None:
            return None

        if hasattr(obj, "root_score_lead"):
            value = getattr(obj, "root_score_lead", None)
        else:
            value = getattr(obj, "score_lead", None)

        if value is None:
            return None

        return float(value)

    def search_monitor_score_text(self, score: float | None) -> str:
        if score is None:
            return "--"

        if score > 0:
            return f"Black +{abs(score):.2f}"

        if score < 0:
            return f"White +{abs(score):.2f}"

        return "Even"

    def search_monitor_pv_text(self, move_info, max_len: int = 12) -> str:
        pv = getattr(move_info, "pv", None)

        if not pv:
            return ""

        pv = list(pv)[:max_len]

        return " -> ".join(str(move) for move in pv)

    def make_visit_bar(self, visits: int, max_visits: int, width: int = 28) -> str:
        if max_visits <= 0:
            return "-" * width

        filled = int(width * visits / max_visits)
        filled = max(0, min(width, filled))

        return "█" * filled + "░" * (width - filled)

    def build_search_monitor_text(self) -> str:
        lines = []

        state = getattr(self, "analysis_state", None)

        if hasattr(self, "route_analysis_state"):
            try:
                self.route_analysis_state()
            except Exception:
                pass

        if hasattr(self, "get_current_position_result"):
            result = self.get_current_position_result()
        else:
            result = getattr(state, "latest_result", None) if state is not None else None

        thinking = bool(getattr(state, "is_thinking", False)) if state is not None else False
        latest_request_id = getattr(state, "latest_request_id", None) if state is not None else None
        completed_request_id = getattr(state, "completed_request_id", None) if state is not None else None
        elapsed = getattr(state, "latest_elapsed_seconds", None) if state is not None else None
        latest_error = getattr(state, "latest_error", None) if state is not None else None

        mode = self.get_performance_mode().upper() if hasattr(self, "get_performance_mode") else "NORMAL"
        main_visits = self.get_normal_analysis_visits() if hasattr(self, "get_normal_analysis_visits") else "--"
        hover_visits = self.get_hover_max_visits() if hasattr(self, "get_hover_max_visits") else "--"
        depth = self.get_analysis_depth() if hasattr(self, "get_analysis_depth") else "--"
        hover_depth = self.get_hover_pv_depth() if hasattr(self, "get_hover_pv_depth") else "--"

        main_id = getattr(self, "main_analysis_request_id", None)
        hover_id = getattr(self, "hover_analysis_pending_id", None)
        hover_cache = getattr(self, "hover_analysis_cache", {})

        lines.append("GO SENSEI SEARCH MONITOR")
        lines.append("=" * 78)
        lines.append("")
        lines.append(f"Status:              {'THINKING' if thinking else 'IDLE'}")
        lines.append(f"Performance mode:    {mode}")
        lines.append(f"Current player:      {getattr(self.current_player, 'name', self.current_player)}")
        lines.append(f"Board size:          {self.board.size}x{self.board.size}")
        lines.append(f"Rules:               Chinese")
        lines.append(f"Komi:                7.5")
        lines.append(f"Winrate perspective: Black")
        lines.append("")
        lines.append("REQUESTS")
        lines.append("-" * 78)
        lines.append(f"Latest request ID:   {latest_request_id}")
        lines.append(f"Completed request:   {completed_request_id}")
        lines.append(f"Main request ID:     {main_id}")
        lines.append(f"Hover request ID:    {hover_id}")
        lines.append(f"Hover cache size:    {len(hover_cache)}")
        lines.append(f"Last elapsed:        {elapsed:.2f}s" if elapsed is not None else "Last elapsed:        --")
        lines.append("")

        if latest_error:
            lines.append("LATEST ERROR")
            lines.append("-" * 78)
            lines.append(str(latest_error))
            lines.append("")

        lines.append("SEARCH SETTINGS")
        lines.append("-" * 78)
        lines.append(f"Main visits:         {main_visits}")
        lines.append(f"Hover visits:        {hover_visits}")
        lines.append(f"Main PV depth:       {depth}")
        lines.append(f"Hover PV depth:      {hover_depth}")
        lines.append("")

        if result is None:
            lines.append("POSITION")
            lines.append("-" * 78)
            lines.append("No analysis result yet.")
            lines.append("Click ANALYZE in the main board window.")
            lines.append("")
            lines.append("Tip: hover over points after analysis is ON to watch fast hover requests.")
            return "\n".join(lines)

        black = self.search_monitor_black_winrate(result)
        white = 100.0 - black if black is not None else None
        score = self.search_monitor_score(result)
        root_visits = getattr(result, "root_visits", None)

        lines.append("CURRENT POSITION")
        lines.append("-" * 78)

        if black is not None and white is not None:
            lines.append(f"Black winrate:       {black:.2f}%")
            lines.append(f"White winrate:       {white:.2f}%")
        else:
            lines.append("Black winrate:       --")
            lines.append("White winrate:       --")

        lines.append(f"Score lead:          {self.search_monitor_score_text(score)}")
        lines.append(f"Root visits:         {root_visits}")
        lines.append("")

        move_infos = list(getattr(result, "best_moves", []))[:10]
        max_visits = max([int(getattr(move, "visits", 0) or 0) for move in move_infos] + [1])

        lines.append("TOP CANDIDATES")
        lines.append("-" * 78)

        if not move_infos:
            lines.append("No candidate moves yet.")
            return "\n".join(lines)

        for index, move_info in enumerate(move_infos):
            move = getattr(move_info, "move", "")
            visits = int(getattr(move_info, "visits", 0) or 0)
            prior = getattr(move_info, "prior", None)
            black = self.search_monitor_black_winrate(move_info)
            white = 100.0 - black if black is not None else None
            score = self.search_monitor_score(move_info)
            pv = self.search_monitor_pv_text(move_info, max_len=16)
            bar = self.make_visit_bar(visits, max_visits)

            lines.append(f"#{index + 1:<2} {move:<5}  {bar}  {visits} visits")

            if black is not None and white is not None:
                lines.append(f"    Winrate: Black {black:.2f}% | White {white:.2f}%")

            lines.append(f"    Score:   {self.search_monitor_score_text(score)}")

            if prior is not None:
                try:
                    lines.append(f"    Prior:   {float(prior) * 100:.2f}%")
                except Exception:
                    lines.append(f"    Prior:   {prior}")

            if pv:
                lines.append(f"    PV:      {pv}")

            lines.append("")

        lines.append("CONTROLS")
        lines.append("-" * 78)
        lines.append("S = hide/show this search monitor window")
        lines.append("P = cycle FAST / BALANCED / QUALITY")
        lines.append("+/- in the KataGo panel = change variation depth")
        lines.append("Hover any legal point = request fast point analysis")

        return "\n".join(lines)

    def update_search_monitor_window(self) -> None:
        if not self.is_search_monitor_window_enabled():
            return

        self.ensure_search_monitor_window()

        root = getattr(self, "search_monitor_root", None)
        text_box = getattr(self, "search_monitor_text", None)

        if root is None or text_box is None:
            return

        try:
            if not root.winfo_exists():
                self.search_monitor_root = None
                self.search_monitor_text = None
                return

            content = self.build_search_monitor_text()

            text_box.configure(state="normal")
            text_box.delete("1.0", "end")
            text_box.insert("1.0", content)
            text_box.configure(state="disabled")

            root.update_idletasks()
            root.update()

        except Exception as error:
            print(f"[Go Sensei Search Monitor] Window update error: {error}", flush=True)
            self.search_monitor_root = None
            self.search_monitor_text = None

    def run(self) -> None:
        import pygame

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if hasattr(self, "shutdown"):
                        self.shutdown()

                    pygame.quit()
                    raise SystemExit

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.dragging_speed_slider = False

                if event.type == pygame.MOUSEMOTION and getattr(self, "dragging_speed_slider", False):
                    if hasattr(self, "update_speed_from_mouse"):
                        self.update_speed_from_mouse(event.pos[0])

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.reset_board()
                        continue

                    if event.key == pygame.K_a:
                        self.toggle_live_analysis()
                        continue

                    if event.key == pygame.K_i:
                        if hasattr(self, "toggle_ai_opponent"):
                            self.toggle_ai_opponent()
                        continue

                    if event.key == pygame.K_p:
                        if hasattr(self, "cycle_performance_mode"):
                            self.cycle_performance_mode()
                        continue

                    if event.key == pygame.K_s:
                        self.toggle_search_process_overlay()
                        continue

            if hasattr(self, "update_auto_replay"):
                self.update_auto_replay()

            if hasattr(self, "analysis_service"):
                self.analysis_state = self.analysis_service.get_state()

                if hasattr(self, "route_analysis_state"):
                    self.route_analysis_state()

            if hasattr(self, "update_ai_move"):
                self.update_ai_move()

            if hasattr(self, "update_live_move_coaching"):
                self.update_live_move_coaching()

            self.draw()
            self.update_search_monitor_window()

            fps = self.get_target_fps() if hasattr(self, "get_target_fps") else 30
            self.clock.tick(fps)


    def is_search_process_overlay_enabled(self) -> bool:
        return False

    def draw_search_process_overlay(self) -> None:
        return

    def is_search_monitor_window_enabled(self) -> bool:
        return False

    def ensure_search_monitor_window(self) -> None:
        return

    def hide_search_monitor_window(self) -> None:
        root = getattr(self, "search_monitor_root", None)

        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

        self.search_monitor_root = None
        self.search_monitor_text = None
        self.search_monitor_window_enabled = False
        return

    def update_search_monitor_window(self) -> None:
        return

    def toggle_search_process_overlay(self) -> None:
        self.search_monitor_window_enabled = False
        self.hide_search_monitor_window()
        self.status_message = "Search Monitor removed"
        print("[Go Sensei Search Monitor] Removed / disabled", flush=True)
        return


    def ui_theme(self) -> dict:
        return {
            "bg_top": (14, 18, 25),
            "bg_bottom": (27, 24, 18),

            "panel_warm": (28, 24, 18, 246),
            "panel_cool": (18, 23, 32, 246),
            "panel_border_gold": (235, 194, 102),
            "panel_border_blue": (92, 160, 245),

            "card": (38, 42, 50, 238),
            "card_alt": (45, 47, 54, 238),

            "button": (42, 46, 56),
            "button_hover": (58, 65, 80),
            "button_active": (73, 96, 128),
            "button_border": (126, 132, 146),
            "button_text": (238, 241, 246),
            "button_active_text": (255, 242, 204),

            "toolbar": (17, 20, 28, 238),
            "toolbar_border": (76, 84, 104),

            "gold": (255, 218, 132),
            "gold_soft": (210, 170, 92),
            "blue": (104, 174, 255),
            "green": (92, 232, 150),
            "red": (255, 116, 116),
            "purple": (190, 150, 255),

            "muted": (190, 198, 210),
            "white": (246, 247, 242),
            "black": (18, 18, 22),

            "board": (214, 171, 96),
            "board_edge": (116, 72, 34),
            "grid": (55, 37, 22),
            "shadow": (0, 0, 0, 90),
        }

    def draw_vertical_gradient(self, top_color, bottom_color) -> None:
        import pygame

        width, height = self.screen.get_size()

        for y in range(height):
            ratio = y / max(1, height - 1)
            color = (
                int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio),
                int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio),
                int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio),
            )
            pygame.draw.line(self.screen, color, (0, y), (width, y))

    def draw_background_vignette(self) -> None:
        # Kept light and clean so the board stays sharp.
        return

    def draw_soft_shadow_rect(self, rect, radius: int = 18, strength: int = 80, offset=(0, 8)) -> None:
        import pygame

        shadow_rect = rect.move(offset[0], offset[1])

        for i in range(5, 0, -1):
            alpha = max(8, int(strength * (i / 5) * 0.28))
            expanded = shadow_rect.inflate(i * 7, i * 7)

            surface = pygame.Surface((expanded.width, expanded.height), pygame.SRCALPHA)
            pygame.draw.rect(
                surface,
                (0, 0, 0, alpha),
                surface.get_rect(),
                border_radius=radius + i * 3,
            )
            self.screen.blit(surface, expanded.topleft)

    def draw_panel(self, rect, fill, border, radius: int = 18) -> None:
        import pygame

        self.draw_soft_shadow_rect(rect, radius=radius, strength=95, offset=(0, 8))

        surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(surface, fill, surface.get_rect(), border_radius=radius)
        self.screen.blit(surface, rect.topleft)

        pygame.draw.rect(self.screen, border, rect, 2, border_radius=radius)

        inner = rect.inflate(-8, -8)
        pygame.draw.rect(self.screen, (255, 255, 255, 22), inner, 1, border_radius=max(8, radius - 4))

    def button_is_hovered(self, rect) -> bool:
        import pygame
        return rect.collidepoint(pygame.mouse.get_pos())

    def button_is_pressed(self, label: str) -> bool:
        import pygame

        pressed_label = getattr(self, "last_pressed_button_label", None)
        pressed_until = getattr(self, "last_pressed_button_until_ms", 0)

        return pressed_label == label and pygame.time.get_ticks() < pressed_until

    def draw_button(self, rect, label: str, active: bool = False, accent=None) -> None:
        import pygame

        theme = self.ui_theme()
        hovered = self.button_is_hovered(rect)
        pressed = self.button_is_pressed(label)

        if accent is None:
            accent = theme["blue"]

        if active:
            fill = (
                max(0, int(accent[0] * 0.48)),
                max(0, int(accent[1] * 0.48)),
                max(0, int(accent[2] * 0.48)),
            )
            border = accent
            text_color = theme["button_active_text"]
        elif hovered:
            fill = theme["button_hover"]
            border = accent
            text_color = theme["white"]
        else:
            fill = theme["button"]
            border = theme["button_border"]
            text_color = theme["button_text"]

        if pressed:
            rect = rect.move(0, 2)
            fill = (
                max(0, fill[0] - 10),
                max(0, fill[1] - 10),
                max(0, fill[2] - 10),
            )

        shadow = rect.move(0, 4)
        shadow_surface = pygame.Surface((shadow.width, shadow.height), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surface, (0, 0, 0, 95), shadow_surface.get_rect(), border_radius=14)
        self.screen.blit(shadow_surface, shadow.topleft)

        pygame.draw.rect(self.screen, fill, rect, border_radius=14)
        pygame.draw.rect(self.screen, border, rect, 2 if hovered or active else 1, border_radius=14)

        if hovered or active:
            glow_rect = rect.inflate(5, 5)
            glow_surface = pygame.Surface((glow_rect.width, glow_rect.height), pygame.SRCALPHA)
            pygame.draw.rect(glow_surface, (*border, 34), glow_surface.get_rect(), border_radius=17)
            self.screen.blit(glow_surface, glow_rect.topleft)

        font = getattr(self, "small_ui_font", None) or getattr(self, "status_font", None)

        if font is None:
            font = pygame.font.SysFont("arial", 16)

        text_surface = font.render(label, True, text_color)

        if text_surface.get_width() > rect.width - 14:
            small_font = pygame.font.SysFont("arial", 13, bold=True)
            text_surface = small_font.render(label, True, text_color)

        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def get_size_selector_rect(self):
        import pygame

        width = 124
        height = 38
        margin = 20

        return pygame.Rect(
            self.screen.get_width() - width - margin,
            margin,
            width,
            height,
        )

    def draw_size_selector(self) -> None:
        import pygame

        theme = self.ui_theme()
        rect = self.get_size_selector_rect()
        hovered = rect.collidepoint(pygame.mouse.get_pos())

        fill = (44, 50, 64) if hovered else (31, 36, 48)
        border = theme["gold"] if hovered else theme["button_border"]

        self.draw_soft_shadow_rect(rect, radius=18, strength=60, offset=(0, 5))

        pygame.draw.rect(self.screen, fill, rect, border_radius=18)
        pygame.draw.rect(self.screen, border, rect, 2 if hovered else 1, border_radius=18)

        label = f"Board {self.board.size}x{self.board.size}"
        surface = self.small_ui_font.render(label, True, theme["white"])
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def draw_analysis_depth_widget(self, x: int, y: int, width: int) -> int:
        import pygame

        theme = self.ui_theme()

        label = self.small_ui_font.render("Variation Depth", True, theme["gold"])
        self.screen.blit(label, (x, y))
        y += 25

        minus_rect = pygame.Rect(x, y, 38, 32)
        plus_rect = pygame.Rect(x + width - 38, y, 38, 32)
        value_rect = pygame.Rect(x + 46, y, width - 92, 32)

        self.analysis_depth_minus_rect = minus_rect
        self.analysis_depth_plus_rect = plus_rect

        self.draw_button(minus_rect, "-", active=False, accent=theme["gold"])
        self.draw_button(plus_rect, "+", active=False, accent=theme["gold"])

        hovered = value_rect.collidepoint(pygame.mouse.get_pos())
        fill = (38, 43, 55) if hovered else (31, 35, 45)

        pygame.draw.rect(self.screen, fill, value_rect, border_radius=12)
        pygame.draw.rect(self.screen, theme["button_border"], value_rect, 1, border_radius=12)

        value = self.small_ui_font.render(f"{self.get_analysis_depth()} moves", True, theme["white"])
        self.screen.blit(value, value.get_rect(center=value_rect.center))

        return y + 44

    def draw_status_chip(self, toolbar_rect) -> None:
        import pygame

        theme = self.ui_theme()
        status = getattr(self, "status_message", "")

        if not status:
            return

        chip_width = min(520, max(220, len(status) * 8 + 34))
        chip_height = 28

        rect = pygame.Rect(
            toolbar_rect.centerx - chip_width // 2,
            toolbar_rect.top - chip_height - 8,
            chip_width,
            chip_height,
        )

        surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(surface, (22, 26, 36, 228), surface.get_rect(), border_radius=14)
        self.screen.blit(surface, rect.topleft)

        pygame.draw.rect(self.screen, (255, 255, 255, 35), rect, 1, border_radius=14)

        text_surface = self.small_ui_font.render(status, True, theme["muted"])
        self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def get_bottom_button_specs(self):
        specs = [
            ("load", "SGF"),
            ("analysis", "Analyze ON" if getattr(self, "analysis_enabled", False) else "Analyze"),
            ("ai", self.get_ai_button_label() if hasattr(self, "get_ai_button_label") else "AI"),
        ]

        if hasattr(self, "cycle_performance_mode"):
            specs.append(("performance", self.get_performance_mode().upper() if hasattr(self, "get_performance_mode") else "FAST"))

        specs.extend([
            ("beginning", "|<"),
            ("back", "<<"),
            ("play_pause", "Play"),
            ("forward", ">>"),
            ("end", ">|"),
        ])

        return specs

    def draw_bottom_controls(self) -> None:
        import pygame

        theme = self.ui_theme()

        screen_w, screen_h = self.screen.get_size()

        toolbar_margin = 14
        toolbar_h = 58
        toolbar_rect = pygame.Rect(
            toolbar_margin,
            screen_h - toolbar_h - 10,
            screen_w - toolbar_margin * 2,
            toolbar_h,
        )

        toolbar_surface = pygame.Surface((toolbar_rect.width, toolbar_rect.height), pygame.SRCALPHA)
        pygame.draw.rect(toolbar_surface, theme["toolbar"], toolbar_surface.get_rect(), border_radius=20)
        self.screen.blit(toolbar_surface, toolbar_rect.topleft)
        pygame.draw.rect(self.screen, theme["toolbar_border"], toolbar_rect, 1, border_radius=20)

        self.draw_status_chip(toolbar_rect)

        specs = self.get_bottom_button_specs()

        gap = 8
        button_h = 40
        y = toolbar_rect.top + 9

        available_w = toolbar_rect.width - 20
        total_gap = gap * (len(specs) - 1)
        button_w = int((available_w - total_gap) / len(specs))

        self.bottom_button_rects = {}

        x = toolbar_rect.left + 10

        for name, label in specs:
            rect = pygame.Rect(x, y, button_w, button_h)
            self.bottom_button_rects[name] = rect

            active = False
            accent = theme["blue"]

            if name == "analysis":
                active = bool(getattr(self, "analysis_enabled", False))
                accent = theme["green"] if active else theme["blue"]

            elif name == "ai":
                mode = getattr(self, "ai_mode", "off")

                if mode == "human_black":
                    active = True
                    accent = theme["green"]
                elif mode == "human_white":
                    active = True
                    accent = theme["blue"]
                elif mode == "self_play":
                    active = True
                    accent = theme["purple"]
                else:
                    active = False
                    accent = theme["muted"]

            elif name == "performance":
                active = True
                mode = self.get_performance_mode() if hasattr(self, "get_performance_mode") else "fast"

                if mode == "fast":
                    accent = theme["green"]
                elif mode == "balanced":
                    accent = theme["blue"]
                else:
                    accent = theme["purple"]

            elif name in ("play_pause",):
                accent = theme["gold"]

            elif name in ("beginning", "back", "forward", "end"):
                accent = theme["muted"]

            self.draw_button(rect, label, active=active, accent=accent)

            x += button_w + gap

        self.update_mouse_cursor_for_ui()

    def update_mouse_cursor_for_ui(self) -> None:
        import pygame

        mouse_pos = pygame.mouse.get_pos()
        clickable = False

        for rect in getattr(self, "bottom_button_rects", {}).values():
            if rect.collidepoint(mouse_pos):
                clickable = True
                break

        if not clickable:
            try:
                if self.get_size_selector_rect().collidepoint(mouse_pos):
                    clickable = True
            except Exception:
                pass

        if not clickable:
            for rect_name in ("analysis_depth_minus_rect", "analysis_depth_plus_rect"):
                rect = getattr(self, rect_name, None)
                if rect is not None and rect.collidepoint(mouse_pos):
                    clickable = True
                    break

        try:
            if clickable:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
            else:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
        except Exception:
            pass

    def handle_mouse_down(self, mouse_pos: tuple[int, int]) -> None:
        import pygame

        minus_rect = getattr(self, "analysis_depth_minus_rect", None)
        plus_rect = getattr(self, "analysis_depth_plus_rect", None)

        if minus_rect is not None and minus_rect.collidepoint(mouse_pos):
            self.last_pressed_button_label = "-"
            self.last_pressed_button_until_ms = pygame.time.get_ticks() + 120
            self.decrease_analysis_depth()
            return

        if plus_rect is not None and plus_rect.collidepoint(mouse_pos):
            self.last_pressed_button_label = "+"
            self.last_pressed_button_until_ms = pygame.time.get_ticks() + 120
            self.increase_analysis_depth()
            return

        try:
            size_rect = self.get_size_selector_rect()

            if size_rect.collidepoint(mouse_pos):
                self.last_pressed_button_label = f"Board {self.board.size}x{self.board.size}"
                self.last_pressed_button_until_ms = pygame.time.get_ticks() + 120
                print("[Go Sensei UI] Size button clicked", flush=True)
                self.cycle_board_size()
                return
        except Exception:
            pass

        button_rects = getattr(self, "bottom_button_rects", {})

        for button_name, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                label = None

                for candidate_name, candidate_label in self.get_bottom_button_specs():
                    if candidate_name == button_name:
                        label = candidate_label
                        break

                self.last_pressed_button_label = label or button_name
                self.last_pressed_button_until_ms = pygame.time.get_ticks() + 120

                print(f"[Go Sensei UI] Bottom button clicked: {button_name}", flush=True)
                self.handle_button_click(button_name)
                return

        self.handle_board_click(mouse_pos)


    def ui_theme(self) -> dict:
        # Backward-compatible theme.
        # Includes newer polished UI keys AND older keys used by previous draw methods.
        return {
            "background": (17, 20, 28),
            "bg": (17, 20, 28),
            "bg_top": (14, 18, 25),
            "bg_bottom": (27, 24, 18),

            "panel": (24, 27, 35, 245),
            "panel_warm": (28, 24, 18, 246),
            "panel_cool": (18, 23, 32, 246),
            "panel_border": (126, 132, 146),
            "panel_border_gold": (235, 194, 102),
            "panel_border_blue": (92, 160, 245),

            "card": (38, 42, 50, 238),
            "card_alt": (45, 47, 54, 238),

            "button": (42, 46, 56),
            "button_hover": (58, 65, 80),
            "button_active": (73, 96, 128),
            "button_border": (126, 132, 146),
            "button_text": (238, 241, 246),
            "button_active_text": (255, 242, 204),

            "toolbar": (17, 20, 28, 238),
            "toolbar_border": (76, 84, 104),

            "gold": (255, 218, 132),
            "gold_soft": (210, 170, 92),
            "blue": (104, 174, 255),
            "green": (92, 232, 150),
            "red": (255, 116, 116),
            "purple": (190, 150, 255),

            "muted": (190, 198, 210),
            "text": (246, 247, 242),
            "text_muted": (190, 198, 210),
            "white": (246, 247, 242),
            "black": (18, 18, 22),

            "board": (214, 171, 96),
            "board_edge": (116, 72, 34),
            "grid": (55, 37, 22),
            "star": (55, 37, 22),

            "shadow": (0, 0, 0, 90),
            "line": (255, 255, 255, 28),
        }


    def ui_theme(self) -> dict:
        # KeyError-proof theme.
        # This keeps the nicer UI changes, but also supports older drawing code
        # that asks for keys like "background" or "board_inner_highlight".
        class GoSenseiTheme(dict):
            def __missing__(self, key):
                fallback_map = {
                    "background": (17, 20, 28),
                    "bg": (17, 20, 28),
                    "panel": (24, 27, 35, 245),
                    "panel_border": (126, 132, 146),
                    "text": (246, 247, 242),
                    "text_muted": (190, 198, 210),
                    "muted": (190, 198, 210),
                    "white": (246, 247, 242),
                    "black": (18, 18, 22),
                    "gold": (255, 218, 132),
                    "blue": (104, 174, 255),
                    "green": (92, 232, 150),
                    "red": (255, 116, 116),
                    "purple": (190, 150, 255),
                    "board": (214, 171, 96),
                    "board_edge": (116, 72, 34),
                    "board_inner_highlight": (255, 226, 165),
                    "board_outer_shadow": (72, 44, 22),
                    "grid": (55, 37, 22),
                    "star": (55, 37, 22),
                    "line": (255, 255, 255, 28),
                    "shadow": (0, 0, 0, 90),
                    "button": (42, 46, 56),
                    "button_hover": (58, 65, 80),
                    "button_active": (73, 96, 128),
                    "button_border": (126, 132, 146),
                    "button_text": (238, 241, 246),
                    "button_active_text": (255, 242, 204),
                    "toolbar": (17, 20, 28, 238),
                    "toolbar_border": (76, 84, 104),
                    "card": (38, 42, 50, 238),
                    "card_alt": (45, 47, 54, 238),
                }

                value = fallback_map.get(key, (190, 198, 210))
                self[key] = value
                print(f"[Go Sensei Theme] Missing theme key '{key}' used fallback {value}", flush=True)
                return value

        return GoSenseiTheme({
            "background": (17, 20, 28),
            "bg": (17, 20, 28),
            "bg_top": (14, 18, 25),
            "bg_bottom": (27, 24, 18),

            "panel": (24, 27, 35, 245),
            "panel_warm": (28, 24, 18, 246),
            "panel_cool": (18, 23, 32, 246),
            "panel_border": (126, 132, 146),
            "panel_border_gold": (235, 194, 102),
            "panel_border_blue": (92, 160, 245),

            "card": (38, 42, 50, 238),
            "card_alt": (45, 47, 54, 238),

            "button": (42, 46, 56),
            "button_hover": (58, 65, 80),
            "button_active": (73, 96, 128),
            "button_border": (126, 132, 146),
            "button_text": (238, 241, 246),
            "button_active_text": (255, 242, 204),

            "toolbar": (17, 20, 28, 238),
            "toolbar_border": (76, 84, 104),

            "gold": (255, 218, 132),
            "gold_soft": (210, 170, 92),
            "blue": (104, 174, 255),
            "green": (92, 232, 150),
            "red": (255, 116, 116),
            "purple": (190, 150, 255),

            "muted": (190, 198, 210),
            "text": (246, 247, 242),
            "text_muted": (190, 198, 210),
            "white": (246, 247, 242),
            "black": (18, 18, 22),

            "board": (214, 171, 96),
            "board_light": (232, 190, 112),
            "board_dark": (178, 122, 58),
            "board_edge": (116, 72, 34),
            "board_inner_highlight": (255, 226, 165),
            "board_outer_shadow": (72, 44, 22),
            "board_shadow": (72, 44, 22),

            "grid": (55, 37, 22),
            "star": (55, 37, 22),
            "line": (255, 255, 255, 28),
            "shadow": (0, 0, 0, 90),

            "stone_black": (18, 18, 22),
            "stone_white": (245, 242, 232),
            "stone_shadow": (0, 0, 0, 120),
            "last_move": (255, 218, 132),
        })


    def get_go_file_labels(self) -> list[str]:
        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        return list(letters[: self.board.size])

    def draw_board_texture(self, board_rect) -> None:
        import math
        import random
        import pygame

        theme = self.ui_theme()

        outer_shadow = board_rect.inflate(18, 18)
        shadow_surface = pygame.Surface((outer_shadow.width, outer_shadow.height), pygame.SRCALPHA)
        pygame.draw.rect(
            shadow_surface,
            (0, 0, 0, 72),
            shadow_surface.get_rect(),
            border_radius=22,
        )
        self.screen.blit(shadow_surface, outer_shadow.topleft)

        surface = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)

        light = theme["board_light"]
        dark = theme["board_dark"]

        for y in range(board_rect.height):
            ratio = y / max(1, board_rect.height - 1)
            color = (
                int(light[0] * (1 - ratio) + dark[0] * ratio),
                int(light[1] * (1 - ratio) + dark[1] * ratio),
                int(light[2] * (1 - ratio) + dark[2] * ratio),
            )
            pygame.draw.line(surface, color, (0, y), (board_rect.width, y))

        rng = random.Random(self.board.size * 101 + board_rect.width)

        for _ in range(24):
            y = rng.randint(8, max(9, board_rect.height - 8))
            amplitude = rng.uniform(2.0, 7.0)
            thickness = rng.randint(1, 2)
            alpha = rng.randint(14, 32)

            points = []

            for x in range(0, board_rect.width, 12):
                curve = math.sin((x / max(1, board_rect.width)) * math.pi * rng.uniform(3.5, 8.0) + rng.uniform(0, 6.28))
                yy = int(y + curve * amplitude)
                points.append((x, yy))

            if len(points) >= 2:
                pygame.draw.lines(surface, (118, 79, 37, alpha), False, points, thickness)

        pygame.draw.rect(surface, theme["board_edge"], surface.get_rect(), 8, border_radius=18)
        pygame.draw.rect(surface, theme["board_inner_highlight"], surface.get_rect().inflate(-10, -10), 1, border_radius=14)

        self.screen.blit(surface, board_rect.topleft)

    def draw_board_coordinates(self) -> None:
        import pygame

        theme = self.ui_theme()

        files = self.get_go_file_labels()
        size = self.board.size

        board_left = int(self.board_left)
        board_right = int(self.board_right)
        board_top = int(self.board_top)
        board_bottom = int(self.board_bottom)
        cell_size = float(self.cell_size)

        font_size = max(16, int(cell_size * 0.34))
        font = pygame.font.SysFont("segoe ui", font_size, bold=True)

        file_offset = max(18, int(cell_size * 0.58))
        rank_offset = max(18, int(cell_size * 0.60))

        text_color = (248, 239, 214)
        shadow_color = (20, 20, 22)

        for col, file_label in enumerate(files):
            x = int(board_left + col * cell_size)

            top_y = int(board_top - file_offset)
            bottom_y = int(board_bottom + file_offset - font_size * 0.50)

            label_surface = font.render(file_label, True, text_color)
            label_shadow = font.render(file_label, True, shadow_color)

            label_rect_top = label_surface.get_rect(center=(x, top_y))
            label_rect_bottom = label_surface.get_rect(center=(x, bottom_y))

            self.screen.blit(label_shadow, label_rect_top.move(1, 1))
            self.screen.blit(label_surface, label_rect_top)

            self.screen.blit(label_shadow, label_rect_bottom.move(1, 1))
            self.screen.blit(label_surface, label_rect_bottom)

        for row in range(size):
            rank_label = str(size - row)
            y = int(board_top + row * cell_size)

            left_x = int(board_left - rank_offset)
            right_x = int(board_right + rank_offset)

            label_surface = font.render(rank_label, True, text_color)
            label_shadow = font.render(rank_label, True, shadow_color)

            label_rect_left = label_surface.get_rect(center=(left_x, y))
            label_rect_right = label_surface.get_rect(center=(right_x, y))

            self.screen.blit(label_shadow, label_rect_left.move(1, 1))
            self.screen.blit(label_surface, label_rect_left)

            self.screen.blit(label_shadow, label_rect_right.move(1, 1))
            self.screen.blit(label_surface, label_rect_right)

    def draw_coordinates(self) -> None:
        self.draw_board_coordinates()

    def draw_board_labels(self) -> None:
        self.draw_board_coordinates()

    def draw_coordinate_labels(self) -> None:
        self.draw_board_coordinates()


    def draw_board_texture(self, board_rect) -> None:
        import pygame

        theme = self.ui_theme()

        outer_shadow_rect = board_rect.inflate(16, 16)
        shadow_surface = pygame.Surface(
            (outer_shadow_rect.width, outer_shadow_rect.height),
            pygame.SRCALPHA,
        )
        pygame.draw.rect(
            shadow_surface,
            (0, 0, 0, 55),
            shadow_surface.get_rect(),
            border_radius=22,
        )
        self.screen.blit(shadow_surface, outer_shadow_rect.topleft)

        surface = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)

        top_color = (231, 192, 111)
        bottom_color = (205, 157, 82)

        for y in range(board_rect.height):
            ratio = y / max(1, board_rect.height - 1)
            color = (
                int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio),
                int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio),
                int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio),
            )
            pygame.draw.line(surface, color, (0, y), (board_rect.width, y))

        pygame.draw.rect(
            surface,
            (118, 78, 40),
            surface.get_rect(),
            width=8,
            border_radius=18,
        )

        inner_rect = surface.get_rect().inflate(-10, -10)
        pygame.draw.rect(
            surface,
            (246, 214, 146),
            inner_rect,
            width=1,
            border_radius=14,
        )

        highlight = pygame.Surface((board_rect.width, board_rect.height), pygame.SRCALPHA)
        pygame.draw.rect(
            highlight,
            (255, 255, 255, 18),
            pygame.Rect(10, 10, board_rect.width - 20, 28),
            border_radius=12,
        )
        surface.blit(highlight, (0, 0))

        self.screen.blit(surface, board_rect.topleft)


def main() -> None:
    window = GoBoardWindow(board_size=19)
    window.run()


if __name__ == "__main__":
    main()
