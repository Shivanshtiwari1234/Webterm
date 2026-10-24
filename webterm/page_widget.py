"""Page rendering and clickable link support."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class ClickablePage(Static):
    """Display a Rich Text page and navigate when a numbered link is clicked."""

    DEFAULT_CSS = """
    ClickablePage {
        width: 100%;
        height: 1fr;
        padding: 1;
        overflow-x: auto;
        overflow-y: auto;
        background: #101114;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(Text(), **kwargs)
        self.page_text = Text()
        self.links: dict[int, str] = {}
        self.link_ranges: list[tuple[int, int, str]] = []

    def set_page(
        self,
        page: Text,
        links: dict[int, str],
        page_url: str = "",
    ) -> None:
        """Update the displayed page and index its numbered links."""

        self.page_text = page
        self.links = dict(links)
        self.link_ranges = []

        plain = page.plain

        for number, url in self.links.items():
            marker = f"[{number}]"
            start = 0

            while True:
                position = plain.find(marker, start)
                if position == -1:
                    break

                end = position + len(marker)
                self.link_ranges.append((position, end, url))
                start = end

        self.update(page)

    def _position_at(self, x: int, y: int) -> int | None:
        """Convert widget-relative coordinates into a text offset."""

        region = self.content_region
        column = x - region.x
        row = y - region.y

        if column < 0 or row < 0:
            return None

        lines = self.page_text.plain.split("\n")

        if row >= len(lines):
            return None

        # This mapping works for unwrapped lines. Long lines that wrap
        # visually need a more sophisticated cell-to-character mapping.
        line = lines[row]

        if column > len(line):
            return None

        return sum(len(value) + 1 for value in lines[:row]) + column

    def on_click(self, event) -> None:
        """Navigate when the user clicks a numbered link marker."""

        position = self._position_at(event.x, event.y)

        if position is None:
            return

        for start, end, url in self.link_ranges:
            if start <= position < end:
                event.stop()
                self.app.call_later(self.app.open_link_url, url)
                return
