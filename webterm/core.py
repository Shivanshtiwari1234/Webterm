"""Webterm core: URL handling, HTTP fetching, HTML parsing, CSS styling, and forms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from rich.style import Style
from rich.text import Text

from .javascript import JavaScriptRuntime

HOME_URL = "https://duckduckgo.com/"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"
USER_AGENT = "Webterm/0.5 (terminal web browser)"


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def validate_http_url(url: str) -> str:
    """Validate an HTTP(S) URL and return it unchanged."""
    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported.")

    if not parsed.netloc or not parsed.hostname:
        raise ValueError("Invalid URL.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not supported.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid port in URL.") from exc

    return url


def unwrap_redirect_url(url: str) -> str:
    """Unwrap common search-engine redirect URLs without double-decoding them."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    hostname = (parsed.hostname or "").lower().rstrip(".")
    query = parse_qs(parsed.query, keep_blank_values=True)

    # DuckDuckGo HTML results commonly link through /l/?uddg=<encoded URL>.
    if hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com"):
        if parsed.path.rstrip("/") == "/l":
            destination = query.get("uddg", [""])[0]
            if destination:
                try:
                    return validate_http_url(destination)
                except ValueError:
                    return url

    # Google uses /url?q=... or /url?url=... for some outbound links.
    if hostname == "google.com" or hostname.endswith(".google.com"):
        if parsed.path.rstrip("/") == "/url":
            for key in ("q", "url"):
                destination = query.get(key, [""])[0]
                if destination:
                    try:
                        return validate_http_url(destination)
                    except ValueError:
                        continue

    return url


def set_home_url(url: str) -> None:
    """Set Webterm's homepage URL."""
    global HOME_URL
    HOME_URL = validate_http_url(url)


def normalize_address(value: str) -> str:
    """Normalize a URL or turn a search query into a search URL."""
    value = value.strip()

    if not value:
        return ""

    # A bare integer is a valid search query, not necessarily a link number.
    # BrowserView should resolve numeric link shortcuts before calling this.
    if value.startswith("//"):
        value = "https:" + value
    elif "://" not in value:
        # Treat host:port and localhost as addresses, but ordinary words as queries.
        first = value.split("/", 1)[0]
        host_port = bool(re.fullmatch(r"(?:localhost|\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+):\d+", first))
        looks_like_host = "." in first or first == "localhost" or host_port
        if not looks_like_host:
            return SEARCH_URL.format(quote_plus(value))
        value = "https://" + value

    return validate_http_url(value)


# ---------------------------------------------------------------------------
# HTTP fetching
# ---------------------------------------------------------------------------


async def _fetch_html(url: str) -> tuple[str, str]:
    """Fetch HTML while validating every redirect and limiting response size."""
    current = validate_http_url(unwrap_redirect_url(url))
    timeout = httpx.Timeout(20.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        headers=headers,
    ) as client:
        for _ in range(11):
            async with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                        raise ValueError("Redirect response did not include a Location header.")
                    current = validate_http_url(
                        unwrap_redirect_url(urljoin(current, location))
                    )
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type and "xhtml" not in content_type:
                    raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")

                max_bytes = 5 * 1024 * 1024
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Page is larger than Webterm's 5 MiB limit.")
                    chunks.append(chunk)

                encoding = response.encoding or "utf-8"
                return validate_http_url(str(response.url)), b"".join(chunks).decode(encoding, errors="replace")

    raise ValueError("Too many redirects (maximum 10).")


async def fetch_page(url: str) -> tuple[str, str]:
    """Fetch an HTML page, returning its final URL and source."""
    return await _fetch_html(url)


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


def execute_inline_scripts(
    soup: BeautifulSoup,
    runtime: JavaScriptRuntime,
) -> None:
    """Execute supported inline scripts and remove script tags afterward."""
    supported_types = {
        "",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
    }

    for script in list(soup.find_all("script")):
        script_type = str(script.get("type", "")).strip().lower()
        source = script.string or script.get_text()

        if not script.get("src") and script_type in supported_types and source.strip():
            try:
                runtime.execute(source, document_html=str(soup))
            except Exception as exc:
                logs = getattr(runtime, "console_messages", None)
                if isinstance(logs, list):
                    logs.append(f"JavaScript error: {exc}")

        script.decompose()


