#!/usr/bin/env python3
"""Promotion counter (CHECKLIST G8): shipmiracle/usage.py + bin/promote-agent --candidates/--daily-line. Fake transcripts (shapes observed in real Claude
transcripts: assistant message content block {type: tool_use, name: Agent|Task, input: {subagent_type}} and {name: Skill, input: {skill}}; synthetic content only)
and fake projects with .agents/borrowed.json. Full isolation through tests/shipmiracle_isolation.py.
Run: python3 tests/promote_candidates_test.py"""
import json, os, pathlib, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMP = ISO.isolated_env(ws=ROOT)
TMP = pathlib.Path(TMP)
os.environ.update(ENV)
ENV.pop("CLAUDECODE", None)
from shipmiracle import usage  # noqa: E402

fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:600])); fails += 0 if c else 1

HOME = pathlib.Path(ENV["SHIPMIRACLE_HOME"]); DEV = pathlib.Path(ENV["SHIPMIRACLE_DEV"]); STATE = pathlib.Path(ENV["SHIPMIRACLE_STATE"])
TR = HOME / ".claude" / "projects"
CACHE = STATE / "usage-counts.json"
n_files = [0]

def line(kind, name, field=None):
    if kind == "agent":
        blk = {"type": "tool_use", "id": "toolu_x", "name": "Agent", "input": {"description": "d", "prompt": "p", "subagent_type": name}}
    elif kind == "task":
        blk = {"type": "tool_use", "id": "toolu_x", "name": "Task", "input": {"description": "d", "prompt": "p", "subagent_type": name}}
    elif kind == "skill":
        blk = {"type": "tool_use", "id": "toolu_x", "name": "Skill", "input": {"skill": name}}
    else:
        blk = {"type": "tool_use", "id": "toolu_x", "name": "Skill", "input": {"args": "a b", "skill": name}}
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [blk]}}, separators=(",", ":"))

def transcript(lines, sub="-p1", name=None):
    n_files[0] += 1
    d = TR / sub; d.mkdir(parents=True, exist_ok=True)
    f = d / (name or "s%d.jsonl" % n_files[0])
    f.write_text("\n".join(lines) + "\n")
    return f

def reset():
    shutil.rmtree(TR, ignore_errors=True); shutil.rmtree(DEV, ignore_errors=True); DEV.mkdir(parents=True)
    if CACHE.exists(): CACHE.unlink()

def project(name, agents=(), skills=(), borrowed=None, raw=None):
    p = DEV / name; (p / ".claude/agents").mkdir(parents=True, exist_ok=True)
    for a in agents: (p / ".claude/agents" / (a + ".md")).write_text("---\nname: %s\ndescription: x\n---\n" % a)
    for s in skills:
        (p / ".agents/skills" / s).mkdir(parents=True, exist_ok=True); (p / ".agents/skills" / s / "SKILL.md").write_text("x")
    if borrowed is not None or raw is not None:
        (p / ".agents").mkdir(exist_ok=True)
        (p / ".agents/borrowed.json").write_text(raw if raw is not None else json.dumps({"entries": borrowed}))
        for e in (borrowed or []):
            dd = p / e["dest"]
            if "\n" not in e["dest"] and not dd.exists(): dd.parent.mkdir(parents=True, exist_ok=True); dd.write_text("x")
    return p

def entry(eid, kind, dest, sha="a" * 64):
    return {"id": eid, "kind": kind, "dest": dest, "source": {"repo": "r", "sha256": sha}, "ours_sha256": "b" * 64, "borrowed": "2026-10-23", "reason": "r", "risk_flags": [], "by": "lead", "note": "n"}

def cand(**kw):
    return usage.candidates(ws=ROOT, dev=DEV, projects_dir=TR, cache_path=CACHE, **kw)

def row(res, name):
    return next((r for r in res["rows"] if r["name"] == name), None)

# ---- thresholds: ONE place
check("thresholds are the existing constants (10 calls, 2 projects)", usage.PROMOTE_CALLS == 10 and usage.PROMOTE_PROJECTS == 2)
src_all = "".join((ROOT / f).read_text() for f in ("bin/promote-agent", "bin/daily"))
check("the thresholds are not repeated in bin/promote-agent or bin/daily", "PROMOTE_CALLS" in src_all and ">= 10" not in src_all and ">=10" not in src_all)

