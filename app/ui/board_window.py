import math
import sys

import pygame

from app.core.board import Board
from app.core.coordinates import GO_COLUMNS, point_to_human
from app.core.stone import Stone


class GoBoardWindow:
    def __init__(self, board_size: int = 19) -> None:
        self.board = Board(size=board_size)
        self.current_player = Stone.BLACK
        self.last_move: tuple[int, int] | None = None

        pygame.init()
        pygame.display.set_caption("Go Sensei Board")

        self.window_size = 760
        self.margin = 55
        self.grid_pixels = self.window_size - (2 * self.margin)
        self.cell_size = self.grid_pixels / (self.board.size - 1)
        self.stone_radius = int(self.cell_size * 0.42)

        self.screen = pygame.display.set_mode((self.window_size, self.window_size))

        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small_font = pygame.font.SysFont("arial", 18, bold=True)

        self.board_color = (205, 160, 75)
        self.line_color = (30, 20, 10)
        self.star_color = (20, 15, 10)

        self.black_stone = (35, 35, 35)
        self.black_highlight = (80, 80, 80)
        self.white_stone = (240, 240, 240)
        self.white_outline = (170, 170, 170)
        self.last_move_marker = (245, 245, 245)

    def run(self) -> None:
        clock = pygame.time.Clock()

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_click(event.pos)

                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    self.reset_board()

            self.draw()
            pygame.display.flip()
            clock.tick(60)

    def handle_click(self, mouse_pos: tuple[int, int]) -> None:
        point = self.mouse_to_point(mouse_pos)

        if point is None:
            return

        row, col = point
        coordinate = point_to_human(row, col, self.board.size)

        if self.board.get(coordinate) is not None:
            return

        self.board.place_stone(coordinate, self.current_player)
        self.last_move = (row, col)
        self.switch_turn()

    def switch_turn(self) -> None:
        if self.current_player == Stone.BLACK:
            self.current_player = Stone.WHITE
        else:
            self.current_player = Stone.BLACK

    def reset_board(self) -> None:
        self.board.clear()
        self.current_player = Stone.BLACK
        self.last_move = None

    def mouse_to_point(self, mouse_pos: tuple[int, int]) -> tuple[int, int] | None:
        mouse_x, mouse_y = mouse_pos
        closest_point: tuple[int, int] | None = None
        closest_distance = float("inf")

        for row in range(self.board.size):
            for col in range(self.board.size):
                point_x, point_y = self.point_to_pixels(row, col)
                distance = math.dist((mouse_x, mouse_y), (point_x, point_y))

                if distance < closest_distance:
                    closest_distance = distance
                    closest_point = (row, col)

        click_tolerance = self.cell_size * 0.45

        if closest_distance <= click_tolerance:
            return closest_point

        return None

    def point_to_pixels(self, row: int, col: int) -> tuple[int, int]:
        x = self.margin + (col * self.cell_size)
        y = self.margin + (row * self.cell_size)
        return round(x), round(y)

    def draw(self) -> None:
        self.screen.fill(self.board_color)
        self.draw_grid()
        self.draw_star_points()
        self.draw_coordinates()
        self.draw_stones()
        self.draw_status_bar()

    def draw_grid(self) -> None:
        for index in range(self.board.size):
            x = self.margin + (index * self.cell_size)
            y = self.margin + (index * self.cell_size)

            pygame.draw.line(
                self.screen,
                self.line_color,
                (round(self.margin), round(y)),
                (round(self.window_size - self.margin), round(y)),
                1,
            )

            pygame.draw.line(
                self.screen,
                self.line_color,
                (round(x), round(self.margin)),
                (round(x), round(self.window_size - self.margin)),
                1,
            )

    def draw_star_points(self) -> None:
        star_indices = self.get_star_indices()

        for row in star_indices:
            for col in star_indices:
                x, y = self.point_to_pixels(row, col)
                pygame.draw.circle(self.screen, self.star_color, (x, y), 4)

    def get_star_indices(self) -> list[int]:
        if self.board.size == 19:
            return [3, 9, 15]

        if self.board.size == 13:
            return [3, 6, 9]

        if self.board.size == 9:
            return [2, 4, 6]

        return []

    def draw_coordinates(self) -> None:
        columns = GO_COLUMNS[: self.board.size]

        for col, label in enumerate(columns):
            x, _ = self.point_to_pixels(0, col)

            top_text = self.font.render(label, True, self.line_color)
            bottom_text = self.font.render(label, True, self.line_color)

            self.screen.blit(top_text, (x - top_text.get_width() // 2, 12))
            self.screen.blit(
                bottom_text,
                (x - bottom_text.get_width() // 2, self.window_size - 36),
            )

        for row in range(self.board.size):
            human_row = self.board.size - row
            _, y = self.point_to_pixels(row, 0)

            left_text = self.font.render(str(human_row), True, self.line_color)
            right_text = self.font.render(str(human_row), True, self.line_color)

            self.screen.blit(left_text, (12, y - left_text.get_height() // 2))
            self.screen.blit(
                right_text,
                (self.window_size - 36, y - right_text.get_height() // 2),
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

    def draw_black_stone(self, x: int, y: int) -> None:
        pygame.draw.circle(self.screen, self.black_stone, (x, y), self.stone_radius)

        highlight_x = x - int(self.stone_radius * 0.25)
        highlight_y = y - int(self.stone_radius * 0.25)

        pygame.draw.circle(
            self.screen,
            self.black_highlight,
            (highlight_x, highlight_y),
            max(3, int(self.stone_radius * 0.22)),
        )

    def draw_white_stone(self, x: int, y: int) -> None:
        pygame.draw.circle(self.screen, self.white_stone, (x, y), self.stone_radius)

        pygame.draw.circle(
            self.screen,
            self.white_outline,
            (x, y),
            self.stone_radius,
            2,
        )

    def draw_last_move_marker(self, x: int, y: int, stone: Stone) -> None:
        if stone == Stone.BLACK:
            marker_color = self.last_move_marker
        else:
            marker_color = self.black_stone

        pygame.draw.circle(
            self.screen,
            marker_color,
            (x, y),
            int(self.stone_radius * 0.40),
            3,
        )

    def draw_status_bar(self) -> None:
        if self.current_player == Stone.BLACK:
            turn_text = "Black to move"
        else:
            turn_text = "White to move"

        reset_text = "Press R to reset"

        turn_surface = self.small_font.render(turn_text, True, self.line_color)
        reset_surface = self.small_font.render(reset_text, True, self.line_color)

        self.screen.blit(turn_surface, (self.margin, self.window_size - 24))
        self.screen.blit(
            reset_surface,
            (
                self.window_size - self.margin - reset_surface.get_width(),
                self.window_size - 24,
            ),
        )


def main() -> None:
    window = GoBoardWindow(board_size=19)
    window.run()


if __name__ == "__main__":
    main()
