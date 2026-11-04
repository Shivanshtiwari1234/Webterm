"""Small terminal-oriented Canvas 2D rasterizer."""

from __future__ import annotations

import math
import re
from typing import TypeAlias

Color: TypeAlias = tuple[int, int, int] | tuple[int, int, int, int] | None
_ASCII_SHADES = " .:-=+*#%@"

_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255),
    "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255),
    "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "orange": (255, 165, 0),
    "purple": (128, 0, 128), "pink": (255, 192, 203),
    "transparent": None,
}


def parse_color(value: object) -> Color:
    """Parse common CSS color forms; unsupported values become transparent."""
    text = str(value).strip().lower()
    if text in _NAMED_COLORS:
        return _NAMED_COLORS[text]

    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in {3, 4}:
            digits = "".join(character * 2 for character in digits)
        if len(digits) in {6, 8}:
            try:
                channels = tuple(
                    int(digits[index:index + 2], 16)
                    for index in range(0, len(digits), 2)
                )  # type: ignore[return-value]
            except ValueError:
                return None
            if len(channels) == 4:
                if channels[3] == 0:
                    return None
                if channels[3] < 255:
                    return channels  # type: ignore[return-value]
                return channels[:3]  # type: ignore[return-value]
            return channels  # type: ignore[return-value]

    match = re.fullmatch(r"rgba?\(([^)]*)\)", text)
    if match:
        parts = [part.strip() for part in match.group(1).split(",")]
        if len(parts) >= 3:
            try:
                channels = []
                for part in parts[:3]:
                    channel = (
                        round(float(part[:-1]) * 255 / 100)
                        if part.endswith("%") else round(float(part))
                    )
                    channels.append(max(0, min(255, channel)))
                if len(parts) >= 4:
                    alpha = parts[3]
                    alpha_value = (
                        float(alpha[:-1]) / 100
                        if alpha.endswith("%") else float(alpha)
                    )
                    if not math.isfinite(alpha_value):
                        return None
                    alpha_channel = round(max(0, min(1, alpha_value)) * 255)
                    if alpha_channel == 0:
                        return None
                    if alpha_channel < 255:
                        return (*channels, alpha_channel)
                return tuple(channels)  # type: ignore[return-value]
            except (ValueError, OverflowError):
                return None

    return None


