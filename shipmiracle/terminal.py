"""The controlling terminal (/dev/tty) for one typed answer.

Why this module exists: opening /dev/tty with the built-in open() in text mode r+ raises io.UnsupportedOperation ("File or stream is not seekable") on macOS 27 with the system
Python 3.9.6, because text mode r+ needs a seekable stream and a terminal is not one (a Linux tty cannot seek either, so the old pattern probably failed there too: untested).
Every caller treated that OSError as "there is no terminal" and told the owner to open a terminal, inside a terminal.
The device is opened once with os.open(O_RDWR | O_NOCTTY) (never becomes the controlling terminal of a process that has none) and ONE write-only and ONE read-only
file object are wrapped around it (the read one on a dup), so nothing ever asks the terminal to seek.

Type-ahead: whatever was typed or piped before the prompt is dropped (tcflush, like owner.py and githook_apply.py), so a pre-typed "yes" can never answer a question that was not
shown yet. The flush is fail-soft here: a terminal that cannot be flushed still gets asked.

Contract: ask_line(prompt) -> the typed line WITH its newline; "" when the terminal closed or the owner pressed Ctrl-D (also after partial text: a line that does not end with a
newline is a cancel, never an answer); raises OSError when the device cannot be opened (the old 'no terminal' signal, so callers keep their except OSError).
can_open() -> bool. TTY_PATH is the seam for tests (a pty slave path). Known gap (follow-up): no timeout; a prompt waits until the owner answers or closes the terminal."""
from __future__ import annotations

import os

try:
    import termios
except ImportError:                          # not POSIX: the flush is skipped, the open below raises OSError
    termios = None

TTY_PATH = "/dev/tty"          # tests: the path of a pty slave


def _open_fd(path):
    flags = getattr(os, "O_RDWR", 2) | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path or TTY_PATH, flags)


def can_open(path=None) -> bool:
    """True when the terminal device can be opened for reading and writing."""
    try:
        fd = _open_fd(path)
    except OSError:
        return False
    os.close(fd)
    return True


def ask_line(prompt, path=None) -> str:
    """Drop type-ahead, print `prompt` on the terminal and read one line from it. Raises OSError when there is no terminal. '' = cancelled / closed."""
    wfd = _open_fd(path)
    rfd = -1
    out = inp = None
    try:
        if termios is not None:
            try:
                termios.tcflush(wfd, termios.TCIFLUSH)
            except (termios.error, OSError):
                pass
        rfd = os.dup(wfd)
        out = os.fdopen(wfd, "w", encoding="utf-8", errors="replace")
        wfd = -1                                                  # the file object owns it now
        inp = os.fdopen(rfd, "r", encoding="utf-8", errors="replace")
        rfd = -1
        out.write(prompt)
        out.flush()
        line = inp.readline()
        return line if line.endswith("\n") else ""
    finally:
        for f in (out, inp):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        for n in (wfd, rfd):
            if n >= 0:
                os.close(n)