# ---- calls: 9 vs 10, 1 vs 2 projects, Agent and Task, skills
reset()
project("p1", agents=["nine", "ten", "twoproj"], skills=["skl"]); project("p2", agents=["twoproj"])
transcript([line("agent", "nine")] * 9 + [line("agent", "ten")] * 5 + [line("task", "ten")] * 5 + [line("skill", "skl")] * 4 + [line("skillargs", "skl")] * 6)
r = cand()
check("9 calls: not a candidate", row(r, "nine")["calls"] == 9 and not row(r, "nine")["qualifies"], row(r, "nine"))
check("10 calls (Agent + Task blocks): candidate, 'called 10x'", row(r, "ten")["calls"] == 10 and row(r, "ten")["qualifies"] and "called 10x" in row(r, "ten")["why"], row(r, "ten"))
check("1 project, 0 calls: not a candidate; 2 projects: candidate 'in 2 projects'", not row(r, "nine")["qualifies"] and row(r, "twoproj")["qualifies"] and "in 2 projects" in row(r, "twoproj")["why"], row(r, "twoproj"))
check("Skill tool calls counted by skill name (with and without args), project-only skill row kind=skill", row(r, "skl")["kind"] == "skill" and row(r, "skl")["calls"] == 10 and row(r, "skl")["qualifies"], row(r, "skl"))
check("a master agent and a built-in are never candidates", row(r, "engineer") is None and row(r, "Explore") is None)

# ---- borrowed marker and rename via --as across projects
reset()
SRC = "catalog:agent:db-helper"
project("p1", agents=["db-helper"], borrowed=[entry(SRC, "agent", ".claude/agents/db-helper.md", "c" * 64)])
project("p2", agents=["data-pal"], borrowed=[entry(SRC, "agent", ".claude/agents/data-pal.md", "c" * 64)])
project("p3", agents=["lonely"])
transcript([line("agent", "db-helper")] * 3 + [line("agent", "data-pal")] * 4 + [line("agent", "lonely")] * 2)
r = cand()
b = row(r, "data-pal") or row(r, "db-helper")
check("same source renamed with --as in two projects is ONE row in 2 projects", len([x for x in r["rows"] if x["borrowed_from"] == SRC]) == 1 and b and b["projects"] == ["p1", "p2"], r["rows"])
check("calls add up across the two names (3 + 4)", b["calls"] == 7 and sorted([b["name"]] + b["also"]) == ["data-pal", "db-helper"], b)
check("it qualifies (2 projects) and is marked borrowed from the source id", b["qualifies"] and b["borrowed_from"] == SRC, b)
check("a plain project-only agent in one project is not borrowed", row(r, "lonely")["borrowed_from"] is None and not row(r, "lonely")["qualifies"])
check("Borrowed items counter = entries over all projects", r["borrowed"] == 2, r["borrowed"])
tab = usage.render_table(r)
check("table says 'borrowed (inspired by <source id>)'", "borrowed (inspired by %s)" % SRC in tab, tab)
dl = usage.daily_line(r)
check("daily line: plain words, count, candidate with projects, calls, source, owner decides", dl.startswith("Borrowed items: 2. Promotion candidates: ") and "(2 projects, called 7 times, borrowed from %s)" % SRC in dl and dl.endswith("owner decides: bin/promote-agent <dir> <name>"), dl)
# by sha when the id differs
reset()
project("p1", agents=["x1"], borrowed=[entry("catalog:agent:one", "agent", ".claude/agents/x1.md", "d" * 64)])
project("p2", agents=["x2"], borrowed=[entry("catalog:agent:other-id", "agent", ".claude/agents/x2.md", "d" * 64)])
r = cand()
check("same source sha under two ids groups as one row", len([x for x in r["rows"] if x["borrowed_from"]]) == 1 and r["rows"][0]["qualifies"], r["rows"])
# a borrowed item whose file is gone still counts as borrowed; skill dest form
reset()
project("p1", borrowed=[entry("catalog:skill:tdd", "skill", ".agents/skills/tdd/SKILL.md")]); project("p2", borrowed=[entry("catalog:skill:tdd", "skill", ".agents/skills/tdd-mine/SKILL.md")])
transcript([line("skill", "tdd")] * 2 + [line("skill", "tdd-mine")] * 8)
r = cand()
check("borrowed skill dest folder name is the skill name; skill calls added across the two names", r["rows"] and r["rows"][0]["kind"] == "skill" and r["rows"][0]["calls"] == 10 and r["rows"][0]["qualifies"], r["rows"])
# nothing to say
reset(); project("p1", agents=["a"])
r = cand()
check("nothing borrowed and no candidate: the daily line is empty", usage.daily_line(r) == "", usage.daily_line(r))
reset(); project("p1", agents=["a"], borrowed=[entry("catalog:agent:a", "agent", ".claude/agents/a.md")])
check("borrowed but not a candidate: line says so in plain words", usage.daily_line(cand()) == "Borrowed items: 1. No promotion candidates yet.", usage.daily_line(cand()))

