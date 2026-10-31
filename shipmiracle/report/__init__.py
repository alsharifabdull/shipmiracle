"""The reporter (Platform v2 P5c, spec docs/plans/2026-10-20-p5-spec.md section 6).

Everything here is scripted from facts: `facts.build` reads the change-request log (shipmiracle.playbook.store), the event log and git and returns
one dict; `templates` turns it into the fixed report formats; `lint` checks any report file against those formats; `write` puts files where
the spec says (CR report in the repo, stage reports and digests in the private state dir, index for the panel); `queue` hands the one
free-text line ("Summary:") to a small model through the guard job and accepts the answer only when it adds no number; `panel` is the
read-only data contract the panel reads. No model runs in the engine path, nothing here raises into a hook.

Text hygiene (shared): titles and captured evidence come from users and models. `clean` removes control characters, line/paragraph
separators and bidi overrides (so a line can never split or re-order), keeps Arabic and every other script, and clips."""
from __future__ import annotations

import re
import unicodedata

BANNED = re.compile(r"\b(should work|probably|seems|your call|i think)\b", re.I)
_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))


def clean(s, n=200) -> str:
    """One line of printable text, at most n characters. None/non-text -> ''."""
    if not isinstance(s, str):
        return ""
    out = []
    for c in s:
        cat = unicodedata.category(c)
        if c in "\t\n\r":
            out.append(" ")
        elif cat in ("Cc", "Zl", "Zp") or ord(c) in _BIDI:
            continue
        elif cat == "Cf" and c not in "‎‏؜‍‌":
            continue
        else:
            out.append(c)
    return " ".join("".join(out).split())[:n]


def secret_free(t) -> str:
    """`t`, or '' when the P4 record redaction (shipmiracle.hooks.shadow.red) would change it: a text with a secret shape is withheld, never printed half-redacted."""
    if not t:
        return ""
    try:
        from ..hooks.shadow import red
        return t if red(t) == t else ""
    except Exception:
        return ""


def safe(s, n=200) -> str:
    """clean(), or '' when the text contains a banned phrase (the reports never carry hedging words) or a secret shape: the field is withheld instead."""
    t = clean(s, n)
    return "" if BANNED.search(t) else secret_free(t)
