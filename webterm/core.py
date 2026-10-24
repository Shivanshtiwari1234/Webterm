"""Webterm core: URL handling, HTTP fetching, HTML parsing, and forms."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import (
    parse_qsl,
    quote_plus,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import httpx
from bs4 import BeautifulSoup, Tag
from rich.text import Text

from .javascript import JavaScriptRuntime


HOME_URL = "https://duckduckgo.com/"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"
USER_AGENT = "Webterm/0.5 (terminal web browser)"


@dataclass
class FormField:
    """A form control, including its initial HTML value."""

    index: int
    name: str
    kind: str
    label: str = ""
    value: str = ""
    required: bool = False
    disabled: bool = False
    readonly: bool = False
    checked: bool = False
    placeholder: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)
    multiple: bool = False
    min_value: str = ""
    max_value: str = ""
    pattern: str = ""
    autocomplete: str = ""


@dataclass
class FormSpec:
    """An HTML form and its controls."""

    index: int
    action: str
    method: str
    enctype: str
    fields: list[FormField] = field(default_factory=list)
    submitters: list[FormField] = field(default_factory=list)
    name: str = ""
    identifier: str = ""


def validate_http_url(url: str) -> str:
    """Validate a URL before using it for navigation or form submission."""
    parsed = urlparse(url)

    if (
        parsed.scheme.lower() not in ("http", "https")
        or not parsed.hostname
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Only HTTP and HTTPS URLs without embedded credentials are supported.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid port in URL.") from exc

    return url


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

    return validate_http_url(value)


async def fetch_page(url: str) -> tuple[str, str]:
    """Fetch an HTML page. Return its final URL and HTML source."""
    validate_http_url(url)
    timeout = httpx.Timeout(20.0, connect=10.0)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

        final_url = str(response.url)
        validate_http_url(final_url)

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ValueError(
                f"Not an HTML page: {content_type or 'unknown type'}"
            )

        return final_url, response.text


async def submit_form(
    action: str,
    method: str,
    enctype: str,
    values: list[tuple[str, str]],
) -> tuple[str, str]:
    """Submit an HTML form and return the final URL and HTML response.

    Only GET and application/x-www-form-urlencoded POST are supported.
    Redirects are followed only when the final destination remains HTTP(S).
    """
    action = validate_http_url(action)
    method = method.upper()
    enctype = enctype.lower().split(";", 1)[0].strip()

    if method not in ("GET", "POST"):
        raise ValueError(f"Unsupported form method: {method}")

    if enctype != "application/x-www-form-urlencoded":
        raise ValueError(
            "Webterm currently supports only URL-encoded forms. "
            "Multipart and plain-text forms are not supported."
        )

    timeout = httpx.Timeout(20.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers=headers,
    ) as client:
        if method == "GET":
            parsed = urlparse(action)
            query = urlencode(values, doseq=True)
            destination = urlunparse(
                parsed._replace(query=query)
            )
            response = await client.get(destination)
        else:
            response = await client.post(
                action,
                data=values,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
            )

        response.raise_for_status()

        final_url = str(response.url)
        validate_http_url(final_url)

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ValueError(
                f"Form response is not HTML: {content_type or 'unknown type'}"
            )

        return final_url, response.text


def _control_label(
    control: Tag,
    labels_by_id: dict[str, str],
) -> str:
    """Find a label associated with a form control."""
    control_id = str(control.get("id", ""))

    if control_id and control_id in labels_by_id:
        return labels_by_id[control_id]

    parent_label = control.find_parent("label")
    if parent_label:
        clone = BeautifulSoup(str(parent_label), "html.parser")
        for nested in clone.find_all(["input", "textarea", "select", "button"]):
            nested.decompose()
        return clone.get_text(" ", strip=True)

    return str(control.get("aria-label", "")).strip()


def parse_forms(html: str, base_url: str) -> list[FormSpec]:
    """Extract supported HTML forms and their controls."""
    soup = BeautifulSoup(html, "html.parser")
    forms: list[FormSpec] = []

    for form_index, form_tag in enumerate(soup.find_all("form")):
        assert isinstance(form_tag, Tag)

        raw_action = str(form_tag.get("action", "")).strip()
        action = urljoin(base_url, raw_action) if raw_action else base_url
        action = validate_http_url(action)

        method = str(form_tag.get("method", "get")).strip().upper()
        if method not in ("GET", "POST"):
            method = method

        enctype = str(
            form_tag.get(
                "enctype",
                "application/x-www-form-urlencoded",
            )
        ).strip().lower()

        labels_by_id: dict[str, str] = {}
        for label_tag in form_tag.find_all("label", attrs={"for": True}):
            target_id = str(label_tag.get("for", ""))
            if target_id:
                labels_by_id[target_id] = label_tag.get_text(" ", strip=True)

        spec = FormSpec(
            index=form_index,
            action=action,
            method=method,
            enctype=enctype,
            name=str(form_tag.get("name", "")),
            identifier=str(form_tag.get("id", "")),
        )

        control_index = 0

        for control in form_tag.find_all(
            ["input", "textarea", "select", "button"]
        ):
            if not isinstance(control, Tag):
                continue

            # Ignore controls belonging to a nested form, if malformed HTML
            # caused the parser to retain one.
            if control.find_parent("form") is not form_tag:
                continue

            tag_name = control.name.lower()
            input_type = str(control.get("type", "text")).lower()

            if tag_name == "input":
                kind = input_type
            elif tag_name == "textarea":
                kind = "textarea"
            elif tag_name == "select":
                kind = "select"
            else:
                kind = str(control.get("type", "submit")).lower()

            if kind in ("image", "file"):
                # File uploads and image-submit coordinates are not supported.
                continue

            if kind not in (
                "text", "search", "email", "password", "url", "tel",
                "number", "hidden", "checkbox", "radio", "submit",
                "reset", "button", "textarea", "select",
            ):
                continue

            name = str(control.get("name", ""))
            value = str(control.get("value", ""))
            checked = control.has_attr("checked")
            disabled = control.has_attr("disabled")
            required = control.has_attr("required")
            readonly = control.has_attr("readonly")
            label = _control_label(control, labels_by_id)

            options: list[tuple[str, str]] = []
            multiple = control.has_attr("multiple")

            if kind == "textarea":
                value = control.get_text()
            elif kind == "select":
                value = ""
                for option in control.find_all("option"):
                    option_value = str(
                        option.get("value", option.get_text(" ", strip=True))
                    )
                    option_label = option.get_text(" ", strip=True)
                    options.append((option_label, option_value))
                    if option.has_attr("selected") and not value:
                        value = option_value
                if not value and not multiple and options:
                    value = options[0][1]
            elif kind == "checkbox" and not control.has_attr("value"):
                value = "on"
            elif kind == "radio" and not control.has_attr("value"):
                value = "on"
            elif tag_name == "button" and not value:
                value = control.get_text(" ", strip=True)

            field_spec = FormField(
                index=control_index,
                name=name,
                kind=kind,
                label=label or name or kind.replace("_", " ").title(),
                value=value,
                required=required,
                disabled=disabled,
                readonly=readonly,
                checked=checked,
                placeholder=str(control.get("placeholder", "")),
                options=options,
                multiple=multiple,
                min_value=str(control.get("min", "")),
                max_value=str(control.get("max", "")),
                pattern=str(control.get("pattern", "")),
                autocomplete=str(control.get("autocomplete", "")),
            )
            control_index += 1

            if kind in ("submit", "reset", "button"):
                spec.submitters.append(field_spec)
            elif kind != "hidden" or name:
                spec.fields.append(field_spec)

        forms.append(spec)

    return forms


def execute_inline_scripts(
    soup: BeautifulSoup,
    runtime: JavaScriptRuntime,
) -> list[str]:
    """Execute inline scripts in document order and return new console output."""
    previous_count = len(runtime.console_messages)

    for script in soup.find_all("script"):
        source = script.string or script.get_text()

        # External scripts are intentionally not fetched or executed.
        if script.has_attr("src"):
            script.decompose()
            continue

        script_type = str(script.get("type", "")).strip().lower()
        if script_type and script_type not in (
            "text/javascript",
            "application/javascript",
            "text/ecmascript",
            "application/ecmascript",
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
    """Convert HTML into readable terminal text and numbered links."""
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
        soup.title.get_text(" ", strip=True) if soup.title else ""
    ) or base_url

    main = soup.find("main") or soup.find("article") or soup.body or soup
    links: dict[int, str] = {}

    for anchor in main.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()

        if not href or href.lower().startswith(
            ("javascript:", "data:", "mailto:", "tel:")
        ):
            continue

        target = urljoin(base_url, href)

        try:
            validate_http_url(target)
        except ValueError:
            continue

        if target not in links.values():
            links[len(links) + 1] = target

    output = Text()
    output.append(title + "\n", style="bold bright_cyan")
    output.append(base_url + "\n", style="dim")
    output.append("─" * 68 + "\n\n", style="dim")

    block_tags = [
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "li", "blockquote", "pre", "dt", "dd",
        "figcaption", "legend",
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

        if element.name.startswith("h") or element.name == "legend":
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
    output.append(f"LINKS ({len(links)})\n\n", style="bold bright_yellow")

    for number, target in links.items():
        output.append(f"[{number}] ", style="bold bright_green")
        output.append(target + "\n", style="underline blue")

    if not links:
        output.append("No links found.\n", style="dim")

    return output, links, title