"""Webterm application entry point."""

from webterm.static_server import StaticServer
from webterm import core
from webterm.ui import Webterm


def main() -> None:
    server = StaticServer()

    try:
        start_url = server.start()
        core.set_home_url(start_url)

        Webterm().run()
    finally:
        server.stop()


if __name__ == "__main__":
    main()
