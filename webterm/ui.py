"""Webterm UI: Textual application, tabs, navigation, and JavaScript."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Static

from .core import HOME_URL, fetch_page, normalize_address, parse_page
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
    text-style: bold;
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
        self.create_tab_state()

    @property
    def active_tab(self) -> BrowserTab:
        return next(
            tab for tab in self.tabs
            if tab.tab_id == self.active_tab_id
        )

    def create_tab_state(self) -> BrowserTab:
        """Create a tab with its own JavaScript worker."""
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

        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_tabbar()
        self.render_active_tab()
        self.query_one("#url", Input).focus()

    async def on_unmount(self) -> None:
        """Clean up every tab's JavaScript worker when the app exits."""
        for tab in self.tabs:
            tab.js.close()

    def show_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def render_active_tab(self) -> None:
        """Render the selected tab's saved page state."""
        tab = self.active_tab

        self.query_one("#page", Static).update(tab.content)
        self.query_one("#url", Input).value = tab.url
        self.query_one("#viewport", VerticalScroll).scroll_home(
            animate=False
        )

        if tab.url:
            self.show_status(
                f"{tab.title}  ·  {len(tab.links)} links"
            )
        else:
            self.show_status("Ready")

    async def refresh_tabbar(self) -> None:
        """Rebuild the tab strip."""
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

        await bar.mount(
            Button("+", id="new-tab", tooltip="New tab")
        )

    async def navigate(
        self,
        address: str,
        *,
        record_history: bool = True,
    ) -> None:
        """Navigate the active tab and execute its inline scripts."""
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

        # A number selects a link from the current page.
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

            # Execute inline scripts in this tab's separate JS worker.
            content, links, title = parse_page(
                html,
                final_url,
                runtime=tab.js,
            )

            if record_history and tab.url and final_url != tab.url:
                tab.back_stack.append(tab.url)
                tab.forward_stack.clear()

            tab.url = final_url
            tab.title = title
            tab.content = content
            tab.links = links

            if tab.tab_id == self.active_tab_id:
                self.render_active_tab()

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
    async def button_pressed(
        self,
        event: Button.Pressed,
    ) -> None:
        button_id = event.button.id or ""

        if button_id == "new-tab":
            await self.action_new_tab()

        elif button_id == "back":
            await self.action_back()

        elif button_id == "forward":
            await self.action_forward()

        elif button_id == "reload":
            await self.action_reload()

        elif button_id == "home":
            await self.navigate(HOME_URL)

        elif button_id.startswith("close-"):
            await self.close_tab(
                int(button_id.removeprefix("close-"))
            )

        elif button_id.startswith("tab-"):
            await self.switch_tab(
                int(button_id.removeprefix("tab-"))
            )

    async def action_new_tab(self) -> None:
        tab = self.create_tab_state()

        await self.refresh_tabbar()
        self.render_active_tab()
        self.query_one("#url", Input).focus()
        self.show_status(f"New tab {tab.tab_id}")

    async def close_tab(self, tab_id: int) -> None:
        tab = next(
            (item for item in self.tabs if item.tab_id == tab_id),
            None,
        )

        if tab is None:
            return

        if len(self.tabs) == 1:
            # Keep the final tab and its runtime, but reset its page.
            tab.title = "New Tab"
            tab.url = ""
            tab.content = Text(
                "Webterm\n\nEnter a URL above to start browsing.",
                style="bright_cyan",
            )
            tab.links.clear()
            tab.back_stack.clear()
            tab.forward_stack.clear()

        else:
            index = self.tabs.index(tab)
            self.tabs.remove(tab)

            # The removed tab no longer needs a JS worker.
            tab.js.close()

            if self.active_tab_id == tab_id:
                new_index = min(index, len(self.tabs) - 1)
                self.active_tab_id = self.tabs[new_index].tab_id

        await self.refresh_tabbar()
        self.render_active_tab()

    async def switch_tab(self, tab_id: int) -> None:
        if any(tab.tab_id == tab_id for tab in self.tabs):
            self.active_tab_id = tab_id
            await self.refresh_tabbar()
            self.render_active_tab()

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

        next_index = (index + 1) % len(self.tabs)
        await self.switch_tab(self.tabs[next_index].tab_id)

    async def action_previous_tab(self) -> None:
        index = next(
            i for i, tab in enumerate(self.tabs)
            if tab.tab_id == self.active_tab_id
        )

        previous_index = (index - 1) % len(self.tabs)
        await self.switch_tab(self.tabs[previous_index].tab_id)

    def action_focus_url(self) -> None:
        url_input = self.query_one("#url", Input)
        url_input.focus()
        url_input.action_select_all()

    def action_focus_page(self) -> None:
        self.query_one("#viewport", VerticalScroll).focus()