# ---- hostile borrowed.json
reset()
project("g1", agents=["a1"], raw="}{ not json"); project("g2", agents=["a2"], raw="[" * 100000); project("g3", agents=["a3"], raw='{"entries": "x"}')
project("g4", agents=["a4"], raw=json.dumps({"entries": [1, None, "s", {"id": 5, "kind": "agent", "dest": 7}, {"id": "catalog:agent:../..", "kind": "agent", "dest": "../../etc/passwd"}]}))
project("g5", agents=["a5"], raw="x" * (usage.MAX_RECORD + 10))
p6 = project("g6", agents=["a6"]); (p6 / ".agents").mkdir(); os.symlink(str(TMP / "nothing"), p6 / ".agents/borrowed.json")
(TMP / "real.json").write_text(json.dumps({"entries": [entry("catalog:agent:evil", "agent", ".claude/agents/a7.md")]}))
p7 = project("g7", agents=["a7"]); (p7 / ".agents").mkdir(); os.symlink(str(TMP / "real.json"), p7 / ".agents/borrowed.json")
p8 = project("g8x", agents=["a8"]); (p8 / ".agents").mkdir(); os.mkfifo(str(p8 / ".agents/borrowed.json"))
t0 = time.time()
try:
    r = cand(); ok = True
except Exception as e:
    r, ok = None, repr(e)
check("garbage / huge / deeply nested / symlinked / FIFO borrowed.json: ignored, no crash, no hang", ok is True and time.time() - t0 < 10 and r["borrowed"] == 0, ok)
check("a symlinked borrowed.json is not followed (its entry is not counted)", r is not None and not any(x["borrowed_from"] for x in r["rows"]))
check("the agents of those projects are still listed (plain project-only rows)", r is not None and all(row(r, n) for n in ("a1", "a2", "a5", "a8")))

# ---- scope: only the owner's own projects folder
reset()
OUT = TMP / "outside"; (OUT / ".claude/agents").mkdir(parents=True); (OUT / ".claude/agents/ghost.md").write_text("x"); (OUT / ".agents").mkdir()
(OUT / ".agents/borrowed.json").write_text(json.dumps({"entries": [entry("catalog:agent:ghost", "agent", ".claude/agents/ghost.md")]}))
os.symlink(str(OUT), DEV / "linked")
(HOME / "Developer" / "decoy" / ".claude/agents").mkdir(parents=True, exist_ok=True); (HOME / "Developer/decoy/.claude/agents/decoy.md").write_text("x")
project("AI-Workspace", agents=["wsagent"]); project("p1", agents=["real"])
r = cand()
check("a symlinked project folder, the workspace folder and folders outside the projects folder are not read", [x["name"] for x in r["rows"]] == ["real"] and r["borrowed"] == 0, r["rows"])

