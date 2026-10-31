#!/usr/bin/env python3
"""F6 Guided playbook interview, CLI side (panel v3 UX addendum section 2): `shipm playbook interview --short|--long|--resume|--restart`, the progress file, the draft,
`shipm playbook set --from-draft`, the Setup row `describe-work` and the `interview` field of `shipm report panel`. A FAKE claude (SHIPMIRACLE_GOLDEN_CLAUDE, test-only) answers
with canned JSON and records argv, stdin, cwd and environment; the owner's answers come from a scripted file (SHIPMIRACLE_INTERVIEW_INPUT, test-only). No model, no network.
Full isolation through tests/shipmiracle_isolation.py. Run: python3 tests/shipmiracle_interview_test.py"""
import hashlib, json, os, pathlib, subprocess, sys, time, types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMP = ISO.isolated_env()
TMP = pathlib.Path(TMP)
(pathlib.Path(ENV["SHIPMIRACLE_WS"]) / "config").mkdir(parents=True, exist_ok=True)
(pathlib.Path(ENV["SHIPMIRACLE_WS"]) / "config" / "flow.json").write_text('{"default": "strict", "projects": {}}\n')
os.environ.update(ENV)
ENV.pop("CLAUDECODE", None); os.environ.pop("CLAUDECODE", None)
DEV = pathlib.Path(ENV["SHIPMIRACLE_DEV"]); STATE = pathlib.Path(ENV["SHIPMIRACLE_STATE"])
LOG = TMP / "calls.jsonl"; INP = TMP / "input.txt"
FAKE = TMP / "claude-fake"
FAKE.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                'inp = sys.stdin.read()\n'
                'open(%r, "a").write(json.dumps({"argv": sys.argv[1:], "stdin": inp, "cwd": os.getcwd(), "ls": sorted(os.listdir(".")), "env": dict(os.environ)}) + "\\n")\n'
                'if os.path.exists(%r):\n    print(json.dumps({"is_error": True, "result": "x"})); sys.exit(0)\n'
                'rnd = json.loads(inp).get("round", 1)\n'
                'f = %r + "/reply_%%d.json" %% rnd\n'
                'f = f if os.path.exists(f) else %r + "/reply.json"\n'
                'print(json.dumps({"is_error": False, "result": open(f).read(), "usage": {"input_tokens": 11, "output_tokens": 7}}))\n' % (str(LOG), str(TMP / "fail"), str(TMP), str(TMP)))
FAKE.chmod(0o755)

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1

def shipm(*args, extra=None, answers=None, session=False):
    e = dict(ENV); e.update(extra or {})
    e.update(SHIPMIRACLE_GOLDEN_CLAUDE=str(FAKE), GH_TOKEN="ghp_" + "a" * 36, ANTHROPIC_API_KEY="sk-" + "secret")
    if answers is not None:
        INP.write_text("\n".join(x if x != "" else "<ENTER>" for x in answers)); e["SHIPMIRACLE_INTERVIEW_INPUT"] = str(INP)
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, start_new_session=session)
    return r.returncode, r.stdout, r.stderr

def calls():
    return [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []

def reply(d, rnd=None):
    (TMP / ("reply_%d.json" % rnd if rnd else "reply.json")).write_text("Here you go:\n```json\n" + json.dumps(d) + "\n```")

def Q(i, topic, text=None, rec=None, **kw):
    d = {"id": "q%d" % i, "topic": topic, "text": text or "Question about %s number %d?" % (topic, i), "recommended": rec or "Default for %s" % topic, "kind": "ask", "needs": None}
    d.update(kw); return d

def reset():
    for p in list(TMP.glob("reply*.json")) + [LOG, TMP / "fail", INP]:
        p.unlink(missing_ok=True)

def sha(p):
    try:
        return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
    except OSError:
        return None

def mk(name):
    d = DEV / name; d.mkdir(parents=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], env=ENV, check=True)
    (d / "package.json").write_text("{}\n"); (d / "README.md").write_text("# %s\nA coffee recipe site.\n" % name)
    subprocess.run(["git", "-C", str(d), "add", "-A"], env=ENV, check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "init"], env=ENV, check=True)
    return d

