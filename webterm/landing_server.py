"""Background HTTP server for Webterm's built-in landing page."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LANDING_DIR = PROJECT_ROOT / "landing"


class QuietHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serve landing assets without cluttering the terminal with logs."""

    def log_message(self, format: str, *args: object) -> None:
        pass


class LandingServer:
    """Serve the landing directory on a local HTTP server thread."""

    def __init__(self) -> None:
        if not (LANDING_DIR / "index.html").is_file():
            raise FileNotFoundError(
                f"Landing page not found: {LANDING_DIR / 'index.html'}"
            )

        handler = partial(
            QuietHTTPRequestHandler,
            directory=str(LANDING_DIR),
        )

        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler,
        )
        self._server.daemon_threads = True

        self._thread = Thread(
            target=self._server.serve_forever,
            name="webterm-landing-server",
            daemon=True,
        )
        self._started = False
        self._closed = False

    @property
    def url(self) -> str:
        """Return the local landing page URL."""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> str:
        """Start the server and return its URL."""
        if self._closed:
            raise RuntimeError("Cannot start a stopped landing server.")

        if not self._started:
            self._thread.start()
            self._started = True

        return self.url

    def stop(self) -> None:
        """Stop the server and release its socket."""
        if self._closed:
            return

        if self._started:
            self._server.shutdown()
            self._thread.join(timeout=3)

        self._server.server_close()
        self._closed = True
