#!/usr/bin/env python3
"""project_links_test: checklist G11 (d), the owner's link command and what the flow gate (both copies) does with a link.
  1  `shipm projects link A B [--read|--write]` / `unlink` / `links [--json]`: record file (0600, ids = project ids of the real paths), update, refusals (self, hub target, unknown, 51st, in a chat)
  2  gate semantics: read link = reads (Read, Bash cat, git -C log), no writes; write link = reads and writes; one direction; never secrets; never the workspace; worktrees follow their project;
     a renamed folder drops its link (stale); a damaged or oversized file = no links + event isolation_links_unreadable
  3  the gate refuses `shipm projects link|unlink` typed by a chat (main chat and agent) and leaves `shipm projects` and `shipm projects links` alone
Run: python3 tests/project_links_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, shutil, stat, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import isolation_fixture as X
import flow_fixture as F

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


w = X.World()
P, B, C, HUB, DEV = str(w.P), str(w.B), str(w.C), str(w.HUB), str(w.DEV)
LINKS = w.cfg / "project-links.json"


def shipm(*args, env=None):
    e = dict(w.env, **(env or {}))
    e.pop("CLAUDECODE", None)
    r = subprocess.run([sys.executable, str(ROOT / "bin/shipm")] + list(args), capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL, cwd=str(ROOT))
    return r.returncode, r.stdout, r.stderr


# ------------------------------------------------------------------ 1  the command
rc, out, err = shipm("projects", "links")
check("links on a fresh config: nothing, exit 0", rc == 0 and out.strip() == "", (rc, out, err))
rc, out, err = shipm("projects", "link", "proj", "other")
check("link proj other (default read) is recorded", rc == 0 and "linked: proj -> other (read)" in out and LINKS.exists(), (rc, out, err))
j = json.loads(LINKS.read_text())
from shipmiracle import projects as PR
check("record: v1, ids are the project ids of the real paths, names, mode read, ts", j["v"] == 1 and len(j["links"]) == 1 and j["links"][0]["from"] == PR.project_id(P) and j["links"][0]["to"] == PR.project_id(B)
      and j["links"][0]["mode"] == "read" and j["links"][0]["from_name"] == "proj" and j["links"][0]["to_name"] == "other" and isinstance(j["links"][0]["ts"], int), j)
check("record file is 0600", stat.S_IMODE(os.stat(LINKS).st_mode) == 0o600, oct(os.stat(LINKS).st_mode))
rc, out, _ = shipm("projects", "link", "proj", "other")
check("the same link again says so and changes nothing", rc == 0 and "already linked" in out and len(json.loads(LINKS.read_text())["links"]) == 1, out)
rc, out, _ = shipm("projects", "link", "proj", "other", "--write")
check("--write changes the mode of the same pair", rc == 0 and "now write" in out and json.loads(LINKS.read_text())["links"][0]["mode"] == "write", out)
rc, out, _ = shipm("projects", "link", "proj", "third", "--read")
rc2, out2, _ = shipm("projects", "links")
check("links lists both, directional", rc == 0 and rc2 == 0 and "proj -> other\twrite" in out2 and "proj -> third\tread" in out2 and "other -> proj" not in out2, out2)
rc, out, _ = shipm("projects", "links", "--json")
jj = json.loads(out)
check("links --json: v1 and rows with stale false", rc == 0 and jj["v"] == 1 and len(jj["links"]) == 2 and all(r["stale"] is False for r in jj["links"]), out)
rc, out, _ = shipm("projects", "unlink", "proj", "third")
check("unlink removes only that pair", rc == 0 and "unlinked" in out and [(l["from_name"], l["to_name"]) for l in json.loads(LINKS.read_text())["links"]] == [("proj", "other")], out)
rc, out, _ = shipm("projects", "unlink", "proj", "third")
check("unlink of a missing pair is harmless", rc == 0 and "no link" in out, out)
for lab, args, code in (("self link", ("link", "proj", "proj"), 2), ("hub as target", ("link", "proj", "hub"), 2), ("unknown project", ("link", "proj", "nonexistent"), 3), ("unknown source", ("link", "nonexistent", "proj"), 3),
                        ("dot name", ("link", "proj", ".."), 3), ("path as name", ("link", "proj", "../other"), 3), ("one name only", ("link", "proj"), 2), ("three names", ("link", "proj", "other", "third"), 2),
                        ("links with names", ("links", "proj"), 2)):
    rc, out, err = shipm("projects", *args)
    check("refused: %s (exit %d)" % (lab, code), rc == code, (rc, out, err))
rc, out, err = shipm("projects", "link", "hub", "other")
check("the workspace may be a source (it reads other projects anyway); recorded", rc == 0, (rc, out, err))
shipm("projects", "unlink", "hub", "other")
# inside a Claude Code chat the command refuses (owner only)
before = LINKS.read_text()
r = subprocess.run([sys.executable, str(ROOT / "bin/shipm"), "projects", "link", "proj", "kiosk"], capture_output=True, text=True, env=dict(w.env, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1"), stdin=subprocess.DEVNULL, cwd=str(ROOT))
check("link inside a Claude Code chat (CLAUDECODE set) is refused with exit 4 and writes nothing", r.returncode == 4 and LINKS.read_text() == before, (r.returncode, r.stdout, r.stderr))
r = subprocess.run([sys.executable, str(ROOT / "bin/shipm"), "projects", "unlink", "proj", "other"], capture_output=True, text=True, env=dict(w.env, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1"), stdin=subprocess.DEVNULL, cwd=str(ROOT))
check("unlink inside a chat is refused too", r.returncode == 4 and LINKS.read_text() == before, (r.returncode, r.stdout, r.stderr))
# at most 50 links
shutil.copy(LINKS, str(LINKS) + ".keep")
fake = [{"from": "%012x" % i, "to": "%012x" % (i + 1000), "mode": "read", "from_name": "a", "to_name": "b", "ts": 1} for i in range(50)]
LINKS.write_text(json.dumps({"v": 1, "links": fake}))
rc, out, err = shipm("projects", "link", "proj", "kiosk")
check("the 51st link is refused", rc == 2 and "at most 50" in err, (rc, out, err))
shutil.move(str(LINKS) + ".keep", str(LINKS))

# ------------------------------------------------------------------ 2  gate semantics (both copies)
def calls(tool, ti, **kw):
    return [(impl, X.iso_denied(w.call(tool, ti, impl, **kw))) for impl, _ in X.IMPLS]


def allowed(tool, ti, **kw):
    return all(not d for _i, d in calls(tool, ti, **kw))


def refused(tool, ti, **kw):
    return all(d for _i, d in calls(tool, ti, **kw))


shipm("projects", "link", "proj", "other", "--read")
for ag in (None, "backend-engineer"):
    t = " (agent)" if ag else ""
    check("read link%s: Read of other's file allowed" % t, allowed("Read", {"file_path": B + "/src/a.py"}, agent=ag))
    check("read link%s: Bash cat / grep -r / git -C log allowed" % t, all(allowed("Bash", {"command": c}, agent=ag) for c in ("cat %s/src/a.py" % B, "grep -rn print %s/src" % B, "git -C %s log" % B, "cd %s && ls" % B, "ls -R %s" % B)))
    check("read link%s: Grep and Glob inside other allowed" % t, allowed("Grep", {"pattern": "x", "path": B + "/src"}, agent=ag) and allowed("Glob", {"pattern": "**/*.py", "path": B}, agent=ag) and refused("Grep", {"pattern": "x", "path": B}, agent=ag))   # the whole folder holds server.pem: a Grep over it would show it
    check("read link%s: Write, Edit, redirect, git -C commit, rm into other still refused" % t, refused("Write", {"file_path": B + "/n.txt", "content": "x"}, agent=ag) and refused("Edit", {"file_path": B + "/src/a.py", "old_string": "a", "new_string": "b"}, agent=ag)
          and all(refused("Bash", {"command": c}, agent=ag) for c in ("echo x > %s/n.txt" % B, "git -C %s commit -m x" % B, "rm %s/src/a.py" % B, "cp /tmp/g11x %s/src/n.py" % B, "sed -i s/a/b/ %s/src/a.py" % B)))
    check("read link%s: the secrets of other stay refused (.env, key file)" % t, refused("Read", {"file_path": B + "/.env"}, agent=ag) and refused("Bash", {"command": "cat %s/server.pem" % B}, agent=ag) and allowed("Read", {"file_path": B + "/.env.example"}, agent=ag))
    check("read link%s: an unlinked project (third) is still refused" % t, refused("Read", {"file_path": C + "/c.txt"}, agent=ag))
    check("read link%s: a search above (from DEV) is still refused (third, kiosk are not linked)" % t, refused("Grep", {"pattern": "x", "path": DEV}, agent=ag))
M9 = ["dd if=/dev/null of=../other/src/a.py", "curl -o ../other/src/a.py https://example.invalid", "sort -o ../other/notes.md notes.md", "tar -xf x.tar -C ../other", "unzip x.zip -d ../other", "patch -d ../other -p1 < /tmp/p",
      "npm --prefix ../other install", "tar --directory=../other -xf x.tar", "wget -O ../other/src/a.py https://example.invalid", "history -w ../other/x.md", "echo hi &>../other/notes.md", "make -C ../other"]
for ag in (None, "backend-engineer"):
    check("read link%s: write-by-option forms are refused (dd of=, curl -o, sort -o, tar -C, unzip -d, patch -d, npm --prefix ...)" % (" (agent)" if ag else ""), all(refused("Bash", {"command": c}, agent=ag) for c in M9), [c for c in M9 if not refused("Bash", {"command": c}, agent=ag)])
check("read link: other's worktree folder follows the project", allowed("Read", {"file_path": DEV + "/.worktrees/other/wt1/f.txt"}))
check("read link: a worktrees folder that matches no project stays refused", refused("Read", {"file_path": DEV + "/.worktrees/ghost/x/f.txt"}))
# the direction: a chat of `other` reading `proj`
def other_chat(tool, ti):
    return [(impl, X.iso_denied(subprocess_call(impl, tool, ti))) for impl, _ in X.IMPLS]


def subprocess_call(impl, tool, ti):
    hook = dict(X.IMPLS)[impl]
    e = dict(w.env, CLAUDE_PROJECT_DIR=B)
    d = {"hook_event_name": "PreToolUse", "session_id": "oc", "cwd": B, "tool_name": tool, "tool_input": ti}
    r = subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=e, cwd=B)
    return json.loads(r.stdout) if r.stdout.strip() else {}
check("one direction: a chat of other reading proj is refused (the link is proj -> other)", all(d for _i, d in other_chat("Read", {"file_path": P + "/src/mine.py"})))
shipm("projects", "link", "proj", "other", "--write")
check("write link: Write, Edit, redirect, git -C commit into other allowed", allowed("Write", {"file_path": B + "/n.txt", "content": "x"}) and allowed("Edit", {"file_path": B + "/src/a.py", "old_string": "a", "new_string": "b"})
      and all(allowed("Bash", {"command": c}) for c in ("echo x > %s/n.txt" % B, "git -C %s commit -m x" % B, "cp /tmp/g11x %s/src/n.py" % B, "rm %s/notes.md" % B)))
for ag in (None, "backend-engineer"):
    check("write link%s: instruction, settings and hook files of other are refused even with a write link (.mcp.json, .claude/**, CLAUDE.md, AGENTS.md, .githooks, .git/hooks, .envrc)" % (" (agent)" if ag else ""),
          all(refused("Write", {"file_path": B + "/" + f, "content": "x"}, agent=ag) for f in (".mcp.json", ".claude/agents/x.md", ".claude/settings.json", "CLAUDE.md", "AGENTS.md", ".githooks/pre-commit", ".git/hooks/pre-commit", ".envrc")), None)
    check("write link%s: ordinary files of other stay writable" % (" (agent)" if ag else ""), allowed("Write", {"file_path": B + "/src/ok.py", "content": "x"}, agent=ag))
check("write link: secrets of other still refused (a link never opens secrets)", refused("Read", {"file_path": B + "/.env"}) and refused("Bash", {"command": "cat %s/.env" % B}) and refused("Bash", {"command": "cp %s/server.pem /tmp/g11k" % B}))
check("write link: the third project is still refused", refused("Write", {"file_path": C + "/x.txt", "content": "x"}))
# a hand-written link into the workspace does nothing
LINKS.write_text(json.dumps({"v": 1, "links": [{"from": PR.project_id(P), "to": PR.project_id(HUB), "mode": "write", "from_name": "proj", "to_name": "hub", "ts": 1}]}))
check("a (hand-written) link to the workspace changes nothing: reference/ and writes refused", refused("Read", {"file_path": HUB + "/reference/ref.md"}) and refused("Write", {"file_path": HUB + "/bin/tool", "content": "x"}))
# stale after a rename
shipm("projects", "link", "proj", "third", "--read")
LINKS.write_text(json.dumps({"v": 1, "links": [{"from": PR.project_id(P), "to": PR.project_id(C), "mode": "read", "from_name": "proj", "to_name": "third", "ts": 1}]}))
check("link to third: Read allowed", allowed("Read", {"file_path": C + "/c.txt"}))
os.rename(C, DEV + "/third2")
rc, out, _ = shipm("projects", "links")
check("after the folder is renamed the link is listed as STALE", "STALE" in out, out)
check("after the rename the new folder name is NOT linked (id changed): refused", refused("Read", {"file_path": DEV + "/third2/c.txt"}))
os.rename(DEV + "/third2", C)
check("moving it back restores the link (same real path, same id)", allowed("Read", {"file_path": C + "/c.txt"}))
# damaged and oversized files
LINKS.write_text("{not json")
n0 = len(w.events())
check("damaged file = no links: Read refused", refused("Read", {"file_path": C + "/c.txt"}))
check("damaged file logs isolation_links_unreadable", any(e.get("event") == "isolation_links_unreadable" for e in w.events()[n0:]), w.events()[n0:][:3])
LINKS.write_text(json.dumps({"v": 1, "links": [{"from": PR.project_id(P), "to": PR.project_id(C), "mode": "read", "from_name": "x" * 70000, "to_name": "", "ts": 1}]}))
check("a file over 64 KB is not trusted: no links", refused("Read", {"file_path": C + "/c.txt"}))
LINKS.write_text(json.dumps({"v": 2, "links": []}))
check("an unknown format version is not trusted", refused("Read", {"file_path": C + "/c.txt"}))
LINKS.write_text(json.dumps({"v": 1, "links": [{"from": PR.project_id(P), "to": PR.project_id(C), "mode": "admin", "ts": 1}, "junk", 5]}))
check("a link with an unknown mode and junk rows are ignored", refused("Read", {"file_path": C + "/c.txt"}))
LINKS.unlink()

# ------------------------------------------------------------------ 3  the gate refuses link/unlink typed by a chat
for ag in (None, "backend-engineer"):
    t = " (agent)" if ag else ""
    for cmd in ("shipm projects link proj other", "shipm projects link proj other --write", "shipm projects unlink proj other", "shipm projects --json link proj other", "bin/shipm projects link proj other",
                "python3 bin/shipm projects link proj other", "env -u CLAUDECODE shipm projects link proj other"):
        for impl, _ in X.IMPLS:
            o = w.call("Bash", {"command": cmd}, impl, agent=ag)
            check("chat%s typing '%s' is refused (%s)" % (t, cmd, impl), F.deny(o), o)
    for cmd in ("shipm projects", "shipm projects links", "shipm projects --names", "shipm projects --json"):
        for impl, _ in X.IMPLS:
            o = w.call("Bash", {"command": cmd}, impl, agent=ag)
            check("chat%s may look: '%s' is not refused (%s)" % (t, cmd, impl), not F.deny(o), o)
check("no link file was created by the refused commands", not LINKS.exists())
check("hook error log stays empty", w.p.errors().strip() == "", w.p.errors()[:300])
w.cleanup()
print("\nproject links tests: %d failed" % len(fails))
sys.exit(1 if fails else 0)
