"""Webterm core: URL handling, HTTP fetching, HTML parsing, and JavaScript."""

from __future__ import annotations

from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from rich.text import Text

from .javascript import JavaScriptRuntime


HOME_URL = "https://duckduckgo.com/"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"
USER_AGENT = "Webterm/0.4 (terminal web browser)"


def normalize_address(value: str) -> str:
    """Convert user input into an HTTP(S) URL or a search URL."""
    value = value.strip()

    if not value:
        return ""

    if value.isdigit():
        return value

    if " " in value or (
        "://" not in value and "." not in value
    ):
        return SEARCH_URL.format(quote_plus(value))

    if "://" not in value:
        value = "https://" + value

    parsed = urlparse(value)

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or not parsed.hostname
    ):
        raise ValueError("Only valid HTTP and HTTPS URLs are supported.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid port in URL.") from exc

    return value


async def fetch_page(url: str) -> tuple[str, str]:
    """Fetch an HTML page. Return its final URL and HTML source."""
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
                f"Not an HTML page: {content_type or 'unknown type'}"
            )

        return str(response.url), response.text


def execute_inline_scripts(
    soup: BeautifulSoup,
    runtime: JavaScriptRuntime,
) -> list[str]:
    """Execute inline scripts in document order and return new console output.

    Scripts are removed from the soup after extraction so they do not appear
    as visible page content. External scripts are skipped.
    """
    previous_count = len(runtime.console_messages)

    for script in soup.find_all("script"):
        source = script.string or script.get_text()

        # Do not fetch or execute external scripts in this first version.
        if script.has_attr("src"):
            script.decompose()
            continue

        script_type = str(script.get("type", "")).strip().lower()

        # Ignore non-JavaScript script types, such as JSON-LD.
        if script_type and script_type not in (
            "text/javascript",
            "application/javascript",
            "text/ecmascript",
            "application/ecmascript",
            "module",
        ):
            script.decompose()
            continue

        if source.strip():
            runtime.execute(source)

        script.decompose()

    return runtime.console_messages[previous_count:]


def parse_page(
    html: str,
    base_url: str,
    runtime: JavaScriptRuntime | None = None,
) -> tuple[Text, dict[int, str], str]:
    """Convert HTML into readable terminal text and numbered links.

    When a runtime is provided, inline JavaScript is executed in that
    runtime before the visible page content is rendered.
    """
    soup = BeautifulSoup(html, "html.parser")

    js_messages: list[str] = []

    if runtime is not None:
        js_messages = execute_inline_scripts(soup, runtime)
    else:
        for script in soup.find_all("script"):
            script.decompose()

    for element in soup(
        ["style", "noscript", "svg", "iframe", "template"]
    ):
        element.decompose()

    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title else ""
    ) or base_url

    main = soup.find("main") or soup.find("article") or soup.body or soup
    links: dict[int, str] = {}

    for anchor in main.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()

        if not href or href.startswith(
            ("javascript:", "data:", "mailto:", "tel:")
        ):
            continue

        target = urljoin(base_url, href)
        parsed = urlparse(target)

        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or not parsed.hostname
        ):
            continue

        if target not in links.values():
            links[len(links) + 1] = target

    output = Text()
    output.append(title + "\n", style="bold bright_cyan")
    output.append(base_url + "\n", style="dim")
    output.append("─" * 68 + "\n\n", style="dim")

    block_tags = [
        "h1", "h2", "h3", "h4", "p", "li",
        "blockquote", "pre", "dt", "dd", "figcaption",
    ]
    rendered: set[int] = set()

    for element in main.find_all(block_tags):
        if any(
            id(parent) in rendered
            for parent in element.parents
            if isinstance(parent, Tag)
        ):
            continue

        rendered.add(id(element))
        text = element.get_text(" ", strip=True)

        if not text:
            continue

        if element.name.startswith("h"):
            output.append(text + "\n\n", style="bold bright_cyan")
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
            soup.get_text("\n", strip=True) or "No readable text found."
        )

    if js_messages:
        output.append("\n" + "─" * 68 + "\n", style="dim")
        output.append("JAVASCRIPT CONSOLE\n\n", style="bold bright_magenta")

        for message in js_messages:
            output.append(message + "\n", style="bright_black")

    output.append("\n" + "─" * 68 + "\n", style="dim")
    output.append(
        f"LINKS ({len(links)})\n\n",
        style="bold bright_yellow",
    )

    for number, target in links.items():
        output.append(f"[{number}] ", style="bold bright_green")
        output.append(target + "\n", style="underline blue")

    if not links:
        output.append("No links found.\n", style="dim")

    return output, links, title