# ---- cache: reuse, change, version
reset(); project("p1", agents=["foo"])
f1 = transcript([line("agent", "foo")] * 3); f2 = transcript([line("agent", "foo")] * 4, sub="-p2")
s1 = usage.scan_transcripts(TR, 20, CACHE)
check("first scan reads both transcripts", s1["read"] == 2 and s1["agents"]["foo"] == 7 and not s1["partial"], s1)
s2 = usage.scan_transcripts(TR, 20, CACHE)
check("second run reads 0 transcripts (served from the cache), same totals", s2["read"] == 0 and s2["cached"] == 2 and s2["agents"]["foo"] == 7, s2)
f1.write_text("\n".join([line("agent", "foo")] * 5) + "\n")
s3 = usage.scan_transcripts(TR, 20, CACHE)
check("a changed transcript is re-read (only that one) and the total follows", s3["read"] == 1 and s3["agents"]["foo"] == 9, s3)
# same size, same second, different content: size equal but mtime moved by utime
f2.write_text("\n".join([line("agent", "foo")] * 2 + [line("agent", "bar")] * 2) + "\n"); os.utime(f2, (time.time() + 5, time.time() + 5))
s4 = usage.scan_transcripts(TR, 20, CACHE)
check("a rewritten transcript (new mtime) is re-read", s4["read"] == 1 and s4["agents"]["bar"] == 2, s4)
d = json.loads(CACHE.read_text()); d["v"] = usage.USAGE_CACHE_V + 1; CACHE.write_text(json.dumps(d))
s5 = usage.scan_transcripts(TR, 20, CACHE)
check("a cache with another version number is ignored (everything re-read)", s5["read"] == 2, s5)
CACHE.write_text("[" * 50000)
s6 = usage.scan_transcripts(TR, 20, CACHE)
check("a damaged / deeply nested cache file is ignored (everything re-read, no crash)", s6["read"] == 2, s6)
import stat as _st
check("the cache file is private (0600) and holds no file paths beyond relative names", _st.S_IMODE(os.stat(CACHE).st_mode) == 0o600 and str(TR) not in CACHE.read_text())
f2.unlink()
s7 = usage.scan_transcripts(TR, 20, CACHE)
check("a deleted transcript drops out of the totals and the cache", s7["agents"]["foo"] == 5 and "bar" not in s7["agents"], s7)

# ---- time budget
reset(); project("p1", agents=["foo"])
for i in range(6): transcript([line("agent", "foo")] * 2, sub="-p%d" % i)
sp = usage.scan_transcripts(TR, 0, CACHE)
check("a zero time budget returns at once, flagged partial, nothing read", sp["partial"] and sp["read"] == 0, sp)
rp = cand(budget_s=0)
check("candidates carry the partial flag; the table and the daily line say so", rp["partial"] and "partial" in usage.render_table(rp) and "(counts partial)" in usage.daily_line(dict(rp, borrowed=1)), usage.render_table(rp))
sf = usage.scan_transcripts(TR, 20, CACHE)
check("the next run with time finishes (not partial) with the full count", not sf["partial"] and sf["agents"]["foo"] == 12, sf)
# mid-file: a deadline that passes while reading a big file leaves it uncached
reset(); big = transcript([line("agent", "foo")] * 1000 + ["x" * 1000] * 30000)
orig_time = usage.time.time; calls = [0]
def fake_time():
    calls[0] += 1
    return orig_time() + (1000 if calls[0] > 6 else 0)
usage.time.time = fake_time
try: sm = usage.scan_transcripts(TR, 5, CACHE)
finally: usage.time.time = orig_time
cf = json.loads(CACHE.read_text()).get("files", {}) if CACHE.exists() else {}
check("the budget is also checked inside a big file: partial, the unfinished file is not cached as finished", sm["partial"] and ("-p1/" + big.name) not in cf, (sm, list(cf)))

# ---- hostile transcripts
reset(); project("p1", agents=["foo"])
d = TR / "-hostile"; d.mkdir(parents=True)
(d / "huge.jsonl").write_bytes(b"a" * (usage.MAX_LINE + 1000) + b"\n" + line("agent", "foo").encode() + b"\n")
(d / "badjson.jsonl").write_text("{{{ nope\n" + line("agent", "foo") + "\n\x00\x01\n")
(d / "binary.jsonl").write_bytes(os.urandom(300000) + b"\n" + line("agent", "foo").encode() + b"\n")
(d / "nested.jsonl").write_text('{"a":' * 200000 + "1" + "}" * 200000 + "\n" + line("agent", "foo") + "\n")
(TMP / "outside.jsonl").write_text(line("agent", "foo") * 5 + "\n")
os.symlink(str(TMP / "outside.jsonl"), d / "link.jsonl")
OD = TMP / "outdir"; OD.mkdir(); (OD / "x.jsonl").write_text(line("agent", "foo") + "\n"); os.symlink(str(OD), TR / "-linkdir")
t0 = time.time()
try:
    sh = usage.scan_transcripts(TR, 30, CACHE); ok = True
except Exception as e:
    sh, ok = None, repr(e)