def _get_runtime_logs(runtime: JavaScriptRuntime | None) -> str:
    if runtime is None:
        return ""

    logs = getattr(runtime, "console_messages", None)
    if logs is None:
        logs = getattr(runtime, "logs", [])
    if isinstance(logs, list):
        return "\n".join(str(item) for item in logs)

    return ""


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------


@dataclass
class FormField:
    """A supported HTML form control."""

    index: int
    name: str = ""
    field_type: str = "text"
    value: str = ""
    label: str = ""
    placeholder: str = ""
    required: bool = False
    disabled: bool = False
    checked: bool = False
    multiple: bool = False
    options: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FormSpec:
    """A parsed HTML form."""

    index: int
    action: str
    method: str
    fields: list[FormField] = field(default_factory=list)
    submit_name: str = ""
    submit_value: str = ""


def _control_label(control: Tag) -> str:
    """Find an associated HTML label."""
    control_id = control.get("id")

    if control_id:
        for label in control.find_all_previous("label"):
            if label.get("for") == control_id:
                return label.get_text(" ", strip=True)

    parent_label = control.find_parent("label")
    if parent_label:
        return parent_label.get_text(" ", strip=True)

    return str(control.get("aria-label") or control.get("name") or "")


def parse_forms(html: str, base_url: str) -> list[FormSpec]:
    """Extract common HTML forms and controls."""
    soup = BeautifulSoup(html, "html.parser")
    forms: list[FormSpec] = []
    field_index = 0

    for form_index, form_tag in enumerate(soup.find_all("form")):
        action = urljoin(base_url, str(form_tag.get("action") or base_url))
        method = str(form_tag.get("method") or "get").lower()

        if method not in {"get", "post"}:
            method = "get"

        spec = FormSpec(
            index=form_index,
            action=action,
            method=method,
        )

        for control in form_tag.find_all(["input", "textarea", "select", "button"]):
            tag_name = control.name
            name = str(control.get("name") or "")
            disabled = control.has_attr("disabled")

            if tag_name == "input":
                field_type = str(control.get("type") or "text").lower()

                if field_type in {"submit", "button", "image", "reset", "file"}:
                    if field_type == "submit" and not spec.submit_name:
                        spec.submit_name = name
                        spec.submit_value = str(control.get("value") or "")
                    continue

                supported = {
                    "text",
                    "search",
                    "email",
                    "url",
                    "tel",
                    "number",
                    "password",
                    "hidden",
                    "checkbox",
                    "radio",
                }
                if field_type not in supported:
                    continue

                item = FormField(
                    index=field_index,
                    name=name,
                    field_type=field_type,
                    value=str(control.get("value") or ""),
                    label=_control_label(control),
                    placeholder=str(control.get("placeholder") or ""),
                    required=control.has_attr("required"),
                    disabled=disabled,
                    checked=control.has_attr("checked"),
                )

            elif tag_name == "textarea":
                item = FormField(
                    index=field_index,
                    name=name,
                    field_type="textarea",
                    value=control.get_text(),
                    label=_control_label(control),
                    placeholder=str(control.get("placeholder") or ""),
                    required=control.has_attr("required"),
                    disabled=disabled,
                )

            elif tag_name == "select":
                options: list[tuple[str, str]] = []

                for option in control.find_all("option"):
                    option_value = str(
                        option.get("value")
                        if option.has_attr("value")
                        else option.get_text(strip=True)
                    )
                    option_label = option.get_text(" ", strip=True)
                    options.append((option_value, option_label))

                selected = next(
                    (
                        str(
                            option.get("value")
                            if option.has_attr("value")
                            else option.get_text(strip=True)
                        )
                        for option in control.find_all("option")
                        if option.has_attr("selected")
                    ),
                    options[0][0] if options else "",
                )

                item = FormField(
                    index=field_index,
                    name=name,
                    field_type="select",
                    value=selected,
                    label=_control_label(control),
                    required=control.has_attr("required"),
                    disabled=disabled,
                    multiple=control.has_attr("multiple"),
                    options=options,
                )

            else:
                if str(control.get("type") or "submit").lower() == "submit":
                    if not spec.submit_name:
                        spec.submit_name = name
                        spec.submit_value = str(control.get("value") or "")
                continue

            spec.fields.append(item)
            field_index += 1

        forms.append(spec)

    return forms


