#!/usr/bin/env python3
"""shipm release-check and shipm release denylist (P8 T4): a canary is planted for every rule in a temp tree and must be found with the right
check/kind/file/line while its text never shows up in stdout, stderr, --json, the PASS stamp or an exception message.
Canaries are built at run time (split literals) so this file itself passes release-check. Everything runs under SHIPMIRACLE_TEST=1 with temp
HOME/STATE/CONFIG/WS; gh, scutil, git config and gitleaks are never called for real (injected provider, stub binary).
Run: python3 tests/release_check_test.py   (Python 3.9)"""
import ast, contextlib, hashlib, io, json, os, pathlib, shutil, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-relchk-")).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "cfg"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"), HOME=str(TMP / "gh"), SHIPMIRACLE_GITLEAKS_BIN=str(TMP / "no-such-gitleaks"))
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    os.environ.pop(k, None)
for d in ("home", "state", "dev", "ws", "gh"):
    (TMP / d).mkdir()
from shipmiracle import ShipmiracleError, SafetyError, cli, paths  # noqa: E402
from shipmiracle.release import check as chk, cli as rcli, denylist as dl  # noqa: E402
B = "bi" + "n/"                # synthetic tree paths are built from parts: the closure rule must not read them as references
HK = "hoo" + "ks/"

fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


CFG = TMP / "cfg"
DENY = CFG / dl.FILENAME
SALT = "0123456789abcdef0123456789abcdef"
LOG = []                    # every output we ever saw: scanned for canary text at the end


def run(argv, **env):
    old = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    LOG.append(out.getvalue()); LOG.append(err.getvalue())
    return rc, out.getvalue(), err.getvalue()


def tree(name, files, modes=None):
    t = TMP / "trees" / name
    shutil.rmtree(str(t), ignore_errors=True)
    t.mkdir(parents=True)
    for rel, content in files.items():
        p = t / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    for rel, m in (modes or {}).items():
        os.chmod(str(t / rel), m)
    return t


def write_deny(entries, extra=(), mode=0o600, salt=SALT):
    CFG.mkdir(exist_ok=True)
    os.chmod(str(CFG), 0o700)
    if DENY.exists() or DENY.is_symlink():
        DENY.unlink()
    DENY.write_text("# salt: %s\n%s\n" % (salt, "\n".join(["%s\t%s" % kv for kv in entries] + list(extra))))
    os.chmod(str(DENY), mode)


def rj(t, *flags, **env):
    rc, out, err = run(["release-check", "--tree", str(t), "--json"] + list(flags), **env)
    try:
        return rc, json.loads(out), out, err
    except ValueError:
        return rc, None, out, err


def has(j, check_, kind, file, line=None):
    for f in (j or {}).get("findings", []):
        if f["check"] == check_ and f["kind"] == kind and f["file"] == file and (line is None or f["line"] == line):
            return True
    return False


# ------------------------------------------------------------------ canaries (built here, never written literally)
SECRETS = {
    "github_pat": "github" + "_pat_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
    "github_token": "gh" + "o_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3",
    "anthropic_key": "sk-" + "ant-" + "abcdEFGH1234ijkl",
    "openai_project_key": "sk-" + "proj-" + "abcdEFGH1234ijkl",
    "google_api_key": "AI" + "za" + "SyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6x",
    "private_key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "aws_access_key": "AK" + "IA" + "ABCDEFGH12345678",
    "slack_token": "xo" + "xb-" + "1234567890abcd",
    "api_key_sk": "s" + "k-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2",
    "assignment": 'pass' + 'word = "' + 'correcthorsebattery' + '"',
}
NAME, EMAIL, HANDLE, PROJECT, HOST = "Zebulon Quillfeather", "zq.canary@mail.invalid", "zqhandle77", "Glimmerwood-Station", "Plover\u2019s MacBook"
ENTRIES = [("name", NAME), ("email", EMAIL), ("handle", HANDLE), ("project", PROJECT), ("host", HOST), ("id", "9988776")]
FILLER = "just some ordinary text\n"
CANARIES = list(SECRETS.values()) + [NAME, EMAIL, HANDLE, PROJECT, "Plover", "correcthorsebattery"]

# ------------------------------------------------------------------ 1. secrets/builtin: one canary per rule
files = {}
for i, (kind, text) in enumerate(sorted(SECRETS.items())):
    files["src/s_%s.txt" % kind] = FILLER + FILLER + "x = %s\n" % text if kind != "assignment" else FILLER + FILLER + text + "\n"
t = tree("secrets", files)
rc, j, out, err = rj(t)
check("secrets: exit 1 with findings", rc == 1 and j and j["result"] == "FAIL", (rc, out[:200]))
for kind in sorted(SECRETS):
    check("secrets/builtin kind=%s found at file:3" % kind, has(j, "secrets/builtin", kind, "src/s_%s.txt" % kind, 3), [f for f in j["findings"] if f["file"].endswith(kind + ".txt")])
rc, out, err = run(["release-check", "--tree", str(t)])
check("text output has the exact line shape", "FAIL secrets/builtin kind=github_pat src/s_github_pat.txt:3:5" in out and out.rstrip().endswith("tree=" + j["tree_sha"]) and "\nRESULT FAIL findings=%d files=%d tree=" % (j["counts"]["findings"], j["counts"]["files"]) in out, out[-400:])

# a clean tree is clean (nothing flagged by accident)
clean = tree("clean", {"README.md": "# demo\n", "shipmiracle/mod.py": "x = 1\n", (B + "tool"): "#!/bin/sh\necho /usr/bin/env ~/.local/bin/shipm ./node_modules/.bin/x\n"}, {(B + "tool"): 0o755})
rc, j, out, err = rj(clean)
check("clean tree passes (exit 0)", rc == 0 and j["result"] == "PASS" and not j["findings"], (rc, j))
check("PASS skipped list names identifier and gitleaks", {s["check"] for s in j["skipped"]} >= {"identifier", "secrets/gitleaks"}, j["skipped"])

# ------------------------------------------------------------------ 2. identifier: every kind + variants
write_deny(ENTRIES)
files = {
    "docs/name.txt": FILLER + "by %s here\n" % NAME,
    "docs/email.txt": "contact: %s\n" % EMAIL.upper(),
    "docs/handle.txt": "github.com/%s/shipmiracle\n" % HANDLE,
    "docs/project.txt": FILLER + FILLER + FILLER + "repo %s\n" % PROJECT.lower(),
    "docs/host.txt": "host %s\n" % HOST,
    "docs/id.txt": "uid 9988776 end\n",
}
t = tree("ident", files)
rc, j, out, err = rj(t)
for kind, f, line in (("name", "name.txt", 2), ("email", "email.txt", 1), ("handle", "handle.txt", 1), ("project", "project.txt", 4), ("host", "host.txt", 1), ("id", "id.txt", 1)):
    check("identifier kind=%s found %s:%d" % (kind, f, line), has(j, "identifier", kind, "docs/" + f, line), [x for x in j["findings"] if x["file"].endswith(f)])
fs = [x for x in j["findings"] if x["check"] == "identifier" and x["kind"] == "name"]
check("h is the salted 8-hex hash", fs and fs[0]["h"] == dl.entry_hash(SALT, "name", NAME) and len(fs[0]["h"]) == 8, fs)
rc, out, err = run(["release-check", "--tree", str(t)])
check("identifier text line: kind, h, file:line:col", "FAIL identifier kind=name h=%s docs/name.txt:2:4" % dl.entry_hash(SALT, "name", NAME) in out, out[:600])
check("exit 1 on identifier findings", rc == 1)

# variants: case, separators, URL-encoding, fullwidth, NFD, claude_dirname, zero-width
variants = {
    "upper.txt": NAME.upper(),
    "dash.txt": "zebulon-quillfeather",
    "under.txt": "zebulon_quillfeather",
    "none.txt": "ZebulonQuillfeather",
    "url.txt": "name=Zebulon%20Quillfeather",
    "plus.txt": "q=Zebulon+Quillfeather",
    "fullwidth.txt": "\uff3aebulon Quillfeather",
    "zerowidth.txt": "Zebu\u200blon Quil\u200dlfeather",
    "nfd.txt": __import__("unicodedata").normalize("NFD", "REN\u00c9E Duvall"),
    "apos.txt": "Plover's MacBook",
    "noapos.txt": "Plovers MacBook",
    "dirname.txt": "-Users-" + "zq-canary-mail-invalid",
}
write_deny(ENTRIES + [("name", "Ren\u00e9e Duvall")])
t = tree("variants", dict(("v/" + k, FILLER + v + "\n") for k, v in variants.items()))
rc, j, out, err = rj(t)
for k in sorted(variants):
    check("variant matches: " + k, any(f["check"] == "identifier" and f["file"] == "v/" + k for f in j["findings"]), [f for f in j["findings"] if f["file"] == "v/" + k])