STATE.mkdir(parents=True, exist_ok=True)
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {}}))
ALPHA = mk("alpha"); A = str(ALPHA)
REG = pathlib.Path(ENV["SHIPMIRACLE_CONFIG"]) / "registry.json"
def prog(d=ALPHA):
    return json.loads((d / ".shipmiracle" / "playbook.interview.json").read_text())

# ================================================================== Short
reset()
reply({"questions": [Q(1, "work", rec="Sell coffee recipes"), Q(2, "outputs", rec="A web page"), Q(3, "approver", rec="You, before it goes live"), Q(4, "risks"), Q(5, "tools")],
       "proposal": {"type": "software", "risk_paths": ["src/auth/**"]}})
c, o, e = shipm("playbook", "interview", "--short", "--project", A, answers=["", "Recipes for baristas", ""])
check("short: exit 0, three questions only (a fourth and fifth were offered)", c == 0 and "Question 3 of about 3" in o and "Question 4" not in o, (c, o, e))
check("short: one model call; hardened argv: no tools, project/local sources, strict mcp, opus", len(calls()) == 1 and "--tools" in calls()[0]["argv"] and calls()[0]["argv"][calls()[0]["argv"].index("--tools") + 1] == ""
      and "--strict-mcp-config" in calls()[0]["argv"] and "project,local" in calls()[0]["argv"] and '"model": "opus"' in " ".join(calls()[0]["argv"]).replace('"model":"opus"', '"model": "opus"'), calls()[0]["argv"] if calls() else None)
cl = calls()[0]
check("short: the model runs in an empty temp folder with a minimal environment (no tokens)", cl["ls"] == [] and "GH_TOKEN" not in cl["env"] and "ANTHROPIC_API_KEY" not in cl["env"] and str(ALPHA) not in cl["cwd"], cl["cwd"])
pl = json.loads(cl["stdin"])
check("short: stdin is data: facts (files seen), round 1, max 3", pl["round"] == 1 and pl["max_questions"] == 3 and "package.json" in pl["facts"]["files"] and "coffee" in pl["facts"]["readme_head"], pl)
st = prog()
check("short: progress file: draft, 3 answers (accepted, edited, accepted), 2 assumed, mode short, mode 0600", st["status"] == "draft" and st["mode"] == "short" and [a["how"] for a in st["answered"]] == ["accepted", "answer", "accepted"]
      and len(st["assumed"]) == 2 and oct((ALPHA / ".shipmiracle" / "playbook.interview.json").stat().st_mode & 0o777) == "0o600" and st["short_done"] is True, st)
dr = (ALPHA / ".shipmiracle" / "playbook.draft.md").read_text()
check("short: draft has the nine labelled sections, the edited answer, an Assumed list", all(("## " + h) in dr for h in ("Work", "Inputs", "Outputs", "Tools", "Risks", "Who approves", "Definition of done", "Never allowed", "Assumed"))
      and "Recipes for baristas" in dr and "Assumed" in dr and "Sell coffee recipes (assumed)" in dr and "You, before it goes live (assumed)" in dr and "shipmiracle-proposal" in dr, dr)
check("short: the draft hash is stored; nothing trusted was written (no playbook.json, no work.json, registry unchanged)", st["draft_sha"] == sha(ALPHA / ".shipmiracle" / "playbook.draft.md")
      and not (ALPHA / ".shipmiracle" / "playbook.json").exists() and not (ALPHA / ".shipmiracle" / "work.json").exists() and not REG.exists())
p = json.loads(shipm("report", "panel", "--project", A)[1])
check("panel: interview field and the capability flag", p["interview"] == {"status": "draft", "mode": "short", "n": 3, "total": 3, "draft": True} and p["caps"]["interview"] is True, p.get("interview"))
c, o, e = shipm("playbook", "interview", "--short", "--project", A, answers=[""])
check("a finished interview is not started again by accident (exit 2, says what to do)", c == 2 and "--restart" in e and len(calls()) == 1, (c, e))

