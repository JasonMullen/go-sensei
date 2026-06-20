import math
import random
import sys
from pathlib import Path

import pygame
import pygame.gfxdraw

from app.core.board import Board
from app.core.coordinates import GO_COLUMNS, point_to_human
from app.core.stone import Stone


class GoBoardWindow:
    def __init__(self, board_size: int = 19) -> None:
        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move: tuple[int, int] | None = None
        self.status_message = ""
        self.stone_sound = self.load_stone_sound()

        pygame.init()
        pygame.display.set_caption("Go Sensei Board")

        self.window_width = 1400
        self.window_height = 1480
        self.min_window_width = 960
        self.min_window_height = 1000

        self.screen = pygame.display.set_mode(
            (self.window_width, self.window_height),
            pygame.RESIZABLE,
        )
        self.clock = pygame.time.Clock()

        self.coord_font = pygame.font.SysFont("georgia", 28, bold=True)
        self.status_font = pygame.font.SysFont("georgia", 26, bold=True)
        self.ui_font = pygame.font.SysFont("georgia", 22, bold=True)

        self.outer_bg = (232, 200, 118)
        self.board_base = (216, 181, 96)
        self.line_color = (64, 47, 24)
        self.star_color = (28, 20, 8)
        self.text_color = (42, 30, 16)

        self.ui_border = (80, 55, 26)
        self.ui_fill = (223, 188, 102)
        self.ui_hover = (238, 205, 125)

        self.black_core = (32, 32, 34)
        self.black_edge = (12, 12, 12)
        self.black_highlight = (92, 92, 96)

        self.white_edge = (175, 175, 180)
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
        self.cached_stone_radius: int | None = None

        self.dropdown_open = False
        self.dropdown_rect = pygame.Rect(0, 0, 0, 0)
        self.dropdown_option_rects: list[tuple[int, pygame.Rect]] = []

        self.recalculate_layout()

    def recalculate_layout(self) -> None:
        self.cell_size = self.board_pixels / (self.board.size - 1)
        self.stone_radius = int(self.cell_size * 0.43)
        self.rebuild_stone_cache_if_needed()
        header_height = 86
        footer_height = 96
        side_padding = 74

        available_width = self.window_width - (side_padding * 2)
        available_height = self.window_height - header_height - footer_height

        self.board_pixels = int(min(available_width, available_height))
        self.board_pixels = max(540, self.board_pixels)

        self.board_left = (self.window_width - self.board_pixels) // 2
        self.board_top = header_height
        self.board_right = self.board_left + self.board_pixels
        self.board_bottom = self.board_top + self.board_pixels

        self.cell_size = self.board_pixels / (self.board.size - 1)
        self.stone_radius = int(self.cell_size * 0.43)

        self.dropdown_rect = pygame.Rect(
            self.window_width - 220,
            20,
            170,
            44,
        )

        self.dropdown_option_rects = []
        option_top = self.dropdown_rect.bottom + 4

        for index, size in enumerate([19, 13, 9]):
            option_rect = pygame.Rect(
                self.dropdown_rect.left,
                option_top + (index * 44),
                self.dropdown_rect.width,
                44,
            )
            self.dropdown_option_rects.append((size, option_rect))

        self.rebuild_board_surface_if_needed()

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

def rebuild_stone_cache_if_needed(self) -> None:
    if self.cached_stone_radius == self.stone_radius:
        return

    self.black_stone_surface = self.create_stone_surface(Stone.BLACK)
    self.white_stone_surface = self.create_stone_surface(Stone.WHITE)
    self.cached_stone_radius = self.stone_radius