write_deny(ENTRIES)
# a path that contains a value is reported redacted
t = tree("pathhit", {"docs/%s.md" % HANDLE: "hello\n", "docs/%s/inner.md" % PROJECT: "hi\n"})
rc, j, out, err = rj(t)
check("path hits found (line 0) and the path is redacted", any(f["check"] == "identifier" and f["line"] == 0 and f["file"].startswith("<redacted:") for f in j["findings"]) and HANDLE not in out, j["findings"][:3])
# allowed-handle files
t = tree("handle", {"LICENSE": "MIT %s\n" % HANDLE, "README.md": "by %s\n" % HANDLE, "SECURITY.md": HANDLE, "CONTRIBUTING.md": HANDLE,
                    ".github/ISSUE_TEMPLATE/bug.yml": HANDLE + "\n", "docs/x.md": "by %s\n" % HANDLE, "README.md.bak": HANDLE, "LICENSE.md": NAME})
rc, j, out, err = rj(t)
bad = sorted(f["file"] for f in j["findings"] if f["check"] == "identifier")
check("handle allowed only in LICENSE/README/SECURITY/CONTRIBUTING/.github; other kinds and files still fail", bad == ["LICENSE.md", "README.md.bak", "docs/x.md"], bad)
# the owner's real GitHub login (owner decision D1, 21 Oct): the overlay LICENSE carries it; a denylist with it as kind=handle allows it only in the handle files
_OV = pathlib.Path(__file__).resolve().parent.parent / "release" / "overlay"
_LICENSE = (_OV / "LICENSE") if (_OV / "LICENSE").is_file() else pathlib.Path(__file__).resolve().parent.parent / "LICENSE"      # the exported tree carries the overlay at its root
LOGIN = "alsharif" + "abdull"          # split so this file passes release-check with the owner denylist
write_deny([("handle", LOGIN)])
t = tree("login", {"LICENSE": _LICENSE.read_text(), "README.md": "by %s\n" % LOGIN, "docs/notes.md": "by %s\n" % LOGIN, "src/a.py": "# %s\n" % LOGIN})
rc, j, out, err = rj(t)
bad = sorted(f["file"] for f in j["findings"] if f["check"] == "identifier")
check("synthetic denylist with the real login as kind=handle: allowed in LICENSE/README, flagged elsewhere", bad == ["docs/notes.md", "src/a.py"], bad)
t = tree("login-clean", {"LICENSE": _LICENSE.read_text(), "README.md": "by %s\n" % LOGIN})
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("no denylist: the login in LICENSE/README passes (release-check cannot know the handle)", rc == 0 and "RESULT PASS" in out, (rc, out[-200:]))
# exclusion and stoplist and short values
write_deny(ENTRIES + [("name", "Notes"), ("project", "abc"), ("project", "ideas"), ("name", "Mallory Vance")], extra=["!Mallory Vance"])
d = dl.load(DENY)
vals = [v for _, v in d.entries]
check("stoplist, <4 chars and !excludes are dropped", "Notes" not in vals and "abc" not in vals and "ideas" not in vals and "Mallory Vance" not in vals and NAME in vals, vals)
write_deny(ENTRIES)
# no denylist
DENY.unlink()
t = tree("nodeny", {"a.txt": NAME})
rc, out, err = run(["release-check", "--tree", str(t)])
check("no denylist: SKIP identifier line, exit 0", rc == 0 and "SKIP identifier (no denylist on this machine)" in out, (rc, out))
rc, out, err = run(["release-check", "--tree", str(t), "--require-denylist"])
check("--require-denylist without a denylist fails (exit 1)", rc == 1 and "FAIL identifier kind=denylist_missing" in out, (rc, out))
write_deny(ENTRIES)
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("--no-denylist skips the scan even with a denylist present", rc == 0 and "SKIP identifier (--no-denylist)" in out, (rc, out))
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist", "--require-denylist"])
check("--no-denylist with --require-denylist is a usage error (exit 2)", rc == 2, (rc, err))
# --require-login: the literal placeholder must be gone before the first public export
PH = "<log" + "in>"
t = tree("loginph", {"README.md": "clone https://github.com/%s/x\n" % PH, "ok.txt": "fine\n"})
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("the login placeholder passes without --require-login", rc == 0, (rc, out))
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist", "--require-login"])
check("--require-login finds the placeholder (exit 1, file and line named, value not printed)", rc == 1 and "FAIL identifier kind=login_placeholder" in out and "README.md:1" in out, (rc, out))
t = tree("loginok", {"README.md": "clone https://github.com/someone/x\n"})
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist", "--require-login"])
check("--require-login passes when the placeholder is replaced", rc == 0, (rc, out))
# brand pictures: a clean PNG passes, one carrying a text chunk or trailing bytes is a binary finding
import struct as _st, zlib as _z
def _ch(tp, body):
    return _st.pack(">I", len(body)) + tp + body + _st.pack(">I", _z.crc32(tp + body) & 0xFFFFFFFF)