def validate_form(form: FormSpec, values: dict[int, str | bool]) -> None:
    """Perform basic required-field validation."""
    for item in form.fields:
        if item.disabled or not item.required:
            continue

        value = values.get(item.index, item.value)

        if item.field_type == "checkbox":
            if not value:
                raise ValueError(
                    f"Required checkbox missing: {item.label or item.name}"
                )
        elif not str(value).strip():
            raise ValueError(f"Required field missing: {item.label or item.name}")


async def submit_form(
    form: FormSpec,
    values: dict[int, str | bool],
    current_url: str,
) -> tuple[str, str]:
    """Submit a form asynchronously using GET or URL-encoded POST."""
    validate_form(form, values)

    payload: list[tuple[str, str]] = []

    for item in form.fields:
        if item.disabled or not item.name:
            continue

        value = values.get(item.index, item.value)

        if item.field_type == "checkbox":
            if value:
                payload.append((item.name, item.value or "on"))
        elif item.field_type == "radio":
            if value:
                payload.append((item.name, item.value))
        else:
            payload.append((item.name, str(value)))

    if form.submit_name:
        payload.append((form.submit_name, form.submit_value))

    action = urljoin(current_url, form.action)
    action = validate_http_url(action)

    timeout = httpx.Timeout(20.0, connect=10.0)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        if form.method.lower() == "post":
            response = await client.post(action, data=payload)
        else:
            response = await client.get(action, params=payload)

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        if "html" not in content_type and "xhtml" not in content_type:
            raise ValueError(
                "Unsupported form response content type: "
                f"{content_type or 'unknown'}"
            )

        final_url = validate_http_url(str(response.url))
        return final_url, response.text


# ---------------------------------------------------------------------------
# CSS-aware terminal rendering
# ---------------------------------------------------------------------------

BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "details",
    "dialog",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "section",
    "summary",
    "table",
    "tr",
    "ul",
}

SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "object",
    "embed",
    "head",
    "template",
}

HEADING_STYLES = {
    "h1": Style(color="bright_cyan", bold=True),
    "h2": Style(color="bright_blue", bold=True),
    "h3": Style(color="cyan", bold=True),
    "h4": Style(bold=True),
    "h5": Style(bold=True, italic=True),
    "h6": Style(dim=True, bold=True),
}


def _parse_css_declarations(source: str) -> dict[str, str]:
    declarations: dict[str, str] = {}

    for declaration in source.split(";"):
        if ":" not in declaration:
            continue

        key, value = declaration.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if value.endswith("!important"):
            value = value.removesuffix("!important").strip()

        declarations[key] = value

    return declarations


def _collect_css_rules(html: str) -> list[tuple[str, dict[str, str]]]:
    """Collect simple selectors from embedded stylesheets."""
    soup = BeautifulSoup(html, "html.parser")
    rules: list[tuple[str, dict[str, str]]] = []

    for style_tag in soup.find_all("style"):
        source = style_tag.get_text()

        for selector_text, declaration_text in re.findall(
            r"([^{}]+)\{([^{}]*)\}", source
        ):
            declarations = _parse_css_declarations(declaration_text)

            for selector in selector_text.split(","):
                selector = selector.strip()
                if selector and not selector.startswith("@"):
                    rules.append((selector, declarations))

    return rules


