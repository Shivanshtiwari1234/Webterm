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
MAX_PAGE_SIZE = 5 * 1024 * 1024

HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass
class FormField:
    """A supported HTML form control."""

    index: int
    name: str
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
    """A parsed HTML form and its controls."""

    index: int
    action: str
    method: str
    fields: list[FormField] = field(default_factory=list)
    submitters: list[FormField] = field(default_factory=list)
    enctype: str = "application/x-www-form-urlencoded"


def validate_http_url(value: str) -> str:
    """Validate and normalize an absolute HTTP(S) URL."""

    value = value.strip()

    if not value:
        raise ValueError("The URL is empty.")

    if any(ord(char) < 32 for char in value):
        raise ValueError("The URL contains control characters.")

    if "://" not in value:
        value = "https://" + value

    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL or port.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported.")

    if not parsed.hostname or not parsed.netloc:
        raise ValueError("Enter a valid hostname.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not supported.")

    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def set_home_url(url: str) -> None:
    """Set the homepage, for example to the local landing server."""
    global HOME_URL
    HOME_URL = validate_http_url(url)


def normalize_address(value: str) -> str:
    """Interpret address-bar input as a URL or a search query."""

    value = value.strip()

    if not value:
        return ""

    if any(ord(char) < 32 for char in value):
        raise ValueError("The address contains control characters.")

    # A plain hostname or an IP address should be treated as a URL.
    if "://" not in value:
        looks_like_host = (
            "." in value
            and " " not in value
            and not value.startswith(".")
            and not value.endswith(".")
        )

        looks_like_localhost = value.startswith("localhost:")
        looks_like_ipv6 = value.startswith("[") and "]" in value

        if not looks_like_host and not looks_like_localhost and not looks_like_ipv6:
            return SEARCH_URL.format(quote_plus(value))

        value = "https://" + value

    return validate_http_url(value)


async def fetch_page(url: str) -> tuple[str, str]:
    """Fetch an HTML page and return its final URL and decoded HTML."""

    url = validate_http_url(url)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()

            if "html" not in content_type and "xhtml" not in content_type:
                raise ValueError(
                    f"Unsupported content type: "
                    f"{content_type or 'unknown'}. Webterm currently displays HTML."
                )

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_PAGE_SIZE:
                        raise ValueError("Page exceeds the 5 MiB size limit.")
                except ValueError as exc:
                    if "size limit" in str(exc):
                        raise
                    # An invalid Content-Length header is ignored.

            chunks: list[bytes] = []
            total = 0

            async for chunk in response.aiter_bytes():
                total += len(chunk)

                if total > MAX_PAGE_SIZE:
                    raise ValueError("Page exceeds the 5 MiB size limit.")

                chunks.append(chunk)

            raw = b"".join(chunks)
            encoding = response.encoding or "utf-8"

            try:
                html = raw.decode(encoding, errors="replace")
            except LookupError:
                html = raw.decode("utf-8", errors="replace")

            return str(response.url), html


def _script_is_executable(script: Tag) -> bool:
    """Return whether an inline script uses a supported JavaScript type."""

    script_type = str(script.get("type", "")).strip().lower()

    return script_type in {
        "",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
    }


def execute_inline_scripts(
    soup: BeautifulSoup,
    runtime: JavaScriptRuntime,
) -> None:
    """Execute supported inline scripts and remove script elements."""

    for script in list(soup.find_all("script")):
        try:
            source = script.string or script.get_text()

            if not script.get("src") and _script_is_executable(script) and source.strip():
                runtime.execute(source)
        except Exception as exc:
            try:
                runtime.logs.append(f"[JavaScript error] {exc}")
            except Exception:
                pass
        finally:
            script.decompose()


def _element_label(element: Tag) -> str:
    """Find a useful label for a form control."""

    identifier = element.get("id")

    if identifier:
        label = element.find_parent("label")
        if label:
            return label.get_text(" ", strip=True)

    label = element.find_parent("label")
    if label:
        return label.get_text(" ", strip=True)

    return str(element.get("aria-label") or element.get("name") or "")


