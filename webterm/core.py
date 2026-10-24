"""Webterm core: URL handling, HTTP fetching, HTML parsing, CSS styling, and forms."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from rich.style import Style
from rich.text import Text

from .javascript import JavaScriptRuntime

HOME_URL = "https://duckduckgo.com/"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"
USER_AGENT = "Webterm/0.4 (terminal web browser)"


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def validate_http_url(url: str) -> str:
    """Validate an HTTP(S) URL and return it unchanged."""

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
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


def set_home_url(url: str) -> None:
    """Set Webterm's homepage URL."""

    global HOME_URL
    HOME_URL = validate_http_url(url)


def normalize_address(value: str) -> str:
    """Normalize a URL or convert a search query into a search URL."""

    value = value.strip()

    if not value:
        return ""

    if value.isdigit():
        return value

    if " " in value or ("://" not in value and "." not in value):
        return SEARCH_URL.format(quote_plus(value))

    if "://" not in value:
        value = "https://" + value

    return validate_http_url(value)


# ---------------------------------------------------------------------------
# HTTP fetching
# ---------------------------------------------------------------------------


async def fetch_page(url: str) -> tuple[str, str]:
    """Fetch an HTML page, returning its final URL and HTML source."""

    url = validate_http_url(url)

    timeout = httpx.Timeout(20.0, connect=10.0)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        if "html" not in content_type and "xhtml" not in content_type:
            raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")

        final_url = validate_http_url(str(response.url))
        return final_url, response.text


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


def execute_inline_scripts(
    soup: BeautifulSoup,
    runtime: JavaScriptRuntime,
) -> None:
    """Execute supported inline scripts and remove script tags afterward."""

    for script in list(soup.find_all("script")):
        script_type = str(script.get("type", "")).strip().lower()
        source = script.string or script.get_text()

        supported_types = {
            "",
            "text/javascript",
            "application/javascript",
            "text/ecmascript",
            "application/ecmascript",
        }

        if not script.get("src") and script_type in supported_types and source.strip():
            try:
                runtime.execute(source)
            except Exception as exc:
                log = getattr(runtime, "logs", None)
                if isinstance(log, list):
                    log.append(f"JavaScript error: {exc}")

        script.decompose()


def _get_runtime_logs(runtime: JavaScriptRuntime | None) -> str:
    """Return logs exposed by the configured JavaScript runtime."""

    if runtime is None:
        return ""

    logs = getattr(runtime, "logs", [])

    if isinstance(logs, list):
        return "\n".join(str(item) for item in logs)

    return ""


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


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
    """Find a control's associated label, if one exists."""

    control_id = control.get("id")

    if control_id:
        label = control.find_parent("label")

        if label:
            return label.get_text(" ", strip=True)

    if control_id:
        # Search the containing document for <label for="...">.
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

                if field_type not in {
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
                }:
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
                    options=options,
                )

            else:
                # Button elements can act as submit buttons.
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
    """Submit a form using GET or URL-encoded POST."""

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

    timeout = httpx.Timeout(20.0, connect=10.0)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        if form.method == "post":
            response = await client.post(action, data=payload)
        else:
            response = await client.get(action, params=payload)

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        if "html" not in content_type and "xhtml" not in content_type:
            raise ValueError(
                f"Unsupported form response content type: "
                f"{content_type or 'unknown'}"
            )

        return validate_http_url(str(response.url)), response.text


# ---------------------------------------------------------------------------
# CSS-aware terminal rendering
# ---------------------------------------------------------------------------

BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "dd",
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
    "pre",
    "section",
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
}