check("hostile transcripts (huge line, invalid JSON, binary, deeply nested, FIFO, symlinks) do not crash or hang", ok is True and time.time() - t0 < 25, ok)
check("valid lines after the bad ones are still counted (4 files x 1); the FIFO, the symlinked file and the symlinked folder are not read", sh is not None and sh["agents"]["foo"] == 4 and sh["files"] == 4, sh)
# FIFOs in a subprocess with a 5 s timeout (a regression that opens a FIFO blocking fails in 5 s instead of hanging the suite)
def fifo_scan(writer):
    base = TMP / ("fifo-%s" % writer); shutil.rmtree(base, ignore_errors=True); (base / "-p").mkdir(parents=True)
    os.mkfifo(str(base / "-p/fifo.jsonl")); (base / "-p/ok.jsonl").write_text(line("agent", "foo") + "\n")
    code = ("import os,sys,json\nsys.path.insert(0,%r)\nfrom shipmiracle import usage\n" % str(ROOT)
            + ("fd=os.open(%r,os.O_RDWR|os.O_NONBLOCK)\n" % str(base / "-p/fifo.jsonl") if writer else "")
            + "r=usage.scan_transcripts(%r,3,%r)\nprint(json.dumps([r['agents']['foo'],r['files']]))\n" % (str(base), str(base / "c.json")))
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        o, e = p.communicate(timeout=5); return o.strip(), e
    except subprocess.TimeoutExpired:
        import signal; os.killpg(p.pid, signal.SIGKILL); p.communicate(); return "TIMEOUT", ""
o, e = fifo_scan(False)
check("a FIFO named *.jsonl without a writer is skipped at once (5 s subprocess limit); the plain file still counts", o == "[1, 1]", (o, e))
o, e = fifo_scan(True)
check("a FIFO with an open writer does not block the scan either (5 s subprocess limit)", o == "[1, 1]", (o, e))
# names: long / odd names are capped or skipped
transcript([line("agent", "n" * 300), '"subagent_type":"has\\"quote"', line("agent", "ok-name")], sub="-odd")
so = usage.scan_transcripts(TR, 30, CACHE)
check("a 300-character name is not counted (cap 80); a normal name is", "n" * 300 not in so["agents"] and so["agents"]["ok-name"] == 1, list(so["agents"])[:5])

# ---- escaping: control and bidi characters
reset()
bad = "evil‮agent"; nl = "x\ny"
p = project("p1", borrowed=[entry("catalog:agent:ev‮il\x1b[31m\nFAIL ", "agent", ".claude/agents/a.md"), entry("catalog:agent:ok", "agent", ".claude/agents/b\n.md")])
(p / ".claude/agents/z‮z.md").write_text("x"); (p / ".claude/agents/tab\there.md").write_text("x")
project("p2", borrowed=[entry("catalog:agent:ev‮il\x1b[31m\nFAIL ", "agent", ".claude/agents/a.md")])
transcript([line("agent", "a")] * 12)
r = cand()
tab, dl = usage.render_table(r), usage.daily_line(r)
bad_chars = [c for c in tab + dl if (ord(c) < 32 and c != "\n") or c in "‮​\x1b\x7f"]
check("control, escape and bidi characters never reach the table or the daily line", not bad_chars and "\\u202e" in tab + dl and "\\u001b" in tab + dl, (tab + dl)[:400])
check("the daily line is a single line", "\n" not in dl and dl, repr(dl))
check("a name with a newline or bidi char in a file name is not listed at all", not any("‮" in x["name"] or "\n" in x["name"] for x in r["rows"]))
check("esc() escapes a lone surrogate-free format char and cuts long text", usage.esc("a​b") == "a\\u200bb" and usage.esc("z" * 500).endswith("...") and len(usage.esc("z" * 500)) < 100)

# ---- D1: data can never look like a status row (bin/daily counts ' FAIL ' and ' warn ' over the whole log)
reset()
EV = "catalog:agent:q FAIL x warn y WARN z fail"
project("p1", agents=["fail-agent"], borrowed=[entry(EV, "agent", ".claude/agents/q.md")]); project("p2", agents=["fail-agent"], borrowed=[entry(EV, "agent", ".claude/agents/q.md")])
transcript([line("agent", "q")] * 12)
r = cand(); out = usage.render_table(r) + "\n" + usage.daily_line(r)
import re as _re
check("ids and names containing FAIL / warn (any case) are broken in the table and the daily line", not _re.search(r"(?i)fail|warn", out) and "F*AIL" in out and "w*arn" in out, out)
check("esc() leaves ordinary words alone", usage.esc("db-helper") == "db-helper" and usage.esc("failover-agent") == "f*ailover-agent")
check("the fixed wording of the table and the line has no FAIL / warn of its own", not _re.search(r"(?i)\bfail|\bwarn", usage.render_table(dict(r, rows=[]))) and not _re.search(r"(?i)fail|warn", usage.daily_line(dict(r, partial=True))))

