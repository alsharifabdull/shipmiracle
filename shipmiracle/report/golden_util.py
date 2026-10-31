"""Helpers shared by the golden runner script and shipmiracle.report.queue (the summary reporter): agent file parsing, the facts grader,
the minimal environment and the deny list. They live in the package so that a tree without the runner script can import them."""
from __future__ import annotations

import json
import os
import re


def parse_agent(path):
    """-> (frontmatter dict, body). tools becomes a list; maxTurns an int."""
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n(.*)\Z", txt, re.S)
    if not m:
        raise ValueError("no frontmatter in " + path)
    fm = {}
    for ln in m.group(1).splitlines():
        k, _, v = ln.partition(":")
        if _:
            fm[k.strip()] = v.strip()
    fm["tools"] = [t.strip() for t in fm.get("tools", "").split(",") if t.strip()]
    if fm.get("maxTurns", "").isdigit():
        fm["maxTurns"] = int(fm["maxTurns"])
    return fm, m.group(2).strip()


def agent_name(task_id):
    """'reviewer:risk' -> 'reviewer' (the lens is part of the task, not of the agent file)."""
    return task_id.split(":", 1)[0]


def agent_path(ws, role):
    """agents/claude/<agent>.md (the pre-P3b role files are gone; old names go through ALIASES)."""
    return os.path.join(ws, "agents", "claude", agent_name(role) + ".md")


def agents_json(ws, role, model=None):
    fm, body = parse_agent(agent_path(ws, role))
    name = agent_name(role)
    a = {"description": fm.get("description", role), "prompt": body, "tools": fm["tools"], "model": model or fm.get("model", "sonnet")}
    if isinstance(fm.get("maxTurns"), int):
        a["maxTurns"] = fm["maxTurns"]
    return {name: a}, fm


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(s):
    return {n.replace(",", "") for n in _NUM_RE.findall(s or "")}


def summary_lines(text):
    """The reply before its DoD block (the last 'Result:' line), without blank lines."""
    lines = (text or "").splitlines()
    cut = len(lines)
    for i, ln in enumerate(lines):
        if re.match(r"^\W{0,4}Result\W{0,3}:", ln):
            cut = i
    return [x for x in lines[:cut] if x.strip()]


def facts_subset(text, workdir, spec):
    """At most spec.max_lines summary lines; every number in them appears in the facts file (digits are compared as written: no rounding)."""
    try:
        facts = open(os.path.join(workdir, spec["file"]), errors="ignore").read()
    except OSError:
        return False, "facts file missing"
    lines = summary_lines(text)
    if not lines:
        return False, "no summary lines"
    if len(lines) > spec.get("max_lines", 3):
        return False, "%d summary lines" % len(lines)
    extra = sorted(_numbers("\n".join(lines)) - _numbers(facts))
    return (not extra), ("numbers not in the facts: %s" % extra if extra else "")


def minimal_env(parent=None):
    """PATH, HOME, USER, TERM, LANG only. HOME stays real (claude's login lives there); every other variable (tokens, keys, agent sockets) is dropped."""
    parent = os.environ if parent is None else parent
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "HOME": parent.get("HOME", os.path.expanduser("~")),
           "TERM": parent.get("TERM", "dumb"), "LANG": parent.get("LANG", "en_US.UTF-8")}
    if parent.get("USER"):
        env["USER"] = parent["USER"]            # the macOS keychain login lookup needs it (probed: without USER claude says "Not logged in")
    if os.environ.get("SHIPMIRACLE_GOLDEN_CLAUDE") and parent.get("FAKE_LOG"):     # test hook only: the fake claude's log path
        env["FAKE_LOG"] = parent["FAKE_LOG"]
    return env


DENY = ["WebFetch", "WebSearch"] + ["Bash(%s:*)" % c for c in
        ("curl", "wget", "ssh", "scp", "nc", "git push", "rm -rf", "sudo", "brew", "npm install", "pip install", "pip3 install")]