def create_stone_surface(self, stone: Stone) -> pygame.Surface:
    scale = 4
    radius = self.stone_radius
    hi_radius = radius * scale

    width = hi_radius * 4
    height = hi_radius * 4

    hi_surface = pygame.Surface((width, height), pygame.SRCALPHA)
    center_x = width // 2
    center_y = height // 2

    # Shadow
    for shadow_radius in range(hi_radius + 8, hi_radius - 4, -1):
        alpha = max(0, 18 - (hi_radius + 8 - shadow_radius) * 2)
        pygame.gfxdraw.filled_circle(
            hi_surface,
            center_x + int(0.16 * hi_radius),
            center_y + int(0.20 * hi_radius),
            shadow_radius,
            (0, 0, 0, alpha),
        )

    # Main body gradient
    for current_radius in range(hi_radius, 0, -1):
        t = current_radius / hi_radius

        if stone == Stone.BLACK:
            shade = int(28 + (70 - 28) * (1 - t) * 0.9)
            color = (shade, shade, shade + 3, 255)
        else:
            shade = int(220 + (28 * (1 - t)))
            color = (shade, shade, shade, 255)

        pygame.gfxdraw.filled_circle(
            hi_surface,
            center_x,
            center_y,
            current_radius,
            color,
        )

    # Rim / edge
    if stone == Stone.BLACK:
        rim_color = (16, 16, 18, 255)
    else:
        rim_color = (168, 168, 174, 255)

    pygame.gfxdraw.aacircle(
        hi_surface,
        center_x,
        center_y,
        hi_radius,
        rim_color,
    )
    pygame.gfxdraw.aacircle(
        hi_surface,
        center_x,
        center_y,
        hi_radius - 1,
        rim_color,
    )

    # Inner glow / top lighting
    if stone == Stone.BLACK:
        glow_color = (95, 95, 100, 85)
        highlight_color = (170, 170, 175, 110)
    else:
        glow_color = (255, 255, 255, 70)
        highlight_color = (255, 255, 255, 150)

    for glow_radius in range(int(hi_radius * 0.88), int(hi_radius * 0.55), -1):
        alpha = max(0, 6 - (int(hi_radius * 0.88) - glow_radius))
        pygame.gfxdraw.filled_circle(
            hi_surface,
            center_x - int(hi_radius * 0.14),
            center_y - int(hi_radius * 0.18),
            glow_radius,
            (*glow_color[:3], alpha),
        )

    # Specular highlight
    highlight_x = center_x - int(hi_radius * 0.36)
    highlight_y = center_y - int(hi_radius * 0.38)

    for highlight_radius in range(int(hi_radius * 0.24), 0, -1):
        alpha = max(0, int(120 * (highlight_radius / (hi_radius * 0.24))))
        pygame.gfxdraw.filled_circle(
            hi_surface,
            highlight_x,
            highlight_y,
            highlight_radius,
            (*highlight_color[:3], alpha),
        )

    # Subtle bottom shading
    for shade_radius in range(int(hi_radius * 0.92), int(hi_radius * 0.60), -1):
        alpha = max(0, 10 - (int(hi_radius * 0.92) - shade_radius))
        pygame.gfxdraw.filled_circle(
            hi_surface,
            center_x + int(hi_radius * 0.10),
            center_y + int(hi_radius * 0.18),
            shade_radius,
            (0, 0, 0, alpha),
        )

    final_size = radius * 4
    final_surface = pygame.transform.smoothscale(
        hi_surface,
        (final_size, final_size),
    )

    return final_surface