_png = b"\x89PNG\r\n\x1a\n" + _ch(b"IHDR", _st.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + _ch(b"IDAT", _z.compress(b"\0\0\0\0\0")) + _ch(b"IEND", b"")
def _bin_tree(name, data):
    t_ = tree(name, {"x.txt": "x\n"}); (t_ / "brand").mkdir(); (t_ / "brand" / "p.png").write_bytes(data); return t_
rc, out, err = run(["release-check", "--tree", str(_bin_tree("pngok", _png)), "--no-denylist"])
check("a clean brand PNG passes release-check", rc == 0, (rc, out))
_i = _png.rindex(b"IEND") - 4
for nm_, data_ in (("tEXt chunk", _png[:_i] + _ch(b"tEXt", b"k\0" + b"/Users" + b"/x") + _png[_i:]), ("bytes after IEND", _png + b"/Users" + b"/x")):
    rc, out, err = run(["release-check", "--tree", str(_bin_tree("png" + nm_[:3], data_)), "--no-denylist"])
    check("a brand PNG with %s is a binary finding" % nm_, rc == 1 and "FAIL filetype kind=binary" in out and "brand/p.png" in out, (rc, out))
# README pictures (2026-10-31): docs/images/*.png ships under the same strict rule; PNG anywhere else under docs/ is still a binary finding
def _img_tree(name, rel, data):
    t_ = tree(name, {"x.txt": "x\n"}); p_ = t_ / rel; p_.parent.mkdir(parents=True, exist_ok=True); p_.write_bytes(data); return t_
rc, out, err = run(["release-check", "--tree", str(_img_tree("imgok", "docs/images/p.png", _png)), "--no-denylist"])
check("a clean docs/images PNG passes release-check", rc == 0, (rc, out))
rc, out, err = run(["release-check", "--tree", str(_img_tree("imgtxt", "docs/images/p.png", _png[:_i] + _ch(b"tEXt", b"k\0" + b"/Users" + b"/x") + _png[_i:])), "--no-denylist"])
check("a docs/images PNG with a tEXt chunk is a binary finding", rc == 1 and "FAIL filetype kind=binary" in out and "docs/images/p.png" in out, (rc, out))
rc, out, err = run(["release-check", "--tree", str(_img_tree("imgiend", "docs/images/p.png", _png + b"/Users" + b"/x")), "--no-denylist"])
check("a docs/images PNG with bytes after IEND is a binary finding", rc == 1 and "FAIL filetype kind=binary" in out and "docs/images/p.png" in out, (rc, out))
# a trailing newline in the NAME must not pass the picture exemption (a regex '$' matches before a final newline; the anchors are \Z)
for rel_ in ("docs/images/x.png\n", "brand/x.png\n", "brand/sub/x.ico\n"):
    check("the picture exemption refuses the name %r" % rel_, chk.brand_image_clean(rel_, _png) is False and not chk.BINARY_OK.match(rel_))
check("the picture exemption still accepts docs/images/x.png and brand/x.png", chk.brand_image_clean("docs/images/x.png", _png) and chk.brand_image_clean("brand/x.png", _png))
check("a script name with a trailing newline is not exec-exempt (tests/x.sh\\n)", not chk.EXEC_OK.match("tests/x.sh\n") and bool(chk.EXEC_OK.match("tests/x.sh")))
try:
    _nl = _img_tree("imgnl", "docs/images/x.png\n", _png)
    rc, out, err = run(["release-check", "--tree", str(_nl), "--no-denylist"])
    check("a file named 'x.png<newline>' under docs/images is a binary finding", rc == 1 and "FAIL filetype kind=binary" in out, (rc, out))
except OSError as e_:
    print("INFO filesystem refuses a newline in a name (%s): predicate checks above cover it" % e_)
for rel_ in ("docs/p.png", "docs/images/sub/p.png", "docs/images/p.gif"):
    rc, out, err = run(["release-check", "--tree", str(_img_tree("imgbad" + str(len(rel_)), rel_, _png)), "--no-denylist"])
    check("a PNG at %s is still a binary finding" % rel_, rc == 1 and "FAIL filetype kind=binary" in out, (rc, out))

# ------------------------------------------------------------------ 3. home-path
U = "/Users" + "/"
t = tree("home", {"a.md": FILLER + "see " + U + "realperson/Developer\n", "b.md": "ok " + U + "example/x " + U + "<owner>/y " + U + "$USER/z " + U + "x/ " + U + "someone/",
                  "c.md": "lower /user" "s/Someone2/x\n"})
rc, j, out, err = rj(t, "--no-denylist")
check("home-path found a.md:2 and c.md:1", has(j, "home-path", "home_path", "a.md", 2) and has(j, "home-path", "home_path", "c.md", 1), j["findings"])
check("home-path placeholders pass", not any(f["file"] == "b.md" for f in j["findings"]), j["findings"])
check("home-path findings never carry the folder name", "realperson" not in out and "Someone2" not in out)
ws_rel = TMP / "ws" / "release"
ws_rel.mkdir()
(ws_rel / "placeholders.txt").write_text("# mine\nrealperson\nsomeone2\n")
rc, j, out, err = rj(t, "--no-denylist")
check("release/placeholders.txt replaces the built-in list", not any(f["check"] == "home-path" and f["file"] in ("a.md", "c.md") for f in j["findings"]) and any(f["check"] == "home-path" and f["file"] == "b.md" for f in j["findings"]), j["findings"])
(ws_rel / "placeholders.txt").unlink()

# ------------------------------------------------------------------ 4. filetype
long_name = "d" * 3
ft_files = {
    "x/a.jsonl": "{}", "x/a.log": "l", "x/a.db": "d", "x/a.sqlite": "d", "x/a.plist": "p", "x/ok.plist.in": "p", "x/.env": "A=1", "x/.env.local": "A=1",
    "x/.env.example": "A=", "x/a.pem": "k", "x/a.key": "k", "x/a.p12": "k", "x/.DS_Store": "d", "x/a.pyc": "c", "x/.shipmiracle/work.json": "{}",
    "x/registry.json": "{}", "x/nul.txt": b"abc\0def", "x/big.txt": b"a" * (chk.MAX_FILE + 1), "x/edge.txt": b"a" * chk.MAX_FILE,
    "x/exec.py": "x", (B + "ok"): "x", "hooks/ok": "x", ".githooks/ok": "x", "templates/base/hooks/ok.sh": "x", "templates/base/.githooks/ok": "x", "templates/base/.claude/hooks/ok.sh": "x", "templates/a/b/.githooks/ok": "x", "templates/base/other/bad.sh": "x", "tests/ok.sh": "x", "tests/sub/bad.sh": "x",
}
modes = dict((k, 0o755) for k in ("x/exec.py", (B + "ok"), "hooks/ok", ".githooks/ok", "templates/base/hooks/ok.sh", "templates/base/.githooks/ok", "templates/base/.claude/hooks/ok.sh", "templates/a/b/.githooks/ok", "templates/base/other/bad.sh", "tests/ok.sh", "tests/sub/bad.sh"))
t = tree("ft", ft_files, modes)
os.symlink("a.log", str(t / "x" / "link"))
os.symlink("..", str(t / "x" / "dirlink"))
(t / "sub" / "inner").mkdir(parents=True); (t / "sub" / "inner" / ".git").mkdir()
(t / "sub" / "g2").mkdir(); (t / "sub" / "g2" / ".git").write_text("gitdir: /elsewhere\n")
(t / ".gitmodules").write_text("[submodule]\n")
os.mkfifo(str(t / "x" / "pipe"))
rc, j, out, err = rj(t, "--no-denylist")
want = {"x/a.jsonl": "jsonl", "x/a.log": "log", "x/a.db": "database", "x/a.sqlite": "database", "x/a.plist": "plist", "x/.env": "env_file", "x/.env.local": "env_file",
        "x/a.pem": "key_file", "x/a.key": "key_file", "x/a.p12": "key_file", "x/.DS_Store": "ds_store", "x/a.pyc": "pyc", "x/.shipmiracle/work.json": "state_file",
        "x/registry.json": "state_file", "x/nul.txt": "binary", "x/big.txt": "too_large", "x/exec.py": "exec_bit", "tests/sub/bad.sh": "exec_bit", "templates/base/other/bad.sh": "exec_bit",
        "x/link": "symlink", "x/dirlink": "symlink", "sub/inner": "submodule", "sub/g2": "submodule", ".gitmodules": "submodule", "x/pipe": "special_file"}
for f, k in sorted(want.items()):
    check("filetype %s: %s" % (k, f), has(j, "filetype", k, f), [x for x in j["findings"] if x["file"] == f])
okfiles = ["x/ok.plist.in", "x/.env.example", "x/edge.txt", (B + "ok"), "hooks/ok", ".githooks/ok", "templates/base/hooks/ok.sh", "templates/base/.githooks/ok", "templates/base/.claude/hooks/ok.sh", "templates/a/b/.githooks/ok", "tests/ok.sh"]
check("allowed files are not flagged", not [x for x in j["findings"] if x["file"] in okfiles], [x for x in j["findings"] if x["file"] in okfiles])
# nothing outside the tree is read through a symlink
secret_out = TMP / "outside.txt"
secret_out.write_text("x " + SECRETS["github_pat"] + "\n")
t = tree("lnk", {"a.txt": "x"})
os.symlink(str(secret_out), str(t / "evil.txt"))
rc, j, out, err = rj(t, "--no-denylist")
check("a symlink to an outside file is a finding and is not read", has(j, "filetype", "symlink", "evil.txt") and not any(f["check"] == "secrets/builtin" for f in j["findings"]), j["findings"])
# deep tree
p = "deep"
for i in range(chk.MAX_DEPTH + 30):
    p += "/d"
t = TMP / "trees" / "deep"; shutil.rmtree(str(t), ignore_errors=True)
os.makedirs(str(t / p), exist_ok=True) if len(p) < 900 else None
rc, j, out, err = rj(t, "--no-denylist") if t.exists() else (0, {"findings": []}, "", "")
check("deep tree: depth finding, no crash", any(f["kind"] == "depth" for f in j["findings"]), j["findings"][:2])

# ------------------------------------------------------------------ 5. fixtures
fxdir = {"tests/fixtures/a.txt": "alpha\n", "tests/fixtures/sub/b.txt": "beta\n", "tests/fixtures/new.txt": "new\n"}
t = tree("fx", fxdir)
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
(ws_rel / "fixtures-reviewed.txt").write_text("# reviewed\n%s  tests/fixtures/a.txt\n%s tests/fixtures/sub/b.txt\n%s tests/fixtures/gone.txt\n" % (sha("alpha\n"), sha("OTHER\n"), sha("x")))
rc, j, out, err = rj(t, "--no-denylist")
check("fixtures: unreviewed and changed are findings", has(j, "fixtures", "unreviewed", "tests/fixtures/new.txt") and has(j, "fixtures", "changed", "tests/fixtures/sub/b.txt") and not has(j, "fixtures", "changed", "tests/fixtures/a.txt"), j["findings"])
(ws_rel / "fixtures-reviewed.txt").write_text("\n".join("%s  %s" % (sha(v), k) for k, v in fxdir.items()) + "\n")
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("fixtures: all reviewed -> 'PASS fixtures 3/3 reviewed'", "PASS fixtures 3/3 reviewed" in out and rc == 0, out)
(ws_rel / "fixtures-reviewed.txt").write_text("not a list\n")
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("fixtures: malformed list is a usage error (exit 2)", rc == 2, (rc, err))
(ws_rel / "fixtures-reviewed.txt").unlink()
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("fixtures: no list -> SKIP line", "SKIP fixtures (release/fixtures-reviewed.txt not found)" in out and rc == 0, out)

# ------------------------------------------------------------------ 6. closure
t = tree("closure", {(B + "real"): "x", "a/one.md": "run " + B + "real and " + B + "ghost-tool now\n./" + B + "ghost2.\n/usr/" + B + "env ~/.local/" + B + "shipm node_modules/." + B + "x\n" + B + "ghost-*\n",
                     "a/two.md": "call hooks/" + "legacy-thing.sh and .claude/hooks/ok.sh\n", "a/three.md": "see @SHIPMIRACLE_ENGINE@/docs/" + "STATUS.md and @SHIPMIRACLE_ENGINE@/docs/" + "plans/x and ${WS}/" + B + "ghost3\nproject docs/" + "STATUS.md is fine\n"})
rc, j, out, err = rj(t, "--no-denylist")
check("closure: missing bin tool found with line", has(j, "closure", "missing_bin", "a/one.md", 1) and has(j, "closure", "missing_bin", "a/one.md", 2), j["findings"])
check("closure: existing bin tool, /usr/bin, .local/bin, .bin, wildcard not flagged", len([f for f in j["findings"] if f["check"] == "closure" and f["file"] == "a/one.md"]) == 2, [f for f in j["findings"] if f["file"] == "a/one.md"])
check("closure: hooks/*.sh missing, .claude/hooks ignored", has(j, "closure", "missing_hook", "a/two.md", 1) and len([f for f in j["findings"] if f["file"] == "a/two.md"]) == 1, j["findings"])
check("closure: anchored private docs and variable-anchored bin flagged, plain project docs not", has(j, "closure", "private_doc", "a/three.md", 1) and len([f for f in j["findings"] if f["file"] == "a/three.md" and f["kind"] == "private_doc"]) == 2 and has(j, "closure", "missing_bin", "a/three.md", 1) and not any(f["line"] == 2 for f in j["findings"] if f["file"] == "a/three.md"), [f for f in j["findings"] if f["file"] == "a/three.md"])

# closure exemptions (release/closure-exempt.txt): exact path + target, substring of the line, no line numbers
t = tree("closure-ex", {"docs/m.md": "intro\n- `" + HK + "ghost.sh` enforces the flow\n- also " + HK + "ghost.sh runs elsewhere\nrun " + B + "ghost-tool\n", "docs/n.md": "`" + HK + "ghost.sh` enforces the flow\n"})
def cl(ex):
    r = chk.scan(t, inputs=chk.Inputs(closure_exempt=chk.parse_closure_exempt(ex)))
    return [(f.file, f.line, f.kind) for f in r.findings if f.check == "closure"], r.passes.get("closure")
base_, _ = cl("")
check("closure exempt: without an entry all four references are findings", len(base_) == 4, base_)
got, note = cl("# why\ndocs/m.md | " + HK + "ghost.sh | enforces the flow\n")
check("closure exempt: only the reviewed line of the reviewed file is exempt (other line, other file, other target still flagged)",
      ("docs/m.md", 2, "missing_hook") not in got and ("docs/m.md", 3, "missing_hook") in got and ("docs/n.md", 1, "missing_hook") in got
      and ("docs/m.md", 4, "missing_bin") in got and len(got) == 3, got)
check("closure exempt: the pass note counts used entries", note == "(1 reviewed exemption used)", note)
got, note = cl("docs/m.md | " + HK + "ghost.sh | enforces the flow\ndocs/m.md | " + HK + "other.sh | enforces\n")
check("closure exempt: an unused entry is counted, not silently ignored", "1 unused" in (note or ""), note)
got, _ = cl("docs/m.md | " + HK + "ghost.sh | no such text\n")
check("closure exempt: a line text that does not match exempts nothing", len(got) == 4, got)
for bad in ("docs/m.md | " + HK + "ghost.sh\n", "/abs | a | b\n", "../x | a | b\n", "a | | b\n"):
    try:
        chk.parse_closure_exempt(bad); ok_ = False
    except ShipmiracleError:
        ok_ = True
    check("closure exempt: malformed entry refused: %r" % bad.strip(), ok_)
t.joinpath("docs/m.md").write_text("new first line\nintro\n- `" + HK + "ghost.sh` enforces the flow\n")
r = chk.scan(t, inputs=chk.Inputs(closure_exempt=chk.parse_closure_exempt("docs/m.md | " + HK + "ghost.sh | enforces the flow\n")))
check("closure exempt: survives a line-number shift", not [f for f in r.findings if f.check == "closure" and f.file == "docs/m.md"])

# ------------------------------------------------------------------ 7. version
t = tree("ver", {"shipmiracle/__init__.py": '__version__ = "0.1.0"\n', "CHANGELOG.md": "# Changelog\n## Unreleased\n## [0.1.0] - 2026-10-20\n"})
(ws_rel / "VERSION").write_text("0.1.0\n")
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("version: triple agrees -> PASS version 0.1.0", "PASS version 0.1.0" in out and rc == 0, out)
(ws_rel / "VERSION").write_text("0.2.0\n")
rc, j, out, err = rj(t, "--no-denylist")
check("version: mismatch is a finding without values leaking", has(j, "version", "mismatch", None) and any(f["check"] == "version" and f["kind"] == "mismatch" for f in j["findings"]) and rc == 1, j["findings"])
(ws_rel / "VERSION").unlink()
t2 = tree("ver2", {"a.txt": "x"})
rc, out, err = run(["release-check", "--tree", str(t2), "--no-denylist"])
check("version: inputs missing -> SKIP version", "SKIP version (" in out and rc == 0, out)
(ws_rel / "overlay").mkdir(exist_ok=True)
(ws_rel / "overlay" / "CHANGELOG.md").write_text("## 0.3.0\n")
(ws_rel / "VERSION").write_text("0.3.0")
t3 = tree("ver3", {"shipmiracle/__init__.py": "__version__ = '0.3.0'\n"})
rc, out, err = run(["release-check", "--tree", str(t3), "--no-denylist"])
check("version: overlay CHANGELOG + VERSION + tree __version__", "PASS version 0.3.0" in out, out)
shutil.rmtree(str(ws_rel / "overlay")); (ws_rel / "VERSION").unlink()

# ------------------------------------------------------------------ 8. gitleaks seam
STUB = TMP / "stub-gitleaks"
SAMPLE = (ROOT / "tests" / "fixtures" / "release" / "gitleaks-report.sample.json").read_text()


def make_stub(mode="ok"):
    body = '''#!/usr/bin/env python3
import sys, json, os
a = sys.argv[1:]
open(os.environ["STUB_LOG"], "a").write(" ".join(a[:1]) + "\\n")
if %r == "dir_unknown" and a[0] == "dir":
    sys.exit(126)
if %r == "broken":
    sys.exit(126)
tree = a[1] if a[0] == "dir" else a[a.index("--source") + 1]
rep = a[a.index("--report-path") + 1]
s = %r.replace("@TREE@", tree)
d = json.loads(s)
d[0]["Secret"] = %r
d[0]["Match"] = "key=" + %r
open(rep, "w").write(json.dumps(d))
print("gitleaks stdout noise " + %r)
sys.stderr.write("noise " + %r)
sys.exit(1)
''' % (mode, mode, SAMPLE, SECRETS["github_pat"], SECRETS["github_pat"], SECRETS["github_pat"], SECRETS["github_pat"])
    STUB.write_text(body)
    os.chmod(str(STUB), 0o755)


t = tree("gl", {"src/app.txt": "one\ntwo\nthree\n"})
for mode in ("ok", "dir_unknown"):
    make_stub(mode)
    (TMP / "stub.log").write_text("")
    rc, j, out, err = rj(t, "--no-denylist", SHIPMIRACLE_GITLEAKS_BIN=str(STUB), STUB_LOG=str(TMP / "stub.log"))
    check("gitleaks (%s): finding kept as RuleID/file/line only" % mode, rc == 1 and has(j, "secrets/gitleaks", "generic-api-key", "src/app.txt", 3), (rc, j and j["findings"], err))
    check("gitleaks (%s): its secret, noise and report are not echoed" % mode, SECRETS["github_pat"] not in out + err and not list(pathlib.Path(tempfile.gettempdir()).glob("shipmiracle-gl-*")))
make_stub("dir_unknown")
check("older gitleaks: falls back to `detect --no-git --source`", (TMP / "stub.log").read_text().split() == ["dir", "detect"], (TMP / "stub.log").read_text())
make_stub("broken")
rc, j, out, err = rj(t, "--no-denylist", SHIPMIRACLE_GITLEAKS_BIN=str(STUB), STUB_LOG=str(TMP / "stub.log"))
check("broken gitleaks: SKIP not FAIL", rc == 0 and any(s["check"] == "secrets/gitleaks" for s in j["skipped"]), (rc, j))
rc, j, out, err = rj(t, "--no-denylist", "--require-gitleaks", SHIPMIRACLE_GITLEAKS_BIN=str(STUB), STUB_LOG=str(TMP / "stub.log"))
check("broken gitleaks + --require-gitleaks: FAIL", rc == 1 and has(j, "secrets/gitleaks", "unavailable", None), (rc, j["findings"]))
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("gitleaks not installed: SKIP line, builtin scan still runs, exit 0", rc == 0 and "SKIP secrets/gitleaks (gitleaks not installed)" in out and "PASS secrets/builtin" in out, out)
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist", "--require-gitleaks"])
check("gitleaks not installed + --require-gitleaks: FAIL, exit 1", rc == 1 and "FAIL secrets/gitleaks kind=missing" in out, (rc, out))

# ------------------------------------------------------------------ 9. exit codes and stamp
rc, out, err = run(["release-check", "--tree", str(TMP / "does-not-exist")])
check("exit 3: tree missing", rc == 3 and "does-not-exist" in err, (rc, err))
rc, out, err = run(["release-check", "--tree", str(TMP / "trees" / "clean" / "README.md")])
check("exit 3: tree is a file", rc == 3, (rc, err))
rc, out, err = run(["release-check"])
check("exit 3: no --tree and the dry-run export cannot be built (workspace is not a git repo)", rc == 3 and "--tree" in err, (rc, err))
rc, out, err = run(["release-check", "--tree", str(clean), "--bogus"])
check("exit 2: unknown option", rc == 2, (rc, err))
write_deny(ENTRIES)
t = tree("stamp", {"README.md": "x\n"})
rc, j, out, err = rj(t)
stamp = TMP / "state" / "v1" / "release" / ("check-%s.json" % j["tree_sha"])
st_ok = stamp.is_file() and stat.S_IMODE(stamp.stat().st_mode) == 0o600 and stat.S_IMODE(stamp.parent.stat().st_mode) == 0o700
check("PASS writes the 0600 stamp check-<tree_sha>.json", rc == 0 and st_ok, (rc, list((TMP / "state").rglob("*"))))
sj = json.loads(stamp.read_text())
check("stamp content: result, tree_sha, ts, flags", sj["result"] == "PASS" and sj["tree_sha"] == j["tree_sha"] and sj["flags"]["denylist_used"] is True and isinstance(sj["ts"], int), sj)
t = tree("nostamp", {"a.jsonl": "x"})
rc, j2, out, err = rj(t)
check("FAIL writes no stamp", rc == 1 and not (TMP / "state" / "v1" / "release" / ("check-%s.json" % j2["tree_sha"])).exists())
# tree_sha equals git write-tree
G = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e.invalid", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@e.invalid", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
gt = tree("gitsha", {"README.md": "hello\n", (B + "tool"): "#!/bin/sh\n", "a/b/c.txt": "deep\n", "a/b.txt": "x\n", "a-b.txt": "dash\n", "empty/.keep": ""}, {(B + "tool"): 0o755})
os.symlink("README.md", str(gt / "lnk"))
subprocess.run(["git", "init", "-q", str(gt)], env=G, check=True)
subprocess.run(["git", "-C", str(gt), "add", "-A"], env=G, check=True)
want_sha = subprocess.run(["git", "-C", str(gt), "write-tree"], env=G, check=True, stdout=subprocess.PIPE).stdout.decode().strip()
rc, j, out, err = rj(gt, "--no-denylist")
check("tree_sha equals `git write-tree` of the same work tree (.git skipped)", j["tree_sha"] == want_sha, (j["tree_sha"], want_sha))
empty = tree("empty", {})
rc, j, out, err = rj(empty, "--no-denylist")
check("empty tree sha is git's empty tree", j["tree_sha"] == "4b825dc642cb6eb9a060e54bf8d69288fbee4904", j["tree_sha"])

# ------------------------------------------------------------------ 10. denylist safety
t = tree("safe", {"a.txt": "x"})
write_deny(ENTRIES, mode=0o640)
rc, out, err = run(["release-check", "--tree", str(t)])
check("group-readable denylist: exit 4, no scan output", rc == 4 and out == "" and "0600" in err, (rc, out, err))
rc, out, err = run(["release", "denylist", "--show-hashes"])
check("group-readable denylist: --show-hashes exit 4", rc == 4, (rc, err))
write_deny(ENTRIES)
os.chmod(str(CFG), 0o755)
rc, out, err = run(["release-check", "--tree", str(t)])
check("group-readable folder: exit 4", rc == 4 and "0700" in err, (rc, err))
rc, out, err = run(["release-check", "--tree", str(t), "--no-denylist"])
check("--no-denylist never reads the file (unsafe denylist ignored)", rc == 0, (rc, err))
os.chmod(str(CFG), 0o700)
real = DENY.read_text(); DENY.unlink(); other = TMP / "other.txt"; other.write_text(real); os.chmod(str(other), 0o600); os.symlink(str(other), str(DENY))
rc, out, err = run(["release-check", "--tree", str(t)])
check("symlinked denylist: exit 4", rc == 4, (rc, err))
DENY.unlink()
# inside a git work tree
gcfg = TMP / "gitcfg"; (gcfg / ".git").mkdir(parents=True); os.chmod(str(gcfg), 0o700)
(gcfg / dl.FILENAME).write_text("# salt: %s\nname\t%s\n" % (SALT, NAME)); os.chmod(str(gcfg / dl.FILENAME), 0o600)
rc, out, err = run(["release-check", "--tree", str(t)], SHIPMIRACLE_CONFIG=str(gcfg))
check("denylist inside a git work tree: exit 4", rc == 4 and "git work tree" in err, (rc, err))
shutil.rmtree(str(gcfg / "sub"), ignore_errors=True)
sub = gcfg / "sub"
rc, out, err = run(["release", "denylist", "--refresh"], SHIPMIRACLE_CONFIG=str(sub / "deeper"))
check("--refresh inside a git work tree refuses (exit 4) and writes nothing", rc == 4 and not (sub / "deeper").exists(), (rc, err))

# ------------------------------------------------------------------ 11. refresh (injected provider)


class FakeProvider(object):
    calls = 0

    def collect(self):
        FakeProvider.calls += 1
        return {"entries": [("name", NAME), ("email", EMAIL), ("handle", HANDLE), ("project", PROJECT), ("host", HOST), ("name", "ab"),
                            ("project", "ideas"), ("project", "Home"), ("id", "9988776"), ("name", NAME.upper())],
                "notes": ["gh unavailable: handle/name/email/id from GitHub not added"], "author": (HANDLE, "9988776+%s@users.noreply.github.com" % HANDLE)}


shutil.rmtree(str(CFG), ignore_errors=True)
rcli.PROVIDER = FakeProvider()
rc, out, err = run(["release", "denylist", "--refresh"])
check("refresh: exit 0, counts printed, no values", rc == 0 and "denylist written: 6 entries (email=1, handle=1, host=1, id=1, name=1, project=1)" in out and "note: gh unavailable" in out, (rc, out, err))
check("refresh: file 0600 in a 0700 folder with a 32-hex salt", stat.S_IMODE(DENY.stat().st_mode) == 0o600 and stat.S_IMODE(CFG.stat().st_mode) == 0o700 and DENY.read_text().startswith("# salt: ") and dl.SALT_RE.fullmatch(DENY.read_text().split("\n")[0][8:]), (oct(DENY.stat().st_mode), DENY.read_text()[:60]))
txt = DENY.read_text()
check("refresh: stoplist and short values never written", "\tideas" not in txt and "\tHome" not in txt and "\tab" not in txt)
salt1 = txt.split("\n")[0]
DENY.write_text(txt + "!Glimmerwood-Station\nmanual\tHandwritten-Value\n")
rc, out, err = run(["release", "denylist", "--refresh"])
txt2 = DENY.read_text()
check("refresh keeps the salt, '!' lines and manual entries; the exclusion applies", txt2.split("\n")[0] == salt1 and "!Glimmerwood-Station" in txt2 and "manual\tHandwritten-Value" in txt2 and PROJECT not in [v for _, v in dl.load(DENY).entries] and rc == 0)
rc, out, err = run(["release", "denylist", "--show-hashes"])
lines = [l for l in out.splitlines() if l]
salt = salt1[8:]
check("--show-hashes prints kind<TAB>hash only", rc == 0 and all(len(l.split("\t")) == 2 and len(l.split("\t")[1]) == 8 for l in lines) and ("name\t" + dl.entry_hash(salt, "name", NAME)) in lines and NAME not in out and EMAIL not in out and HANDLE not in out, (rc, out))
rc, out, err = run(["release", "denylist"])
check("status without flags prints counts only", rc == 0 and out.startswith("denylist: ") and NAME not in out, out)
rcli.PROVIDER = None
# owner only
before = DENY.read_text()
FakeProvider.calls = 0
rcli.PROVIDER = FakeProvider()
rc, out, err = run(["release", "denylist", "--refresh"], CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
check("--refresh inside a Claude chat: exit 4, nothing collected or written", rc == 4 and FakeProvider.calls == 0 and DENY.read_text() == before, (rc, err))
rc, out, err = run(["release", "denylist", "--show-hashes"], CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
check("--show-hashes is read-only (allowed in a chat)", rc == 0)
rcli.PROVIDER = None
shutil.rmtree(str(CFG), ignore_errors=True)
rc, out, err = run(["release", "denylist", "--show-hashes"])
check("no denylist yet: exit 3 with the refresh hint", rc == 3 and "--refresh" in err, (rc, err))
rc, out, err = run(["release", "nothing"])
check("unknown release action: exit 2", rc == 2)
# a refresh hardens an existing 0755 folder we own
CFG.mkdir(); os.chmod(str(CFG), 0o755)
rcli.PROVIDER = FakeProvider()
rc, out, err = run(["release", "denylist", "--refresh"])
check("refresh tightens our own 0755 folder to 0700", rc == 0 and stat.S_IMODE(CFG.stat().st_mode) == 0o700, (rc, err))
rcli.PROVIDER = None

# ------------------------------------------------------------------ 12. hostile inputs
write_deny(ENTRIES)
t0 = time.time()
big = TMP / "trees" / "many"; shutil.rmtree(str(big), ignore_errors=True)
for i in range(50000):
    d = big / ("d%03d" % (i // 500))
    if i % 500 == 0:
        d.mkdir(parents=True)
    (d / ("f%d.txt" % i)).write_text("line %d of some ordinary text\nanother line\n" % i)
mk = time.time() - t0
t0 = time.time()
rc, j, out, err = rj(big)
el = time.time() - t0
check("50k files scanned (with denylist) in a sensible time", rc == 0 and j["counts"]["files"] == 50000 and el < 120, (rc, el, mk))
print("INFO 50k files: scan %.1fs (create %.1fs)" % (el, mk))
shutil.rmtree(str(big), ignore_errors=True)
t = tree("hostile", {"huge.bin": b"\0" * (30 * 1024 * 1024), "huge.txt": b"a" * (30 * 1024 * 1024), "lines.txt": ("x" * 100000 + "\n") * 2,
                     "weird\nname.txt": "ok\n", "bad-utf8.txt": b"\xff\xfe\xfdabc\n", "empty.txt": ""})
t0 = time.time()
rc, j, out, err = rj(t)
check("huge/binary/odd-name files: no crash, findings, fast", rc == 1 and has(j, "filetype", "too_large", "huge.txt") and has(j, "filetype", "too_large", "huge.bin") and time.time() - t0 < 30, (rc, time.time() - t0))
check("control characters in a file name cannot forge output lines", all(l.split(" ", 1)[0] in ("PASS", "FAIL", "SKIP", "RESULT") for l in run(["release-check", "--tree", str(t)])[1].splitlines()))
shutil.rmtree(str(t), ignore_errors=True)

# ------------------------------------------------------------------ 13. canary text never leaks
write_deny(ENTRIES)
t = tree("all", dict(files, **{"s/%s.txt" % k: "k %s\n" % v for k, v in SECRETS.items()}, **{"docs/%s.md" % NAME.replace(" ", "-"): NAME}))
make_stub("ok")
(TMP / "stub.log").write_text("")
outs = []
for fl in ([], ["--json"]):
    rc, out, err = run(["release-check", "--tree", str(t)] + fl, SHIPMIRACLE_GITLEAKS_BIN=str(STUB), STUB_LOG=str(TMP / "stub.log"))
    outs += [out, err]
blob = "\n".join(outs + LOG)
for p in (TMP / "state").rglob("*"):
    if p.is_file():
        blob += p.read_text(errors="replace")
leaked = [c for c in CANARIES if c in blob or c.lower() in blob.lower()]
check("canary text never appears in stdout, stderr, json, stamps or logs (%d outputs)" % len(LOG), not leaked, leaked)
# exceptions raised by the library carry no values
try:
    dl.parse("name\t%s\n" % NAME)
except ShipmiracleError as e:
    check("a denylist without salt raises a message that has no value", NAME not in str(e), str(e))
try:
    dl.check_safe(DENY.parent / "nope.txt")
except FileNotFoundError:
    check("check_safe on a missing file raises FileNotFoundError", True)
except ShipmiracleError as e:
    check("check_safe on a missing file raises FileNotFoundError", False, e)

# ------------------------------------------------------------------ 14. misc: SECRET_RE import is side-effect free, py39, helpers
r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); import shipmiracle.hooks.project as p; print(sorted(m for m in sys.modules if m.startswith('shipmiracle')))" % str(ROOT)],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, SHIPMIRACLE_STATE=str(TMP / "state2"), SHIPMIRACLE_CONFIG=str(TMP / "cfg2")))
check("importing SECRET_RE's module has no side effects (no state/config created, only shipmiracle.hooks modules)", r.returncode == 0 and not (TMP / "state2").exists() and not (TMP / "cfg2").exists() and "release" not in r.stdout.decode(), r.stderr.decode()[-300:])
for f in sorted((ROOT / "shipmiracle" / "release").glob("*.py")):
    src = f.read_text(encoding="utf-8")
    try:
        tr = ast.parse(src, filename=str(f), feature_version=(3, 9))
        fut = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names) for n in tr.body)
        check("py39: %s parses and has the __future__ import" % f.name, fut)
    except SyntaxError as e:
        check("py39: %s parses" % f.name, False, e)
rc, out, err = run(["release-check", "--help"])
check("--help works (exit 0)", rc == 0 and "--require-gitleaks" in out)
r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "release-check", "--tree", str(clean), "--no-denylist"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   env=dict(os.environ))
check("bin/shipm release-check end to end (subprocess)", r.returncode == 0 and b"RESULT PASS" in r.stdout, (r.returncode, r.stdout[-200:], r.stderr[-200:]))

# ---- 21 Oct 2026: isolation lint (tests that run shipmiracle/hooks/browsers must go through the shared isolation) ----
def iso(files):
    rep = chk.scan(tree("iso", files), inputs=chk.Inputs())
    return [f for f in rep.findings if f.check == "isolation"], rep
RUN_BAD = "import subprocess\nsubprocess.run(['" + B + "shipm', 'sync'])\n"
f, _ = iso({"tests/x_test.py": RUN_BAD})
check("isolation lint: a test that runs bin/shipm without the helper or the full sandbox -> isolation/unisolated_exec with file:line", len(f) == 1 and f[0].kind == "unisolated_exec" and f[0].file == "tests/x_test.py" and f[0].line == 1, [x.text() for x in f])
f, _ = iso({"tests/x_test.py": "import os, subprocess\nos.environ['HOME'] = '/tmp/x'\nsubprocess.run(['" + B + "shipm'])\n"})
check("isolation lint: HOME alone is not enough (the 21 Oct incident)", len(f) == 1, [x.text() for x in f])
f, _ = iso({"tests/x_test.py": "import shipmiracle_isolation\n" + RUN_BAD})
check("isolation lint: importing the shared helper passes", f == [], [x.text() for x in f])
f, _ = iso({"tests/x_test.py": "from shipmiracle_timing import timed\n" + RUN_BAD})
check("isolation lint: shipmiracle_timing (a shared helper) passes", f == [], [x.text() for x in f])
f, _ = iso({"tests/x_test.py": "ENV = dict(SHIPMIRACLE_TEST='1', SHIPMIRACLE_HOME=h, SHIPMIRACLE_STATE=s, SHIPMIRACLE_CONFIG=c, HOME=h)\n" + RUN_BAD})
check("isolation lint: setting the whole sandbox (SHIPMIRACLE_TEST, SHIPMIRACLE_HOME, SHIPMIRACLE_STATE, SHIPMIRACLE_CONFIG, HOME) passes", f == [], [x.text() for x in f])
f, _ = iso({"tests/x_test.py": "ENV = dict(SHIPMIRACLE_TEST='1', SHIPMIRACLE_HOME=h, SHIPMIRACLE_STATE=s)\n" + RUN_BAD})
check("isolation lint: a partial sandbox (no SHIPMIRACLE_CONFIG, no HOME) fails", len(f) == 1, [x.text() for x in f])
f, _ = iso({"tests/x_test.py": "import subprocess\nsubprocess.run(['git', 'status'])\n", "tests/y_test.py": "# runs " + B + "shipm in the docs only\nprint(1)\n"})
check("isolation lint: git-only subprocess and a mere mention are not 'executing Shipmiracle'", f == [], [x.text() for x in f])
f, _ = iso({"tests/fixtures/a.py": RUN_BAD, "tests/fakes/b.py": RUN_BAD, "tests/private/c.py": RUN_BAD, "tests/shipmiracle_isolation.py": RUN_BAD, "tests/chrome_helper.js": "spawn(" + "CHROME, [])\n"})
check("isolation lint: fixtures, fakes, private and the helpers themselves are exempt", f == [], [x.text() for x in f])
f, _ = iso({"tests/u_test.js": "const { spawn } = require('child_process');\nconst c = spawn(" + "CHROME, ['--headless=new']);\n"})
check("isolation lint: a browser spawned without tests/chrome_helper.js -> isolation/unisolated_browser", [x.kind for x in f] == ["unisolated_browser"] and f[0].line == 2, [x.text() for x in f])
f, _ = iso({"tests/u_test.js": "const H = require('./chrome_helper');\nconst r = H.launch({});\n"})
check("isolation lint: a browser through chrome_helper passes", f == [], [x.text() for x in f])
f, _ = iso({"tests/u_test.js": "const { execFileSync } = require('child_process');\nexecFileSync('/Applications/Google " + "Chrome.app/Contents/MacOS/Google Chrome', []);\n"})
check("isolation lint: a Chrome path in execFileSync is a browser launch", [x.kind for x in f] == ["unisolated_browser"], [x.text() for x in f])
f, rep = iso({"tests/x_test.py": RUN_BAD})
check("isolation lint: the finding is in the FAIL line and the result is FAIL", rep.result == "FAIL" and any(l.startswith("FAIL isolation kind=unisolated_exec tests/x_test.py:1") for l in rep.lines()), rep.lines())
# L10 canaries: a helper or sandbox that is only MENTIONED (comment, string, docstring) is not isolation; more launch shapes; .mjs / .cjs
CANARY = [("py comment names the helper", "tests/c_test.py", "# import shipmiracle_isolation  (TODO)\n" + RUN_BAD, 1),
          ("py string names the helper", "tests/c_test.py", 'NOTE = "shipmiracle_isolation"\n' + RUN_BAD, 1),
          ("py docstring names the helper", "tests/c_test.py", '"""uses shipmiracle_isolation and setup_fixture"""\n' + RUN_BAD, 1),
          ("py sandbox names only in a message", "tests/c_test.py", 'print("SHIPMIRACLE_TEST SHIPMIRACLE_HOME SHIPMIRACLE_STATE SHIPMIRACLE_CONFIG HOME")\n' + RUN_BAD, 1),
          ("py sandbox names only in a comment", "tests/c_test.py", "# SHIPMIRACLE_TEST=1 SHIPMIRACLE_HOME=x SHIPMIRACLE_STATE=x SHIPMIRACLE_CONFIG=x HOME=x\n" + RUN_BAD, 1),
          ("py asyncio.create_subprocess_exec", "tests/c_test.py", "import asyncio\nasyncio.create_subprocess_exec('" + B + "shipm', 'sync')\n", 1),
          ("py os.popen", "tests/c_test.py", "import os\nos.popen('" + B + "shipm sync')\n", 1),
          ("js child_process.exec( in .mjs", "tests/c_test.mjs", "import cp from 'child_process';\ncp.exec('" + B + "shipm sync');\n", 1),
          ("js execSync in .cjs", "tests/c_test.cjs", "const { execSync } = require('child_process');\nexecSync('" + B + "shipm sync');\n", 1),
          ("js comment names the helper", "tests/c_test.js", "// require('./shipmiracle_isolation').apply();\nconst { execSync } = require('child_process');\nexecSync('" + B + "shipm sync');\n", 1),
          ("py string literal that looks like an import", "tests/c_test.py", 'print(" import shipmiracle_isolation")\n' + RUN_BAD, 1),
          ("py string literal that looks like env keys", "tests/c_test.py", 'print("SHIPMIRACLE_TEST: SHIPMIRACLE_HOME: SHIPMIRACLE_STATE: SHIPMIRACLE_CONFIG: HOME:")\n' + RUN_BAD, 1),
          ("py dict-looking text inside a string", "tests/c_test.py", 'X = "{SHIPMIRACLE_TEST: 1, SHIPMIRACLE_HOME: 2, SHIPMIRACLE_STATE: 3, SHIPMIRACLE_CONFIG: 4, HOME: 5}"\n' + RUN_BAD, 1),
          ("js string literal that looks like a require", "tests/c_test.cjs", "console.log(\"require('./shipmiracle_isolation')\");\nconst { execSync } = require('child_process');\nexecSync('" + B + "shipm sync');\n", 1),
          ("js string literal that looks like env keys", "tests/c_test.cjs", "console.log(\"SHIPMIRACLE_TEST: 1 SHIPMIRACLE_HOME: x SHIPMIRACLE_STATE: y SHIPMIRACLE_CONFIG: z HOME: h\");\nconst { execSync } = require('child_process');\nexecSync('" + B + "shipm sync');\n", 1),
          ("js env object with the whole sandbox (control)", "tests/c_test.cjs", "const env = { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_HOME: h, SHIPMIRACLE_STATE: s, 'SHIPMIRACLE_CONFIG': c, HOME: h };\nconst { execSync } = require('child_process');\nexecSync('" + B + "shipm sync', { env });\n", 0),
          ("py env keys via update(kwargs) and a subscript (control)", "tests/c_test.py", "import os\nos.environ.update(SHIPMIRACLE_TEST='1', SHIPMIRACLE_HOME='h')\nos.environ['SHIPMIRACLE_STATE'] = 's'\nE = {'SHIPMIRACLE_CONFIG': 'c', 'HOME': 'h'}\n" + RUN_BAD, 0),
          ("py import of the helper (control)", "tests/c_test.py", "import os, sys; sys.path.insert(0, '.'); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()\n" + RUN_BAD, 0),
          ("js require of the helper in .cjs (control)", "tests/c_test.cjs", "require('./shipmiracle_isolation').apply();\nconst { execSync } = require('child_process');\nexecSync('" + B + "shipm sync');\n", 0),
          ("py whole sandbox as env keys (control)", "tests/c_test.py", "E = dict(SHIPMIRACLE_TEST='1', SHIPMIRACLE_HOME='h', SHIPMIRACLE_STATE='s', SHIPMIRACLE_CONFIG='c', HOME='h')\n" + RUN_BAD, 0)]
for name, rel, body, want in CANARY:
    f, _ = iso({rel: body})
    check("isolation lint canary: %s -> %d finding(s)" % (name, want), len([x for x in f if x.kind == "unisolated_exec"]) == want, [x.text() for x in f])
real = [x for x in chk.scan(ROOT, inputs=chk.Inputs()).findings if x.check == "isolation"] if (ROOT / "tests").is_dir() else []
check("isolation lint: every tests/** file of this very tree passes", real == [], [x.text() for x in real][:5])

# ---- 21 Oct 2026: release-check reads its inputs from the tree being checked ----
EX = "# reviewed\ndocs/standards/base.md | " + HK + "flow-gate.sh | enforces the flow\n"
BASE_MD = "Rules.\nThe flow is what " + HK + "flow-gate.sh enforces the flow.\n"
t_in = tree("inputs", {"docs/standards/base.md": BASE_MD, "release/closure-exempt.txt": EX, "release/VERSION": "0.1.0\n", "shipmiracle/__init__.py": "__version__ = '0.1.0'\n"})
empty_ws = TMP / "empty-ws"; (empty_ws / "release").mkdir(parents=True, exist_ok=True)
inp = chk.load_inputs_for_tree(t_in, empty_ws / "release")
rep = chk.scan(t_in, inputs=inp)
check("tree inputs: with release/closure-exempt.txt in the tree and an EMPTY workspace release folder, the reviewed closure reference is exempt", not [f for f in rep.findings if f.check == "closure"], [f.text() for f in rep.findings])
rep = chk.scan(t_in, inputs=chk.load_inputs(empty_ws / "release"))
check("tree inputs: without the tree's list the same tree reports the closure finding (the public CI bug)", any(f.check == "closure" for f in rep.findings), [f.text() for f in rep.findings])
check("tree inputs: VERSION and fixtures lists of the tree win over the workspace's", inp.version == "0.1.0", inp.version)
t_in2 = tree("inputs2", {"docs/standards/base.md": BASE_MD, "tests/fixtures/a.txt": "alpha\n", "release/fixtures-reviewed.txt": "%s  tests/fixtures/a.txt\n" % sha("alpha\n")})
rep = chk.scan(t_in2, inputs=chk.load_inputs_for_tree(t_in2, empty_ws / "release"))
check("tree inputs: the tree's reviewed-fixtures list is used (fixture is reviewed -> no fixtures finding)", not [f for f in rep.findings if f.check == "fixtures"], [f.text() for f in rep.findings])

# ------------------------------------------------------------------ 13. refresh skips common words (30 Oct 2026) and the reviewed login exemption
GEN = "san" + "dbox"          # the common word a project can be named; built from parts so this file stays plain


class GenericProvider(object):
    def collect(self):
        return {"entries": [("project", GEN), ("project", GEN.capitalize()), ("project", "Demo"), ("project", "Silverfen-Atlas"), ("handle", "zqlogin88x"), ("user", "zqlogin88x")],
                "notes": [], "author": None}


shutil.rmtree(str(CFG), ignore_errors=True)
rcli.PROVIDER = GenericProvider()
rc, out, err = run(["release", "denylist", "--refresh"])
txt = DENY.read_text()
check("refresh: a project named like a common word is skipped and the report names the word and the reason", rc == 0 and ("project\t" + GEN) not in txt.lower() and "project\tdemo" not in txt.lower() and "project\tSilverfen-Atlas" in txt
      and ("skipped (common word, not added): demo, %s" % GEN) in out and "project=1" in out, (rc, out))
check("refresh: a skipped word is the built-in term only (the line never carries other text)", all(l.startswith("note: ") or l.startswith("denylist written") or l.startswith("skipped (common word") for l in out.splitlines()), out)
rc, out, err = run(["release", "denylist", "--refresh", "--include-generic", GEN])
txt = DENY.read_text()
check("refresh: --include-generic NAME force-includes the skipped word (and only that one)", rc == 0 and ("project\t" + GEN) in txt.lower() and "project\tdemo" not in txt.lower() and "skipped (common word, not added): demo" in out and GEN not in out.split("skipped")[-1], (rc, out))
check("refresh: the force-included word is a normal entry that the strict check flags again", any(k == "project" and dl.norm(v) == GEN for k, v in dl.load(DENY).entries))
rc, out, err = run(["release", "denylist", "--refresh", "--include-generic", "Silverfen-Atlas"])
check("refresh: --include-generic with a name that is not a built-in common word is a usage error (exit 2), nothing written", rc == 2 and "not a built-in common word" in err, (rc, err))
for w in ("sandbox", "ideas", "notes", "test", "demo", "app", "web", "site", "docs", "tmp", "example"):
    check("stop-list holds %r" % w, w in dl.GENERIC_PROJECT_TERMS, sorted(dl.GENERIC_PROJECT_TERMS))
rcli.PROVIDER = None

LOGIN = "zqlogin88x"
LOGIN_DENY = [("handle", LOGIN), ("user", LOGIN), ("project", PROJECT)]
OK_FILES = ["LICENSE", ".github/CODEOWNERS", ".github/ISSUE_TEMPLATE/config.yml", "README.md"]
check("login exemption table: exactly the four files the owner decided, each with its decision reference", sorted(chk.LOGIN_EXEMPT) == sorted(OK_FILES) and all("D1" in v and "2026-10-" in v for v in chk.LOGIN_EXEMPT.values()), chk.LOGIN_EXEMPT)
write_deny(LOGIN_DENY)
t = tree("login-ok", dict((f, "Copyright (c) 2026 %s\n" % LOGIN) for f in OK_FILES))
rc, j, out, err = rj(t)
check("login (user kind, equal to the handle entry) is exempt in LICENSE, CODEOWNERS, ISSUE_TEMPLATE/config.yml, README.md: 0 identifier findings", not [f for f in (j or {}).get("findings", []) if f["check"] == "identifier"] and LOGIN not in out, (rc, out[:400]))
check("login exemption is shown in the report line", "4 reviewed login exemption" in " ".join(l for l in run(["release-check", "--tree", str(t)])[1].splitlines()), run(["release-check", "--tree", str(t)])[1][:400])
bad = {"docs/x.md": LOGIN, "sub/README.md": LOGIN, "SECURITY.md": LOGIN, "CONTRIBUTING.md": LOGIN, ".github/workflows/ci.yml": LOGIN, ".github/CODEOWNERS.bak": LOGIN, "LICENSE.md": LOGIN, "shipmiracle/x.py": "# %s\n" % LOGIN}
t = tree("login-bad", bad)
rc, j, out, err = rj(t)
check("login in any other file is still a finding (user kind)", rc == 1 and all(has(j, "identifier", "user", f, 1) for f in bad), [(f["file"], f["kind"]) for f in (j or {}).get("findings", [])])
tw = dict((f, LOGIN + "\n") for f in OK_FILES)
tw.update({"docs/x.md": LOGIN + "\n", "release/login-exempt.txt": "docs/x.md\n", "release/closure-exempt.txt": "docs/x.md | docs/x.md | %s\n" % LOGIN, "release/overlay/login.txt": "docs/x.md\n"})
t = tree("login-widen", tw)
rc, j, out, err = rj(t)
check("exemption cannot be widened by repo content: files in the tree that list another path change nothing", has(j, "identifier", "user", "docs/x.md", 1) and not has(j, "identifier", "user", "LICENSE") and not has(j, "identifier", "user", "README.md"), [(f["file"], f["kind"]) for f in (j or {}).get("findings", [])])
write_deny([("user", LOGIN), ("project", PROJECT)])
t = tree("login-nohandle", dict((f, LOGIN + "\n") for f in OK_FILES))
rc, j, out, err = rj(t)
check("a user entry that is not also a handle entry (not a public login) gets no exemption: flagged in every file", rc == 1 and all(has(j, "identifier", "user", f, 1) for f in OK_FILES), [(f["file"], f["kind"]) for f in (j or {}).get("findings", [])])
write_deny([("handle", LOGIN), ("user", "otheruser99"), ("project", PROJECT)])
t = tree("login-other", {"LICENSE": "otheruser99\n"})
rc, j, out, err = rj(t)
check("a different user value is not exempt even in LICENSE", has(j, "identifier", "user", "LICENSE", 1), (rc, out[:300]))
write_deny([("handle", LOGIN), ("user", LOGIN), ("name", LOGIN)])
t = tree("login-name", {"LICENSE": LOGIN + "\n"})
rc, j, out, err = rj(t)
check("only the user kind is exempt: a name entry with the same text is still a finding", has(j, "identifier", "name", "LICENSE", 1) and not has(j, "identifier", "user", "LICENSE"), [(f["file"], f["kind"]) for f in (j or {}).get("findings", [])])
write_deny(ENTRIES)

shutil.rmtree(str(TMP), ignore_errors=True)
print("\n%s: %d failure(s)" % ("FAIL" if fails else "OK", fails))
sys.exit(1 if fails else 0)