def _selector_matches(element: Tag, selector: str) -> bool:
    """Match basic tag, class, and ID selectors."""
    selector = selector.strip()

    if not selector or any(char in selector for char in (" ", ">", "+", "~", ":", "[")):
        return False

    if selector.startswith("#"):
        return element.get("id") == selector[1:]

    if selector.startswith("."):
        return selector[1:] in element.get("class", [])

    if "." in selector:
        tag_name, class_name = selector.split(".", 1)
        return element.name == tag_name.lower() and class_name in element.get(
            "class", []
        )

    return element.name == selector.lower()


def _element_style(
    element: Tag,
    rules: list[tuple[str, dict[str, str]]],
) -> Style:
    """Resolve basic CSS text styling."""
    properties: dict[str, str] = {}

    for selector, declarations in rules:
        if _selector_matches(element, selector):
            properties.update(declarations)

    inline_style = element.get("style")
    if inline_style:
        properties.update(_parse_css_declarations(str(inline_style)))

    color = properties.get("color")
    background = properties.get("background-color")

    if color and color.lower().startswith("var("):
        color = None
    if background and background.lower().startswith("var("):
        background = None

    kwargs: dict[str, object] = {}

    if color:
        kwargs["color"] = color
    if background:
        kwargs["bgcolor"] = background

    weight = properties.get("font-weight", "").lower()
    if weight in {"bold", "bolder", "600", "700", "800", "900"}:
        kwargs["bold"] = True

    if properties.get("font-style", "").lower() == "italic":
        kwargs["italic"] = True

    decoration = properties.get("text-decoration", "").lower()
    if "underline" in decoration:
        kwargs["underline"] = True
    if "line-through" in decoration:
        kwargs["strike"] = True

    try:
        return Style(**kwargs)
    except Exception:
        return Style(
            bold=bool(kwargs.get("bold")),
            italic=bool(kwargs.get("italic")),
            underline=bool(kwargs.get("underline")),
        )


