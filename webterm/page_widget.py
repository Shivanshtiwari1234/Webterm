"""Page rendering, line wrapping, and clickable numbered links."""

from __future__ import annotations

from rich.text import Text
from rich.cells import cell_len
from textual.widgets import Static


class ClickablePage(Static):
    """Display a styled page with wrapped lines and clickable link markers."""

    DEFAULT_CSS = """
    ClickablePage {
        width: 100%;
        height: 1fr;
        padding: 1;
        overflow-x: hidden;
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
        """Update content and derive clickable spans from explicit metadata."""
        self.page_text = page
        self.links = dict(links)
        self.link_ranges = []
        for span in page.spans:
            meta = getattr(span.style, "meta", None) or {}
            url = meta.get("webterm_url") if hasattr(meta, "get") else None
            if url and span.end > span.start:
                self.link_ranges.append((span.start, span.end, str(url)))
        self.update(page)

    @staticmethod
    def _wrap_line(line: str, width: int) -> list[tuple[int, str]]:
        """Wrap by terminal display cells, preserving character offsets."""
        width = max(1, width)
        if not line:
            return [(0, "")]
        segments: list[tuple[int, str]] = []
        start = 0
        while start < len(line):
            end = start
            cells = 0
            last_space = -1
            while end < len(line):
                char_width = max(0, cell_len(line[end]))
                if cells + char_width > width and end > start:
                    break
                cells += char_width
                if line[end].isspace():
                    last_space = end
                end += 1
                if cells >= width:
                    break
            if end < len(line) and last_space > start:
                end = last_space
            if end <= start:
                end = start + 1
            segments.append((start, line[start:end]))
            start = end
            while start < len(line) and line[start] == " ":
                start += 1
        return segments or [(0, "")]

    def _visual_lines(self) -> list[tuple[int, int, str]]:
        """Map visual lines to their source offsets."""
        width = max(1, self.content_region.width)
        result: list[tuple[int, int, str]] = []
        source_offset = 0

        for line in self.page_text.plain.split("\n"):
            for segment_offset, segment in self._wrap_line(line, width):
                result.append(
                    (
                        source_offset + segment_offset,
                        source_offset + segment_offset + len(segment),
                        segment,
                    )
                )

            source_offset += len(line) + 1

        return result

    def _position_at(self, x: int, y: int) -> int | None:
        """Convert screen coordinates into a source-text offset."""
        region = self.content_region
        column = x - region.x
        row = y - region.y

        if column < 0 or row < 0:
            return None

        lines = self._visual_lines()

        if row >= len(lines):
            return None

        start, end, segment = lines[row]

        if column < 0 or column >= cell_len(segment):
            return None
        used = 0
        for offset, char in enumerate(segment):
            width = max(0, cell_len(char))
            if used <= column < used + max(1, width):
                return start + offset
            used += width
        return None

    def on_click(self, event) -> None:
        """Navigate when the user clicks a numbered link marker."""
        position = self._position_at(event.x, event.y)

        if position is None:
            return

        for start, end, url in self.link_ranges:
            if start <= position < end:
                event.stop()
                # Schedule navigation as a Textual worker so the coroutine is
                # awaited by Textual instead of being called as a plain callback.
                self.app.run_worker(
                    self.app.open_link_url(url),
                    group="link-navigation",
                    exclusive=True,
                )
                return
