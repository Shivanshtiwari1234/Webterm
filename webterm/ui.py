"""Main Textual application for Webterm."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import on
from textual.widgets import Button, Footer, Header, Input, Static

from . import core
from .browser_view import BrowserTab, BrowserView
from .page_widget import ClickablePage

CSS = (
    Path(__file__).resolve().parent / "static" / "app.tcss"
).read_text(encoding="utf-8")


class Webterm(App):
    """A keyboard-first terminal web browser."""

    TITLE = "Webterm — Terminal Web Browser"
    CSS = CSS

    BINDINGS = [
        Binding("ctrl+l", "focus_address", "Address"),
        Binding("ctrl+t", "new_tab", "New tab"),
        Binding("ctrl+w", "close_tab", "Close tab"),
        Binding("ctrl+r", "reload", "Reload"),
        Binding("alt+left", "back", "Back"),
        Binding("alt+right", "forward", "Forward"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.tabs: list[BrowserTab] = []
        self.active_tab_id = 0
        self.next_tab_id = 1
        self.browser = BrowserView(self)

    @property
    def active_tab(self) -> BrowserTab | None:
        return next(
            (tab for tab in self.tabs if tab.tab_id == self.active_tab_id),
            None,
        )

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="toolbar"):
            yield Button("Back", id="back")
            yield Button("Forward", id="forward")
            yield Button("Home", id="home")
            yield Button("Reload", id="reload")
            yield Input(placeholder="Enter URL or search", id="url")
            yield Button("Go", id="go", variant="primary")

        with Horizontal(id="tabbar"):
            yield Button("+ New Tab", id="new-tab", variant="success")

        # One scroll container owns both rendered page text and its forms.
        # This prevents the forms panel from creating a second scrollbar.
        with VerticalScroll(id="page"):
            yield ClickablePage(id="page-text")
            with Vertical(id="forms"):
                pass

        yield Static("Ready", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        await self.create_tab(load=False)
        await self.browser.navigate(core.HOME_URL)
        self.query_one("#url", Input).focus()

    async def refresh_tabbar(self) -> None:
        """Rebuild the tab bar using compact labels."""

        bar = self.query_one("#tabbar", Horizontal)

        for child in list(bar.children):
            await child.remove()

        for tab in self.tabs:
            marker = "● " if tab.tab_id == self.active_tab_id else ""
            title = tab.title or "New Tab"

            if len(title) > 19:
                title = title[:16] + "..."

            await bar.mount(
                Button(
                    marker + title,
                    id=f"tab-{tab.tab_id}",
                    variant=(
                        "primary" if tab.tab_id == self.active_tab_id else "default"
                    ),
                )
            )

        await bar.mount(Button("+ New Tab", id="new-tab", variant="success"))

    async def create_tab(
        self,
        *,
        load: bool = True,
        url: str | None = None,
    ) -> None:
        tab = BrowserTab(tab_id=self.next_tab_id)
        self.next_tab_id += 1

        self.tabs.append(tab)
        self.active_tab_id = tab.tab_id

        await self.refresh_tabbar()

        if load:
            await self.browser.navigate(url or core.HOME_URL, tab=tab)
        else:
            tab.content.plain = "Webterm\n\nEnter a URL or search."
            self.query_one("#page-text", ClickablePage).set_page(
                tab.content, {}, tab.url
            )

    async def switch_tab(self, tab_id: int) -> None:
        tab = next((item for item in self.tabs if item.tab_id == tab_id), None)

        if tab is None:
            return

        self.active_tab_id = tab_id

        self.query_one("#url", Input).value = tab.url
        self.query_one("#page-text", ClickablePage).set_page(
            tab.content, tab.links, tab.url
        )

        await self.browser.render_forms(tab)
        await self.refresh_tabbar()

    async def close_current_tab(self) -> None:
        tab = self.active_tab

        if tab is None:
            return

        if len(self.tabs) == 1:
            if tab.js is not None:
                try:
                    tab.js.close()
                except Exception:
                    pass

            tab.js = None
            tab.url = ""
            tab.title = "New Tab"
            tab.content = __import__("rich.text", fromlist=["Text"]).Text("New Tab")
            tab.links.clear()
            tab.forms.clear()
            tab.back_stack.clear()
            tab.forward_stack.clear()

            await self.switch_tab(tab.tab_id)
            return

        index = self.tabs.index(tab)
        self.tabs.remove(tab)

        if tab.js is not None:
            try:
                tab.js.close()
            except Exception:
                pass

        next_index = min(index, len(self.tabs) - 1)
        await self.switch_tab(self.tabs[next_index].tab_id)

    async def open_link_url(self, url: str) -> None:
        """Open a clicked link inside Webterm."""

        await self.browser.navigate(url)

    async def action_focus_address(self) -> None:
        address = self.query_one("#url", Input)
        address.focus()
        address.action_select_all()

    async def action_new_tab(self) -> None:
        await self.create_tab()

    async def action_close_tab(self) -> None:
        await self.close_current_tab()

    async def action_reload(self) -> None:
        await self.browser.reload()

    async def action_back(self) -> None:
        await self.browser.go_back()

    async def action_forward(self) -> None:
        await self.browser.go_forward()

    @on(Input.Submitted, "#url")
    async def address_submitted(self, event: Input.Submitted) -> None:
        await self.browser.navigate(event.value)

    @on(Button.Pressed)
    async def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""

        if button_id == "back":
            await self.browser.go_back()
        elif button_id == "forward":
            await self.browser.go_forward()
        elif button_id == "home":
            await self.browser.navigate(core.HOME_URL)
        elif button_id == "reload":
            await self.browser.reload()
        elif button_id == "go":
            await self.browser.navigate(self.query_one("#url", Input).value)
        elif button_id == "new-tab":
            await self.create_tab()
        elif button_id.startswith("tab-"):
            try:
                await self.switch_tab(int(button_id.removeprefix("tab-")))
            except ValueError:
                pass
        elif button_id.startswith("submit-form-"):
            try:
                await self.browser.submit_form(
                    int(button_id.removeprefix("submit-form-"))
                )
            except ValueError:
                pass
        elif button_id.startswith("reset-form-"):
            try:
                await self.browser.reset_form(
                    int(button_id.removeprefix("reset-form-"))
                )
            except ValueError:
                pass

    async def on_unmount(self) -> None:
        for tab in self.tabs:
            if tab.js is not None:
                try:
                    tab.js.close()
                except Exception:
                    pass
                tab.js = None
