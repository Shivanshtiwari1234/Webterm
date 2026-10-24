"""Background HTTP server for Webterm static resources."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


class QuietHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serve static assets without cluttering the terminal with logs."""

    def log_message(self, format: str, *args: object) -> None:
        pass


class StaticServer:
    """Serve the static directory on a local HTTP server thread."""

    def __init__(self) -> None:
        if not (STATIC_DIR / "index.html").is_file():
            raise FileNotFoundError(
                f"Static start page not found: {STATIC_DIR / 'index.html'}"
            )

        handler = partial(
            QuietHTTPRequestHandler,
            directory=str(STATIC_DIR),
        )

        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler,
        )
        self._server.daemon_threads = True

        self._thread = Thread(
            target=self._server.serve_forever,
            name="webterm-static-server",
            daemon=True,
        )
        self._started = False
        self._closed = False

    @property
    def url(self) -> str:
        """Return the local start-page URL."""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> str:
        """Start the server and return its URL."""
        if self._closed:
            raise RuntimeError("Cannot start a stopped static server.")

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