# ================================================================== from-draft
before_pb = sha(ALPHA / ".shipmiracle" / "playbook.json")
dp = ALPHA / ".shipmiracle" / "playbook.draft.md"
orig = dp.read_text()
dp.write_text(orig + "\nedited by someone\n")
c, o, e = shipm("playbook", "set", "--from-draft", "--project", A, "--allow-open-chat")
check("from-draft: a draft changed after Shipmiracle wrote it is refused (exit 2)", c == 2 and "changed" in e and not (ALPHA / ".shipmiracle" / "playbook.json").exists(), (c, e))
dp.write_text(orig)
c, o, e = shipm("playbook", "set", "--from-draft", "--project", A, extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("from-draft inside a chat is refused (exit 4)", c == 4 and not (ALPHA / ".shipmiracle" / "playbook.json").exists(), (c, e))
c, o, e = shipm("playbook", "set", "--from-draft", "--project", A, "--allow-open-chat")
pbj = json.loads((ALPHA / ".shipmiracle" / "playbook.json").read_text()) if (ALPHA / ".shipmiracle" / "playbook.json").exists() else {}
check("from-draft: applies type and risk_paths (shown first), committed, trusted", c == 0 and "risk_paths" in o and pbj.get("type") == "software" and pbj["overrides"]["risk_paths"] == ["src/auth/**"]
      and pbj["set_by"] == "shipm playbook set --from-draft" and json.loads(shipm("playbook", "show", "--project", A, "--json")[1])["trust"] == "trusted", (c, o, e))
check("from-draft: the interview is done", prog()["status"] == "done" and json.loads(shipm("report", "panel", "--project", A)[1])["interview"]["status"] == "done")
c, o, e = shipm("playbook", "set", "--from-draft", "--project", A, "--allow-open-chat")
check("from-draft again: refused (the interview is no longer waiting)", c == 2, (c, e))
# typed confirmation in process
os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
from shipmiracle.playbook import cli as PB, interview as IV  # noqa: E402
from shipmiracle import SafetyError, UsageError  # noqa: E402
B = mk("bravo"); BS = str(B)
reset()
reply({"questions": [Q(1, "work")], "proposal": {"type": "content"}})
c, o, e = shipm("playbook", "interview", "--short", "--project", BS, answers=[""])
check("setup for typed confirmation: bravo has a draft proposing type content", c == 0 and "type" in (B / ".shipmiracle" / "playbook.draft.md").read_text() and prog(B)["status"] == "draft", (c, e))
ns = types.SimpleNamespace(from_draft=True, project=BS, allow_open_chat=True, rargs=[], json=False)
def refused(fn, *a):
    try:
        fn(*a)
    except SafetyError:
        return True
    except BaseException:
        return False
    return False
PB._tty_ask = lambda prompt: None
check("typed confirmation: no terminal = refused, nothing written", refused(PB.cmd_set, ns) and not (B / ".shipmiracle" / "playbook.json").exists())
PB._tty_ask = lambda prompt: "yes"
check("typed confirmation: a wrong word = refused", refused(PB.cmd_set, ns) and not (B / ".shipmiracle" / "playbook.json").exists())
asked = []
PB._tty_ask = lambda prompt: asked.append(prompt) or "set"
rc = PB.cmd_set(ns)
check("typed confirmation: typing `set` applies it; the prompt names the action", rc == 0 and asked and "from-draft" in asked[0] and json.loads((B / ".shipmiracle" / "playbook.json").read_text())["type"] == "content", asked)
os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)

# ================================================================== question rules
reset()
C = mk("charlie"); CS = str(C)
reply({"questions": [Q(1, "work", rec="x" * 500), Q(2, "inputs", kind="readable"), Q(3, "outputs", kind="feel", text="How should the page look?"), Q(4, "tools", needs="q99"),
                     Q(5, "risks", text="See https://evil.example/x for details?"), Q(6, "never", text="Bad \x1b[31m\u202e text with key sk-ant-api03-" + "A" * 40 + "?"), Q(7, "done"), Q(8, "approver"), "junk", {"topic": "zzz"}]})
c, o, e = shipm("playbook", "interview", "--short", "--project", CS, answers=["", "", ""])
st = prog(C)
check("rules: readable, link, needs-unanswered and junk questions are dropped; a feel question becomes a prototype note", c == 0 and [a["id"] for a in st["answered"]] == ["q1", "q6", "q7"]
      and [x["id"] for x in st["prototype"]] == ["q3"], st)
check("rules: control and bidi characters and secret-shaped text are cleaned; the recommendation is capped", all(len(a["a"]) <= 200 for a in st["answered"]) and "\x1b" not in json.dumps(st) and "\u202e" not in json.dumps(st, ensure_ascii=False) and "sk-ant-api03-A" not in json.dumps(st), st["answered"])
d = (C / ".shipmiracle" / "playbook.draft.md").read_text()
check("rules: the prototype question is listed as assumed in the draft (never guessed silently)", "throwaway prototype" in d and "How should the page look" in d, d[-500:])
check("rules: every answer was restated", o.count("Noted.") == 3, o)

