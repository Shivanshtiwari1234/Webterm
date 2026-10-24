
# Webterm

A lightweight, multi-tab web browser that runs entirely in the terminal.

## Features

- Textual-based terminal interface
- Multiple tabs
- Back and forward navigation
- Numbered links
- HTML text rendering
- Search queries through DuckDuckGo
- Keyboard-driven navigation

## Requirements

- Python 3.11 or newer
- A terminal with Unicode support

## Installation

Clone or download the project, then run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Usage

Launch the browser:

```bash
webterm
```

Alternatively:

```bash
python main.py
```

## License

Webterm is licensed under the GNU General Public
License, version 3 only. See [LICENSE](LICENSE).
