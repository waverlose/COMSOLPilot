"""The COMSOLPILOT ASCII wordmark, shared by the menu and the spinner.

Keeping one copy means the banner the menu shows and the banner the spinner
animates can never drift apart.
"""

from __future__ import annotations

FONT = {
    "C": ["  ____ ", " / ___|", "| |    ", "| |___ ", " \\____|"],
    "O": ["  ___  ", " / _ \\ ", "| | | |", "| |_| |", " \\___/ "],
    "M": [" __  __ ", "|  \\/  |", "| |\\/| |", "| |  | |", "|_|  |_|"],
    "S": [" ____  ", "/ ___| ", "\\___ \\ ", " ___) |", "|____/ "],
    "L": [" _     ", "| |    ", "| |    ", "| |___ ", "|_____|"],
    "P": [" ____  ", "|  _ \\ ", "| |_) |", "|  __/ ", "|_|    "],
    "I": [" ___ ", "|_ _|", " | | ", " | | ", "|___|"],
    "T": [" _____ ", "|_   _|", "  | |  ", "  | |  ", "  |_|  "],
}

WORD = "COMSOLPILOT"
INDENT = "  "
HEIGHT = 5


def rows() -> list:
    """The wordmark as lines, trailing spaces stripped, no indent."""
    out = [""] * HEIGHT
    for letter in WORD:
        glyph = FONT[letter]
        for index in range(HEIGHT):
            out[index] += glyph[index]
    return [row.rstrip() for row in out]


def text() -> str:
    """The wordmark as one indented block, for a static header."""
    return "\n".join(INDENT + row for row in rows())


def width() -> int:
    return max(len(row) for row in rows())
