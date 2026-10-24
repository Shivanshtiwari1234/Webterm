"""Webterm UI: tabs, navigation, HTML forms, and JavaScript."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)

from .core import (
    HOME_URL,
    FormField,
    FormSpec,
    fetch_page,
    normalize_address,
    parse_forms,
    parse_page,
    submit_form,
    validate_http_url,
)
from .javascript import JavaScriptRuntime


CSS = """
Screen {
    background: #101318;
    color: #e6edf3;
}
Header {
    height: 1;
    background: #161b22;
    color: #58a6ff;
}
#tabbar {
    height: 2;
    padding: 0 1;
    background: #171b22;
    align: left middle;
    overflow: hidden;
}
.tab-item {
    height: 2;
    min-width: 10;
    max-width: 30;
    margin-right: 1;
    padding: 0;
    background: #252b34;
}
.tab-item.active {
    background: #303844;
    border-bottom: tall #58a6ff;
}
.tab {
    width: 1fr;
    min-width: 6;
    height: 2;
    padding: 0 1;
    background: transparent;
    color: #b1bac4;
    border: none;
}
.tab-item.active .tab {
    color: #ffffff;
    text-style: bold;
}
.close-tab {
    width: 3;
    min-width: 3;
    height: 2;
    padding: 0;
    background: transparent;
    color: #8b949e;
    border: none;
}
.close-tab:hover {
    background: #da3633;
    color: white;
}
#new-tab {
    width: 4;
    min-width: 4;
    height: 2;
    padding: 0;
    background: transparent;
    color: #58a6ff;
    border: none;
}
#new-tab:hover {
    background: #303844;
}
#toolbar {
    height: 3;
    padding: 0 1;
    background: #1c2129;
    align: left middle;
}
.nav-button {
    width: 4;
    min-width: 4;
    height: 3;
    margin-right: 1;
    padding: 0;
    background: transparent;
    color: #c9d1d9;
    border: none;
}
.nav-button:hover {
    background: #303844;
    color: #58a6ff;
}
#url {
    width: 1fr;
    height: 3;
    border: round #30363d;
    background: #101318;
}
#url:focus {
    border: round #58a6ff;
}
#status {
    height: 1;
    padding: 0 1;
    background: #171b22;
    color: #8b949e;
}
#viewport {
    height: 1fr;
    margin: 0 1;
    padding: 1 2;
    border: round #30363d;
}
#page {
    width: 100%;
    height: auto;
    padding-bottom: 1;
}
#forms {
    width: 100%;
    height: auto;
    padding-bottom: 2;
}
.browser-form {
    width: 100%;
    height: auto;
    margin-top: 1;
    margin-bottom: 2;
    padding: 1;
    border: round #30363d;
    background: #171b22;
}
.form-title {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    color: #58a6ff;
    text-style: bold;
}
.form-label {
    width: 100%;
    height: auto;
    margin-top: 1;
    color: #c9d1d9;
}
.form-input {
    width: 100%;
    margin-bottom: 1;
}
.form-actions {
    width: 100%;
    height: auto;
    margin-top: 1;
}
.form-actions Button {
    margin-right: 1;
}
.form-error {
    width: 100%;
    height: auto;
    color: #ff7b72;
    margin-top: 1;
}
Footer {
    height: 1;
    background: #161b22;
}
"""


@dataclass
class BrowserTab:
    """State and JavaScript runtime belonging to one browser tab."""

    tab_id: int
    title: str = "New Tab"
    url: str = ""
    content: Text = field(
        default_factory=lambda: Text(
            "Webterm\n\nEnter a URL above to start browsing.",
            style="bright_cyan",
        )
    )
    links: dict[int, str] = field(default_factory=dict)
    forms: list[FormSpec] = field(default_factory=list)
    back_stack: list[str] = field(default_factory=list)
    forward_stack: list[str] = field(default_factory=list)
    loading: bool = False
    js: JavaScriptRuntime = field(
        default_factory=JavaScriptRuntime,
        repr=False,
        compare=False,
    )


class Webterm(App[None]):
    TITLE = "Webterm"
    SUB_TITLE = "Terminal Web Browser"
    CSS = CSS

    BINDINGS = [
        Binding("ctrl+l", "focus_url", "Address bar"),
        Binding("ctrl+t", "new_tab", "New tab"),
        Binding("ctrl+w", "close_tab", "Close tab"),
        Binding("ctrl+tab", "next_tab", "Next tab"),
        Binding("ctrl+shift+tab", "previous_tab", "Previous tab"),
        Binding("ctrl+b", "back", "Back"),
        Binding("ctrl+f", "forward", "Forward"),
        Binding("ctrl+r", "reload", "Reload"),
        Binding("alt+left", "back", "Back", show=False),
        Binding("alt+right", "forward", "Forward", show=False),
        Binding("escape", "focus_page", "Page", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.tabs: list[BrowserTab] = []
        self.active_tab_id = 0
        self.next_tab_id = 1
        self._form_errors: dict[int, str] = {}
        self.create_tab_state()

    @property
    def active_tab(self) -> BrowserTab:
        return next(
            tab for tab in self.tabs
            if tab.tab_id == self.active_tab_id
        )

    def create_tab_state(self) -> BrowserTab:
        tab = BrowserTab(tab_id=self.next_tab_id)
        self.next_tab_id += 1
        self.tabs.append(tab)
        self.active_tab_id = tab.tab_id
        return tab

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="tabbar"):
            pass

        with Horizontal(id="toolbar"):
            yield Button("‹", id="back", classes="nav-button")
            yield Button("›", id="forward", classes="nav-button")
            yield Button("↻", id="reload", classes="nav-button")
            yield Button("⌂", id="home", classes="nav-button")
            yield Input(
                placeholder="Search or enter website address",
                id="url",
            )

        yield Static("Ready", id="status")

        with VerticalScroll(id="viewport"):
            yield Static("", id="page")
            yield Vertical(id="forms")

        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_tabbar()
        self.render_active_tab()
        await self.render_forms()
        self.query_one("#url", Input).focus()

    async def on_unmount(self) -> None:
        for tab in self.tabs:
            tab.js.close()

    def show_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def render_active_tab(self) -> None:
        tab = self.active_tab
        self.query_one("#page", Static).update(tab.content)
        self.query_one("#url", Input).value = tab.url

        if tab.url:
            self.show_status(
                f"{tab.title}  ·  {len(tab.links)} links  ·  "
                f"{len(tab.forms)} forms"
            )
        else:
            self.show_status("Ready")

    async def refresh_tabbar(self) -> None:
        bar = self.query_one("#tabbar", Horizontal)
        await bar.remove_children()

        for tab in self.tabs:
            label = tab.title.strip() or "New Tab"
            if len(label) > 22:
                label = label[:21] + "…"

            classes = (
                "tab-item active"
                if tab.tab_id == self.active_tab_id
                else "tab-item"
            )

            item = Horizontal(
                id=f"tab-item-{tab.tab_id}",
                classes=classes,
            )
            await bar.mount(item)

            await item.mount(
                Button(
                    label,
                    id=f"tab-{tab.tab_id}",
                    classes="tab",
                    tooltip=tab.url or "New Tab",
                ),
                Button(
                    "×",
                    id=f"close-{tab.tab_id}",
                    classes="close-tab",
                    tooltip="Close tab",
                ),
            )

        await bar.mount(Button("+", id="new-tab", tooltip="New tab"))

    async def render_forms(self) -> None:
        """Render the active page's HTML forms as native Textual widgets."""
        tab = self.active_tab
        container = self.query_one("#forms", Vertical)
        await container.remove_children()

        for form in tab.forms:
            widgets = [
                Static(
                    f"Form {form.index + 1}",
                    classes="form-title",
                )
            ]

            # Render ordinary controls. Radio controls are grouped into one
            # Select because Textual's Select supports keyboard navigation.
            rendered_radio_groups: set[str] = set()

            for field_spec in form.fields:
                if field_spec.kind == "hidden":
                    continue

                if field_spec.kind == "radio":
                    if field_spec.name in rendered_radio_groups:
                        continue

                    rendered_radio_groups.add(field_spec.name)
                    group = [
                        candidate
                        for candidate in form.fields
                        if candidate.kind == "radio"
                        and candidate.name == field_spec.name
                    ]

                    options = [
                        (candidate.label, candidate.value)
                        for candidate in group
                    ]
                    selected = next(
                        (
                            candidate.value
                            for candidate in group
                            if candidate.checked
                        ),
                        Select.BLANK,
                    )

                    widgets.append(Label(
                        field_spec.label,
                        classes="form-label",
                    ))
                    widgets.append(Select(
                        options,
                        value=selected,
                        allow_blank=True,
                        disabled=all(item.disabled for item in group),
                        id=self._radio_widget_id(form, field_spec),
                        classes="form-input",
                    ))
                    continue

                widgets.extend(self._field_widgets(form, field_spec))

            actions: list[Button] = []
            submitters = [
                item for item in form.submitters
                if item.kind == "submit" and not item.disabled
            ]
            resetters = [
                item for item in form.submitters
                if item.kind == "reset" and not item.disabled
            ]

            if submitters:
                for submitter in submitters:
                    actions.append(Button(
                        submitter.label or "Submit",
                        id=self._submit_button_id(form, submitter),
                        variant="primary",
                    ))
            else:
                actions.append(Button(
                    "Submit",
                    id=self._submit_button_id(form, None),
                    variant="primary",
                ))

            if resetters:
                for resetter in resetters:
                    actions.append(Button(
                        resetter.label or "Reset",
                        id=self._reset_button_id(form, resetter),
                        variant="default",
                    ))
            else:
                actions.append(Button(
                    "Reset",
                    id=f"form-reset-{form.index}-default",
                    variant="default",
                ))

            widgets.append(Horizontal(*actions, classes="form-actions"))

            error = self._form_errors.get(form.index)
            if error:
                widgets.append(Static(error, classes="form-error"))

            panel = Vertical(
                *widgets,
                id=f"form-panel-{form.index}",
                classes="browser-form",
            )
            await container.mount(panel)

    def _field_widgets(
        self,
        form: FormSpec,
        field_spec: FormField,
    ) -> list:
        """Build widgets for a single non-hidden form field."""
        if field_spec.kind == "button":
            return []

        if field_spec.kind == "checkbox":
            return [
                Checkbox(
                    field_spec.label,
                    value=field_spec.checked,
                    disabled=field_spec.disabled,
                    id=self._field_widget_id(form, field_spec),
                    classes="form-input",
                )
            ]

        if field_spec.kind == "select":
            return [
                Label(field_spec.label, classes="form-label"),
                Select(
                    field_spec.options,
                    value=(
                        field_spec.value
                        if any(
                            value == field_spec.value
                            for _, value in field_spec.options
                        )
                        else Select.BLANK
                    ),
                    allow_blank=True,
                    disabled=field_spec.disabled,
                    id=self._field_widget_id(form, field_spec),
                    classes="form-input",
                ),
            ]

        if field_spec.kind == "textarea":
            return [
                Label(field_spec.label, classes="form-label"),
                TextArea(
                    field_spec.value,
                    read_only=field_spec.readonly or field_spec.disabled,
                    id=self._field_widget_id(form, field_spec),
                    classes="form-input",
                ),
            ]

        if field_spec.kind == "reset":
            return []

        return [
            Label(
                field_spec.label
                + (" *" if field_spec.required else ""),
                classes="form-label",
            ),
            Input(
                value=field_spec.value,
                placeholder=field_spec.placeholder,
                password=field_spec.kind == "password",
                disabled=field_spec.disabled or field_spec.readonly,
                id=self._field_widget_id(form, field_spec),
                classes="form-input",
            ),
        ]

    @staticmethod
    def _field_widget_id(form: FormSpec, field_spec: FormField) -> str:
        return f"form-{form.index}-field-{field_spec.index}"

    @staticmethod
    def _radio_widget_id(form: FormSpec, field_spec: FormField) -> str:
        return f"form-{form.index}-radio-{field_spec.index}"

    @staticmethod
    def _submit_button_id(
        form: FormSpec,
        submitter: FormField | None,
    ) -> str:
        if submitter is None:
            return f"form-submit-{form.index}-default"
        return f"form-submit-{form.index}-{submitter.index}"

    @staticmethod
    def _reset_button_id(
        form: FormSpec,
        resetter: FormField,
    ) -> str:
        return f"form-reset-{form.index}-{resetter.index}"

    async def navigate(
        self,
        address: str,
        *,
        record_history: bool = True,
    ) -> None:
        tab = self.active_tab

        if tab.loading:
            self.show_status("This tab is already loading.")
            return

        try:
            url = normalize_address(address)
        except ValueError as exc:
            self.show_status(str(exc))
            return

        if not url:
            return

        if url.isdigit():
            target = tab.links.get(int(url))
            if target:
                await self.navigate(target)
            else:
                self.show_status(f"No link numbered {url}.")
            return

        tab.loading = True
        self.show_status(f"Loading {url} ...")

        try:
            final_url, html = await fetch_page(url)
            content, links, title = parse_page(
                html,
                final_url,
                runtime=tab.js,
            )
            forms = parse_forms(html, final_url)

            if record_history and tab.url and final_url != tab.url:
                tab.back_stack.append(tab.url)
                tab.forward_stack.clear()

            tab.url = final_url
            tab.title = title
            tab.content = content
            tab.links = links
            tab.forms = forms
            self._form_errors.clear()

            if tab.tab_id == self.active_tab_id:
                self.render_active_tab()
                await self.render_forms()

            await self.refresh_tabbar()

        except Exception as exc:
            if tab.tab_id == self.active_tab_id:
                self.show_status(f"Error: {exc}")

        finally:
            tab.loading = False

    @on(Input.Submitted, "#url")
    async def submit_url(self, event: Input.Submitted) -> None:
        await self.navigate(event.value)

    @on(Button.Pressed)
    async def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""

        if button_id == "new-tab":
            await self.action_new_tab()
            return
        if button_id == "back":
            await self.action_back()
            return
        if button_id == "forward":
            await self.action_forward()
            return
        if button_id == "reload":
            await self.action_reload()
            return
        if button_id == "home":
            await self.navigate(HOME_URL)
            return

        if button_id.startswith("close-"):
            await self.close_tab(
                int(button_id.removeprefix("close-"))
            )
            return

        if button_id.startswith("tab-"):
            await self.switch_tab(
                int(button_id.removeprefix("tab-"))
            )
            return

        match = re.fullmatch(r"form-submit-(\d+)-(\d+|default)", button_id)
        if match:
            form_index = int(match.group(1))
            submitter_index = (
                None if match.group(2) == "default"
                else int(match.group(2))
            )
            await self.handle_form_submit(form_index, submitter_index)
            return

        match = re.fullmatch(r"form-reset-(\d+)-(.+)", button_id)
        if match:
            await self.handle_form_reset(int(match.group(1)))

    async def handle_form_reset(self, form_index: int) -> None:
        tab = self.active_tab
        if not any(form.index == form_index for form in tab.forms):
            return

        self._form_errors.pop(form_index, None)
        await self.render_forms()
        self.show_status("Form reset.")

    def _read_form_values(
        self,
        form: FormSpec,
        submitter_index: int | None,
    ) -> list[tuple[str, str]]:
        """Collect enabled controls in document order."""
        values: list[tuple[str, str]] = []
        processed_radio_names: set[str] = set()

        for field_spec in form.fields:
            if field_spec.disabled or not field_spec.name:
                continue

            if field_spec.kind == "hidden":
                values.append((field_spec.name, field_spec.value))
                continue

            if field_spec.kind == "radio":
                if field_spec.name in processed_radio_names:
                    continue

                processed_radio_names.add(field_spec.name)
                group = [
                    candidate
                    for candidate in form.fields
                    if candidate.kind == "radio"
                    and candidate.name == field_spec.name
                ]
                group_widget = next(
                    (
                        candidate for candidate in group
                        if candidate.checked
                    ),
                    group[0],
                )
                widget_id = self._radio_widget_id(form, group_widget)
                selected = self.query_one(widget_id, Select).value

                if selected is not Select.BLANK and selected is not None:
                    values.append((field_spec.name, str(selected)))
                continue

            if field_spec.kind == "checkbox":
                widget = self.query_one(
                    self._field_widget_id(form, field_spec),
                    Checkbox,
                )
                if widget.value:
                    values.append((field_spec.name, field_spec.value))
                continue

            if field_spec.kind == "select":
                widget = self.query_one(
                    self._field_widget_id(form, field_spec),
                    Select,
                )
                selected = widget.value
                if selected is not Select.BLANK and selected is not None:
                    values.append((field_spec.name, str(selected)))
                continue

            if field_spec.kind == "textarea":
                widget = self.query_one(
                    self._field_widget_id(form, field_spec),
                    TextArea,
                )
                values.append((field_spec.name, widget.text))
                continue

            if field_spec.kind in ("submit", "reset", "button"):
                continue

            widget = self.query_one(
                self._field_widget_id(form, field_spec),
                Input,
            )
            values.append((field_spec.name, widget.value))

        # Include the clicked submit button's name/value.
        if submitter_index is not None:
            submitter = next(
                (
                    item for item in form.submitters
                    if item.index == submitter_index
                    and item.kind == "submit"
                    and not item.disabled
                ),
                None,
            )
            if submitter and submitter.name:
                values.append((submitter.name, submitter.value))

        return values

    def _validate_form(self, form: FormSpec) -> str | None:
        """Perform basic browser-like required/type checks."""
        for field_spec in form.fields:
            if field_spec.disabled:
                continue

            if field_spec.kind in ("hidden", "submit", "reset", "button"):
                continue

            if field_spec.kind == "radio":
                group = [
                    candidate for candidate in form.fields
                    if candidate.kind == "radio"
                    and candidate.name == field_spec.name
                ]
                if field_spec.required and not any(
                    candidate.checked for candidate in group
                ):
                    selected = self.query_one(
                        self._radio_widget_id(form, group[0]),
                        Select,
                    ).value
                    if selected is Select.BLANK or selected is None:
                        return f"Please select {field_spec.label}."
                continue

            if field_spec.kind == "checkbox":
                value = self.query_one(
                    self._field_widget_id(form, field_spec),
                    Checkbox,
                ).value
                if field_spec.required and not value:
                    return f"Please check {field_spec.label}."
                continue

            if field_spec.kind == "select":
                value = self.query_one(
                    self._field_widget_id(form, field_spec),
                    Select,
                ).value
                empty = value is None or value is Select.BLANK
                text_value = "" if empty else str(value)
            elif field_spec.kind == "textarea":
                text_value = self.query_one(
                    self._field_widget_id(form, field_spec),
                    TextArea,
                ).text
            else:
                text_value = self.query_one(
                    self._field_widget_id(form, field_spec),
                    Input,
                ).value

            if field_spec.required and not text_value.strip():
                return f"{field_spec.label} is required."

            if not text_value:
                continue

            if field_spec.kind == "email" and (
                "@" not in text_value
                or text_value.startswith("@")
                or text_value.endswith("@")
            ):
                return f"Enter a valid email address for {field_spec.label}."

            if field_spec.kind == "url":
                try:
                    parsed = urljoin("https://example.invalid", text_value)
                    validate_http_url(parsed)
                except ValueError:
                    return f"Enter a valid HTTP(S) URL for {field_spec.label}."

            if field_spec.kind == "number":
                try:
                    number = float(text_value)
                except ValueError:
                    return f"Enter a number for {field_spec.label}."

                if field_spec.min_value:
                    try:
                        if number < float(field_spec.min_value):
                            return f"{field_spec.label} must be at least {field_spec.min_value}."
                    except ValueError:
                        pass

                if field_spec.max_value:
                    try:
                        if number > float(field_spec.max_value):
                            return f"{field_spec.label} must be at most {field_spec.max_value}."
                    except ValueError:
                        pass

            if field_spec.pattern:
                try:
                    if not re.fullmatch(field_spec.pattern, text_value):
                        return f"{field_spec.label} has an invalid format."
                except re.error:
                    # Ignore invalid patterns rather than crashing the browser.
                    pass

        return None

    async def handle_form_submit(
        self,
        form_index: int,
        submitter_index: int | None,
    ) -> None:
        tab = self.active_tab

        if tab.loading:
            self.show_status("This tab is already loading.")
            return

        form = next(
            (item for item in tab.forms if item.index == form_index),
            None,
        )
        if form is None:
            self.show_status("That form is no longer available.")
            return

        error = self._validate_form(form)
        if error:
            self._form_errors[form_index] = error
            await self.render_forms()
            self.show_status(error)
            return

        try:
            action = validate_http_url(urljoin(tab.url, form.action))
            method = form.method.upper()
            enctype = form.enctype.lower().split(";", 1)[0].strip()

            if method not in ("GET", "POST"):
                raise ValueError(
                    f"Unsupported form method: {method}. Use GET or POST."
                )

            if enctype != "application/x-www-form-urlencoded":
                raise ValueError(
                    "This form uses an unsupported encoding. "
                    "Webterm supports URL-encoded forms only."
                )

            values = self._read_form_values(form, submitter_index)

        except (ValueError, LookupError) as exc:
            self.show_status(f"Form error: {exc}")
            return

        tab.loading = True
        self.show_status(f"Submitting form to {action} ...")

        try:
            final_url, html = await submit_form(
                action,
                method,
                enctype,
                values,
            )

            content, links, title = parse_page(
                html,
                final_url,
                runtime=tab.js,
            )
            forms = parse_forms(html, final_url)

            if tab.url:
                tab.back_stack.append(tab.url)
                tab.forward_stack.clear()

            tab.url = final_url
            tab.title = title
            tab.content = content
            tab.links = links
            tab.forms = forms
            self._form_errors.clear()

            self.render_active_tab()
            await self.render_forms()
            await self.refresh_tabbar()

        except Exception as exc:
            self.show_status(f"Form submission failed: {exc}")

        finally:
            tab.loading = False

    async def action_new_tab(self) -> None:
        self.create_tab_state()
        await self.refresh_tabbar()
        self.render_active_tab()
        await self.render_forms()
        self.query_one("#url", Input).focus()

    async def close_tab(self, tab_id: int) -> None:
        tab = next(
            (item for item in self.tabs if item.tab_id == tab_id),
            None,
        )
        if tab is None:
            return

        if len(self.tabs) == 1:
            tab.title = "New Tab"
            tab.url = ""
            tab.content = Text(
                "Webterm\n\nEnter a URL above to start browsing.",
                style="bright_cyan",
            )
            tab.links.clear()
            tab.forms.clear()
            tab.back_stack.clear()
            tab.forward_stack.clear()
            self._form_errors.clear()
        else:
            index = self.tabs.index(tab)
            self.tabs.remove(tab)
            tab.js.close()

            if self.active_tab_id == tab_id:
                self.active_tab_id = self.tabs[
                    min(index, len(self.tabs) - 1)
                ].tab_id

        await self.refresh_tabbar()
        self.render_active_tab()
        await self.render_forms()

    async def switch_tab(self, tab_id: int) -> None:
        if any(tab.tab_id == tab_id for tab in self.tabs):
            self.active_tab_id = tab_id
            await self.refresh_tabbar()
            self.render_active_tab()
            await self.render_forms()

    async def action_back(self) -> None:
        tab = self.active_tab

        if tab.loading or not tab.back_stack:
            self.show_status("No previous page.")
            return

        previous = tab.back_stack.pop()
        if tab.url:
            tab.forward_stack.append(tab.url)

        await self.navigate(previous, record_history=False)

    async def action_forward(self) -> None:
        tab = self.active_tab

        if tab.loading or not tab.forward_stack:
            self.show_status("No next page.")
            return

        following = tab.forward_stack.pop()
        if tab.url:
            tab.back_stack.append(tab.url)

        await self.navigate(following, record_history=False)

    async def action_reload(self) -> None:
        if self.active_tab.url:
            await self.navigate(
                self.active_tab.url,
                record_history=False,
            )
        else:
            self.show_status("Nothing to reload.")

    async def action_next_tab(self) -> None:
        index = next(
            i for i, tab in enumerate(self.tabs)
            if tab.tab_id == self.active_tab_id
        )
        await self.switch_tab(
            self.tabs[(index + 1) % len(self.tabs)].tab_id
        )

    async def action_previous_tab(self) -> None:
        index = next(
            i for i, tab in enumerate(self.tabs)
            if tab.tab_id == self.active_tab_id
        )
        await self.switch_tab(
            self.tabs[(index - 1) % len(self.tabs)].tab_id
        )

    def action_focus_url(self) -> None:
        url_input = self.query_one("#url", Input)
        url_input.focus()
        url_input.action_select_all()

    def action_focus_page(self) -> None:
        self.query_one("#viewport", VerticalScroll).focus()