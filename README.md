# Webterm

**Webterm** is a terminal-based web browser built with Python and [Textual](https://textual.textualize.io/). It brings browser-style navigation and web page rendering into a terminal interface.

## Features

- Terminal-native interface powered by Textual and Rich
- Multiple tabs and URL navigation
- Page rendering with BeautifulSoup
- Link navigation and numbered-link interaction
- Browser history
- JavaScript execution using QuickJS in isolated worker processes
- Basic HTML form support
- Built-in landing page

## Requirements

- Python 3.12+
- A terminal with Textual support

Dependencies are managed through the project configuration. They include:

- [Textual](https://textual.textualize.io/)
- [Rich](https://rich.readthedocs.io/)
- [HTTPX](https://www.python-httpx.org/)
- [Beautiful Soup 4](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
- [QuickJS](https://github.com/PetterS/quickjs)

## Installation

Clone the repository and enter the project directory:

```bash
git clone https://github.com/Shivanshtiwari1234/Webterm.git
cd Webterm
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install Webterm in editable mode:

```bash
pip install -e .
```

## Usage

Launch Webterm:

```bash
webterm
```

Use the URL bar to navigate to a website. Use the browser's tab and navigation controls to browse.

## Development

Run the test suite from the project directory:

```bash
pytest
```

## License

Webterm is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.