# ---- D5: a built-in name used as a project agent: its calls are not counted
reset(); project("p1", agents=["Explore"]); transcript([line("agent", "Explore")] * 12)
r = cand()
check("a project agent named like a built-in (Explore) with 12 calls reports calls=0 and is not a candidate", row(r, "Explore")["calls"] == 0 and not row(r, "Explore")["qualifies"], row(r, "Explore"))

# ---- nested transcripts: the old depth (<project>/*.jsonl) only, unless asked
reset(); project("p1", agents=["foo"])
transcript([line("agent", "foo")] * 2, sub="-p1")
nd = TR / "-p1" / "sess-1" / "subagents"; nd.mkdir(parents=True); (nd / "agent-1.jsonl").write_text(line("agent", "foo") + "\n")
(TR / "stray.jsonl").write_text(line("agent", "foo") + "\n")
s = usage.scan_transcripts(TR, 20, CACHE)
check("only <project>/*.jsonl is read by default (nested subagent transcripts and stray root files are not)", s["agents"]["foo"] == 2 and s["files"] == 1, s)
s = usage.scan_transcripts(TR, 20, CACHE, nested=True)
check("nested=True also reads <project>/<session>/subagents/*.jsonl", s["agents"]["foo"] == 4, s)

# ---- recorded vs in use
reset()
project("p1", agents=["here"], borrowed=[entry("catalog:agent:here", "agent", ".claude/agents/here.md"), entry("catalog:agent:gone", "agent", ".claude/agents/gone.md")])
os.unlink(DEV / "p1/.claude/agents/gone.md")
r = cand()
check("a record whose file is gone is not counted as a borrowed item in use, and the line says how many are recorded", r["borrowed"] == 1 and r["recorded"] == 2 and "Borrowed items: 1 (1 more recorded, file gone)." in usage.daily_line(r), (r["borrowed"], usage.daily_line(r)))
check("a gone record does not make a project count for its source", not any(x["borrowed_from"] == "catalog:agent:gone" for x in r["rows"]))