def parse_forms(html: str, base_url: str) -> list[FormSpec]:
    """Extract common HTML forms and supported controls."""

    soup = BeautifulSoup(html, "html.parser")
    forms: list[FormSpec] = []
    control_index = 0

    for form_index, form_tag in enumerate(soup.find_all("form")):
        assert isinstance(form_tag, Tag)

        action = urljoin(base_url, str(form_tag.get("action") or base_url))
        method = str(form_tag.get("method") or "get").lower()

        if method not in {"get", "post"}:
            method = "get"

        enctype = str(
            form_tag.get("enctype") or "application/x-www-form-urlencoded"
        ).lower()

        spec = FormSpec(
            index=form_index,
            action=action,
            method=method,
            enctype=enctype,
        )

        # Associated external controls using form="id" are not handled here.
        for element in form_tag.find_all(["input", "textarea", "select", "button"]):
            assert isinstance(element, Tag)

            if element.has_attr("disabled"):
                disabled = True
            else:
                disabled = False

            tag_name = element.name
            name = str(element.get("name") or "")

            if tag_name == "input":
                field_type = str(element.get("type") or "text").lower()

                if field_type in {
                    "hidden",
                    "text",
                    "search",
                    "email",
                    "url",
                    "tel",
                    "number",
                    "password",
                    "checkbox",
                    "radio",
                    "submit",
                    "reset",
                    "button",
                }:
                    pass
                else:
                    continue

                value = str(element.get("value") or "")
                checked = element.has_attr("checked")
                placeholder = str(element.get("placeholder") or "")
                required = element.has_attr("required")

                if field_type in {"submit", "reset", "button"}:
                    if field_type == "submit" and not disabled:
                        spec.submitters.append(
                            FormField(
                                index=control_index,
                                name=name,
                                field_type=field_type,
                                value=value or "Submit",
                                label=_element_label(element),
                                disabled=disabled,
                            )
                        )
                    control_index += 1
                    continue

                if field_type == "hidden" and not name:
                    control_index += 1
                    continue

                item = FormField(
                    index=control_index,
                    name=name,
                    field_type=field_type,
                    value=value,
                    label=_element_label(element),
                    placeholder=placeholder,
                    required=required,
                    disabled=disabled,
                    checked=checked,
                )

            elif tag_name == "textarea":
                item = FormField(
                    index=control_index,
                    name=name,
                    field_type="textarea",
                    value=element.get_text(),
                    label=_element_label(element),
                    placeholder=str(element.get("placeholder") or ""),
                    required=element.has_attr("required"),
                    disabled=disabled,
                )

            elif tag_name == "select":
                options: list[tuple[str, str]] = []

                for option in element.find_all("option"):
                    option_value = str(
                        option.get("value") or option.get_text(strip=True)
                    )
                    option_label = option.get_text(" ", strip=True)
                    options.append((option_value, option_label))

                selected = element.find("option", selected=True)
                value = ""

                if selected:
                    value = str(
                        selected.get("value") or selected.get_text(strip=True)
                    )
                elif options:
                    value = options[0][0]

                item = FormField(
                    index=control_index,
                    name=name,
                    field_type="select",
                    value=value,
                    label=_element_label(element),
                    required=element.has_attr("required"),
                    disabled=disabled,
                    options=options,
                )

            else:
                # Buttons are submitters only when their type is submit.
                button_type = str(element.get("type") or "submit").lower()

                if button_type == "submit" and not disabled:
                    spec.submitters.append(
                        FormField(
                            index=control_index,
                            name=name,
                            field_type="submit",
                            value=str(element.get("value") or element.get_text(strip=True) or "Submit"),
                            label=element.get_text(" ", strip=True),
                            disabled=disabled,
                        )
                    )

                control_index += 1
                continue

            spec.fields.append(item)
            control_index += 1

        if spec.fields or spec.submitters:
            forms.append(spec)

    return forms


