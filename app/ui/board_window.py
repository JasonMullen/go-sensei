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


class GoBoardWindow:
    def __init__(self, board_size: int = 19) -> None:
        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move: tuple[int, int] | None = None
        self.status_message = ""

        self.loaded_game: SgfGame | None = None
        self.loaded_sgf_path: Path | None = None
        self.move_index = 0
        self.black_captures = 0
        self.white_captures = 0
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

                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    self.reset_board()

            self.update_auto_replay()
            self.draw()
            pygame.display.flip()
            self.clock.tick(60)

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

        if self.loaded_game is None:
            self.status_message = "Load an SGF file first"
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

        try:
            captured_count = self.board.place_stone(coordinate, self.current_player)
        except ValueError:
            self.status_message = f"Illegal move: {coordinate}"
            return

        self.play_stone_sound()
        self.last_move = (row, col)

        if captured_count == 1:
            self.status_message = "Captured 1 stone"
        elif captured_count > 1:
            self.status_message = f"Captured {captured_count} stones"
        else:
            self.status_message = ""

        self.switch_turn()

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
        self.draw_dropdown()
        self.draw_speed_slider()
        self.draw_status_text()
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
            "beginning": "|<",
            "back": "<<",
            "play_pause": "PAUSE" if self.is_playing else "PLAY",
            "forward": ">>",
            "end": ">|",
        }

        for button_name, rect in self.button_rects.items():
            enabled = button_name == "load" or self.loaded_game is not None
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


def main() -> None:
    window = GoBoardWindow(board_size=19)
    window.run()


if __name__ == "__main__":
    main()
