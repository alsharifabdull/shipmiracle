#!/usr/bin/env python3
"""Regression guard for the 19 Oct 2026 flow-gate IndexError burst (flow-errors.log, 15 entries 15:36-16:27, "IndexError: list index out of range"
in the Bash parser's main(), plus the doctor row that turns red on any fresh flow-errors.log entry.
Run: python3 tests/flow_gate_indexerror_test.py

The log keeps only the traceback (no input), and the 16:27 source was an uncommitted work-in-progress copy (the next commit, b99dfa1 at 17:43, has different
line numbers), so the exact input is not recoverable. The traces sit in the argument-indexing code of the Bash command walker (list indexing on empty/short
argument lists after a command name: cp/mv/install/dd/git/patch/find/shell -c with a missing operand). This test feeds those shapes (command name alone,
trailing operator, missing operand, unterminated quote/heredoc) to the CURRENT hook and asserts nothing is written to flow-errors.log."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import pathlib, subprocess, sys, tempfile, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import flow_fixture as F

fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)[:300]))
    if not c: fails.append(n)

p = F.make_project(); p.prompt()
CMDS = "cp mv install rsync ln dd git patch sed awk perl python3 node bash sh find rm chmod touch tee cd pushd popd ex ed truncate cat env sudo xargs".split()
TAILS = ["", ">", "2>", "&>", "<<", "<<<", "|", "&&", ";", "(", "((", "$(", "-", "--", "-c", "-e", "-i", "-t", "-d", "-C", "-c ''", "-t ''",
         "--target-directory=", "of=", "'", "\"", "-delete", "-exec", "-exec rm", "-name", "!", "[[", "{}", "\;", "+", "apply", "-C x", "-c x apply", "-d x"]
inputs = [f"{c} {t}".rstrip() for c in CMDS for t in TAILS]
inputs += ["", " ", ";", "|", "&&", "()", "(())", "$(())", "<<EOF", "cat <<", "cat <<-", "x=", "x= y", "\n", "\\\n", "#", "!", "{", "}", "case x in", "for", "if",
           "echo >", "echo >>", "echo 2>&1 >", "find . -exec rm", "find ( ", "find -exec", "env -i", "env A=b", "bash -c ''", "sh -c", "awk '{print >", "sed -i ''", "perl -pi", "git -C", "git -c", "pushd -", "cd -"]
for c in inputs:
    p.bash(c)
check(f"{len(inputs)} short/odd Bash commands: no traceback in flow-errors.log", p.errors() == "", p.errors()[-600:])

# non-Bash tools with missing/short inputs too
for tool, ti in (("Edit", {}), ("Write", {}), ("Bash", {}), ("Bash", {"command": ""}), ("MultiEdit", {"edits": []}), ("NotebookEdit", {}), ("Task", {})):
    p.pre(tool, ti)
    p.post(tool, ti)
check("empty tool inputs on Pre/PostToolUse: no traceback", p.errors() == "", p.errors()[-600:])

# --- doctor row: red when flow-errors.log has an entry from the last 24 h, ok otherwise (only the row is run, not the whole doctor)
doctor = (F.WS / "bin/doctor").read_text().splitlines()
i = next(k for k, l in enumerate(doctor) if l.startswith("fe=$("))
j = next(k for k in range(i, len(doctor)) if doctor[k].startswith('[[ "${fe:-0}"'))
row = "\n".join(doctor[i:j + 1])
def run_row(log_text):
    d = pathlib.Path(tempfile.mkdtemp())
    if log_text is not None: (d / "flow-errors.log").write_text(log_text)
    script = 'ok() { echo "OK $1"; }; bad() { echo "FAIL $1"; }; warn() { echo "WARN $1"; }\n' + row
    t0 = time.time()
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "SHIPMIRACLE_TEST": "1", "SHIPMIRACLE_STATE": str(d), "HOME": str(d)})
    return r.stdout, time.time() - t0
fmt = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
tb = " Traceback (most recent call last): |   File \"<string>\", line 561, in main | IndexError: list index out of range | \n"
o, dt = run_row(fmt(time.time() - 3600) + tb)
check("doctor: entry 1 h old -> FAIL row with count", o.startswith("FAIL") and "1 internal error" in o, o)
o, _ = run_row(fmt(time.time() - 3600) + tb + fmt(time.time() - 60) + tb)
check("doctor: two fresh entries -> FAIL, counts 2", o.startswith("FAIL") and "2 internal error" in o, o)
o, _ = run_row(fmt(time.time() - 3 * 86400) + tb)
check("doctor: entry 3 days old -> ok", o.startswith("OK"), o)
o, _ = run_row("")
check("doctor: empty log -> ok", o.startswith("OK"), o)
o, _ = run_row(None)
check("doctor: no log file -> ok", o.startswith("OK"), o)
o, _ = run_row("garbage line without a date\n")
check("doctor: garbage line -> ok (not counted)", o.startswith("OK"), o)
check("doctor row is fast (< 1 s)", dt < 1.0, dt)

p.cleanup()
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
