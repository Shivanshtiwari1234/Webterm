"""Webterm application entry point."""

from webterm.landing_server import LandingServer
from webterm import core
from webterm.ui import Webterm


def main() -> None:
    server = LandingServer()

    try:
        landing_url = server.start()
        core.set_home_url(landing_url)

        Webterm().run()
    finally:
        server.stop()


if __name__ == "__main__":
    main()