# skip rest
reset()
D = mk("delta"); DS = str(D)
reply({"questions": [Q(1, "work"), Q(2, "outputs"), Q(3, "approver")]})
c, o, e = shipm("playbook", "interview", "--short", "--project", DS, answers=["Real answer", "s"])
st = prog(D)
check("skip rest: 's' fills the current and the remaining questions with defaults, all marked assumed", c == 0 and [a["how"] for a in st["answered"]] == ["answer", "skipped", "skipped"] and len(st["assumed"]) == 2 and st["status"] == "draft", st)

# model trouble
reset()
E_ = mk("echo"); ES = str(E_)
(TMP / "fail").write_text("1")
c, o, e = shipm("playbook", "interview", "--short", "--project", ES, answers=[""])
check("model error: exit 2, nothing written but an error progress, no draft", c == 2 and "no questions" in e and not (E_ / ".shipmiracle" / "playbook.draft.md").exists() and prog(E_)["status"] == "error", (c, e))
c, o, e = shipm("playbook", "interview", "--resume", "--project", ES, answers=[""])
check("model error: --resume asks again (the error state is resumable)", c == 2 and len(calls()) == 2, (c, e, len(calls())))
reset()
(TMP / "reply.json").write_text("I cannot help with that.")
c, o, e = shipm("playbook", "interview", "--restart", "--project", ES, answers=[""])
check("a reply that is not JSON: exit 2, no draft", c == 2 and not (E_ / ".shipmiracle" / "playbook.draft.md").exists(), (c, e))

# ================================================================== pause and resume
reset()
F = mk("foxtrot"); FS = str(F)
reply({"questions": [Q(1, "work"), Q(2, "outputs"), Q(3, "approver")]})
c, o, e = shipm("playbook", "interview", "--short", "--project", FS, answers=["First answer", "<EOF>"])
st = prog(F)
check("closed terminal: exit 1, status paused, one answer saved, the rest queued", c == 1 and st["status"] == "paused" and len(st["answered"]) == 1 and len(st["queue"]) == 2 and "--resume" in o, (c, o, e, st))
c, o, e = shipm("playbook", "interview", "--short", "--project", FS, answers=[""])
check("starting again while paused: exit 2, tells --resume / --restart, no model call", c == 2 and "--resume" in e and "--restart" in e and len(calls()) == 1, (c, e))
c, o, e = shipm("playbook", "interview", "--resume", "--project", FS, answers=["", ""])
st = prog(F)
check("resume: continues from the queue with no new model call; draft written", c == 0 and len(calls()) == 1 and st["status"] == "draft" and len(st["answered"]) == 3 and st["answered"][0]["a"] == "First answer", (c, e, st))
c, o, e = shipm("playbook", "interview", "--restart", "--short", "--project", FS, answers=["", "", ""])
check("restart: throws the old answers and draft away and asks again (second model call)", c == 0 and len(calls()) == 2 and prog(F)["status"] == "draft", (c, e))
c, o, e = shipm("playbook", "interview", "--resume", "--project", str(mk("golf")), answers=[""])
check("resume with nothing saved: exit 3", c == 3, (c, e))

# ================================================================== Long
reset()
G = mk("hotel"); GS = str(G)
reply({"questions": [Q(1, "work"), Q(2, "outputs"), Q(3, "approver"), Q(4, "risks")]}, 1)
c, o, e = shipm("playbook", "interview", "--short", "--project", GS, answers=["", "", ""])
check("long setup: a Short interview is finished first", c == 0 and prog(G)["mode"] == "short" and len(prog(G)["answered"]) == 3)
reply({"questions": [Q(5, "work", text="Question about work number 1?"), Q(6, "risks", rec="Money"), Q(7, "tools"), Q(8, "inputs"), Q(9, "done"), Q(10, "never"), Q(11, "tools", text="More about tools?"),
                     Q(12, "done", text="More about done?"), Q(13, "inputs", text="More about inputs?")]}, 1)
