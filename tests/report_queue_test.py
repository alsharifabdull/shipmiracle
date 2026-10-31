#!/usr/bin/env python3
"""The summary queue's reporter run (shipmiracle/report/queue.py), P5 security M4: a FAKE claude records its argv, stdin and cwd. The reporter gets no tools at all
(`--tools ""`, an empty agent tool list, no Read, no allowedTools), the golden runner's hardening flags and deny list, the facts inline on stdin, and an empty
temp folder as cwd. A summary with a link, URL or image is rejected. The queue's edit of a report is logged with the new content sha (M3).
Temp dirs + SHIPMIRACLE_TEST=1 only; no model, no network. Run: python3 tests/report_queue_test.py"""
import hashlib, json, os, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-rq-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_GOLDEN_CLAUDE"):
    ENV.pop(k, None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_") or k == "HOME"})
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
for d in (HOME, DEV, STATE, CONF, WS / "config"):
    d.mkdir(parents=True, exist_ok=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config" / "flow.json").write_text('{"default": "strict", "projects": {}}')
(CONF / "config.json").write_text(json.dumps({"guard.jobs": True}))
from shipmiracle.playbook import engine, store  # noqa: E402
from shipmiracle.report import lint, queue, write  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:800]))
    fails += 0 if ok else 1

def shipm(*args):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr

# ---------------------------------------------------------------- a fake claude that records what it was given
REC = TMP / "rec.json"
FAKE = TMP / "claude-fake"
FAKE.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                'inp = sys.stdin.read()\n'
                'json.dump({"argv": sys.argv[1:], "stdin": inp, "cwd": os.getcwd(), "ls": sorted(os.listdir(".")), "env": sorted(os.environ)}, open(%r, "w"))\n'
                'print(json.dumps({"is_error": False, "result": os.environ.get("FAKE_ANSWER", "CR-001 delivered.\\nResult: ok\\nEvidence: `x` -> 1\\nFiles: none\\nNot verified: none\\nVerdict: PASS")}))\n' % str(REC))
FAKE.chmod(0o755)
os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"] = str(FAKE)

qd = TMP / "qd"; qd.mkdir()
(qd / "facts.json").write_text(json.dumps({"cr": "CR-001", "title": "T", "stages": {"Do": "done"}}))
text, err = queue._ask(qd)
rec = json.loads(REC.read_text())
av = rec["argv"]
check("M4 the reporter run succeeds with a fake claude", err is None and text and text.startswith("CR-001"), (text, err))
check("M4 no Read and no allowedTools anywhere in argv", "Read" not in av and "--allowedTools" not in av and "--allowed-tools" not in av and True, av)
i = av.index("--tools")
check("M4 --tools is the empty string (all built-in tools off)", av[i + 1] == "", av)
a = json.loads(av[av.index("--agents") + 1])
check("M4 the agent definition carries an empty tool list", all(v.get("tools") == [] for v in a.values()), a)
check("M4 same hardening flags as bin" "/shipm-golden: --setting-sources project,local, --strict-mcp-config, a permission mode", av[av.index("--setting-sources") + 1] == "project,local"
      and "--strict-mcp-config" in av and av[av.index("--permission-mode") + 1] == "acceptEdits", av)
dn = av[av.index("--disallowedTools") + 1]
check("M4 the golden deny list is passed (WebFetch, WebSearch, curl, git push ...)", all(x in dn for x in ("WebFetch", "WebSearch", "Bash(curl:*)", "Bash(git push:*)")), dn)
check("M4 the facts arrive on stdin", json.loads(rec["stdin"])["cr"] == "CR-001", rec["stdin"])
check("M4 the cwd is an empty temp folder, not the queue folder, and it is removed afterwards", rec["cwd"] != str(qd) and rec["ls"] == [] and not os.path.exists(rec["cwd"]), rec)
check("M4 the environment is minimal (no tokens)", not any(k in rec["env"] for k in ("GH_TOKEN", "ANTHROPIC_API_KEY", "SSH_AUTH_SOCK")), rec["env"])
check("M4 the prompt tells the model not to write links", "no links" in queue.PROMPT.lower())

# ---------------------------------------------------------------- link rejection
for name, line in (("URL", "See https://evil.example/x for details."), ("www", "More at www.evil.example"), ("markdown link", "Details [here](http://a.b/c)."),
                   ("markdown image", "![x](https://a.b/p.png)"), ("html anchor", "<a href=x>go</a>"), ("bare domain", "Open evil.com now"), ("ccTLD link", "Open evil.de/x now"), ("data uri", "data:text/html;base64,AAAA")):
    os.environ["FAKE_ANSWER"] = "CR-001 delivered. %s\nResult: ok\nEvidence: `x` -> 1\nFiles: none\nNot verified: none\nVerdict: PASS" % line
    lines, why = queue.accept(os.environ["FAKE_ANSWER"], qd)
    check("M4 queue.accept rejects a %s in the summary" % name, lines is None and ("link" in (why or "") or "hedg" in (why or "") or why), (lines, why))