# ---- D4: speed on short lines, and resume inside one big file
reset(); project("p1", agents=["foo"])
sl = (line("agent", "foo") + "\n").encode()
shortf = TR / "-p1" / "short.jsonl"; shortf.parent.mkdir(parents=True)
filler = (b'{"type":"user","message":{"role":"user","content":"' + b"y" * 120 + b'"}}\n')
unit = filler * 500 + sl
with open(shortf, "wb") as fh:
    for _ in range(100 * 1024 * 1024 // len(unit)): fh.write(unit)
t0 = time.time(); ss = usage.scan_transcripts(TR, 60, CACHE); dt = time.time() - t0
check("100 MB of ~190-byte lines is scanned in under 3 s (linear)", dt < 3 and not ss["partial"] and ss["agents"]["foo"] == 100 * 1024 * 1024 // len(unit), (dt, ss["agents"], ss["partial"]))
os.unlink(shortf); CACHE.unlink()
# resume: a deadline in the middle of one file saves offset + counts; next runs continue and finish with the exact total
body = (line("agent", "foo") + "\n").encode() * 3000 + b"z" * 3000 + b"\n"
bigf = TR / "-p1" / "big.jsonl"; bigf.write_bytes(body * 35)      # ~ 20 MB
total = 3000 * 35
orig = usage.time.time
def clock_jump_after(n):
    c = [0]
    def f():
        c[0] += 1
        return orig() + (1000 if c[0] > n else 0)
    return f
def scan_interrupted(n):
    usage.time.time = clock_jump_after(n)
    try: return usage.scan_transcripts(TR, 5, CACHE)
    finally: usage.time.time = orig
runs, res_ = 0, None
while runs < 100:
    runs += 1; res_ = scan_interrupted(12 + 6 * runs)
    if not res_["partial"]: break
check("a file that never fits one budget is finished over several runs (offset resume) with the exact total", res_ and not res_["partial"] and res_["agents"]["foo"] == total and 1 < runs < 100, (runs, res_))
check("the finished file leaves no partial entry behind", json.loads(CACHE.read_text()).get("part") == {}, json.loads(CACHE.read_text()).get("part"))
CACHE.unlink()
sp1 = scan_interrupted(12)
pc = json.loads(CACHE.read_text()).get("part", {})
check("an interrupted scan saves a partial entry (offset > 0, sha256, counts so far)", sp1["partial"] and pc and list(pc.values())[0][0] > 0 and len(list(pc.values())[0][1]) == 64 and sum(list(pc.values())[0][2].values()) > 0, (sp1, pc))
off1 = list(pc.values())[0][0]
sp1b = scan_interrupted(15)
pc2 = json.loads(CACHE.read_text()).get("part", {})
check("the next run continues from the saved offset (it moves forward)", list(pc2.values())[0][0] > off1, (off1, pc2))
# bytes before the saved offset change (same size): the partial entry is dropped and the file is counted from its start
raw = bytearray(bigf.read_bytes()); i0 = raw.index(b'"foo"'); raw[i0 + 1:i0 + 4] = b"bar"; bigf.write_bytes(bytes(raw))
spr = usage.scan_transcripts(TR, 60, CACHE)
check("a rewrite of bytes before the saved offset invalidates the partial entry: exact count of the new content", not spr["partial"] and spr["agents"]["foo"] == total - 1 and spr["agents"]["bar"] == 1, spr["agents"])
# truncated below the saved offset
CACHE.unlink(); bigf.write_bytes(body * 35)
scan_interrupted(12)
bigf.write_bytes(body[:100] + b"\n" + sl)
spt = usage.scan_transcripts(TR, 60, CACHE)
check("a file truncated below the saved offset is counted from its new content only", not spt["partial"] and spt["agents"]["foo"] == 1, spt["agents"])

# ---- CLI: bin/promote-agent --candidates / --daily-line (real script, isolated env)
reset()
project("p1", agents=["cli-one"], borrowed=[entry(SRC, "agent", ".claude/agents/cli-one.md", "e" * 64)]); project("p2", borrowed=[entry(SRC, "agent", ".claude/agents/cli-two.md", "e" * 64)])
transcript([line("agent", "cli-one")] * 11)
def run(*a, extra=None):
    e = dict(ENV, **(extra or {}))
    return subprocess.run([str(ROOT / "bin/promote-agent"), *a], env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
rc = run("--candidates")
check("--candidates prints the table with the borrowed marker, exit 0", rc.returncode == 0 and "cli-one" in rc.stdout and "borrowed (inspired by %s)" % SRC in rc.stdout and "called 11x" in rc.stdout, rc)
rd = run("--daily-line")
check("--daily-line prints the one plain line", rd.returncode == 0 and rd.stdout.startswith("Borrowed items: 2. Promotion candidates: cli-one (2 projects, called 11 times, borrowed from %s)" % SRC) and rd.stdout.count("\n") == 1, rd)
rr = run("--report")
check("--report prints the table and then the summary line from one scan", rr.returncode == 0 and rr.stdout.startswith(rc.stdout.rstrip("\n")) and rr.stdout.rstrip("\n").endswith(rd.stdout.rstrip("\n")), rr)
run_again = run("--daily-line")
check("second CLI run reuses the cache file in the state folder", CACHE.exists() and run_again.stdout == rd.stdout)
rb = run("--candidates", extra={"SHIPMIRACLE_USAGE_BUDGET": "0"})
check("tiny budget through the test seam: partial note, exit 0", rb.returncode == 0 and "partial" in rb.stdout or rb.returncode == 0 and "cached" not in rb.stdout and CACHE.exists(), rb)
rno = run("--daily-line", extra={"SHIPMIRACLE_STATE": str(TMP / "nostate"), "SHIPMIRACLE_DEV": str(TMP / "nodev")})
check("no projects folder: empty line, exit 0", rno.returncode == 0 and rno.stdout == "", rno)
check("promote-agent still ends with the owner step wording (promotion itself unchanged)", "OWNER STEP (not run from here)" in (ROOT / "bin/promote-agent").read_text())
check("bash syntax of bin/promote-agent", subprocess.run(["bash", "-n", str(ROOT / "bin/promote-agent")]).returncode == 0)
check("usage.py and the two scripts carry no private names", not any(w in (ROOT / "shipmiracle/usage.py").read_text() + src_all for w in ("alsharif" + "abdull", "Abdul" + "lah")))

ISO.cleanup(str(TMP))
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