reply({"questions": [Q(20, "tools", text="Second round tools?"), Q(21, "never", text="Second round never?"), Q(22, "risks", text="Second round risks?"), Q(23, "done", text="Second round done?")]})
c, o, e = shipm("playbook", "interview", "--long", "--project", GS, answers=[""] * 12)
st = prog(G)
cl = calls()[1]
check("long: continues from the Short answers (they are sent to the model, never asked again)", c == 0 and st["mode"] == "long" and len(json.loads(cl["stdin"])["answered"]) == 3 and "Question about work number 1?" not in o, (c, o[-300:], e))
check("long: at most 10 questions in all, at most 3 rounds, at most 2 per topic", len(st["answered"]) <= 10 and st["round"] <= 3 and max(sum(1 for a in st["answered"] if a["topic"] == t) for t in set(a["topic"] for a in st["answered"])) <= 2, [(a["id"], a["topic"]) for a in st["answered"]])
check("long: more than the 3 short answers were collected, in the same progress file", len(st["answered"]) > 3 and [a["id"] for a in st["answered"]][:3] == ["q1", "q2", "q3"], st["answered"])
rounds = [json.loads(x["stdin"])["round"] for x in calls()]
check("long: model rounds are numbered 1.. and capped at 3 for the long part", max(rounds) <= 3, rounds)

# ================================================================== guards
reset()
H = mk("india"); HS = str(H)
reply({"questions": [Q(1, "work")]})
c, o, e = shipm("playbook", "interview", "--short", "--project", HS, answers=[""], extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("inside a chat: refused (exit 4), no model call, no files", c == 4 and not calls() and not (H / ".shipmiracle").exists(), (c, e))
c, o, e = shipm("playbook", "interview", "--short", "--long", "--project", HS, answers=[""])
check("--short and --long together: exit 2", c == 2, (c, e))
c, o, e = shipm("playbook", "interview", "--short", "--project", HS, session=True)
check("no terminal at all: refused (exit 4) before any model call", c == 4 and not calls() and "terminal" in e, (c, e, len(calls())))
# an existing trusted playbook is never touched by an interview
J = mk("juliet"); JS = str(J)
check("setup: juliet has a trusted playbook", shipm("playbook", "set", "type", "software", "--project", JS, "--allow-open-chat")[0] == 0)
pb0, reg0 = sha(J / ".shipmiracle" / "playbook.json"), sha(REG)
reply({"questions": [Q(1, "work")], "proposal": {"type": "content", "risk_paths": ["a/**"]}})
c, o, e = shipm("playbook", "interview", "--short", "--project", JS, answers=[""])
check("an interview cannot change playbook.json, work.json or the registry", c == 0 and sha(J / ".shipmiracle" / "playbook.json") == pb0 and sha(REG) == reg0 and not (J / ".shipmiracle" / "work.json").exists())
(J / ".shipmiracle" / "playbook.draft.md").write_text("x")
os.symlink(str(TMP / "evil.md"), str(J / ".shipmiracle" / "link.md"))
K = mk("kilo"); KS = str(K); (K / ".shipmiracle").mkdir(); os.symlink(str(TMP / "evil.md"), str(K / ".shipmiracle" / "playbook.interview.json"))
c, o, e = shipm("playbook", "interview", "--short", "--project", KS, answers=[""])
check("a symlinked progress file is never written through", not (TMP / "evil.md").exists(), (c, e))
L = mk("lima"); LS = str(L); os.symlink(str(TMP), str(L / ".shipmiracle"))
c, o, e = shipm("playbook", "interview", "--short", "--project", LS, answers=[""])
check("a symlinked .shipmiracle folder is refused (exit 4) and nothing lands behind it", c == 4 and not list(TMP.glob("playbook.*")), (c, e))

# ================================================================== Setup row
c, o, e = shipm("init", "--check", "--json")
rows = json.loads(o)["rows"]
row = next(r for r in rows if r["id"] == "describe-work")
check("init --check: describe-work is row 19, optional, never red", row["n"] == 19 and row["need"] == "optional" and row["state"] in ("skipped", "green") and len(rows) == 22, row)
check("init --check: ready does not count the row", "describe-work" not in json.dumps(json.loads(o).get("ready_rows", [])) and row["n"] not in (0, 1, 2, 3, 4, 5, 7))

print("\nresult: %d failed" % fails)
ISO.cleanup(TMP)
sys.exit(1 if fails else 0)