os.environ.pop("FAKE_ANSWER", None)
lines, why = queue.accept("CR-001 delivered.\nResult: ok\nEvidence: `x` -> 1\nFiles: none\nNot verified: none\nVerdict: PASS", qd)
check("M4 control: a clean 1-line summary is accepted", lines == ["CR-001 delivered."], (lines, why))

# lint: the same rule on the written report
rep = ("# CR-001 T · DELIVERED · PASS\nSummary: pending\nStages: Do done\nEvidence: `npm test` -> 2 passed\nFiles: none\nRollback: git revert\nOwner waits: 0 · Auto-decisions: 0\nCost: n/a\nNot verified: none\n")
check("lint control: this tiny CR report is clean", lint.lint_text(rep) == [], lint.lint_text(rep))
for line in ("Summary: see https://x.example", "Summary: ![i](http://x.y/z.png)", "Summary: click [here](a)"):
    check("lint rejects %r" % line[:30], any("link" in p for p in lint.lint_text(rep.replace("Summary: pending", line))), lint.lint_text(rep.replace("Summary: pending", line)))
check("lint: an Arabic summary with numbers and file names passes", not any("link" in p for p in lint.lint_text(rep.replace("Summary: pending", "Summary: تم إصلاح الاتجاه في tests/login.ts و README.md"))))

# ---------------------------------------------------------------- the queue's edit is logged with the new sha (M3)
P = DEV / "qproj"
(P / "docs").mkdir(parents=True)
subprocess.run(["git", "init", "-q", str(P)], env=ENV, check=True)
(P / "a.txt").write_text("1\n")
subprocess.run(["git", "-C", str(P), "add", "-A"], env=ENV, check=True)
subprocess.run(["git", "-C", str(P), "commit", "-qm", "init"], env=ENV, check=True)
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"qproj": {"chats": 0}}}))
check("setup: playbook set", shipm("playbook", "set", "type", "software", "--project", "qproj")[0] == 0)
check("setup: open + abandon a CR (owner, sandbox)", shipm("cr", "open", "queue sha check", "--project", "qproj")[0] == 0 and shipm("cr", "abandon", "CR-001", "--project", "qproj")[0] == 0)
reps = sorted((P / "docs" / "reports").glob("*CR-001.md"))
check("the abandon wrote one CR report with Summary: pending", len(reps) == 1 and "Summary: pending" in reps[0].read_text(encoding="utf-8"), reps)
rp = reps[0]
rel = os.path.relpath(str(rp), str(P))
def logged():
    c = engine.get_cr(store.load(str(P), STATE), "CR-001")
    return (c.get("report_sha") or {}).get(rel)
check("the engine logged the sha of the report it wrote", logged() == hashlib.sha256(rp.read_bytes()).hexdigest(), logged())
os.environ.pop("FAKE_ANSWER", None)           # the reporter runs with a minimal environment: the fake answers with its default
r = queue.run_one(STATE, int(time.time()))
check("queue.run_one accepts the clean summary", r["outcome"] == "done", r)
check("... the report changed and the NEW sha is logged (the stage module still accepts the file)", "Summary: CR-001 delivered." in rp.read_text(encoding="utf-8") and logged() == hashlib.sha256(rp.read_bytes()).hexdigest(), logged())
p2 = write.write_cr(P, "CR-001", base=STATE)
check("a later write_cr replaces the engine's own (edited) report without quarantining it", p2 == rp and not list(rp.parent.glob("*.forged-*")), list(rp.parent.iterdir()))

# ---- review remediation A: shipm switch reporter.model ----
from shipmiracle import config  # noqa: E402
def model_of_run():
    queue._ask(qd)
    return list(json.loads(json.loads(REC.read_text())["argv"][json.loads(REC.read_text())["argv"].index("--agents") + 1]).values())[0]["model"]
check("reporter.model default: the run uses the model the agent file pins (haiku)", model_of_run() == "haiku")
config.set("reporter.model", "sonnet")
check("reporter.model sonnet: the run uses sonnet", model_of_run() == "sonnet")
config.set("reporter.model", "haiku")
check("reporter.model set to haiku explicitly: haiku", model_of_run() == "haiku")
config.set("reporter.model", "off")
REC.unlink()
p3 = write.write_cr(P, "CR-001", base=STATE)
r = queue.run_one(STATE, int(time.time()))
check("reporter.model off: the pending summary becomes 'not generated' and the model is never started", r["outcome"] == "not_generated" and "off" in r["why"] and not REC.exists()
      and "Summary: not generated" in p3.read_text(encoding="utf-8"), (r, REC.exists()))
config.unset("reporter.model")

print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