def parse_page(
    html: str,
    base_url: str,
    runtime: JavaScriptRuntime | None = None,
) -> tuple[Text, dict[int, str], str]:
    """Render HTML as readable styled Rich text.

    Supports basic inline CSS, headings, paragraphs, lists, links, code,
    blockquotes, tables in a simplified text layout, and horizontal rules.
    """
    soup = BeautifulSoup(html, "html.parser")
    css_rules = _collect_css_rules(html)

    if runtime is not None:
        execute_inline_scripts(soup, runtime)

    for element in list(soup.find_all(list(SKIP_TAGS))):
        element.decompose()

    rendered = Text()
    links: dict[int, str] = {}
    next_link = 1
    list_depth = 0
    pre_depth = 0

    def ensure_newlines(count: int = 1) -> None:
        current = rendered.plain
        trailing = len(current) - len(current.rstrip("\n"))

        if current:
            rendered.append("\n" * max(0, count - trailing))

    def append_collapsed(value: str) -> None:
        if pre_depth:
            rendered.append(value)
            return

        value = re.sub(r"\s+", " ", value)
        if not value:
            return

        if value.startswith(" ") and (
            not rendered.plain or rendered.plain.endswith((" ", "\n"))
        ):
            value = value[1:]

        # Adjacent inline tags often have no whitespace in the source HTML,
        # but still need a separator when their text nodes are separate words.
        if value and rendered.plain and not rendered.plain.endswith((" ", "\n")):
            previous = rendered.plain[-1]
            if value[0].isalnum() and previous.isalnum():
                rendered.append(" ")
        if value:
            rendered.append(value)

    def walk(node) -> None:
        nonlocal next_link, list_depth, pre_depth

        if isinstance(node, NavigableString):
            append_collapsed(str(node))
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower()

        if tag in SKIP_TAGS:
            return

        if tag == "br":
            ensure_newlines(1)
            return

        if tag == "hr":
            ensure_newlines(2)
            rendered.append("─" * 48, style="dim")
            ensure_newlines(2)
            return

        if tag == "img":
            alt = str(node.get("alt") or "").strip()
            if alt:
                rendered.append(f"[Image: {alt}]", style="dim italic")
            return

        if tag in {"input", "select", "textarea", "button"}:
            # Interactive controls are rendered in the separate form panel.
            return

        is_block = tag in BLOCK_TAGS
        if is_block:
            ensure_newlines(2 if tag in {"p", "div", "section", "article"} else 1)

        if tag in {"ul", "ol"}:
            list_depth += 1

        if tag == "li":
            ensure_newlines(1)
            indent = "  " * max(0, list_depth - 1)
            parent = node.find_parent(["ol", "ul"])
            if parent and parent.name == "ol":
                siblings = parent.find_all("li", recursive=False)
                number = siblings.index(node) + 1 if node in siblings else 1
                rendered.append(f"{indent}{number}. ", style="bright_yellow")
            else:
                rendered.append(f"{indent}• ", style="bright_yellow")

        if tag == "blockquote":
            ensure_newlines(1)
            rendered.append("│ ", style="dim cyan")

        if tag == "pre":
            ensure_newlines(1)
            pre_depth += 1

        start = len(rendered)

        if tag == "a":
            href = node.get("href")
            label = node.get_text(" ", strip=True)

            if href:
                absolute_url = unwrap_redirect_url(urljoin(base_url, str(href)))
                parsed_href = urlparse(absolute_url)
                if parsed_href.scheme not in {"http", "https"} or not parsed_href.hostname:
                    # Do not expose javascript:, data:, mailto:, or malformed URLs
                    # as navigable browser links.
                    for child in node.children:
                        walk(child)
                    return

                number = next_link
                next_link += 1
                links[number] = absolute_url

                link_start = len(rendered)
                for child in node.children:
                    walk(child)
                if len(rendered) == link_start and label:
                    rendered.append(label)
                link_end = len(rendered)

                # Store the destination on the entire visible label. ClickablePage
                # reads this metadata, so clicking any character opens the link.
                link_style = Style(
                    color="bright_cyan",
                    underline=True,
                    meta={"webterm_url": absolute_url},
                )
                if link_end > link_start:
                    rendered.stylize(link_style, link_start, link_end)
            else:
                for child in node.children:
                    walk(child)

        else:
            for child in node.children:
                walk(child)

        end = len(rendered)

        if tag == "pre":
            pre_depth = max(0, pre_depth - 1)
            if end > start:
                rendered.stylize(
                    Style(color="bright_green", bgcolor="#191b20"),
                    start,
                    end,
                )

        if tag == "code" and end > start:
            rendered.stylize(
                Style(color="bright_yellow", bgcolor="#242630"),
                start,
                end,
            )

        if tag in {"strong", "b"} and end > start:
            rendered.stylize(Style(bold=True), start, end)

        if tag in {"em", "i"} and end > start:
            rendered.stylize(Style(italic=True), start, end)

        if tag in HEADING_STYLES and end > start:
            rendered.stylize(HEADING_STYLES[tag], start, end)

        if tag == "blockquote" and end > start:
            rendered.stylize(Style(italic=True), start, end)

        if end > start:
            style = _element_style(node, css_rules)
            rendered.stylize(style, start, end)

        if tag in {"ul", "ol"}:
            list_depth = max(0, list_depth - 1)

        if is_block:
            ensure_newlines(2 if tag in {"p", "div", "section", "article"} else 1)

    body = soup.body or soup
    for child in body.children:
        walk(child)

    # Normalize excessive blank lines and remove outer whitespace.
    cleaned = Text()
    for index, line in enumerate(rendered.split("\n")):
        if index:
            cleaned.append("\n")
        cleaned.append(line)

    plain_lines = cleaned.plain.splitlines()
    while plain_lines and not plain_lines[0].strip():
        plain_lines.pop(0)
    while plain_lines and not plain_lines[-1].strip():
        plain_lines.pop()

    if plain_lines:
        # Preserve styles by trimming the original Text rather than rebuilding
        # it from plain text.
        plain = cleaned.plain
        left = len(plain) - len(plain.lstrip("\n"))
        right = len(plain.rstrip("\n"))
        cleaned = cleaned[left:right] if right >= left else Text()

    if not cleaned.plain.strip():
        cleaned = Text("(This page contains no readable text.)", style="dim")

    return cleaned, links, _get_runtime_logs(runtime)