class CanvasRasterizer:
    """Rasterize a bounded canvas into colored terminal characters."""

    MAX_WIDTH = 512
    MAX_HEIGHT = 256
    MAX_COLUMNS = 80
    MAX_PIXEL_ROWS = 48

    def __init__(self, width: int = 300, height: int = 150) -> None:
        self.width = self._dimension(width)
        self.height = self._dimension(height)
        self.fill_style = "#000000"
        self.stroke_style = "#000000"
        self.font = "10px sans-serif"
        self.text_align = "start"
        self.text_baseline = "alphabetic"
        self._path: list[list[tuple[float, float]]] = []
        self._text: dict[tuple[int, int], tuple[str, Color]] = {}
        self._allocate()

    @staticmethod
    def _dimension(value: object) -> int:
        try:
            dimension = int(float(value))
        except (TypeError, ValueError, OverflowError):
            dimension = 300
        return max(1, min(2048, dimension))

    def _allocate(self) -> None:
        self._pixel_width = min(self.width, self.MAX_WIDTH)
        self._pixel_height = min(self.height, self.MAX_HEIGHT)
        self._pixels: list[list[Color]] = [
            [None] * self._pixel_width for _ in range(self._pixel_height)
        ]
        self._text.clear()

    def resize(self, width: object, height: object) -> None:
        self.width = self._dimension(width)
        self.height = self._dimension(height)
        self._allocate()
        self.fill_style = "#000000"
        self.stroke_style = "#000000"
        self.font = "10px sans-serif"
        self.text_align = "start"
        self.text_baseline = "alphabetic"
        self._path.clear()

    def _point(self, x: float, y: float) -> tuple[int, int]:
        return (
            round(x * self._pixel_width / self.width),
            round(y * self._pixel_height / self.height),
        )

    def _paint(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self._pixel_width and 0 <= y < self._pixel_height:
            self._pixels[y][x] = self._composite(color, self._pixels[y][x])

    @staticmethod
    def _composite(color: Color, background: Color) -> Color:
        if color is None or len(color) == 3:
            return color
        alpha = color[3] / 255
        base = background[:3] if background is not None else (0, 0, 0)
        return tuple(
            round(color[index] * alpha + base[index] * (1 - alpha))
            for index in range(3)
        )  # type: ignore[return-value]

    def _rectangle(
        self, x: float, y: float, width: float, height: float,
        color: Color, *, fill: bool,
    ) -> None:
        start_x, start_y = self._point(x, y)
        end_x, end_y = self._point(x + width, y + height)

        if fill:
            left, right = sorted((start_x, end_x))
            top, bottom = sorted((start_y, end_y))
            left, right = max(0, left), min(self._pixel_width, right)
            top, bottom = max(0, top), min(self._pixel_height, bottom)
            for row in range(top, bottom):
                for column in range(left, right):
                    self._paint(column, row, color)
            return

        self._line_pixels(start_x, start_y, end_x, start_y, color)
        self._line_pixels(end_x, start_y, end_x, end_y, color)
        self._line_pixels(end_x, end_y, start_x, end_y, color)
        self._line_pixels(start_x, end_y, start_x, start_y, color)

    def fill_rect(self, x: float, y: float, width: float, height: float) -> None:
        self._rectangle(x, y, width, height, parse_color(self.fill_style), fill=True)

    def clear_rect(self, x: float, y: float, width: float, height: float) -> None:
        self._rectangle(x, y, width, height, None, fill=True)

    def stroke_rect(self, x: float, y: float, width: float, height: float) -> None:
        self._rectangle(
            x, y, width, height, parse_color(self.stroke_style), fill=False
        )

    def begin_path(self) -> None:
        self._path.clear()

    def move_to(self, x: float, y: float) -> None:
        self._path.append([(x, y)])

    def line_to(self, x: float, y: float) -> None:
        if not self._path:
            self.move_to(x, y)
        else:
            self._path[-1].append((x, y))

    def close_path(self) -> None:
        if self._path and len(self._path[-1]) > 1:
            subpath = self._path[-1]
            if subpath[-1] != subpath[0]:
                subpath.append(subpath[0])

    def arc(
        self, x: float, y: float, radius: float, start_angle: float,
        end_angle: float, counterclockwise: bool = False,
    ) -> None:
        radius = abs(radius)
        sweep = end_angle - start_angle
        if abs(sweep) >= 2 * math.pi:
            sweep = -2 * math.pi if counterclockwise else 2 * math.pi
        elif counterclockwise and sweep > 0:
            sweep -= 2 * math.pi
        elif not counterclockwise and sweep < 0:
            sweep += 2 * math.pi
        segments = max(8, min(256, math.ceil(abs(sweep) * radius / 2)))
        points = [
            (x + math.cos(start_angle + sweep * index / segments) * radius,
             y + math.sin(start_angle + sweep * index / segments) * radius)
            for index in range(segments + 1)
        ]
        if self._path:
            self._path[-1].extend(points)
        else:
            self._path.append(points)

    def _line_pixels(
        self, x0: int, y0: int, x1: int, y1: int, color: Color,
    ) -> None:
        delta_x, delta_y = x1 - x0, y1 - y0
        lower, upper = 0.0, 1.0
        for direction, distance in (
            (-delta_x, x0),
            (delta_x, self._pixel_width - 1 - x0),
            (-delta_y, y0),
            (delta_y, self._pixel_height - 1 - y0),
        ):
            if direction == 0:
                if distance < 0:
                    return
                continue
            ratio = distance / direction
            if direction < 0:
                lower = max(lower, ratio)
            else:
                upper = min(upper, ratio)
            if lower > upper:
                return

        x0, y0 = round(x0 + lower * delta_x), round(y0 + lower * delta_y)
        x1, y1 = round(x0 + (upper - lower) * delta_x), round(
            y0 + (upper - lower) * delta_y
        )
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx - dy
        while True:
            self._paint(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            doubled = 2 * error
            if doubled > -dy:
                error -= dy
                x0 += sx
            if doubled < dx:
                error += dx
                y0 += sy

    def _stroke_path(self) -> None:
        color = parse_color(self.stroke_style)
        for subpath in self._path:
            for start, end in zip(subpath, subpath[1:]):
                self._line_pixels(*self._point(*start), *self._point(*end), color)

    def stroke(self) -> None:
        self._stroke_path()

    def fill(self) -> None:
        color = parse_color(self.fill_style)
        for subpath in self._path:
            if len(subpath) < 3:
                continue
            points = [self._point(*point) for point in subpath]
            min_y = max(0, min(point[1] for point in points))
            max_y = min(self._pixel_height - 1, max(point[1] for point in points))
            for y in range(min_y, max_y + 1):
                intersections: list[float] = []
                for start, end in zip(points, points[1:] + points[:1]):
                    if (start[1] <= y < end[1]) or (end[1] <= y < start[1]):
                        intersections.append(
                            start[0] + (y - start[1]) * (end[0] - start[0])
                            / (end[1] - start[1])
                        )
                intersections.sort()
                for index in range(0, len(intersections) - 1, 2):
                    left = max(0, math.ceil(intersections[index]))
                    right = min(
                        self._pixel_width, math.ceil(intersections[index + 1])
                    )
                    for x in range(left, right):
                        self._paint(x, y, color)

    def draw_text(
        self, text: object, x: float, y: float, *, stroke: bool = False,
    ) -> None:
        value = str(text)
        columns = min(self.MAX_COLUMNS, max(1, self.width))
        rows = max(1, math.ceil(min(self.height, self.MAX_PIXEL_ROWS) / 2))
        cell_x = round(x * columns / self.width)
        cell_y = round(y * rows / self.height)
        if self.text_align == "center":
            cell_x -= len(value) // 2
        elif self.text_align in {"right", "end"}:
            cell_x -= len(value)
        if self.text_baseline in {"bottom", "ideographic", "alphabetic", "hanging"}:
            cell_y -= 1
        color = self._composite(
            parse_color(self.stroke_style if stroke else self.fill_style), None
        )
        for offset, character in enumerate(value):
            target_x = cell_x + offset
            if 0 <= target_x < columns and 0 <= cell_y < rows:
                self._text[(target_x, cell_y)] = (character, color)

    def measure_text(self, text: object) -> dict[str, float]:
        return {"width": float(len(str(text)) * 6)}

    @staticmethod
    def _ansi_color(color: Color, background: bool = False) -> str:
        if color is None:
            return "\x1b[49m" if background else "\x1b[39m"
        prefix = "48" if background else "38"
        return f"\x1b[{prefix};2;{color[0]};{color[1]};{color[2]}m"

    def _sample(self, column: int, row: int, columns: int, rows: int) -> Color:
        source_x = min(self._pixel_width - 1, int((column + 0.5) * self._pixel_width / columns))
        source_y = min(self._pixel_height - 1, int((row + 0.5) * self._pixel_height / rows))
        return self._pixels[source_y][source_x]

    def to_ansi(self) -> str:
        columns = min(self.MAX_COLUMNS, self.width)
        pixel_rows = min(self.MAX_PIXEL_ROWS, self.height)
        rows = math.ceil(pixel_rows / 2)
        output: list[str] = []
        for row in range(rows):
            for column in range(columns):
                overlay = self._text.get((column, row))
                if overlay is not None:
                    character, color = overlay
                    output.extend((self._ansi_color(color), character, "\x1b[0m"))
                    continue

                top = self._sample(column, row * 2, columns, pixel_rows)
                bottom = (
                    self._sample(column, row * 2 + 1, columns, pixel_rows)
                    if row * 2 + 1 < pixel_rows else None
                )
                if top is None and bottom is None:
                    output.append(" ")
                else:
                    foreground = top if top is not None else bottom
                    background = (
                        bottom
                        if top is not None and bottom is not None and top != bottom
                        else None
                    )
                    shade = (
                        _ASCII_SHADES[-1]
                        if top is not None and bottom is not None
                        else _ASCII_SHADES[len(_ASCII_SHADES) // 2]
                    )
                    output.extend((
                        self._ansi_color(foreground),
                        self._ansi_color(background, True),
                        shade,
                        "\x1b[0m",
                    ))
            output.append("\n")
        return "".join(output).rstrip("\n")