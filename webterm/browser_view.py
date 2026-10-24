"""Browser tab state and page operations for Webterm."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)

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


@dataclass
class BrowserTab:
    """State associated with one browser tab."""

    tab_id: int
    title: str = "New Tab"
    url: str = ""
    content: str = ""
    links: dict[int, str] = field(default_factory=dict)
    forms: list[FormSpec] = field(default_factory=list)
    back_stack: list[str] = field(default_factory=list)
    forward_stack: list[str] = field(default_factory=list)
    loading: bool = False
    js: JavaScriptRuntime | None = None


class BrowserView:
    """Browser navigation, rendering, and form handling."""

    def __init__(self, app) -> None:
        self.app = app
        self.form_widgets: dict[int, object] = {}
        self.next_widget_id = 1

    @property
    def tab(self) -> BrowserTab | None:
        return self.app.active_tab

    def status(self, message: str) -> None:
        self.app.query_one("#status", Static).update(message)

    @staticmethod
    def extract_title(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")
        if title:
            return title.get_text(" ", strip=True)

        heading = soup.find("h1")
        return heading.get_text(" ", strip=True) if heading else ""

    async def navigate(
        self,
        address: str,
        *,
        record_history: bool = True,
        tab: BrowserTab | None = None,
    ) -> None:
        tab = tab or self.tab
        if tab is None:
            return

        try:
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
            page, tab.links, js_logs = parse_page(html, final_url, tab.js)

            tab.content = str(page)
            if js_logs.strip():
                tab.content += "\n\n--- JavaScript console ---\n" + js_logs.strip()

            if tab.tab_id == self.app.active_tab_id:
                self.app.query_one("#url", Input).value = final_url
                self.app.query_one("#page-text", Static).update(tab.content)
                await self.render_forms(tab)
                self.status(f"{tab.title} — {final_url}")

            await self.app.refresh_tabbar()

        except Exception as exc:
            if tab.tab_id == self.app.active_tab_id:
                self.app.query_one("#page-text", Static).update(
                    f"Could not load page:\n{type(exc).__name__}: {exc}"
                )
                self.status("Navigation failed")
        finally:
            tab.loading = False

    async def render_forms(self, tab: BrowserTab) -> None:
        container = self.app.query_one("#forms", Vertical)
        await container.remove_children()
        self.form_widgets.clear()

        for form in tab.forms:
            panel = Vertical(classes="form-panel")
            await container.mount(panel)
            await panel.mount(Label(f"Form {form.index + 1}"))

            for item in form.fields:
                if item.disabled or item.field_type == "hidden":
                    continue

                if not item.name and item.field_type != "checkbox":
                    continue

                label = item.label or item.name or item.field_type.title()
                widget_id = self.next_widget_id
                self.next_widget_id += 1

                await panel.mount(Label(label, classes="form-label"))

                if item.field_type == "checkbox":
                    widget = Checkbox(
                        label,
                        value=item.checked,
                        id=f"field-{widget_id}",
                        classes="form-control",
                    )
                elif item.field_type == "select":
                    options = [
                        (option_label, option_value)
                        for option_value, option_label in item.options
                    ]
                    widget = Select(
                        options,
                        value=item.value if item.options else Select.BLANK,
                        allow_blank=not item.required,
                        id=f"field-{widget_id}",
                        classes="form-control",
                    )
                elif item.field_type == "textarea":
                    widget = TextArea(
                        item.value,
                        id=f"field-{widget_id}",
                        classes="form-control",
                    )
                else:
                    widget = Input(
                        value=item.value,
                        placeholder=item.placeholder or label,
                        password=item.field_type == "password",
                        id=f"field-{widget_id}",
                        classes="form-control",
                    )

                await panel.mount(widget)
                self.form_widgets[item.index] = widget

            buttons = Horizontal(classes="form-buttons")
            await panel.mount(buttons)
            await buttons.mount(
                Button("Submit", id=f"submit-form-{form.index}", variant="primary")
            )
            await buttons.mount(Button("Reset", id=f"reset-form-{form.index}"))
    
    def get_runtime(self, tab: BrowserTab) -> JavaScriptRuntime:
        """Create the JavaScript runtime only when needed."""
        if tab.js is None:
            tab.js = JavaScriptRuntime()
        return tab.js

    async def submit_form(self, form_index: int) -> None:
        tab = self.tab
        if tab is None:
            return

        form = next((f for f in tab.forms if f.index == form_index), None)
        if form is None:
            self.status("Form no longer exists.")
            return

        values: dict[int, str | bool] = {}

        for item in form.fields:
            widget = self.form_widgets.get(item.index)

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

        try:
            self.status("Submitting form ...")
            final_url, html = await submit_form(form, values, tab.url)

            if tab.url and final_url != tab.url:
                tab.back_stack.append(tab.url)
                tab.forward_stack.clear()

            tab.url = final_url
            tab.title = self.extract_title(html) or "Form response"
            tab.forms = parse_forms(html, final_url)

            runtime = self.get_runtime(tab)
            page, tab.links, js_logs = parse_page(html, final_url, runtime)
            tab.content = str(page)

            if js_logs.strip():
                tab.content += "\n\n--- JavaScript console ---\n" + js_logs.strip()

            self.app.query_one("#url", Input).value = final_url
            self.app.query_one("#page-text", Static).update(tab.content)
            await self.render_forms(tab)
            await self.app.refresh_tabbar()
            self.status(f"Form submitted — {final_url}")

        except Exception as exc:
            self.status(f"Form error: {exc}")

    async def reset_form(self, form_index: int) -> None:
        tab = self.tab
        if tab is None:
            return

        form = next((f for f in tab.forms if f.index == form_index), None)
        if form is None:
            return

        for item in form.fields:
            widget = self.form_widgets.get(item.index)

            if isinstance(widget, Checkbox):
                widget.value = item.checked
            elif isinstance(widget, Select):
                widget.value = item.value if item.options else Select.BLANK
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
        if tab and tab.url:
            await self.navigate(tab.url, record_history=False, tab=tab)