"""Terminal layer: colors, tables, interactive prompts.

Everything terminal-facing lives here so business logic stays free of ANSI
codes. Colors auto-disable when the stream is not a TTY, when ``NO_COLOR`` is
set, or when ``TERM=dumb``.
"""

from __future__ import annotations

import json
import os
import sys

from sentinel.errors import AbortError

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
CYAN = "\x1b[36m"

SYM_OK = "✓"
SYM_WARN = "⚠"
SYM_ERR = "✗"
SYM_OK_ASCII = "OK"
SYM_WARN_ASCII = "!"
SYM_ERR_ASCII = "X"

TYPE_LABELS = {"github": "GitHub", "http": "HTTP", "api": "API"}


def type_label(kind: str) -> str:
    return TYPE_LABELS.get(kind, kind.capitalize())


class Output:
    """A colored, TTY-aware writer with table/JSON helpers."""

    def __init__(self, stream=None, color: bool | None = None) -> None:
        self.stream = stream or sys.stdout
        if color is None:
            color = (
                self.stream.isatty()
                and os.environ.get("NO_COLOR") is None
                and os.environ.get("TERM") != "dumb"
            )
        self.color = bool(color)
        encoding = getattr(self.stream, "encoding", "") or ""
        self.unicode = "utf" in encoding.lower()
        self.ok_sym = SYM_OK if self.unicode else SYM_OK_ASCII
        self.warn_sym = SYM_WARN if self.unicode else SYM_WARN_ASCII
        self.err_sym = SYM_ERR if self.unicode else SYM_ERR_ASCII

    # -- painting ---------------------------------------------------------
    def paint(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def ok(self, text: str) -> str:
        return self.paint(text, GREEN)

    def warn(self, text: str) -> str:
        return self.paint(text, YELLOW)

    def err(self, text: str) -> str:
        return self.paint(text, RED)

    def info(self, text: str) -> str:
        return self.paint(text, CYAN)

    def dim(self, text: str) -> str:
        return self.paint(text, DIM)

    def bold(self, text: str) -> str:
        return self.paint(text, BOLD)

    # -- writing ----------------------------------------------------------
    def print(self, text: str = "", end: str = "\n") -> None:
        print(text, end=end, file=self.stream)
        if not self.stream.isatty():
            self.stream.flush()

    def header(self, text: str) -> None:
        self.print(self.info(self.bold(text)))

    def print_json(self, data) -> None:
        print(json.dumps(data, indent=2, default=str), file=self.stream)

    # -- tables -----------------------------------------------------------
    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        widths = [len(h) for h in headers]
        str_rows = [[str(c) for c in row] for row in rows]
        for row in str_rows:
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(cell))
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        self.print(fmt.format(*headers).rstrip())
        self.print("─" * (sum(widths) + 2 * (len(widths) - 1)))
        for row in str_rows:
            padded = row + [""] * (len(widths) - len(row))
            self.print(fmt.format(*padded[: len(widths)]).rstrip())


def _use_unicode() -> bool:
    return "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()


def _select_plain(title: str, options: list[str], out: Output) -> str:
    out.print(title)
    for i, option in enumerate(options, 1):
        out.print(f"  {i}. {option}")
    while True:
        try:
            raw = input(f"Select (1-{len(options)}): ")
        except (EOFError, KeyboardInterrupt):
            raise AbortError("aborted")
        if raw.strip().isdigit() and 1 <= int(raw.strip()) <= len(options):
            return options[int(raw.strip()) - 1]
        out.print(f"Invalid choice: {raw!r}")


def _select_tty(title: str, options: list[str], out: Output) -> str:
    import termios
    import tty

    arrow = "❯" if _use_unicode() else ">"
    idx = 0
    line_count = len(options) + 1  # title + options

    def render() -> None:
        lines = [f"\r\x1b[K{title}"] + [
            f"\r\x1b[K  {arrow if i == idx else ' '} {o}" for i, o in enumerate(options)
        ]
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    render()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                seq = os.read(fd, 2)
                if seq == b"[A":
                    idx = (idx - 1) % len(options)
                elif seq == b"[B":
                    idx = (idx + 1) % len(options)
                else:
                    continue
            elif ch in (b"k", b"K"):
                idx = (idx - 1) % len(options)
            elif ch in (b"j", b"J"):
                idx = (idx + 1) % len(options)
            elif ch in (b"\r", b"\n"):
                break
            elif ch in (b"q", b"\x03"):
                raise AbortError("aborted")
            else:
                continue
            sys.stdout.write(f"\x1b[{line_count}A")
            render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # Clear the menu and leave the chosen line behind.
    sys.stdout.write(f"\x1b[{line_count}A")
    for _ in range(line_count):
        sys.stdout.write("\x1b[K\x1b[B")
    sys.stdout.write("\r\x1b[K" + out.ok(f"{arrow} {options[idx]}") + "\n")
    sys.stdout.flush()
    return options[idx]


def select(title: str, options: list[str], out: Output | None = None) -> str:
    """Interactive single-choice menu with arrow keys / j-k / q.

    Falls back to a numbered prompt when stdin is not a TTY.
    """
    out = out or Output()
    if not out.stream.isatty():
        return _select_plain(title, options, out)
    try:
        return _select_tty(title, options, out)
    except ImportError:  # non-POSIX without termios/tty
        return _select_plain(title, options, out)


def input_text(prompt: str, default: str | None = None) -> str:
    """Prompt for a line of text. Empty input returns *default*."""
    suffix = f" [{default}]" if default is not None else ""
    try:
        raw = input(f"{prompt}{suffix}: ")
    except (EOFError, KeyboardInterrupt):
        raise AbortError("aborted")
    if not raw.strip() and default is not None:
        return default
    return raw.strip()


def confirm(prompt: str, default: bool = False) -> bool:
    """Yes/no prompt. Empty input returns *default*."""
    suffix = " [y/N]" if not default else " [Y/n]"
    try:
        raw = input(f"{prompt}{suffix}: ")
    except (EOFError, KeyboardInterrupt):
        raise AbortError("aborted")
    if not raw.strip():
        return default
    return raw.strip().lower() in ("y", "yes")
