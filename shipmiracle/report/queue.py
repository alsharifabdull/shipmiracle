"""The summary queue (spec section 6). The engine writes reports with no model; the one free-text line `Summary: pending` of a CR report is
filled later by a small model, through the guard job `report_summaries` (shipmiracle.guard.jobs; interval 5 min, budget 120 s, one per tick, at most
20 a day, only when guard.jobs is on and the battery is not low).

Queue: <state>/v1/report-queue/<id>/{facts.json, job.json}, 0700/0600, kept 7 days. The model gets the facts inline on stdin and NO tools at all
(`--tools ""`, an empty agent tool list, the golden runner's deny list and settings flags; cwd = a fresh empty temp folder, minimal environment,
SHIPMIRACLE_QUIET=1); facts.json stays in the queue folder only for the acceptance check. Its answer is accepted only when it is 1-3 lines, has no hedging word and every number in it
appears in facts.json as written (the golden grader's own function, shipmiracle.report.golden_util.facts_subset). Anything else, a timeout, a missing
claude: the job stays pending (3 tries); after 3 tries or 24 hours the line becomes `Summary: not generated`. Nothing here blocks or raises
into the engine or the guard loop (`job()` swallows everything and returns a short outcome)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .. import SafetyError, SchemaError, UsageError, config, paths, state
from . import BANNED, clean, golden_util, lint

DAILY_CAP = 20
MAX_TRIES = 3
EXPIRE_S = 24 * 3600
KEEP_S = 7 * 86400
TIMEOUT_S = 100
PROMPT = ("The facts are the JSON on standard input. Summarise them for the owner in at most 3 lines, then the DoD block. "
          "Do not add anything that is not in the facts. Write no links, URLs or images.")
PENDING = "\nSummary: pending\n"
NOT_GENERATED = "\nSummary: not generated\n"


def _qdir(base=None) -> Path:
    b = Path(base) if base is not None else paths.state_dir()
    paths.assert_isolated(b)
    return state.ensure_dir(state.ensure_root(b) / "report-queue")


def _jobs(base=None):
    """[(created, folder, job dict)] oldest first; damaged entries are skipped."""
    q = Path(base) if base is not None else paths.state_dir()
    q = q / "v1" / "report-queue"
    out = []
    try:
        names = sorted(os.listdir(str(q)))
    except OSError:
        return out
    for n in names:
        d = q / n
        try:
            j = json.loads(state.read_bytes_nofollow(d / "job.json").decode("utf-8"))
        except Exception:
            continue
        if isinstance(j, dict) and j.get("v") == 1 and isinstance(j.get("created"), (int, float)) and isinstance(j.get("report"), str):
            out.append((j["created"], d, j))
    out.sort(key=lambda t: t[0])
    return out


def has_pending(base=None) -> bool:
    return any(j.get("status") == "pending" for _c, _d, j in _jobs(base))


def slim(facts) -> dict:
    """The part of the facts the model may summarise (small, flat: every number in it is a fact)."""
    cr = facts["cr"]
    return {"project": facts["project"], "cr": cr["id"], "title": cr["title"], "lane": cr["lane"], "status": cr["status"],
            "verified": cr["verified"], "stages": {s["label"]: str(s["status"]) for s in facts["stages"] if s["id"] != "learn"},
            "verdicts": [{"stage": v["stage"], "verdict": v["verdict"], "attempt": v["attempt"], "counts": v.get("counts"), "evidence": v.get("evidence")}
                         for v in facts["verdicts"][-6:]],
            "files_changed": facts["git"].get("files_total", 0), "commits": len(facts["git"].get("commits") or []), "pushed": facts["git"].get("pushed", False),
            "owner_waits": facts["owner_waits"]["n"], "auto_decisions": len(facts["auto_decisions"]), "wall_minutes": facts["wall_s"] // 60}


def enqueue(project_dir, report_path, facts, base=None, now=None) -> str:
    now = int(time.time()) if now is None else int(now)
    root = _qdir(base)
    jid = "%s-%d-%s" % (facts["cr"]["id"], now, uuid.uuid4().hex[:6])
    d = state.ensure_dir(root / jid)
    state.atomic_write(d / "facts.json", (json.dumps(slim(facts), ensure_ascii=False, indent=1) + "\n").encode("utf-8"), 0o600)
    job = {"v": 1, "id": jid, "project_dir": os.path.realpath(str(project_dir)), "report": os.path.realpath(str(report_path)), "created": now,
           "status": "pending", "tries": 0, "done_ts": None, "why": None}
    state.atomic_write(d / "job.json", (json.dumps(job, sort_keys=True) + "\n").encode("utf-8"), 0o600)
    return jid


def _save(d, job):
    state.atomic_write(d / "job.json", (json.dumps(job, sort_keys=True) + "\n").encode("utf-8"), 0o600)


# ------------------------------------------------------------------ the golden helpers (shipmiracle.report.golden_util, shared with the golden runner)

def _load_golden():
    return golden_util, Path(__file__).resolve().parent.parent.parent


def claude_cmd() -> str:
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_GOLDEN_CLAUDE"):
        return os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"]
    return shutil.which("claude", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + str(Path.home() / ".local" / "bin")) or "claude"


def build_cmd(g, ajson):
    """argv of the reporter run: the golden runner's hardening (the golden runner's build_cmd: --setting-sources project,local, --strict-mcp-config, permission
    mode, the deny list) and no tools at all: `--tools ""` plus an empty tool list in the agent; the facts arrive on stdin."""
    for a in ajson.values():
        a["tools"] = []
        a["prompt"] = "The facts JSON is your input (standard input). You have no tools and cannot read files; do not try.\n\n" + str(a.get("prompt") or "")
    return [claude_cmd(), "-p", PROMPT, "--agent", "reporter", "--agents", json.dumps(ajson), "--setting-sources", "project,local", "--strict-mcp-config",
            "--output-format", "json", "--permission-mode", "acceptEdits", "--tools", "", "--disallowedTools", ",".join(g.DENY), "--max-turns", "5"]


def _ask(qdir):
    """Run the reporter on the queue folder's facts. -> (text, error text or None)."""
    import tempfile
    g, ws = _load_golden()
    try:
        stored = config.load().get("reporter.model")        # only an explicit owner value overrides the model the agent file pins
    except SchemaError:
        stored = None
    ajson, _fm = g.agents_json(str(ws), "reporter", model=stored if stored in ("haiku", "sonnet", "opus") else None)
    cmd = build_cmd(g, ajson)
    env = g.minimal_env()
    env["SHIPMIRACLE_QUIET"] = "1"
    try:
        facts = state.read_bytes_nofollow(Path(qdir) / "facts.json")
    except (OSError, SafetyError, SchemaError):
        return None, "no facts"
    cwd = tempfile.mkdtemp(prefix="shipmiracle-reporter-")
    try:
        p = subprocess.run(cmd, cwd=cwd, input=facts.decode("utf-8", "replace"), capture_output=True, text=True, timeout=TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as e:
        return None, "cannot start claude (%s)" % type(e).__name__
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return None, "unparseable output (exit %d)" % p.returncode
    if isinstance(data, list):
        data = next((x for x in reversed(data) if isinstance(x, dict) and x.get("type") == "result"), {})
    if not isinstance(data, dict) or data.get("is_error") or not isinstance(data.get("result"), str):
        return None, "model error"
    return data["result"], None


def accept(text, qdir):
    """-> (summary lines or None, reason). The golden grader's rules: <= 3 lines, every number in facts.json; plus no hedging word."""
    g, _ws = _load_golden()
    lines = [clean(x, 240) for x in g.summary_lines(text)]
    lines = [x for x in lines if x]
    if not lines:
        return None, "no summary lines"
    ok, why = g.facts_subset(text, str(qdir), {"file": "facts.json", "max_lines": 3})
    if not ok:
        return None, why
    if any(BANNED.search(x) for x in lines):
        return None, "hedging wording"
    if any(lint.LINK.search(x) for x in lines):
        return None, "link or image in the summary"
    return lines, ""


def _replace(job, new_line_block, base=None):
    """Swap `Summary: pending` in the report. True when done. The report must be a regular file we own inside <project>/docs/reports."""
    rp = Path(job["report"])
    root = os.path.join(os.path.realpath(job["project_dir"]), "docs", "reports")
    if os.path.dirname(os.path.realpath(str(rp))) != os.path.realpath(root) or os.path.islink(str(rp)):
        raise SafetyError("report path is outside docs/reports")
    raw = state.read_bytes_nofollow(rp).decode("utf-8")
    if PENDING not in raw:
        return False
    new = raw.replace(PENDING, "\nSummary: " + new_line_block + "\n", 1)
    if lint.lint_text(new):
        raise UsageError("the summary would break the report format")
    state.atomic_write(rp, new.encode("utf-8"), 0o644)
    _record_sha(job, new.encode("utf-8"), base)
    return True


def _record_sha(job, body, base) -> None:
    """The queue edited a report the engine wrote: log the new content sha so the stage module still accepts the file (best effort)."""
    try:
        import hashlib
        from ..playbook import engine, store
        m = re.match(r"(CR-\d{3,6})-", job.get("id") or "")
        pd = os.path.realpath(job["project_dir"])
        rel = os.path.relpath(os.path.realpath(job["report"]), pd)
        if m:
            store.transact(pd, lambda w: (None, engine.record_report(w, m.group(1), rel[:80], {"kind": "report_written", "by": "engine", "ts": int(time.time())},
                                                                      sha=hashlib.sha256(body).hexdigest())), base)
    except Exception:
        pass


def run_one(base=None, now=None, ask=None) -> dict:
    """Process at most one pending job. -> {"job", "outcome": done|retry|not_generated|capped|idle, "why"}. `ask(qdir) -> (text, err)` is a test seam."""
    now = int(time.time()) if now is None else int(now)
    jobs = _jobs(base)
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    done_today = sum(1 for _c, _d, j in jobs if j.get("done_ts") and time.strftime("%Y-%m-%d", time.localtime(j["done_ts"])) == today)
    for created, d, job in jobs:
        if job.get("status") != "pending":
            continue
        if now - created > EXPIRE_S:
            return _give_up(base, d, job, now, "older than 24 hours")
        if done_today >= DAILY_CAP:
            return {"job": job["id"], "outcome": "capped", "why": "%d summaries today" % done_today}
        try:
            if config.get("reporter.model") == "off":        # shipm switch reporter.model off: reports stay script-only
                return _give_up(base, d, job, now, "reporter.model is off")
        except (SchemaError, UsageError):
            pass
        text, err = (ask or _ask)(d)
        lines, why = (None, err) if err else accept(text, d)
        if lines is None:
            job["tries"] = int(job.get("tries", 0)) + 1
            job["why"] = clean(why, 120)
            if job["tries"] >= MAX_TRIES:
                return _give_up(base, d, job, now, why)
            _save(d, job)
            return {"job": job["id"], "outcome": "retry", "why": why}
        try:
            _replace(job, "\n  ".join(lines), base)
        except (OSError, SafetyError, SchemaError, UsageError) as e:
            job["tries"] = int(job.get("tries", 0)) + 1
            job["why"] = clean(str(e), 120)
            if job["tries"] >= MAX_TRIES:
                return _give_up(base, d, job, now, str(e))
            _save(d, job)
            return {"job": job["id"], "outcome": "retry", "why": str(e)}
        job.update(status="done", done_ts=now, why=None)
        _save(d, job)
        return {"job": job["id"], "outcome": "done", "why": ""}
    return {"job": None, "outcome": "idle", "why": ""}


def _give_up(base, d, job, now, why):
    try:
        _replace(job, "not generated")
    except Exception:
        pass
    job.update(status="failed", done_ts=now, why=clean(why, 120))
    try:
        _save(d, job)
    except Exception:
        pass
    return {"job": job["id"], "outcome": "not_generated", "why": clean(why, 120)}


def prune(base=None, now=None) -> int:
    now = time.time() if now is None else now
    n = 0
    for created, d, _j in _jobs(base):
        if now - created > KEEP_S:
            shutil.rmtree(str(d), ignore_errors=True)
            n += 1
    return n


def job():
    """The guard job: never raises, returns a short word for the log."""
    try:
        prune()
        return run_one()["outcome"]
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return "error:" + type(e).__name__