def _parse_css_declarations(source: str) -> dict[str, str]:
    """Parse simple CSS declarations."""

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

        # Supports simple rules, not nested media queries or at-rules.
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

    if not selector:
        return False

    # Complex selectors are intentionally not implemented.
    if any(char in selector for char in (" ", ">", "+", "~", ":", "[")):
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
    """Resolve basic CSS color and font properties for an element."""

    properties: dict[str, str] = {}

    for selector, declarations in rules:
        if _selector_matches(element, selector):
            properties.update(declarations)

    # Inline styles override ordinary stylesheet declarations.
    inline_style = element.get("style")

    if inline_style:
        properties.update(_parse_css_declarations(str(inline_style)))

    color = properties.get("color")
    background = properties.get("background-color")

    if color and color.lower().startswith("var("):
        color = None

    if background and background.lower().startswith("var("):
        background = None

    font_weight = properties.get("font-weight", "").lower()
    decoration = properties.get("text-decoration", "").lower()

    kwargs: dict[str, object] = {}

    if color:
        kwargs["color"] = color

    if background:
        kwargs["bgcolor"] = background

    if font_weight in {"bold", "bolder", "600", "700", "800", "900"}:
        kwargs["bold"] = True

    if properties.get("font-style", "").lower() == "italic":
        kwargs["italic"] = True

    if "underline" in decoration:
        kwargs["underline"] = True

    if "line-through" in decoration:
        kwargs["strike"] = True

    try:
        return Style(**kwargs)
    except Exception:
        # Unsupported CSS color syntax should not break page rendering.
        return Style(
            bold=bool(kwargs.get("bold", False)),
            italic=bool(kwargs.get("italic", False)),
            underline=bool(kwargs.get("underline", False)),
        )


def parse_page(
    html: str,
    base_url: str,
    runtime: JavaScriptRuntime | None = None,
) -> tuple[Text, dict[int, str], str]:
    """Render HTML to styled Rich text and return numbered links and JS logs.

    CSS support includes basic tag, class, and ID selectors, inline styles,
    text/background colors, bold, italic, underline, and strikethrough.
    """

    soup = BeautifulSoup(html, "html.parser")
    css_rules = _collect_css_rules(html)

    if runtime is not None:
        execute_inline_scripts(soup, runtime)

    for element in soup.find_all(list(SKIP_TAGS)):
        element.decompose()

    rendered = Text()
    links: dict[int, str] = {}
    next_link = 1

    def newline() -> None:
        if rendered.plain and not rendered.plain.endswith("\n"):
            rendered.append("\n")

    def walk(node) -> None:
        nonlocal next_link

        if isinstance(node, str):
            # Preserve spaces inside preformatted blocks.
            value = node

            if value.strip():
                rendered.append(value)
            elif value and rendered.plain and not rendered.plain.endswith((" ", "\n")):
                rendered.append(" ")

            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower()

        if tag == "br":
            newline()
            return

        if tag == "hr":
            newline()
            rendered.append("─" * 40, style="dim")
            newline()
            return

        if tag == "img":
            alt = str(node.get("alt") or "").strip()

            if alt:
                rendered.append(f"[Image: {alt}]", style="dim italic")

            return

            if tag == "a":
                href = node.get("href")
                label = node.get_text(" ", strip=True)

                if href:
                    absolute_url = urljoin(base_url, str(href))
                    links[next_link] = absolute_url
                    label = label or absolute_url

                    start = len(rendered)
                    rendered.append(
                        f"[{next_link}] {label}",
                        style=Style(color="cyan", underline=True),
                    )
                    end = len(rendered)

                    rendered.spans.append(Span(start, end, Style(link=absolute_url)))

                    next_link += 1
                else:
                    for child in node.children:
                        walk(child)

                return
            else:
                for child in node.children:
                    walk(child)

            return

        if tag in BLOCK_TAGS:
            newline()

        start = len(rendered)

        for child in node.children:
            walk(child)

        end = len(rendered)

        if tag in {"strong", "b"}:
            rendered.stylize(Style(bold=True), start, end)

        elif tag in {"em", "i"}:
            rendered.stylize(Style(italic=True), start, end)

        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            rendered.stylize(Style(bold=True), start, end)

        elif tag == "code":
            rendered.stylize(
                Style(color="bright_yellow", bgcolor="#242630"),
                start,
                end,
            )

        elif tag == "pre":
            rendered.stylize(
                Style(color="bright_green", bgcolor="#191b20"),
                start,
                end,
            )

        style = _element_style(node, css_rules)

        if end > start:
            rendered.stylize(style, start, end)

        if tag in BLOCK_TAGS:
            newline()

    body = soup.body or soup

    for child in body.children:
        walk(child)

    # Trim leading/trailing blank lines without converting to plain text.
    while rendered.plain.startswith("\n"):
        rendered = rendered[1:]

    rendered.rstrip()

    if not rendered.plain.strip():
        rendered = Text("(This page contains no readable text.)", style="dim")

    return rendered, links, _get_runtime_logs(runtime)
