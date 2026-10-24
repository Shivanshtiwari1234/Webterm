"""Navigation, page state, history, and forms."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from . import core
from .core import (
    FormSpec,
    fetch_page,
    normalize_address,
    parse_forms,
    parse_page,
    submit_form,
)
from .javascript import JavaScriptRuntime
from .page_widget import ClickablePage


@dataclass
class BrowserTab:
    """State belonging to one browser tab."""

    tab_id: int
    title: str = "New Tab"
    url: str = ""
    content: Text = field(default_factory=Text)
    links: dict[int, str] = field(default_factory=dict)
    forms: list[FormSpec] = field(default_factory=list)
    back_stack: list[str] = field(default_factory=list)
    forward_stack: list[str] = field(default_factory=list)
    loading: bool = False
    js: JavaScriptRuntime | None = None


class BrowserView:
    """Manage browser navigation and page rendering."""

    def __init__(self, app) -> None:
        self.app = app
        self.form_widgets: dict[tuple[int, int], object] = {}
        self.next_widget_id = 1

    @property
    def tab(self) -> BrowserTab | None:
        return self.app.active_tab

    def status(self, message: str) -> None:
        self.app.query_one("#status", Static).update(message)

    def get_runtime(self, tab: BrowserTab) -> JavaScriptRuntime:
        """Create a JavaScript runtime if one is not already available."""

        if tab.js is None:
            tab.js = JavaScriptRuntime()

        return tab.js

    @staticmethod
    def extract_title(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")

        if title:
            value = title.get_text(" ", strip=True)
            if value:
                return value

        heading = soup.find("h1")
        if heading:
            return heading.get_text(" ", strip=True)

        return ""

    def _append_console_logs(self, page: Text, logs: str) -> Text:
        if logs.strip():
            if page.plain and not page.plain.endswith("\n"):
                page.append("\n")

            page.append("\n--- JavaScript console ---\n", style="bold yellow")
            page.append(logs.strip(), style="dim")

        return page

    async def _display_tab(self, tab: BrowserTab) -> None:
        """Update visible content if this is the active tab."""

        if tab.tab_id != self.app.active_tab_id:
            return

        self.app.query_one("#url", Input).value = tab.url

        self.app.query_one("#page-text", ClickablePage).set_page(
            tab.content,
            tab.links,
            tab.url,
        )

        await self.render_forms(tab)
        await self.app.refresh_tabbar()

    async def navigate(
        self,
        address: str,
        *,
        record_history: bool = True,
        tab: BrowserTab | None = None,
    ) -> None:
        """Navigate to a URL or a numbered link."""

        tab = tab or self.tab

        if tab is None:
            return

        try:
            address = address.strip()

            if not address:
                return

            if address.isdigit():
                link_url = tab.links.get(int(address))

                if link_url is None:
                    self.status(f"Link {address} does not exist.")
                    return

                address = link_url

            url = normalize_address(address)

            if not url:
                return

            tab.loading = True
            self.status(f"Loading {url} ...")

            final_url, html = await fetch_page(url)

            if record_history and tab.url and tab.url != final_url:
                tab.back_stack.append(tab.url)
                tab.forward_stack.clear()

            tab.url = final_url
            tab.title = self.extract_title(html) or (
                urlparse(final_url).hostname or "Page"
            )

            tab.forms = parse_forms(html, final_url)

            # JavaScript is disabled temporarily to avoid the multiprocessing
            # failure previously encountered under Textual.
            page, links, js_logs = parse_page(html, final_url, None)

            tab.links = links
            tab.content = self._append_console_logs(page, js_logs)

            await self._display_tab(tab)
            self.status(f"{tab.title} — {final_url}")

        except Exception as exc:
            if tab.tab_id == self.app.active_tab_id:
                error_page = Text()
                error_page.append("Could not load page\n", style="bold red")
                error_page.append(
                    f"{type(exc).__name__}: {exc}",
                    style="yellow",
                )

                tab.content = error_page
                tab.links.clear()

                self.app.query_one("#page-text", ClickablePage).set_page(
                    error_page, {}, tab.url
                )
                try:
                    await self.render_forms(tab)
                except Exception:
                    pass
                self.status("Navigation failed")

        finally:
            tab.loading = False

    async def render_forms(self, tab: BrowserTab) -> None:
        """Render supported HTML forms beneath the page content."""

        container = self.app.query_one("#forms", Vertical)
        await container.remove_children()
        self.form_widgets.clear()

        for form in tab.forms:
            panel = Vertical(classes="form-panel")
            await container.mount(panel)
            await panel.mount(Label(f"Form {form.index + 1}", classes="form-label"))

            for item in form.fields:
                if item.disabled or item.field_type == "hidden":
                    continue

                if not item.name and item.field_type != "checkbox":
                    continue

                label = item.label or item.name or item.field_type.title()
                await panel.mount(Label(label, classes="form-label"))

                widget_id = self.next_widget_id
                self.next_widget_id += 1
                common = {
                    "id": f"field-{widget_id}",
                    "classes": "form-control",
                }

                if item.field_type == "checkbox":
                    widget = Checkbox(
                        label,
                        value=item.checked,
                        **common,
                    )

                elif item.field_type == "select":
                    options = [
                        (option_label, option_value)
                        for option_value, option_label in item.options
                    ]
                    valid_values = {value for _, value in options}

                    initial_value = (
                        item.value
                        if item.value in valid_values
                        else (
                            options[0][1] if options and item.required else Select.BLANK
                        )
                    )

                    widget = Select(
                        options,
                        value=initial_value,
                        allow_blank=not item.required,
                        **common,
                    )

                elif item.field_type == "textarea":
                    widget = TextArea(item.value, **common)

                else:
                    widget = Input(
                        value=item.value,
                        placeholder=item.placeholder or label,
                        password=item.field_type == "password",
                        **common,
                    )

                await panel.mount(widget)
                self.form_widgets[(form.index, item.index)] = widget

            buttons = Horizontal(classes="form-buttons")
            await panel.mount(buttons)

            await buttons.mount(
                Button(
                    "Submit",
                    id=f"submit-form-{form.index}",
                    variant="primary",
                )
            )
            await buttons.mount(
                Button(
                    "Reset",
                    id=f"reset-form-{form.index}",
                )
            )

    def _collect_form_values(
        self,
        form: FormSpec,
    ) -> dict[int, str | bool]:
        values: dict[int, str | bool] = {}

        for item in form.fields:
            widget = self.form_widgets.get((form.index, item.index))

            if isinstance(widget, Checkbox):
                values[item.index] = widget.value

            elif isinstance(widget, Select):
                values[item.index] = (
                    "" if widget.value is Select.BLANK else str(widget.value)
                )

            elif isinstance(widget, TextArea):
                values[item.index] = widget.text

            elif isinstance(widget, Input):
                values[item.index] = widget.value

            else:
                values[item.index] = item.value

        return values

    async def submit_form(self, form_index: int) -> None:
        """Submit a form from the current page."""

        tab = self.tab

        if tab is None:
            return

        form = next(
            (form for form in tab.forms if form.index == form_index),
            None,
        )

        if form is None:
            self.status("Form no longer exists.")
            return

        try:
            values = self._collect_form_values(form)
            self.status("Submitting form ...")

            final_url, html = await submit_form(form, values, tab.url)

            if tab.url and tab.url != final_url:
                tab.back_stack.append(tab.url)
                tab.forward_stack.clear()

            tab.url = final_url
            tab.title = self.extract_title(html) or (
                urlparse(final_url).hostname or "Form response"
            )

            tab.forms = parse_forms(html, final_url)
            page, links, js_logs = parse_page(html, final_url, None)

            tab.links = links
            tab.content = self._append_console_logs(page, js_logs)

            await self._display_tab(tab)
            self.status(f"Form submitted — {final_url}")

        except Exception as exc:
            self.status(f"Form error: {type(exc).__name__}: {exc}")

    async def reset_form(self, form_index: int) -> None:
        """Reset controls to their parsed initial values."""

        tab = self.tab

        if tab is None:
            return

        form = next(
            (form for form in tab.forms if form.index == form_index),
            None,
        )

        if form is None:
            return

        for item in form.fields:
            widget = self.form_widgets.get((form.index, item.index))

            if isinstance(widget, Checkbox):
                widget.value = item.checked

            elif isinstance(widget, Select):
                valid_values = {value for value, _ in item.options}
                widget.value = (
                    item.value if item.value in valid_values else Select.BLANK
                )

            elif isinstance(widget, TextArea):
                widget.text = item.value

            elif isinstance(widget, Input):
                widget.value = item.value

        self.status("Form reset.")

    async def go_back(self) -> None:
        tab = self.tab

        if tab is None or not tab.back_stack:
            self.status("No previous page.")
            return

        previous = tab.back_stack.pop()

        if tab.url:
            tab.forward_stack.append(tab.url)

        await self.navigate(previous, record_history=False, tab=tab)

    async def go_forward(self) -> None:
        tab = self.tab

        if tab is None or not tab.forward_stack:
            self.status("No forward page.")
            return

        following = tab.forward_stack.pop()

        if tab.url:
            tab.back_stack.append(tab.url)

        await self.navigate(following, record_history=False, tab=tab)

    async def reload(self) -> None:
        tab = self.tab

        if tab is not None and tab.url:
            await self.navigate(tab.url, record_history=False, tab=tab)

    async def open_link(self, number: int) -> None:
        tab = self.tab

        if tab is None:
            return

        url = tab.links.get(number)

        if url is None:
            self.status(f"Link {number} does not exist.")
            return

        await self.navigate(url)