def validate_form(
    form: FormSpec,
    values: dict[int, str | bool],
) -> list[str]:
    """Perform basic required-field checks."""

    errors: list[str] = []

    for item in form.fields:
        if item.disabled or not item.required:
            continue

        value = values.get(item.index, item.value)

        if item.field_type == "checkbox":
            if not value:
                errors.append(f"{item.label or item.name or 'Checkbox'} is required.")
        elif not str(value).strip():
            errors.append(f"{item.label or item.name or 'Field'} is required.")

    return errors


async def submit_form(
    form: FormSpec,
    values: dict[int, str | bool],
    base_url: str,
    submitter: FormField | None = None,
) -> tuple[str, str]:
    """Submit a supported GET or URL-encoded POST form."""

    errors = validate_form(form, values)
    if errors:
        raise ValueError("\n".join(errors))

    action = urljoin(base_url, form.action)
    action = validate_http_url(action)

    data: list[tuple[str, str]] = []

    for item in form.fields:
        if item.disabled or not item.name:
            continue

        value = values.get(item.index, item.value)

        if item.field_type in {"checkbox", "radio"}:
            if value:
                data.append((item.name, item.value or "on"))
        else:
            data.append((item.name, str(value)))

    if submitter and submitter.name:
        data.append((submitter.name, submitter.value))

    method = form.method.lower()

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        if method == "get":
            parsed = urlparse(action)
            existing = parse_qsl(parsed.query, keep_blank_values=True)
            query = urlencode(existing + data)
            action = urlunparse(parsed._replace(query=query))
            response = await client.get(action)

        elif method == "post":
            if form.enctype != "application/x-www-form-urlencoded":
                raise ValueError(
                    "Only URL-encoded POST forms are supported. "
                    "File uploads and multipart forms are not supported."
                )

            response = await client.post(action, data=data)

        else:
            raise ValueError(f"Unsupported form method: {method}")

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        if "html" not in content_type and "xhtml" not in content_type:
            raise ValueError(
                f"Form returned unsupported content type: "
                f"{content_type or 'unknown'}."
            )

        if len(response.content) > MAX_PAGE_SIZE:
            raise ValueError("Response exceeds the 5 MiB size limit.")

        return str(response.url), response.text


def parse_page(
    html: str,
    base_url: str,
    runtime: JavaScriptRuntime | None = None,
) -> tuple[Text, dict[int, str], str]:
    """Render page text, numbered links, and JavaScript console output."""

    soup = BeautifulSoup(html, "html.parser")

    if runtime is not None:
        execute_inline_scripts(soup, runtime)
        js_logs = "\n".join(getattr(runtime, "logs", []))
    else:
        js_logs = ""

    for element in soup(
        ["style", "noscript", "svg", "canvas", "iframe", "object", "embed"]
    ):
        element.decompose()

    links: dict[int, str] = {}
    output: list[str] = []
    link_index = 1

    for element in soup.find_all(
        ["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote", "a", "img", "br", "hr"]
    ):
        if not isinstance(element, Tag):
            continue

        if element.name == "a":
            href = element.get("href")

            if not href:
                continue

            absolute_url = urljoin(base_url, str(href))
            label = element.get_text(" ", strip=True) or absolute_url

            links[link_index] = absolute_url
            output.append(f"[{link_index}] {label} ({absolute_url})")
            link_index += 1

        elif element.name == "img":
            alt = str(element.get("alt") or "").strip()
            if alt:
                output.append(f"[Image: {alt}]")

        elif element.name == "br":
            output.append("")

        elif element.name == "hr":
            output.append("-" * 50)

        elif element.name in {"h1", "h2", "h3", "h4"}:
            text = element.get_text(" ", strip=True)
            if text:
                output.append(f"\n{text.upper()}\n")

        elif element.name == "pre":
            text = element.get_text("\n", strip=True)
            if text:
                output.append(f"\n{text}\n")

        else:
            text = element.get_text(" ", strip=True)
            if text:
                output.append(text)

    # Fall back to page text when no common structural elements were found.
    if not output:
        output = [soup.get_text("\n", strip=True)]

    rendered = "\n".join(output).strip()
    if not rendered:
        rendered = "(This page contains no readable text.)"

    page = Text(rendered)

    return page, links, js_logs