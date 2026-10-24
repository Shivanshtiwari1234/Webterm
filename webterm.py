
#!/usr/bin/env python3
"""Webterm: a lightweight terminal-based web browser."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Static


APP_NAME = "Webterm"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"
USER_AGENT = (
    "Webterm/0.1 "
    "(terminal browser; compatible HTML text rendering)"
)

CSS = """
Screen {
    layout: vertical;
    background: #101318;
    color: #e6edf3;
}

#url {
    margin: 0 1;
    border: round #58a6ff;
}

#status {
    height: 1;
    padding: 0 1;
    color: #8b949e;
    background: #171b22;
}

#viewport {
    height: 1fr;
    border: round #30363d;
    margin: 0 1;
    padding: 1 2;
}

#page {
    width: 100%;
    height: auto;
    padding-bottom: 1;
}

Header {
    background: #161b22;
    color: #58a6ff;
}

Footer {
    background: #161b22;
}
"""


class Webterm(App[None]):
    """A small, keyboard-driven terminal browser."""

    TITLE = "Webterm"
    SUB_TITLE = "Terminal Web Browser"
    CSS = CSS

    BINDINGS = [
        Binding("ctrl+l", "focus_url", "URL", show=True),
        Binding("ctrl+b", "back", "Back", show=True),
        Binding("ctrl+f", "forward", "Forward", show=True),
        Binding("ctrl+r", "reload", "Reload", show=True),
        Binding("escape", "focus_page", "Page", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_url = ""
        self.back_stack: list[str] = []
        self.forward_stack: list[str] = []
        self.links: dict[int, str] = {}
        self.loading = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(
            placeholder=(
                "URL, search query, or link number "
                "(Ctrl+L to focus)"
            ),
            id="url",
        )
        yield Static("Ready. Enter a URL to start browsing.", id="status")
        with VerticalScroll(id="viewport"):
            yield Static("", id="page")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#url", Input).focus()
        self.show_message(
            "Ready | Enter a URL or search query. "
            "Type a link number to open it."
        )

    def show_message(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def show_page(self, content: Text) -> None:
        page = self.query_one("#page", Static)
        page.update(content)
        self.query_one("#viewport", VerticalScroll).scroll_home(
            animate=False
        )

    @staticmethod
    def normalize_address(value: str) -> str:
        value = value.strip()

        if not value:
            return ""

        # Treat a number as a link selection, not a URL.
        if value.isdigit():
            return value

        # Search queries, or strings without a hostname-like dot.
        if " " in value or (
            "://" not in value and "." not in value
        ):
            return SEARCH_URL.format(quote_plus(value))

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
            value = "https://" + value

        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Only valid HTTP and HTTPS URLs are supported.")

        return value

    async def fetch_page(self, url: str) -> tuple[str, str]:
        timeout = httpx.Timeout(20.0, connect=10.0)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                raise ValueError(
                    "This page is not HTML. "
                    f"Content-Type: {content_type or 'unknown'}"
                )

            return str(response.url), response.text

    def parse_page(self, html: str, base_url: str) -> tuple[Text, dict[int, str], str]:
        soup = BeautifulSoup(html, "html.parser")

        for element in soup(
            ["script", "style", "noscript", "svg", "iframe", "template"]
        ):
            element.decompose()

        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        title = title or base_url

        output = Text()
        output.append(f"{title}\n", style="bold bright_cyan")
        output.append(f"{base_url}\n", style="dim")
        output.append("=" * 72 + "\n\n", style="dim")

        # Render the main content when possible.
        main = soup.find("main") or soup.find("article") or soup.body or soup
        block_tags = {
            "h1", "h2", "h3", "h4", "p", "li", "blockquote",
            "pre", "dt", "dd", "figcaption", "address",
        }

        links: dict[int, str] = {}
        link_ids: dict[int, int] = {}
        seen_blocks: set[int] = set()

        for anchor in main.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            label = anchor.get_text(" ", strip=True) or href

            if not href or href.startswith(("javascript:", "data:", "mailto:", "tel:")):
                continue

            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)

            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue

            # Reuse the same number for repeated occurrences of a URL.
            existing = next(
                (number for number, target in links.items() if target == absolute),
                None,
            )
            if existing is None:
                existing = len(links) + 1
                links[existing] = absolute

            link_ids[id(anchor)] = existing

        for element in main.find_all(list(block_tags)):
            # Avoid rendering a nested block twice.
            if any(
                id(parent) in seen_blocks
                for parent in element.parents
                if isinstance(parent, Tag)
            ):
                continue

            seen_blocks.add(id(element))
            text = element.get_text(" ", strip=True)

            if not text:
                continue

            if element.name.startswith("h"):
                level = int(element.name[1])
                output.append(text + "\n", style="bold bright_cyan")
                output.append("\n")
            elif element.name == "li":
                output.append("  • " + text + "\n")
            elif element.name == "blockquote":
                output.append("  │ " + text + "\n", style="italic")
            elif element.name == "pre":
                output.append(text + "\n", style="bright_black")
            else:
                output.append(text + "\n\n")

        if not output.plain.strip():
            output.append(
                soup.get_text("\n", strip=True) or "No readable page text found.",
                style="white",
            )

        output.append("\n" + "=" * 72 + "\n", style="dim")
        output.append(f"LINKS ({len(links)})\n\n", style="bold bright_yellow")

        if links:
            for number, target in links.items():
                # Limit the visible URL width by allowing terminal wrapping.
                output.append(f"[{number}] ", style="bold bright_green")
                output.append(target + "\n", style="underline blue")
        else:
            output.append("No HTTP/HTTPS links found.\n", style="dim")

        return output, links, title

    async def navigate(self, address: str, *, record_history: bool = True) -> None:
        if self.loading:
            self.show_message("A request is already in progress.")
            return

        try:
            url = self.normalize_address(address)

            if not url:
                return

            if url.isdigit():
                number = int(url)
                target = self.links.get(number)
                if target:
                    await self.navigate(target)
                else:
                    self.show_message(f"No link numbered {number}.")
                return

        except ValueError as exc:
            self.show_message(str(exc))
            return

        self.loading = True
        self.show_message(f"Loading {url} ...")
        self.query_one("#url", Input).value = url

        try:
            final_url, html = await self.fetch_page(url)
            content, links, title = self.parse_page(html, final_url)

            if record_history and self.current_url and final_url != self.current_url:
                self.back_stack.append(self.current_url)
                self.forward_stack.clear()

            self.current_url = final_url
            self.links = links
            self.query_one("#url", Input).value = final_url
            self.show_page(content)
            self.show_message(
                f"{title} | {final_url} | {len(links)} links"
            )

        except (httpx.HTTPError, ValueError) as exc:
            self.show_message(f"Error: {exc}")
        except Exception as exc:
            self.show_message(
                f"Could not render page: {type(exc).__name__}: {exc}"
            )
        finally:
            self.loading = False

    @on(Input.Submitted, "#url")
    async def on_url_submitted(self, event: Input.Submitted) -> None:
        await self.navigate(event.value)

    async def action_back(self) -> None:
        if not self.back_stack or self.loading:
            self.show_message("No previous page.")
            return

        previous = self.back_stack.pop()
        if self.current_url:
            self.forward_stack.append(self.current_url)

        await self.navigate(previous, record_history=False)

    async def action_forward(self) -> None:
        if not self.forward_stack or self.loading:
            self.show_message("No next page.")
            return

        following = self.forward_stack.pop()
        if self.current_url:
            self.back_stack.append(self.current_url)

        await self.navigate(following, record_history=False)

    async def action_reload(self) -> None:
        if self.current_url:
            await self.navigate(self.current_url, record_history=False)
        else:
            self.show_message("Nothing to reload.")

    def action_focus_url(self) -> None:
        self.query_one("#url", Input).focus()
        self.query_one("#url", Input).action_select_all()

    def action_focus_page(self) -> None:
        self.query_one("#viewport", VerticalScroll).focus()

    def action_quit(self) -> None:
        self.exit()


if __name__ == "__main__":
    Webterm().run()