def draw_cached_stone(self, x: int, y: int, stone: Stone) -> None:
    if stone == Stone.BLACK:
        stone_surface = self.black_stone_surface
    else:
        stone_surface = self.white_stone_surface

    if stone_surface is None:
        return

    rect = stone_surface.get_rect(center=(x, y))
    self.screen.blit(stone_surface, rect)


    def draw_wood_grain(
        self,
        surface: pygame.Surface,
        rng: random.Random,
    ) -> None:
        for _ in range(420):
            x = rng.randint(0, self.board_pixels - 1)
            width = rng.randint(1, 3)
            alpha = rng.randint(8, 24)

            strip = pygame.Surface((width, self.board_pixels), pygame.SRCALPHA)
            strip.fill((120, 84, 36, alpha))
            surface.blit(strip, (x, 0))

        for _ in range(260):
            x = rng.randint(0, self.board_pixels - 1)
            width = rng.randint(1, 2)
            alpha = rng.randint(5, 14)

            strip = pygame.Surface((width, self.board_pixels), pygame.SRCALPHA)
            strip.fill((255, 238, 180, alpha))
            surface.blit(strip, (x, 0))

        for _ in range(140):
            y = rng.randint(0, self.board_pixels - 1)
            alpha = rng.randint(3, 8)

            strip = pygame.Surface((self.board_pixels, 1), pygame.SRCALPHA)
            strip.fill((255, 242, 205, alpha))
            surface.blit(strip, (0, y))

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

            return pygame.mixer.Sound(str(sound_path))
        except pygame.error:
            return None
        except FileNotFoundError:
            return None

    def play_stone_sound(self) -> None:
        if self.stone_sound is not None:
            self.stone_sound.play()

    def draw_grid(self, surface: pygame.Surface) -> None:
        grid_width = 2 if self.board_pixels >= 900 else 1

        for index in range(self.board.size):
            x = round(index * self.cell_size)
            y = round(index * self.cell_size)

            pygame.draw.line(
                surface,
                self.line_color,
                (0, y),
                (self.board_pixels, y),
                grid_width,
            )

            pygame.draw.line(
                surface,
                self.line_color,
                (x, 0),
                (x, self.board_pixels),
                grid_width,
            )

    def draw_star_points(self, surface: pygame.Surface) -> None:
        star_radius = max(3, int(self.cell_size * 0.085))

        for row, col in self.get_star_points():
            x = round(col * self.cell_size)
            y = round(row * self.cell_size)

            pygame.draw.circle(
                surface,
                self.star_color,
                (x, y),
                star_radius,
            )

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
                    try:
                        self.handle_mouse_down(event.pos)
                    except ValueError:
                        self.status_message = "Illegal move"
                    except Exception as error:
                        self.status_message = f"Move rejected: {error}"

                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    self.reset_board()

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

    def change_board_size(self, board_size: int) -> None:
        if board_size == self.board.size:
            return

        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move = None
        self.status_message = ""
        self.cached_board_key = None
        self.recalculate_layout()

    def reset_board(self) -> None:
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
        except Exception as error:
            self.status_message = f"Move rejected: {error}"
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
            self.screen.blit(
                self.board_surface,
                (self.board_left, self.board_top),
            )

        self.draw_coordinates()
        self.draw_hover_preview()
        self.draw_stones()
        self.draw_footer()
        self.draw_dropdown()

    def draw_coordinates(self) -> None:
        columns = GO_COLUMNS[: self.board.size]

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top = self.coord_font.render(label, True, self.text_color)
            bottom = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(top, (x - top.get_width() // 2, 28))
            self.screen.blit(
                bottom,
                (x - bottom.get_width() // 2, self.board_bottom + 20),
            )

        for row in range(self.board.size):
            label = str(self.board.size - row)
            _, y = self.point_to_pixels(row, 0)

            left = self.coord_font.render(label, True, self.text_color)
            right = self.coord_font.render(label, True, self.text_color)

            self.screen.blit(left, (18, y - left.get_height() // 2))
            self.screen.blit(
                right,
                (
                    self.window_width - 18 - right.get_width(),
                    y - right.get_height() // 2,
                ),
            )

    def draw_hover_preview(self) -> None:
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
                self.draw_cached_stone(x, y, stone)

                if self.last_move == (row, col):
                    self.draw_last_move_marker(x, y, stone)


  

    def draw_last_move_marker(self, x: int, y: int, stone: Stone) -> None:
        marker_radius = max(4, int(self.stone_radius * 0.16))

        if stone == Stone.BLACK:
            color = (245, 245, 245)
        else:
            color = (32, 32, 32)

        pygame.gfxdraw.aacircle(
            self.screen,
            x,
            y,
            marker_radius,
            color,
        )
        pygame.gfxdraw.aacircle(
            self.screen,
            x,
            y,
            marker_radius - 1,
            color,
        )

    def draw_footer(self) -> None:
        footer_y = self.board_bottom + 60

        if self.current_player == Stone.BLACK:
            turn_text = "Black to move"
        else:
            turn_text = "White to move"

        if self.status_message:
            status_text = self.status_message
        else:
            status_text = turn_text

        status = self.status_font.render(status_text, True, self.text_color)
        reset = self.status_font.render(
            "Press R to reset",
            True,
            self.text_color,
        )

        self.screen.blit(status, (self.board_left, footer_y))
        self.screen.blit(
            reset,
            (self.board_right - reset.get_width(), footer_y),
        )

    def draw_dropdown(self) -> None:
        mouse_pos = pygame.mouse.get_pos()

        if self.dropdown_rect.collidepoint(mouse_pos):
            fill = self.ui_hover
        else:
            fill = self.ui_fill

        pygame.draw.rect(
            self.screen,
            fill,
            self.dropdown_rect,
            border_radius=8,
        )
        pygame.draw.rect(
            self.screen,
            self.ui_border,
            self.dropdown_rect,
            2,
            border_radius=8,
        )

        label = f"{self.board.size} x {self.board.size}  ▼"
        label_surface = self.ui_font.render(label, True, self.text_color)

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
                option_fill = self.ui_hover
            else:
                option_fill = self.ui_fill

            pygame.draw.rect(
                self.screen,
                option_fill,
                rect,
                border_radius=6,
            )
            pygame.draw.rect(
                self.screen,
                self.ui_border,
                rect,
                1,
                border_radius=6,
            )

            option_label = f"{size} x {size}"
            option_surface = self.ui_font.render(
                option_label,
                True,
                self.text_color,
            )

            self.screen.blit(
                option_surface,
                (
                    rect.centerx - option_surface.get_width() // 2,
                    rect.centery - option_surface.get_height() // 2,
                ),
            )


def main() -> None:
    window = GoBoardWindow(board_size=19)
    window.run()


if __name__ == "__main__":
    main()
