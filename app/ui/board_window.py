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


class GoBoardWindow:
    def __init__(self, board_size: int = 19) -> None:
        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move: tuple[int, int] | None = None
        self.status_message = ""

        self.analysis_enabled = False
        self.analysis_service = LiveAnalysisService(max_visits=4)
        self.analysis_state = LiveAnalysisState()

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

    def draw_wood_grain(
        self,
        surface: pygame.Surface,
        rng: random.Random,
    ) -> None:
        for _ in range(500):
            x = rng.randint(0, self.board_pixels - 1)
            width = rng.randint(1, 2)
            alpha = rng.randint(8, 22)

            strip = pygame.Surface((width, self.board_pixels), pygame.SRCALPHA)
            strip.fill((102, 73, 30, alpha))
            surface.blit(strip, (x, 0))

        for _ in range(240):
            x = rng.randint(0, self.board_pixels - 1)
            width = 1
            alpha = rng.randint(5, 12)

            strip = pygame.Surface((width, self.board_pixels), pygame.SRCALPHA)
            strip.fill((255, 231, 160, alpha))
            surface.blit(strip, (x, 0))

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
                    self.shutdown()
                    self.shutdown()
                    pygame.quit()
                    sys.exit()

                if event.type == pygame.VIDEORESIZE:
                    self.handle_resize(event.w, event.h)

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.dragging_speed_slider = False

                if event.type == pygame.MOUSEMOTION and self.dragging_speed_slider:
                    self.update_speed_from_mouse(event.pos[0])

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.reset_board()
                    elif event.key == pygame.K_a:
                        self.toggle_live_analysis()

            self.update_auto_replay()
            self.analysis_state = self.analysis_service.get_state()
            self.draw()
            pygame.display.flip()
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
        if self.speed_slider_hit_rect.collidepoint(mouse_pos):
            self.dragging_speed_slider = True
            self.update_speed_from_mouse(mouse_pos[0])
            return

        for button_name, rect in self.button_rects.items():
            if rect.collidepoint(mouse_pos):
                self.handle_button_click(button_name)
                return

        if self.dropdown_rect.collidepoint(mouse_pos):
            self.dropdown_open = not self.dropdown_open
            return

        if self.dropdown_open:
            for size, rect in self.dropdown_option_rects:
                if rect.collidepoint(mouse_pos):
                    self.change_board_size(size)
                    self.dropdown_open = False
                    return

            self.dropdown_open = False

        self.handle_board_click(mouse_pos)

    def handle_button_click(self, button_name: str) -> None:
        if button_name == "load":
            self.load_sgf_from_dialog()
            return

        if button_name == "analysis":
            self.toggle_live_analysis()
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

        point = self.mouse_to_point(mouse_pos)

        if point is None:
            return

        row, col = point
        coordinate = point_to_human(row, col, self.board.size)
        played_stone = self.current_player

        # If you undid a move and click the exact same next move,
        # treat it like redo instead of creating a duplicate branch.
        if self.manual_move_index < len(self.manual_move_history):
            next_coordinate, next_stone = self.manual_move_history[self.manual_move_index]

            if next_coordinate == coordinate and next_stone == played_stone:
                self.step_manual_forward(play_sound=True)
                return

            # If the new move is different, cut off the old future line.
            self.manual_move_history = self.manual_move_history[: self.manual_move_index]

        try:
            captured_count = self.board.place_stone(coordinate, played_stone)
        except ValueError:
            self.status_message = f"Illegal move: {coordinate}"
            return

        self.manual_move_history.append((coordinate, played_stone))
        self.manual_move_index += 1

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
        else:
            self.status_message = self.get_manual_status_text()

        self.switch_turn()

        if self.analysis_enabled:
            self.request_live_analysis()


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
        self.draw_analysis_panel()
        self.draw_control_bar()

    def draw_coordinates(self) -> None:
        columns = GO_COLUMNS[: self.board.size]

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, 8))
            self.screen.blit(
                bottom,
                (x - bottom.get_width() // 2, self.board_bottom + 27),
            )

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (15, y - left.get_height() // 2))
            self.screen.blit(
                right,
                (
                    self.window_width - 15 - right.get_width(),
                    y - right.get_height() // 2,
                ),
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
            "beginning": "|<",
            "back": "<<",
            "play_pause": "PAUSE" if self.is_playing else "PLAY",
            "forward": ">>",
            "end": ">|",
        }

        for button_name, rect in self.button_rects.items():
            enabled = button_name in ("load", "analysis", "beginning", "back", "forward", "end", "play_pause") or self.loaded_game is not None
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

    def request_live_analysis(self) -> None:
        print(
            f"[Go Sensei Board] Sending current board to KataGo for {self.current_player.name}...",
            flush=True,
        )
        self.analysis_service.request_analysis(
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
        recommendations = self.get_analysis_recommendations(limit=5)

        for index, (row, col, move) in enumerate(recommendations, start=1):
            x, y = self.point_to_pixels(row, col)
            self.draw_recommendation_marker(x, y, index)

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
        panel_width = 380
        panel_height = min(620, self.window_height - 116)

        panel_left = self.window_width - panel_width - 18
        panel_top = 76

        if panel_left < self.board_right + 12:
            panel_left = self.board_right + 12

        if panel_left + panel_width > self.window_width - 8:
            panel_left = self.window_width - panel_width - 8

        panel_rect = pygame.Rect(panel_left, panel_top, panel_width, panel_height)

        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill((24, 26, 31, 235))
        self.screen.blit(panel_surface, panel_rect.topleft)

        pygame.draw.rect(
            self.screen,
            (238, 205, 125),
            panel_rect,
            2,
            border_radius=14,
        )

        x = panel_rect.left + 18
        y = panel_rect.top + 16
        content_right = panel_rect.right - 18

        def draw_text(
            value: str,
            font=None,
            color=(240, 240, 240),
            gap: int = 24,
            x_offset: int = 0,
        ) -> None:
            nonlocal y

            if y > panel_rect.bottom - 28:
                return

            selected_font = font or self.small_ui_font
            surface = selected_font.render(value, True, color)
            self.screen.blit(surface, (x + x_offset, y))
            y += gap

        def draw_card(height: int, title: str) -> pygame.Rect:
            nonlocal y

            card_rect = pygame.Rect(
                x - 4,
                y,
                panel_width - 28,
                height,
            )

            card_surface = pygame.Surface((card_rect.width, card_rect.height), pygame.SRCALPHA)
            card_surface.fill((255, 255, 255, 24))
            self.screen.blit(card_surface, card_rect.topleft)

            pygame.draw.rect(
                self.screen,
                (255, 255, 255, 45),
                card_rect,
                1,
                border_radius=10,
            )

            title_surface = self.small_ui_font.render(title, True, (255, 224, 150))
            self.screen.blit(title_surface, (card_rect.left + 12, card_rect.top + 9))

            y += 34
            return card_rect

        def end_card(card_rect: pygame.Rect) -> None:
            nonlocal y
            y = card_rect.bottom + 12

        def draw_winrate_bar(
            black_winrate: float | None,
            white_winrate: float | None,
        ) -> None:
            nonlocal y

            bar_rect = pygame.Rect(x + 4, y, panel_width - 44, 20)
            pygame.draw.rect(self.screen, (238, 238, 238), bar_rect, border_radius=10)

            if black_winrate is None or white_winrate is None:
                pygame.draw.rect(self.screen, (90, 90, 95), bar_rect, border_radius=10)
            else:
                black_width = int(bar_rect.width * (black_winrate / 100.0))
                black_rect = pygame.Rect(bar_rect.left, bar_rect.top, black_width, bar_rect.height)
                white_rect = pygame.Rect(bar_rect.left + black_width, bar_rect.top, bar_rect.width - black_width, bar_rect.height)

                pygame.draw.rect(self.screen, (25, 25, 28), black_rect, border_radius=10)
                pygame.draw.rect(self.screen, (235, 235, 235), white_rect, border_radius=10)
                pygame.draw.rect(self.screen, (238, 205, 125), bar_rect, 1, border_radius=10)

            y += 30

        title = self.status_font.render("KataGo Analysis", True, (255, 224, 150))
        self.screen.blit(title, (x, y))
        y += 32

        subtitle = "ON" if self.analysis_enabled else "OFF"
        status_color = (90, 235, 145) if self.analysis_enabled else (235, 120, 120)
        subtitle_surface = self.small_ui_font.render(f"Engine: {subtitle}", True, status_color)
        self.screen.blit(subtitle_surface, (x, y))
        y += 28

        result = self.analysis_state.latest_result
        black_winrate, white_winrate = self.get_stable_black_white_winrates()
        black_score_lead = self.get_stable_black_score_lead()

        # Status card
        card = draw_card(92, "Status")

        if self.analysis_state.is_thinking:
            draw_text("Thinking...", color=(90, 190, 255), gap=22, x_offset=8)
        elif self.analysis_state.latest_error:
            draw_text("Error", color=(255, 110, 110), gap=22, x_offset=8)
        elif result is not None:
            draw_text("Ready", color=(90, 235, 145), gap=22, x_offset=8)
        else:
            draw_text("Waiting for analysis", color=(220, 220, 220), gap=22, x_offset=8)

        if self.analysis_state.latest_elapsed_seconds is not None:
            draw_text(
                f"Last run: {self.analysis_state.latest_elapsed_seconds:.2f}s",
                color=(200, 200, 205),
                gap=22,
                x_offset=8,
            )
        else:
            draw_text("Click ANALYZE to begin", color=(200, 200, 205), gap=22, x_offset=8)

        end_card(card)

        # Winrate card
        card = draw_card(126, "Black / White winrate")

        if black_winrate is None or white_winrate is None:
            draw_text("No result yet", color=(210, 210, 210), gap=24, x_offset=8)
            draw_winrate_bar(None, None)
        else:
            draw_text(
                f"Black: {black_winrate:.1f}%",
                color=(245, 245, 245),
                gap=22,
                x_offset=8,
            )
            draw_text(
                f"White: {white_winrate:.1f}%",
                color=(245, 245, 245),
                gap=22,
                x_offset=8,
            )
            draw_winrate_bar(black_winrate, white_winrate)

        end_card(card)

        # Score card
        card = draw_card(112, "Point estimate")

        if black_score_lead is None:
            draw_text("Waiting for score estimate", color=(210, 210, 210), gap=24, x_offset=8)
        else:
            white_score_lead = -black_score_lead

            draw_text(f"Black: {black_score_lead:+.2f} pts", gap=22, x_offset=8)
            draw_text(f"White: {white_score_lead:+.2f} pts", gap=22, x_offset=8)

            if black_score_lead > 0:
                draw_text(f"Leader: Black by {abs(black_score_lead):.2f}", color=(90, 235, 145), gap=22, x_offset=8)
            elif black_score_lead < 0:
                draw_text(f"Leader: White by {abs(black_score_lead):.2f}", color=(90, 235, 145), gap=22, x_offset=8)
            else:
                draw_text("Leader: Even", color=(90, 235, 145), gap=22, x_offset=8)

        end_card(card)

        # Captures card
        card = draw_card(108, "Captures")

        draw_text(f"Black captured: {self.black_captures}", gap=22, x_offset=8)
        draw_text(f"White captured: {self.white_captures}", gap=22, x_offset=8)
        draw_text(
            f"Stones removed — B:{self.white_captures}  W:{self.black_captures}",
            color=(200, 200, 205),
            gap=22,
            x_offset=8,
        )

        end_card(card)

        # Best moves card
        remaining_height = panel_rect.bottom - y - 12
        card = draw_card(max(120, remaining_height), "Recommended moves")

        if result is None:
            draw_text("No recommendations yet", color=(210, 210, 210), gap=24, x_offset=8)
        else:
            for index, move in enumerate(result.best_moves[:5], start=1):
                # Anchor recommended move winrates to Black/White.
                # Do not flip based on whose turn KataGo is analyzing.
                black_after = move.winrate_percent
                white_after = 100.0 - black_after

                move_line = f"{index}. {move.move}"
                stat_line = f"B {black_after:.1f}% | W {white_after:.1f}% | {move.visits}v"

                draw_text(move_line, color=(255, 255, 255), gap=20, x_offset=8)
                draw_text(stat_line, color=(185, 205, 255), gap=24, x_offset=24)

        end_card(card)


def main() -> None:
    window = GoBoardWindow(board_size=19)
    window.run()


if __name__ == "__main__":
    main()
