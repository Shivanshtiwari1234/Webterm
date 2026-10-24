"""Textual application shell for Webterm."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll, Vertical
from textual.widgets import Button, Footer, Header, Input, Static

from . import core
from .browser_view import BrowserTab, BrowserView


class Webterm(App):
    """A keyboard-friendly terminal browser."""

    TITLE = "Webterm"
    SUB_TITLE = "Terminal Web Browser"

    CSS = """
    #toolbar {
        height: 3;
        padding: 0 1;
    }

    #url {
        width: 1fr;
    }

    #tabbar {
        height: 3;
        padding: 0 1;
    }

    #page {
        height: 1fr;
        border: round $primary;
        padding: 1 2;
    }

    #page-text {
        width: 100%;
        height: auto;
    }

    #forms {
        height: auto;
        padding-top: 1;
    }

    .form-panel {
        border: round $secondary;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }

    .form-label {
        margin-top: 1;
    }

    .form-control {
        width: 100%;
        margin-bottom: 1;
    }

    .form-buttons {
        height: auto;
        margin-top: 1;
    }

    #status {
        height: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("ctrl+l", "focus_address", "Address"),
        ("ctrl+t", "new_tab", "New tab"),
        ("ctrl+w", "close_tab", "Close tab"),
        ("ctrl+r", "reload_page", "Reload"),
        ("alt+left", "go_back", "Back"),
        ("alt+right", "go_forward", "Forward"),
        ("escape", "focus_address", "Focus address"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.tabs: list[BrowserTab] = []
        self.active_tab_id: int | None = None
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

        with VerticalScroll(id="page"):
            yield Static("Starting Webterm...", id="page-text", markup=False)
            yield Vertical(id="forms")

        yield Static("Ready", id="status")
        yield Footer()

    def create_tab(self) -> BrowserTab:
        tab = BrowserTab(tab_id=self.next_tab_id)
        self.next_tab_id += 1
        self.tabs.append(tab)
        self.active_tab_id = tab.tab_id
        return tab

    async def on_mount(self) -> None:
        self.create_tab()
        await self.refresh_tabbar()
        await self.browser.navigate(core.HOME_URL)
        self.query_one("#url", Input).focus()

    async def refresh_tabbar(self) -> None:
        tabbar = self.query_one("#tabbar", Horizontal)
        await tabbar.remove_children()
        await tabbar.mount(
            Button("+ New Tab", id="new-tab", variant="success")
        )

        for tab in self.tabs:
            label = tab.title[:18]
            if tab.tab_id == self.active_tab_id:
                label = f"[{label}]"

            await tabbar.mount(
                Button(
                    label,
                    id=f"tab-{tab.tab_id}",
                    variant="primary" if tab.tab_id == self.active_tab_id else "default",
                )
            )

    async def activate_tab(self, tab_id: int) -> None:
        tab = next((t for t in self.tabs if t.tab_id == tab_id), None)
        if tab is None:
            return

        self.active_tab_id = tab_id
        self.query_one("#url", Input).value = tab.url
        self.query_one("#page-text", Static).update(tab.content or "New tab")
        await self.browser.render_forms(tab)
        await self.refresh_tabbar()
        self.query_one("#status", Static).update(f"Tab {tab.tab_id}: {tab.title}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "url":
            await self.open_address()

    async def open_address(self) -> None:
        address = self.query_one("#url", Input).value.strip()
        if address:
            await self.browser.navigate(address)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""

        if button_id == "go":
            await self.open_address()
        elif button_id == "home":
            await self.browser.navigate(core.HOME_URL)
        elif button_id == "back":
            await self.browser.go_back()
        elif button_id == "forward":
            await self.browser.go_forward()
        elif button_id == "reload":
            await self.browser.reload()
        elif button_id == "new-tab":
            await self.action_new_tab()
        elif button_id.startswith("tab-"):
            try:
                await self.activate_tab(int(button_id.removeprefix("tab-")))
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

    async def action_focus_address(self) -> None:
        self.query_one("#url", Input).focus()

    async def action_new_tab(self) -> None:
        tab = self.create_tab()
        await self.refresh_tabbar()
        self.query_one("#url", Input).value = ""
        self.query_one("#page-text", Static).update("New tab")
        await self.browser.render_forms(tab)
        self.query_one("#url", Input).focus()

    async def action_close_tab(self) -> None:
        if len(self.tabs) == 1:
            tab = self.active_tab
            if tab:
                tab.url = ""
                tab.title = "New Tab"
                tab.content = ""
                tab.links.clear()
                tab.forms.clear()
                self.query_one("#url", Input).value = ""
                self.query_one("#page-text", Static).update("New tab")
                await self.browser.render_forms(tab)
            return

        self.tabs = [t for t in self.tabs if t.tab_id != self.active_tab_id]
        if self.tabs:
            await self.activate_tab(self.tabs[-1].tab_id)

    async def action_reload_page(self) -> None:
        await self.browser.reload()

    async def action_go_back(self) -> None:
        await self.browser.go_back()

    async def action_go_forward(self) -> None:
        await self.browser.go_forward()

    async def on_unmount(self) -> None:
        for tab in self.tabs:
            try:
                tab.js.close()
            except Exception:
                pass


def main() -> None:
    Webterm().run()


if __name__ == "__main__":
    main()