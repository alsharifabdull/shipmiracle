"""flow: the team-flow gate (UserPromptSubmit, PreToolUse, PostToolUse, SubagentStop, Stop) as a dispatcher module (Phase 4a T2).
Everything between the two marker lines is the python part of legacy flow-gate.sh moved over VERBATIM. Allowed differences, checked by
tests/flow_source_sync_test.py: the imports of subprocess, shlex, difflib, unicodedata and hashlib sit in the functions that use them
(lines ending in `# SHIPMIRACLE-LAZY`), and the final `try: main() ... sys.exit(0)` block is the body of `def run()`.
A gate fix must be applied to BOTH files until legacy flow-gate.sh is deleted. The adapter below the second marker runs the gate the way the
old process did (stdin swapped for the raw input, stdout captured, SystemExit caught) and turns its answer into a core.Result."""
from __future__ import annotations

# --- SHIPMIRACLE GATE SOURCE BEGIN (moved verbatim from legacy flow-gate.sh; do not edit outside the allowed differences) ---
import fcntl, glob, json, math, os, pwd, re, sys, time, traceback
HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".local/state/shipmiracle")
if os.environ.get("SHIPMIRACLE_STATE") and any((os.path.realpath(os.environ["SHIPMIRACLE_STATE"]) + "/").startswith(_t) for _t in ("/tmp/", "/private/tmp/", "/private/var/folders/", "/var/folders/", "/var/tmp/", "/private/var/tmp/")):
    STATE = os.environ["SHIPMIRACLE_STATE"]                              # P6 sec M4: SHIPMIRACLE_STATE is honoured only when it names a temp folder (a nested claude cannot point the gate at a folder of its choice)
def _engine_dir():
    """The engine checkout this gate runs from: <engine>/hooks/flow-gate.sh (path in argv[1]) or <engine>/shipmiracle/hooks/flow.py (__file__)."""
    f = globals().get("__file__") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not f:
        return "/nonexistent-shipmiracle-engine"                         # no location known: a path that holds nothing, never a guess
    d = os.path.dirname(os.path.realpath(f))
    return os.path.dirname(d) if os.path.basename(f) == "flow-gate.sh" else os.path.dirname(os.path.dirname(d))
WS = os.environ.get("SHIPMIRACLE_WS") or _engine_dir()
RECORD = re.compile(r"^(docs/(STATUS\.md|DECISIONS\.md|FEATURE-IDEAS\.md|ACCEPTANCE\.md|SKILLS\.md|plans/|memory/|status-archive/)|\.claude/plans/|\.claude/agents-drafts/)", re.I)
ENGINE_OUT = re.compile(r"^(\.shipmiracle/|docs/reports/)")                # P5 T4: written by the playbook engine / reporter, not by the team: never "outside the team", never agent credit
# Old master name -> new function role (resolution only). Copies must equal shipmiracle/agents.ALIASES and vscode-ext/shipmiracle-panel/data.js (tests/flow_gate_roles_test.py).
ALIASES = {"product-analyst": "scoper", "solution-architect": "planner", "frontend-engineer": "builder-frontend", "backend-engineer": "builder-backend", "data-integration-engineer": "builder-backend", "devops-sre": "builder-ops", "qa-engineer": "verifier", "independent-reviewer": "reviewer", "security-reviewer": "reviewer", "ux-designer": "designer"}
DEFAULT_ROLE = {"planner": "plan", "Plan": "plan", "verifier": "test", "reviewer": "review", "scoper": "scope", "designer": "design", "reporter": "report",
                "builder": "build", "builder-frontend": "build", "builder-backend": "build", "builder-ops": "build",
                "engineering-lead": "route",
                "general-purpose": "build"}                      # built-in agent: the only one a chat started before the team existed has
READ_ONLY = {"scope", "plan", "review", "report"}
PRIV = {"plan", "test", "review", "report"}
TEST_PATHS_DEFAULT = ["tests/**", "test/**", "spec/**", "**/__tests__/**", "**/*.test.*", "**/*.spec.*", "**/*_test.*", "**/test_*.py", "**/*Tests/**", "**/tests/**", "**/test/**", "**/conftest.py", "**/testdata/**", "**/*.cy.*", "**/e2e/**"]
SMALL = 10
UL = [False]
QA = ["verifier"]


def shipmiracle_home():
    if os.environ.get("SHIPMIRACLE_TEST") == "1":
        return os.environ.get("SHIPMIRACLE_HOME") or ""
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        return HOME


def shipmiracle_cfg_dir():
    if os.environ.get("SHIPMIRACLE_TEST") == "1":
        return os.environ.get("SHIPMIRACLE_CONFIG") or ""
    h = shipmiracle_home()
    return os.path.join(h, ".config/shipmiracle") if h else ""


def shipmiracle_layout():
    d = shipmiracle_cfg_dir()
    if not d:
        return "legacy"
    try:
        v = json.load(open(os.path.join(d, "config.json"))).get("agents.layout")
    except Exception:
        return "legacy"
    return "userlevel" if isinstance(v, str) and v.strip().lower() == "userlevel" else "legacy"


def reg_entry(pd):
    import hashlib  # SHIPMIRACLE-LAZY
    d = shipmiracle_cfg_dir()
    if not d:
        return None
    try:
        raw = open(os.path.join(d, "registry.json"), "rb").read(8 * 1024 * 1024 + 1)
    except FileNotFoundError:
        return None
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("registry.json is too large")
    j = json.loads(raw.decode("utf-8"))
    if not isinstance(j, dict) or j.get("v") != 1 or not isinstance(j.get("projects"), dict) or any(not isinstance(e, dict) for e in j["projects"].values()):
        raise ValueError("registry.json has an unexpected shape")
    return j["projects"].get(hashlib.sha256(("shipmiracle-project:" + os.path.realpath(pd)).encode("utf-8", "surrogateescape")).hexdigest()[:12])


def worktree_of(pd):
    """P6 T3 (F1): a folder under <DEV>/.worktrees/. None = not under it. ("unknown", "", "") = under it but not a verified worktree of the project
    <DEV>/<p> (forged or foreign .git file, other project, plain folder): gated at the default level, never trusted. ("ok", main project dir, branch) =
    <DEV>/.worktrees/<p>/<x> whose .git FILE (not a symlink) says gitdir: <DEV>/<p>/.git/worktrees/<n> (absolute, no '..', no symlinks, same name <p>)
    and whose admin folder points back at this .git file. Same parse as shipmiracle.paths.main_checkout, no Shipmiracle import."""
    wt_root = fold(os.path.join(DEV, ".worktrees"))
    unk = ("unknown", "", "")
    if not fold(pd).startswith(wt_root + "/"):
        return None
    cur = pd; chain = []
    for _ in range(64):
        par = os.path.dirname(cur)
        if par == cur:
            return unk
        chain.append(cur)
        if fold(par) == wt_root:
            break
        cur = par
    else:
        return unk
    if len(chain) != 2:
        return unk
    p_ = os.path.basename(chain[1]); g_ = os.path.join(pd, ".git")
    try:
        if os.path.islink(g_) or not os.path.isfile(g_):
            return unk
        with open(g_, "rb") as f_:
            first = f_.read(4096).decode("utf-8", "replace").splitlines()[0].strip()
        m_ = re.fullmatch(r"gitdir:\s*(/.+)/\.git/worktrees/([^/]+)/?", first)
        if not m_:
            return unk
        x_, n_ = m_.group(1), m_.group(2)
        if ".." in x_.split("/") or "//" in x_ or n_ in (".", ".."):
            return unk
        main = os.path.join(DEV, p_)
        if fold(x_) != fold(main) or os.path.realpath(x_) != x_ or os.path.islink(os.path.join(x_, ".git")) or not os.path.isdir(os.path.join(x_, ".git")):
            return unk
        gd_ = os.path.join(x_, ".git/worktrees", n_)
        if os.path.islink(gd_) or not os.path.isdir(gd_):
            return unk
        with open(os.path.join(gd_, "gitdir"), "rb") as f_:
            back = f_.read(4096).decode("utf-8", "replace").strip()
        if fold(os.path.realpath(back)) != fold(g_):
            return unk
        br = ""
        with open(os.path.join(gd_, "HEAD"), "rb") as f_:
            h_ = f_.read(1024).decode("utf-8", "replace").strip()
        mh_ = re.fullmatch(r"ref: refs/heads/(.+)", h_)
        if mh_:
            br = mh_.group(1)
        return ("ok", x_, br)
    except (OSError, IndexError, ValueError):
        return unk


def cfg_value(key):
    """One key of the owner's config.json (<config dir>/config.json); None when the file or key is missing, "unparseable" when it cannot be read as JSON."""
    d_ = shipmiracle_cfg_dir()
    if not d_:
        return None
    try:
        raw_ = open(os.path.join(d_, "config.json"), "rb").read()
    except OSError:
        return None
    try:
        j_ = json.loads(raw_.decode("utf-8"))
    except ValueError:
        return "unparseable"
    return j_.get(key) if isinstance(j_, dict) else None


def _projects_dir():
    """SHIPMIRACLE_DEV, else config paths.projects_dir (absolute or ~/...), else ~/Developer; resolved."""
    v_ = os.environ.get("SHIPMIRACLE_DEV")
    if not v_:
        c_ = cfg_value("paths.projects_dir")
        if isinstance(c_, str) and c_ and "\0" not in c_ and (c_.startswith("/") or c_.startswith("~/")):
            v_ = os.path.join(shipmiracle_home() or HOME, c_[2:]) if c_.startswith("~/") else c_
    return os.path.realpath(v_ or os.path.join(HOME, "Developer"))


DEV = _projects_dir()


def gate_engine():
    """The configured gate.engine (legacy|shadow|playbook; anything else or unreadable = 'unparseable'). Missing = legacy."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_GATE_ENGINE"):
        return os.environ["SHIPMIRACLE_GATE_ENGINE"].strip().lower()
    v_ = cfg_value("gate.engine")
    if v_ == "unparseable":
        return v_
    return v_.strip().lower() if isinstance(v_, str) and v_.strip() else "legacy"


def autopilot_writes(d, pd):
    """P6 T3 (C6): True when this PreToolUse call writes: Edit/Write/MultiEdit/NotebookEdit, or a Bash command that mutates anything but /tmp and /dev.
    Fail closed: a command that cannot be parsed, or whose command word is unknown, counts as a write."""
    tool = sp(d.get("tool_name")); ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return True
    if tool in ("Read", "Grep", "Glob", "LS", "NotebookRead", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "WebSearch", "WebFetch", "ExitPlanMode", "AskUserQuestion", "Agent", "Task", "BashOutput"):
        return False
    if tool != "Bash":
        return True                                              # P6 sec C2: every other tool (Monitor, CronCreate, ScheduleWakeup, RemoteTrigger, Skill, SlashCommand, mcp__*, ...) is denied by default
    c = sp(ti.get("command"))
    try:
        if len(c) > BIG_CMD:
            return True
        segs = long_segs(c)
        if unknown_cmd(c, segs) or any(mut_seg(w_, lambda x_: False) for _a, _u, w_ in segs):
            return True
        troots = [fold(os.path.realpath(x_)).rstrip("/") for x_ in ("/tmp", "/private/tmp")]

        def tam(ap, kind="write"):
            k_ = fold(os.path.realpath(ap))
            return not (k_.startswith("/dev/") or any(k_ == t_ or k_.startswith(t_ + "/") for t_ in troots))
        return bool(bash_targets(c, sp(d.get("cwd")) or pd, pd, tam))
    except Exception:
        return True


def glob_re(g):
    out = []; i = 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif g.startswith("**", i):
            out.append(".*"); i += 2
        elif g[i] == "*":
            out.append("[^/]*"); i += 1
        elif g[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(g[i])); i += 1
    return re.compile("".join(out) + r"\Z")
sp = lambda v: v if isinstance(v, str) else ""                   # every tool_input path/command goes through this: a list, dict or number counts as empty
BIG = 10 ** 6
BIG_CMD = 100000                                                 # Bash commands above this length get the cheap regex check only
now = time.time()


def changed(old, new):
    """Real changed lines between two texts: for each non-equal opcode max(removed, added)."""
    import difflib  # SHIPMIRACLE-LAZY
    a = old.splitlines(); b = new.splitlines()
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    j = 0
    while j < len(a) - i and j < len(b) - i and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    a = a[i:len(a) - j]; b = b[i:len(b) - j]
    n = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            n += max(i2 - i1, j2 - j1)
    return max(n, int(math.ceil(sum(len(x) + 1 for x in b) / 200.0)) if n else 0)   # one 500-statement line is not one line


def read_text(path):
    """File text, or None when it is over 1 MB, over 5000 lines or not UTF-8 (the callers then count it as a big change)."""
    try:
        if os.path.getsize(path) > 1048576:
            return None
        t = open(path, "rb").read().decode("utf-8")
    except Exception:
        return None
    return None if t.count("\n") > 5000 else t


def apply_edits(text, edits):
    """Apply Edit/MultiEdit entries in order, in memory. Returns (text, all_applied)."""
    ok = True
    for e in edits:
        o = sp(e.get("old_string")); nw = sp(e.get("new_string"))
        if o == "":
            if text == "":
                text = nw
            else:
                ok = False
        elif o not in text:
            ok = False
        else:
            text = text.replace(o, nw) if e.get("replace_all") else text.replace(o, nw, 1)
    return text, ok


def n_changed(tool, path, ti):
    """Changed lines a write would make (BIG when unknown)."""
    if any(len(str(v)) > 1048576 for v in ti.values()):
        return BIG
    if tool == "Edit":
        old = sp(ti.get("old_string"))
        n = changed(old, sp(ti.get("new_string")))
        if ti.get("replace_all"):
            t = read_text(path)
            if t is None:
                return BIG
            n *= max(1, t.count(old)) if old else 1
        return n
    if tool == "Write":
        content = sp(ti.get("content"))
        if not os.path.exists(path):
            return changed("", content)                           # max(lines, chars / 200)
        t = read_text(path)
        return BIG if t is None else changed(t, content)
    if tool == "MultiEdit":
        edits = [e for e in (ti.get("edits") or []) if isinstance(e, dict)]
        if not os.path.exists(path):
            return sum(changed("", e.get("new_string") or "") for e in edits)
        t = read_text(path)
        if t is None:
            return BIG
        res, ok = apply_edits(t, edits)
        if ok:
            return changed(t, res)
        return sum(changed(e.get("old_string") or "", e.get("new_string") or "") for e in edits)
    if tool == "NotebookEdit":
        mode = ti.get("edit_mode") or "replace"; src = ti.get("new_source") or ""
        if isinstance(src, list):
            src = "".join(src)
        if mode == "insert":
            return changed("", src)
        t = read_text(path)
        cid = ti.get("cell_id")
        if t is None or not cid:
            return BIG
        for c in (json.loads(t).get("cells") or []):
            if c.get("id") == cid:
                old = c.get("source") or ""
                if isinstance(old, list):
                    old = "".join(old)
                return changed(old, "" if mode == "delete" else src)
        return BIG
    return BIG


PUNCT = set(";<>|&()")
SUB_PWD = "\x02W"; SUB_PD = "\x02P"; SUB_HOME = "\x02H"; SUB_UNK = "\x03"; QMARK = "\x04"
ENVVAR = re.compile(r"\$(?:\{(PWD|CLAUDE_PROJECT_DIR|HOME)\}|(PWD|CLAUDE_PROJECT_DIR|HOME)(?![A-Za-z0-9_]))")


def _ci_drive(p):
    """WSL: a Windows drive mounted at /mnt/<letter> (NTFS through drvfs) ignores case. Same rule as shipmiracle/platform.case_insensitive; nothing is imported on the hook path.
    Test seam (SHIPMIRACLE_TEST=1 only): SHIPMIRACLE_FAKE_OS says wsl or not."""
    if not re.match(r"/mnt/[A-Za-z](?:/|$)", p):
        return False
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_FAKE_OS"):
        return os.environ["SHIPMIRACLE_FAKE_OS"] == "wsl"
    try:
        with open("/proc/sys/kernel/osrelease") as f_:
            return "microsoft" in f_.read(512).lower()
    except OSError:
        return False


def fold(p):
    """Path comparison key: case-insensitive on macOS (the default file system is) and on a WSL Windows drive (/mnt/c)."""
    p = os.path.normcase(p)
    return p.casefold() if sys.platform == "darwin" or (p.startswith("/mnt/") and _ci_drive(p)) else p


def pfold(p):
    """Key for the PROTECTED paths (gate files and folders, site-packages): always case-folded, on every OS. Full case folding maps U+017F (long s) to s and U+212A (Kelvin sign)
    to k, the spellings an APFS, NTFS or casefolding ext4/ZFS volume treats as the same file. A path that only looks like a protected one on a case-sensitive file system is refused
    too (over-refusal inside the protected folders, never an opening). `fold` stays platform-aware for everything else (project folders)."""
    return os.path.normcase(p).casefold()


def relto(ap, pd):
    """Relative path of the real path ap below pd; on macOS the project folder is matched without regard to case."""
    r = os.path.relpath(ap, pd)
    if (r == ".." or r.startswith("../")) and (sys.platform == "darwin" or _ci_drive(ap)):
        if len(ap) > len(pd) and ap[len(pd)] == "/" and fold(ap[:len(pd)]) == fold(pd):
            return ap[len(pd) + 1:]
        if fold(ap) == fold(pd):
            return "."
    return r

# Literal text that names a gate path (used only when cd / $VAR / cd - makes the real target unknown): full path pieces, never a bare "hooks/".
GATE_NAMED = re.compile(r"(?:^|/)(?:\.claude/(?:settings[^/]*\.json|hooks|agents)(?:/|$)|\.config/shipmiracle(?:/|$)|config/flow\.json$|\.shipmiracle(?:/|$))")
GATE_BASENAMES = ("settings.json", "settings.local.json", "flow.json", "flow-gate.sh", "shipm-hook")
# Basename rule (DECISIONS 2026-10-26 gate hot path): a write whose directory is unresolved ($VAR, $(...), a glob) is refused when its BASENAME is a gate/state file, whatever the directory is called.
GATE_WRITE_FIXED = ("flow-gate.sh", "shipm-hook", "flow.py", "flow.json", "hooks.json")
GATE_WRITE_RE = re.compile(r"^(?:flow-gate\..*\.code(?:\.[0-9]+)?|flow\.[^/]*\.json|hooks-apply\.log)$")
GATE_WRITE_WORDS = re.compile(r"\.local/state|v1/pyc|__pycache__")
_GWN = [None]


def gate_write_names():
    if _GWN[0] is None:
        s_ = {pfold(x) for x in GATE_WRITE_FIXED}
        try:
            s_ |= {pfold(x) for x in os.listdir(os.path.join(WS, "hooks")) if x != "__init__.py" and not x.startswith(".")}
        except OSError:
            pass
        _GWN[0] = s_
    return _GWN[0]


def gate_basename_hit(w):
    """True for a path with an unresolved part (variable, substitution, glob) that names a gate/state file by its last component, or that names a state-folder word (.local/state, v1/pyc, __pycache__)."""
    if w.startswith(TMP_PREFIXES) and ".." not in w.split("/"):
        return False
    b = pfold(os.path.basename(w.replace(SUB_UNK, "$")))
    if b in gate_write_names() or GATE_WRITE_RE.match(b) or (b.endswith(".pyc") and re.search(r"pyc|__pycache__", w)):
        return True
    return bool(GATE_WRITE_WORDS.search(w))
TMP_PREFIXES = ("/tmp/", "/private/tmp/")
# D14 M1: persistence files (run code later, outside this chat). The SAME literal tuples as shipmiracle/autopilot/rules.py PERSIST_* (the hard stop is built from that table; tests/gate_persist_test.py compares).
PERSIST_HOME_FILES = (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".zlogout", ".bashrc", ".bash_profile", ".bash_login", ".bash_logout", ".profile", ".login", ".cshrc", ".tcshrc", ".kshrc",
                      ".gitconfig", ".netrc", ".pypirc", ".git-credentials", ".npmrc", ".gitignore_global", ".yarnrc.yml", ".vimrc", ".tmux.conf", ".pythonrc", ".pythonrc.py",
                      ".ssh/config", ".ssh/rc", ".cargo/config.toml", ".docker/config.json", ".aws/config", ".kube/config", ".gnupg/gpg-agent.conf",
                      "Library/Application Support/Code/User/settings.json", "Library/Application Support/Code/User/tasks.json", "Library/Application Support/Code/User/keybindings.json",
                      ".config/Code/User/settings.json", ".config/Code/User/tasks.json", ".config/Code/User/keybindings.json",
                      ".ssh/authorized_keys", ".ssh/environment", ".aws/credentials", ".claude/CLAUDE.md", ".inputrc", ".condarc", ".config/pip/pip.conf", ".pip/pip.conf")
PERSIST_HOME_DIRS = ("Library/LaunchAgents", ".config/git", ".config/systemd", ".config/autostart", ".config/environment.d", ".config/fish", ".config/direnv", ".config/nvim", ".oh-my-zsh/custom",
                     ".gradle/init.d", ".vscode/extensions", ".local/share/applications", "Library/Application Support/iTerm2/Scripts/AutoLaunch", ".git-templates")
PERSIST_ABS_DIRS = ("/Library/LaunchAgents", "/Library/LaunchDaemons")
PERSIST_PROJECT_FILES = (".vscode/tasks.json", ".vscode/settings.json", ".envrc", ".devcontainer/devcontainer.json", ".devcontainer.json", "mise.toml", ".mise.toml", ".git/config",
                         ".claude/settings.json", ".claude/settings.local.json")
PERSIST_PROJECT_DIRS = (".git/hooks", ".githooks", ".husky")
PERSIST_PROJECT_SUFFIXES = (".code-workspace",)
PERSIST_SETTINGS_FILES = (".vscode/settings.json",)
PERSIST_SETTINGS_RISKY = ("path", "exec", "command", "shell", "args", "interpreter", "automation", "profile", "task", "env", "cmd", "tsdk", "launch", "debug", "runon", "hook", "proxy", "runtime",
                          "home", "root", "tools", "library", "rterm", "npm")
PERSIST_SETTINGS_ALLOW = ("editor.", "files.", "search.", "workbench.", "window.", "explorer.", "breadcrumbs.", "diffeditor.", "scm.", "problems.", "python.analysis.extrapaths",
                          "python.testing.pytestargs", "python.testing.unittestargs", "python.envfile", "python.terminal.activateenvironment", "terminal.integrated.shellintegration.",
                          "debug.console.", "debug.inlinevalues", "*.fontsize", "*.fontfamily", "*.fontweight", "*.lineheight", "*.letterspacing")
PERSIST_TEXT = "This writes to a file that runs code later (shell start-up, launch agents, git hooks, editor tasks ...); ask the owner to change it."


def settings_flat(text):
    """{setting name: json value} of the TOP-LEVEL settings of a settings.json text (comments and trailing commas allowed; `[language]` blocks give their inner names as `[lang]|name`),
    {} for an empty text, None when it cannot be read. Nested keys of a value (exclude globs, file associations ...) are data, never judged."""
    if text is None:
        return None
    if not text.strip():
        return {}
    try:
        t = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', lambda m: m.group(0) if m.group(0)[0] == '"' else "", text, flags=re.S)
        d = json.loads(re.sub(r",(\s*[}\]])", r"\1", t))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    out = {}
    for k_, v_ in d.items():
        if str(k_).startswith("[") and isinstance(v_, dict):
            for k2_, w_ in v_.items():
                out[str(k_) + "|" + str(k2_)] = json.dumps(w_, sort_keys=True)
        else:
            out[str(k_)] = json.dumps(v_, sort_keys=True)
    return out


def settings_risky_key(p):
    n = p.rsplit("|", 1)[-1].lower()
    if any(n.endswith(a_[1:]) if a_[0] == "*" else n.startswith(a_) for a_ in PERSIST_SETTINGS_ALLOW):
        return False
    return any(x_ in n for x_ in PERSIST_SETTINGS_RISKY)


GIT_CODE_KEY = re.compile(r"^(?:core\.(?:hookspath|fsmonitor|sshcommand|pager|editor|askpass|gitproxy)|credential\..+|gpg\.(?:.+\.)?program|sequence\.editor|pager\..+|diff\.external|diff\..+\.(?:textconv|command)|"
                          r"filter\..+\.(?:clean|smudge|process)|merge\..+\.driver|url\..+\.(?:push)?insteadof|remote\..+\.(?:receivepack|uploadpack|vcs)|http\.sslca(?:info|path)|include\.path|includeif\..+\.path|interactive\.difffilter)$")
GIT_ONESHOT_KEY = re.compile(r"^core\.(?:hookspath|fsmonitor)$")                # `git -c` is one command: only the two keys that load code by themselves; sshCommand / pager / editor keep the D9 rule (refused when the value names shipm or a launcher; `-c core.editor=true` stays normal)
GIT_CFG_ARG = ("-f", "--file", "--blob", "--type", "--default", "--comment")
GIT_CFG_READ = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "--unset", "--unset-all", "--remove-section", "--rename-section")
HUSKY_RUN = frozenset(("npx", "pnpx", "bunx", "pnpm", "yarn", "npm", "bun", "node", "dlx", "exec", "x", "husky", "husky-init"))


def git_config_bad(rest, tam, cwd):
    """D14 D2: True for a `git config` that SETS a code-running key (core.hooksPath, core.fsmonitor, core.sshCommand, an alias that starts with !, include.path, a filter, a driver, a
    credential helper, url insteadOf ...), edits the config by hand (-e), or writes a persistence file with -f. Reads, --unset and plain keys (user.name, pull.rebase ...) pass."""
    flags, pos, file_, i = [], [], None, 0
    while i < len(rest):
        x = rest[i]
        if x in GIT_CFG_ARG:
            if x in ("-f", "--file") and i + 1 < len(rest):
                file_ = rest[i + 1]
            i += 2; continue
        if x.startswith("--file="):
            file_ = x[7:]
        if x.startswith("-"):
            flags.append(x.split("=", 1)[0]); i += 1; continue
        pos.append(x); i += 1
    if "-e" in flags or "--edit" in flags or (pos and pos[0] == "edit"):
        return True
    if pos and pos[0] in ("get", "list", "unset"):
        return False
    setf = bool(pos and pos[0] == "set")
    if setf:
        pos = pos[1:]
    if any(f in GIT_CFG_READ for f in flags):
        return False
    if not (len(pos) >= 2 or setf or "--add" in flags or "--replace-all" in flags) or not pos:
        return False
    if file_ and tam(os.path.expanduser(file_) if file_.startswith("~") or os.path.isabs(file_) else os.path.join(cwd, file_)):
        return True
    key = pos[0].lower(); val = pos[1] if len(pos) > 1 else ""
    return bool(GIT_CODE_KEY.match(key)) or (key.startswith("alias.") and val.lstrip().startswith("!"))


def git_persist_hit(segs, tam, cwd):
    """D14 D2: the command line sets up code that runs later outside this chat through git or husky: see git_config_bad; `git -c core.hooksPath=...` (one command, but it runs code);
    `git init|clone --template X` (the template carries hooks); husky install|init|add|set (it sets core.hooksPath)."""
    for _a, _u, w in segs:
        if not w:
            continue
        b = _cmd_name(w[0]); r = [re.sub(r"[\\'\"]", "", x) for x in w[1:]]
        if b == "git":
            sub = ""; i = 0
            while i < len(r):
                x = r[i]
                if x == "-c" and i + 1 < len(r):
                    k1_, _, v1_ = r[i + 1].partition("=")
                    if GIT_ONESHOT_KEY.match(k1_.strip().lower()) and not (k1_.strip().lower() == "core.fsmonitor" and v1_.strip().lower() in ("", "false", "true", "0", "1")):
                        return True
                    i += 2; continue
                if x in ("-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix") and i + 1 < len(r):
                    i += 2; continue
                if x.startswith("-"):
                    i += 1; continue
                sub = x; break
            rest = r[i + 1:] if sub else []
            if sub in ("init", "clone"):
                for j, x in enumerate(rest):
                    if (x == "--template" and j + 1 < len(rest) and rest[j + 1]) or (x.startswith("--template=") and len(x) > 11):
                        return True
            if sub == "config" and git_config_bad(rest, tam, cwd):
                return True
        elif b in HUSKY_RUN:
            names = [_cmd_name(x) for x in r]
            for j, x in enumerate(names):
                if x == "husky-init" or re.match(r"^husky-init@", x):
                    return True
                runs_ = b in ("npx", "pnpx", "bunx", "husky", "node") or j == 0 or any(y_ in ("exec", "dlx", "x") for y_ in names[:j])           # `npm install husky` only installs the package
                if runs_ and (x == "husky" or re.match(r"^husky@", x) or (j == 0 and b == "husky")):
                    nxt = names[j + 1] if j + 1 < len(names) else ""
                    if nxt in ("", "install", "init", "add", "set") or nxt.startswith("."):
                        return True
            if b == "husky" and (not r or r[0] in ("install", "init", "add", "set") or r[0].startswith(".")):
                return True
    return False


def names_gate(w, marks=(), remove=False):
    if GATE_NAMED.search(w) or any(m and m in w.split("/") for m in marks):
        return True
    return remove and bool(re.search(r"(?:^|/)\.claude/?$", w))


Q_ = r"""(?P<q>['"])(?P<p>[^'"\n]+)(?P=q)"""
CODE_PATTERNS = [re.compile(x) for x in (
    r"""\bopen\(\s*""" + Q_ + r"""\s*,\s*(?:mode\s*=\s*)?(?P<q2>['"])[rbtU]*[wax+][^'"]*(?P=q2)""",
    r"""\bPath\(\s*""" + Q_ + r"""\s*\)\s*\.\s*(?:write_text|write_bytes)\b""",
    r"""\bshutil\.(?:copy2?|copyfile|copytree|move)\(\s*[^,()]+,\s*""" + Q_,
    r"""\bos\.(?:replace|rename)\(\s*[^,()]+,\s*""" + Q_,
    r"""\b(?:writeFileSync|appendFileSync|writeFile|appendFile|createWriteStream)\(\s*""" + Q_,
    r"""\bFile\.write\(\s*""" + Q_,
    r"""\bFile\.open\(\s*""" + Q_ + r"""\s*,\s*['"][wa]""")]
CODE_WRITES = re.compile(r"""\bopen\(.*,\s*(?:mode\s*=\s*)?['"][rbtU]*[wax+][bt+]*['"]|\.(?:write_text|write_bytes|symlink_to|hardlink_to|touch)\(|\b(?:copy2?|copyfile|copytree|move|rename|replace|symlink|link|writeFileSync|appendFileSync|writeFile|appendFile|createWriteStream|truncate)\(|\bFile\.(?:write|open)\(""")
WRAPPERS = ("sudo", "command", "env", "nohup", "time", "exec", "nice", "builtin", "xargs", "parallel")
XARGS_VAL = ("-I", "-i", "-n", "-L", "-l", "-P", "-s", "-E", "-e", "-d", "-a", "-J", "-R", "-S", "-j", "-N", "--jobs", "--max-args", "--max-procs", "--delimiter", "--arg-file")
EXEC_FLAGS = ("-exec", "-execdir", "-ok", "-okdir")
WRAPPERS2 = ("script", "unbuffer", "stdbuf", "timeout", "gtimeout", "setsid", "caffeinate", "arch", "sandbox-exec", "doas", "flock", "watch", "chronic",
             "wsl", "runuser", "chrt", "ionice", "taskset", "systemd-inhibit")     # run their arguments (owner proof: `script -q /dev/null shipm autopilot checkpoint`); only norm_seg strips them
W2_VALFLAGS = {"stdbuf": ("-i", "-o", "-e"), "timeout": ("-s", "-k", "--signal", "--kill-after"), "gtimeout": ("-s", "-k", "--signal", "--kill-after"), "caffeinate": ("-t", "-w"),
               "sandbox-exec": ("-f", "-p", "-n", "-D"), "doas": ("-u", "-C"), "watch": ("-n", "-d", "--interval"), "script": ("-t", "-F"),
               "wsl": ("-d", "--distribution", "-u", "--user", "--cd"), "runuser": ("-u", "-g", "-G", "-l"), "ionice": ("-c", "-n", "-p"), "chrt": ("-p",), "taskset": ("-c", "-p")}
W2_NPOS = {"script": 1, "timeout": 1, "gtimeout": 1, "flock": 1, "taskset": 1}                  # positional words before the command: script's file, the timeout's duration, flock's lock file
SHELLS = ("bash", "sh", "zsh", "dash")
INTERP = re.compile(r"^(python[0-9.]*|node|nodejs|ruby|perl)$")


class _Scan:
    """Normalises a shell string for shlex: heredoc bodies cut out (the marker line stays, with a \\x01H<n> token), command substitutions
    replaced by placeholders (known ones by their value), newlines become ';', comments dropped. Raises ValueError on an unterminated quote/substitution."""
    def __init__(self, s, hd):
        self.s = s; self.i = 0; self.hd = hd; self.pending = []; self.subs = []; self.rawsubs = []

    def expand(self):
        s = self.s; i = self.i
        if s.startswith("$((", i):
            d = 0; j = i + 1
            while j < len(s):
                if s[j] == "(":
                    d += 1
                elif s[j] == ")":
                    d -= 1
                    if d == 0:
                        break
                j += 1
            else:
                raise ValueError("unterminated $((")
            self.i = j + 1
            return SUB_UNK
        if s.startswith("$(", i):
            self.i = i + 2
            inner = self.run(")")
            c = " ".join(inner.split())
            if c == "pwd":
                return SUB_PWD
            if c == "git rev-parse --show-toplevel":
                return SUB_PD
            self.subs.append(inner)
            return SUB_UNK
        if s[i] == "`":
            j = i + 1
            while j < len(s) and s[j] != "`":
                j += 2 if s[j] == "\\" else 1
            if j >= len(s):
                raise ValueError("unterminated `")
            raw = s[i + 1:j]; self.i = j + 1
            if raw.strip() == "pwd":
                return SUB_PWD
            if raw.strip() == "git rev-parse --show-toplevel":
                return SUB_PD
            self.rawsubs.append(raw)
            return SUB_UNK
        if s[i] == "$":
            m = ENVVAR.match(s, i)
            if m:
                self.i = m.end()
                nm = m.group(1) or m.group(2)
                return SUB_PWD if nm == "PWD" else SUB_HOME if nm == "HOME" else SUB_PD
        return None

    def dq(self):
        s = self.s; n = len(s); self.i += 1; buf = []
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                buf.append(s[self.i:self.i + 2]); self.i += 2; continue
            if c == '"':
                self.i += 1
                inner = "".join(buf)
                return '"' + (QMARK if inner and set(inner) <= PUNCT else "") + inner + '"'
            if c in "$`":
                e = self.expand()
                if e is not None:
                    buf.append(e); continue
            buf.append(c); self.i += 1
        raise ValueError("unterminated \"")

    def run(self, closer=None):
        s = self.s; n = len(s); out = []; depth = 0
        while self.i < n:
            i = self.i; c = s[i]
            if c == "\\":
                nx = s[i + 1:i + 2]
                if nx == "\n":
                    out.append(" ")
                elif nx and nx in PUNCT:
                    out.append(QMARK + c + nx)
                else:
                    out.append(c + nx)
                self.i += 2; continue
            if c == "'":
                j = s.find("'", i + 1)
                if j < 0:
                    raise ValueError("unterminated '")
                inner = s[i + 1:j]
                out.append("'" + (QMARK if inner and set(inner) <= PUNCT else "") + inner + "'")
                self.i = j + 1; continue
            if c == '"':
                out.append(self.dq()); continue
            if c in "$`":
                e = self.expand()
                if e is not None:
                    out.append(e); continue
            if c == "#" and (i == 0 or s[i - 1] in " \t\n;|&("):
                j = s.find("\n", i)
                self.i = n if j < 0 else j; continue
            if c == "<" and s.startswith("<<", i) and not s.startswith("<<<", i):
                j = i + 2; dash = False
                if s[j:j + 1] == "-":
                    dash = True; j += 1
                while j < n and s[j] in " \t":
                    j += 1
                if s[j:j + 1] in ("'", '"') and j < n:
                    k = s.find(s[j], j + 1)
                    if k < 0:
                        raise ValueError("unterminated heredoc marker")
                    delim = s[j + 1:k]; j = k + 1
                else:
                    m = re.match(r"[^\s;&|<>()]+", s[j:])
                    if not m:
                        raise ValueError("bad heredoc marker")
                    delim = m.group(0).replace("\\", "").replace("'", "").replace('"', ""); j += m.end()
                self.hd.append(None); self.pending.append((len(self.hd) - 1, delim, dash))
                out.append(" << \x01H%d " % (len(self.hd) - 1)); self.i = j; continue
            if c == "!" and out and out[-1] == ">":              # zsh >! file and >>! file are plain redirects
                self.i += 1; continue
            if c == "\n":
                self.i += 1
                for idx, delim, dash in self.pending:
                    lines = []
                    while self.i < n:
                        e = s.find("\n", self.i); e = n if e < 0 else e
                        line = s[self.i:e]; self.i = min(e + 1, n)
                        if (line.lstrip("\t") if dash else line) == delim:
                            break
                        lines.append(line)
                    self.hd[idx] = "\n".join(lines)
                self.pending = []
                out.append(" ; "); continue
            if closer == ")":
                if c == "(":
                    depth += 1
                elif c == ")":
                    if depth == 0:
                        self.i += 1
                        return "".join(out)
                    depth -= 1
            out.append(c); self.i += 1
        if closer:
            raise ValueError("unterminated $(")
        return "".join(out)


AWK_OUT = re.compile(r"""\bprintf?\b(?:"(?:\\.|[^"\\\n])*"|[^">\n]){0,400}>>?\s*"([^"\n]+)\"""")
SED_W = [re.compile(r"(?:^|[;{}\n])\s*[0-9$,]*\s*w\s+([^\s;}]+)"), re.compile(r"s(.)(?:(?!\1).){0,200}\1(?:(?!\1).){0,200}\1[gpIiMm0-9]*w\s*([^\s;}]+)")]


def opt_dir(rest):
    """The directory given by -t DIR / -tDIR-style combined flags / --target-directory[=]DIR (cp, mv, install, ln), else None."""
    for k, a in enumerate(rest):
        if a.startswith("--target-directory="):
            return a.split("=", 1)[1]
        if a == "--target-directory" and k + 1 < len(rest):
            return rest[k + 1]
        if re.match(r"^-[A-Za-z]*t$", a) and k + 1 < len(rest):
            return rest[k + 1]
    return None


def bash_targets(cmd, cwd, pd, tamper=None, home=None):
    """Project files a Bash command would write (list of display strings); with `tamper` (a function real-path -> bool) the files it would write,
    rm or chmod that the function flags instead. Raises on anything it cannot parse: the caller falls back to the regex check."""
    pd = os.path.realpath(pd)
    cwd0 = os.path.realpath(cwd if cwd and os.path.isabs(cwd) else pd)
    hits = []
    dirstack = []
    unsure = {"cwd": False, "home": False}                       # cd - / cd $X / export HOME=...: relative and ~ paths can no longer be resolved
    marks = tuple(home or ())

    def counts(ap, kind="write"):
        if tamper:
            return tamper(os.path.abspath(ap), kind)            # L4: tamper judges the link itself as well as its target
        ap = os.path.realpath(ap)
        r = relto(ap, pd)
        if r == ".git" or r.startswith(".git/"):
            return False                                         # git internals are not source
        if r == ".." or r.startswith("../") or os.path.isabs(r) or ap.startswith("/dev/"):
            return False
        if os.path.isdir(ap):
            r += "/"
        return not RECORD.match(r)

    def add(w, base, disp=None, kind="write", code=False, parent_ok=False):
        if parent_ok:
            kind = "write"                                       # find with name predicates: only gate paths themselves (or inside them) count, not a folder that merely contains them
        raw = w
        w = w.replace(QMARK, "").replace(SUB_PWD, base).replace(SUB_PD, pd).replace(SUB_HOME, HOME)
        if not w:
            return
        if w.startswith("~"):
            w = os.path.expanduser(w)
        shown = disp or w.replace(SUB_UNK, "$(...)")
        if tamper:
            unres = SUB_UNK in w or "$" in w or (unsure["cwd"] and not os.path.isabs(w)) or (unsure["home"] and raw.startswith(("~", SUB_HOME)))
            if (unres or any(ch_ in w for ch_ in "*?[")) and gate_basename_hit(w):
                hits.append(shown); return                       # unresolved folder, gate/state basename: refused whatever the folder is called
            if unres:                                            # the real target is unknown: refuse only what the literal text names
                if code and not w.startswith(TMP_PREFIXES) and os.path.basename(w) in GATE_BASENAMES:
                    hits.append(shown); return
                if names_gate(w, marks, kind == "remove"):
                    hits.append(shown); return
        if SUB_UNK in w:                                         # unknown substitution: only a literal tail that is an existing project file counts
            tail = w.rsplit(SUB_UNK, 1)[1]
            if not tail or "$" in tail or SUB_UNK in tail:
                return
            t = tail.lstrip("/")
            for cand in (tail if os.path.isabs(tail) else None, os.path.join(pd, t), os.path.join(base, t)):
                if cand and os.path.isfile(cand) and counts(cand, kind):
                    hits.append(shown); return
            return
        if "$" in w:
            return
        ap_ = w if os.path.isabs(w) else os.path.join(base, w)
        if counts(ap_, kind):
            if tamper and kind == "remove" and not counts(ap_, "write"):
                shown += " [PARENT]"                             # removing a folder that holds a gate path
            hits.append(shown)

    def clean(w, base):
        return w.replace(QMARK, "").replace(SUB_PWD, base).replace(SUB_PD, pd).replace(SUB_HOME, HOME)

    def scan_code(code, base):
        if tamper and CODE_WRITES.search(code):                  # a path built at run time that still ends in a literal gate basename
            for m_ in re.finditer(r"""['"]([^'"\n]*)['"]""", code):
                lit = m_.group(1)
                if lit and not lit.startswith(TMP_PREFIXES) and (pfold(os.path.basename(lit)) in gate_write_names() or GATE_WRITE_RE.match(pfold(os.path.basename(lit))) or re.search(r"\.local/state|v1/pyc|__pycache__", lit)):
                    hits.append(lit); return
        for pat in CODE_PATTERNS:
            for m in pat.finditer(code):
                p = m.group("p")
                if "{" not in p:
                    add(p, base, code=True)

    def newdir(w, base):
        w = clean(w, base)
        if not w or "$" in w or SUB_UNK in w or w == "-":
            unsure["cwd"] = True
            return base
        return os.path.realpath(os.path.join(base, os.path.expanduser(w)))

    def simple(cmd_, base, hd, depth):
        """Analyse one simple command; returns the base directory for the commands after it."""
        for w in cmd_["reds"]:
            add(w, base)
        args = list(cmd_["args"])
        if any(a.startswith("HOME=") for a in args[:6]):
            unsure["home"] = True                                # export HOME=..., HOME=x cmd, env HOME=x cmd
        while args and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]):
            args.pop(0)
        while args and os.path.basename(args[0]) in WRAPPERS:
            w = args.pop(0)
            while args and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]) or (w == "env" and args[0].startswith("-")) or (w in ("xargs", "parallel") and args[0].startswith("-"))):
                f_ = args.pop(0)
                if w in ("xargs", "parallel") and f_ in XARGS_VAL and args:
                    args.pop(0)                                  # P3 R2: xargs/parallel run what follows their options
        if not args:
            return base
        name = os.path.basename(args[0]); rest = args[1:]
        if "--" in rest:
            k = rest.index("--"); opts = [a for a in rest[:k] if a.startswith("-") and a != "-"]
            pos = [a for a in rest[:k] if not (a.startswith("-") and a != "-")] + rest[k + 1:]
        else:
            opts = [a for a in rest if a.startswith("-") and a != "-"]
            pos = [a for a in rest if not (a.startswith("-") and a != "-")]
        bodies = [hd[x] or "" for x in cmd_["hd"] if x < len(hd)]
        if name == "cd":
            return newdir(pos[0], base) if pos else os.path.expanduser("~")
        if name == "pushd":
            dirstack.append(base)
            return newdir(pos[0], base) if pos else base
        if name == "popd":
            return dirstack.pop() if dirstack else base
        if name == "tee":
            for a in pos:
                add(a, base)
        elif name == "sed":
            for a in pos:                                        # w FILE command and s///w FILE flag inside the program
                if len(a) < 2000:
                    for pat in SED_W:
                        for m in pat.finditer(a):
                            add(m.group(m.lastindex), base)
            if any(re.match(r"^-[A-Za-z]*i", o) or o.startswith("--in-place") for o in opts):
                files = [a for a in pos if a != ""]
                ns = len([o for o in opts if re.match(r"^-[A-Za-z]*[ef]$", o)]) or 1
                for a in files[ns:]:
                    add(a, base)
        elif name in ("awk", "gawk", "mawk", "nawk"):
            for a in pos:                                        # print > "file" / >> "file" inside the program
                if len(a) < 4000:
                    for m in AWK_OUT.finditer(a):
                        add(m.group(1), base)
            if "inplace" in rest:                                # gawk -i inplace: the file arguments are rewritten
                for a in pos:
                    if a != "inplace" and "{" not in a and "=" not in a:
                        add(a, base)
        elif name == "truncate":
            k = 0; fl = []
            while k < len(rest):
                a = rest[k]
                if a in ("-s", "--size", "-r", "--reference"):
                    k += 2; continue
                if not a.startswith("-"):
                    fl.append(a)
                k += 1
            for a in fl:
                add(a, base)
        elif name in ("ed", "ex"):                               # in-place editors: the file argument is rewritten (the argument of -c/-sc is a command)
            k = 0
            while k < len(rest):
                a = rest[k]
                if re.match(r"^-[A-Za-z]*c$", a):
                    k += 2; continue
                if not a.startswith("-"):
                    add(a, base)
                k += 1
        elif tamper and name in ("rm", "unlink", "rmdir"):
            for a in pos:
                add(a, base, kind="remove")
        elif tamper and name in ("chmod", "chown", "touch"):
            for a in pos:
                add(a, base)
        elif tamper and name == "find":
            starts = []
            for a in rest:
                if a.startswith("-") or a in ("(", "!"):
                    break
                starts.append(a)
            if "-delete" in rest or (any(x in rest for x in ("-exec", "-execdir", "-ok")) and any(os.path.basename(x) in ("rm", "unlink", "rmdir", "mv") for x in rest)):
                restrict = any(x in rest for x in ("-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-type"))
                named = any(re.search(r"settings|flow\.json|flow-gate|\.claude|hooks|agents", x) for x in rest[len(starts):] if not x.startswith("-") or "." in x)
                for a in starts or ["."]:
                    ra_ = os.path.realpath(os.path.join(base, os.path.expanduser(clean(a, base))))
                    in_pd = ra_ == pd or ra_.startswith(pd + "/")           # only the project folder gets the name-predicate leniency, not ~/.claude, the workspace or the state folder
                    add(a, base, kind="remove", parent_ok=restrict and not named and in_pd)
        elif name == "perl" or INTERP.match(name):
            if name == "perl" and any(re.match(r"^-[A-Za-z0-9]*i", o) for o in opts):
                ns = len([o for o in opts if re.match(r"^-[A-Za-z]*e$", o)]) or 1
                for a in pos[ns:]:
                    add(a, base)
            if any(re.match(r"^-[A-Za-z0-9]*[ce]$", o) for o in opts) and pos:
                scan_code(clean(pos[0], base), base)
            for b in bodies:
                scan_code(b, base)
        elif name in ("cp", "install", "rsync", "ln", "ditto"):
            td = opt_dir(rest) if name != "rsync" else None      # rsync -t is "preserve times", not a target directory
            if tamper and name == "ln":                          # ln -s <gate file> /tmp/x, then a write through /tmp/x: the link itself is refused
                for a in pos:
                    add(a, base)
            elif name == "install" and "-d" in opts:
                for a in pos:
                    add(a, base)
            elif td is not None:
                add(td, base)
            elif len(pos) >= 2:
                add(pos[-1], base)
        elif name == "mv":
            td = opt_dir(rest)
            if td is not None and not any(a == td for a in pos):
                add(td, base)                                    # --target-directory=DIR form (DIR is not among the positionals)
            if len(pos) >= 2 or td is not None:
                for a in pos[:-1] if td is None else pos:
                    add(a, base, kind="remove")                  # the sources vanish: a parent folder of a gate file may not be moved
                if td is None:
                    add(pos[-1], base)
        elif name == "dd":
            for a in rest:
                if a.startswith("of="):
                    add(a[3:], base)
        elif name == "git":
            b = base; k = 0
            while k < len(rest):
                a = rest[k]
                if a == "-C" and k + 1 < len(rest):
                    b = newdir(rest[k + 1], b); k += 2; continue
                if a == "-c" and k + 1 < len(rest):
                    k += 2; continue
                if a.startswith("-"):
                    k += 1; continue
                break
            if k < len(rest) and rest[k] == "apply" and not any(x in ("--check", "--stat", "--numstat", "--dry-run") for x in rest[k + 1:]):
                add(b, base, "git apply (target unknown)")
        elif name == "patch":
            b = base
            for k, a in enumerate(rest[:-1]):
                if a in ("-d", "--directory"):
                    b = newdir(rest[k + 1], base)
            if not any(o in ("--dry-run", "--check") for o in opts):
                add(b, base, "patch (target unknown)")
        elif name in SHELLS:
            c_ = [o for o in opts if re.match(r"^-[A-Za-z]*c$", o)]
            if c_ and pos:
                run_raw(clean(pos[0], base), base, depth + 1)
            elif not c_:
                for b in bodies:
                    run_raw(b, base, depth + 1)
        return base

    def parse(norm, hd, base, depth):
        import shlex  # SHIPMIRACLE-LAZY
        if depth > 3:
            return
        lex = shlex.shlex(norm, posix=True, punctuation_chars=True)
        lex.whitespace_split = True; lex.commenters = ""
        toks = list(lex)
        stack = []; cur = {"args": [], "reds": [], "hd": []}; carry = []

        def flush():
            nonlocal cur, base, carry
            if cur["args"] or cur["reds"]:
                cur["hd"] = carry + cur["hd"]; carry = []        # cat <<EOF | python3: the body reaches the next command
                base = simple(cur, base, hd, depth)
            cur = {"args": [], "reds": [], "hd": []}

        def sep(chars):
            nonlocal base, carry
            held = list(cur["hd"])
            flush()
            if chars in ("|", "|&"):
                carry = carry + held
            for ch in chars:
                if ch == "(":
                    stack.append(base)
                elif ch == ")" and stack:
                    base = stack.pop()

        i = 0; n = len(toks); dbl = False; arith = False
        while i < n:
            t = toks[i]; i += 1
            if t == "[[" and all(a in ("if", "while", "until", "elif", "!") for a in cur["args"]):
                dbl = True
            elif t == "]]":
                dbl = False
            if t and set(t) == set("(") and len(t) >= 2 and not cur["args"]:
                arith = True                                     # (( a > b )): arithmetic, not a redirect
            elif arith and t.startswith("))"):
                arith = False
            if (dbl or arith) and t and set(t) <= set("<>"):
                cur["args"].append(t); continue                  # [[ a > b ]]: string comparison
            if ";" in t:
                dbl = False
            if not (t and set(t) <= PUNCT):
                cur["args"].append(t); continue
            if ">" in t:
                idx = t.index(">"); prefix = t[:idx]; ops = t[idx:]; amp = False
                if prefix.endswith("&"):
                    amp = True; prefix = prefix[:-1]
                if prefix:
                    sep(prefix)
                elif cur["args"] and cur["args"][-1].isdigit():
                    cur["args"].pop()                            # N> : N is a file descriptor
                dup = "&" in ops and not amp
                nxt = toks[i] if i < n else None
                if nxt is not None and not (set(nxt) <= PUNCT):
                    i += 1
                    if not (dup and (nxt.isdigit() or nxt.startswith("-"))) and not nxt.startswith("&"):
                        cur["reds"].append(nxt)
            elif "<" in t:
                if t.startswith("<<") and not t.startswith("<<<"):
                    if i < n and re.fullmatch(r"\x01H\d+", toks[i]):
                        cur["hd"].append(int(toks[i][2:])); i += 1
                elif i < n and not (set(toks[i]) <= PUNCT):
                    i += 1                                       # < file, <<< string: input only
            else:
                sep(t)
        flush()

    def run_raw(raw, base, depth):
        if depth > 3:
            return
        hd = []; sc = _Scan(raw, hd)
        norm = sc.run()
        parse(norm, hd, base, depth)
        for s_ in sc.subs:
            parse(s_, hd, base, depth + 1)
        for r_ in sc.rawsubs:
            run_raw(r_, base, depth + 1)

    run_raw(cmd, cwd0, 0)
    return list(dict.fromkeys(hits))


def blank_quotes(c):
    out = []; i = 0; n = len(c)
    while i < n:
        j = i
        while j < n and c[j] not in "'\"":
            j += 1
        out.append(c[i:j])
        if j >= n:
            break
        q = c[j]; k = j + 1
        while k < n and c[k] != q:
            k += 2 if (q == '"' and c[k] == "\\") else 1
        if k >= n:
            out.append(c[j:]); break
        out.append(q + q); i = k + 1
    return "".join(out)


def cmd_segments(c, depth=0):
    segs = []; words = []; cur = []; has = [False]; pend = []; i = 0; n = len(c)

    def endw():
        if has[0]:
            words.append("".join(cur))
        del cur[:]; has[0] = False

    def endseg():
        endw()
        if words:
            segs.append(list(words))
        del words[:]
    while i < n:
        ch = c[i]
        if ch == "'":
            j = c.find("'", i + 1); j = n if j < 0 else j
            cur.append(c[i + 1:j]); has[0] = True; i = j + 1
        elif ch == '"':
            j = i + 1; buf = []
            while j < n and c[j] != '"':
                if c[j] == "\\" and j + 1 < n:
                    buf.append(c[j + 1]); j += 2
                else:
                    buf.append(c[j]); j += 1
            s_ = "".join(buf); cur.append(s_); has[0] = True; i = j + 1
            if depth < 3 and ("$(" in s_ or "`" in s_):
                for m in re.finditer(r"\$\(([^()]*)\)|`([^`]*)`", s_[:20000]):
                    segs.extend(cmd_segments(m.group(1) or m.group(2) or "", depth + 1))
        elif ch == "\\":
            if i + 1 < n and c[i + 1] != "\n":
                cur.append(c[i + 1]); has[0] = True
            i += 2
        elif ch in " \t":
            endw(); i += 1
        elif ch == "#" and not has[0]:
            j = c.find("\n", i); i = n if j < 0 else j
        elif ch == "<" and c.startswith("<<", i) and not c.startswith("<<<", i):
            endw(); j = i + 2; dash = c.startswith("-", j)
            j += 1 if dash else 0
            while j < n and c[j] in " \t":
                j += 1
            k = j
            while k < n and c[k] not in " \t\n;&|<>()":
                k += 1
            pend.append(c[j:k].replace("'", "").replace('"', "").replace("\\", "")); i = k
        elif ch == "\n" or ch in ";&|(){}`":
            endseg(); i += 1
            if ch == "\n" and pend:
                for d in pend:
                    while i < n:
                        e = c.find("\n", i); e = n if e < 0 else e
                        line = c[i:e]; i = min(e + 1, n)
                        if line.strip("\t") == d:
                            break
                del pend[:]
        elif ch == "$" and c.startswith("$(", i):
            endseg(); i += 2
        else:
            cur.append(ch); has[0] = True; i += 1
    endseg()
    return segs


_ASG = re.compile(r"[A-Za-z_]\w*=")
_ENV_S = re.compile(r"^-([^-uCPS]*)S(.*)$", re.S)          # env -S / -iS / -S'cmd args' (the value is attached or the next word)


def norm_seg(w):
    a = []; u = []; i = 0; ns = 0
    while i < len(w):
        x = w[i]
        if _ASG.match(x):
            a.append(x.split("=", 1)[0]); i += 1
            continue
        wr = os.path.basename(x)
        if wr.lower().endswith(".exe") and wr.lower()[:-4] in WRAPPERS2:
            wr = wr[:-4].lower()                                 # wsl.exe, timeout.exe ... (WSL and Windows spellings)
        if wr == "find" and any(y in EXEC_FLAGS for y in w[i + 1:]):     # P3 R2: find -exec CMD ...: CMD is what runs (a `{}` command word is unknown)
            j = next(k for k in range(i + 1, len(w)) if w[k] in EXEC_FLAGS)
            inner = []
            for y in w[j + 1:]:
                if y in (";", "+"):
                    break
                inner.append(y)
            a2, u2, w2 = norm_seg(inner or ["{}"])
            return a + a2, u + u2, w2
        if wr not in WRAPPERS and wr not in WRAPPERS2:
            break
        i += 1
        if wr in ("xargs", "parallel"):
            a.append("XARGS")                                    # the arguments come from stdin: unknown
        while i < len(w) and (w[i].startswith("-") or _ASG.match(w[i])):
            if wr in W2_VALFLAGS and w[i] in W2_VALFLAGS[wr] and i + 1 < len(w):
                i += 2
            elif wr == "env" and (_ENV_S.match(w[i]) or (w[i].startswith("--sp") and "split-string".startswith(w[i][2:].split("=", 1)[0]))):
                ns += 1; a.append("ENVSPLIT")                    # D9 M2: env -S 'cmd args' splits the string into the command that runs: judge the inner command, not the string
                x_ = w[i]
                if x_.startswith("--"):
                    val_, k_ = (x_.split("=", 1)[1], 1) if "=" in x_ else (w[i + 1] if i + 1 < len(w) else "", 2)
                else:
                    m_ = _ENV_S.match(x_)
                    if "i" in m_.group(1):
                        u.append("CLAUDECODE")
                    val_, k_ = (m_.group(2), 1) if m_.group(2) else (w[i + 1] if i + 1 < len(w) else "", 2)
                if ns > 20 or len(val_) > 20000:
                    u.append("CLAUDECODE"); i += k_                # fail closed: too many nested -S or a huge value is refused as an admin segment, never judged by the old handling
                else:
                    w = w[:i] + (cmd_segments(val_, 3) or [[]])[0] + w[i + k_:]
            elif wr == "env" and (w[i] in ("-", "--ignore-environment") or re.match(r"^-[^-uSCP]*i", w[i])):
                u.append("CLAUDECODE"); i += 1                   # env -i: the command runs without CLAUDECODE (same as unsetting it)
            elif wr == "exec" and re.match(r"^-[A-Za-z]*c[A-Za-z]*$", w[i]):
                u.append("CLAUDECODE"); i += 1                   # exec -c: empty environment
            elif wr in ("xargs", "parallel") and w[i] in XARGS_VAL and i + 1 < len(w):
                i += 2
            elif wr == "env" and w[i] in ("-u", "--unset") and i + 1 < len(w):
                u.append(w[i + 1]); i += 2
            elif wr == "env" and w[i].startswith("-u"):
                u.append(w[i][2:]); i += 1
            elif _ASG.match(w[i]):
                a.append(w[i].split("=", 1)[0]); i += 1
            elif wr in ("sudo", "nice") and w[i] in ("-u", "-n", "-g", "-h") and i + 1 < len(w):
                i += 2
            else:
                i += 1
        for _k in range(W2_NPOS.get(wr, 0)):                     # script FILE, timeout DURATION, flock LOCKFILE
            if i < len(w) and not w[i].startswith("-") and not _ASG.match(w[i]):
                i += 1
    return a, u, w[i:]


def _find_clauses(w):
    """D9: `find ... -exec A \\; -exec B \\;` (also -execdir, -ok, -okdir): norm_seg judges the first clause, every clause is judged here as a command of its own."""
    if not any(x in EXEC_FLAGS for x in w) or not (any(os.path.basename(x) == "find" for x in w) or any(x in ("-exec", "-execdir") for x in w)):
        return []                                                # cmd_segments cuts a segment at `{}`: the later clauses arrive without the `find` word
    res = []; k = 0
    while k < len(w):
        if w[k] in EXEC_FLAGS:
            inner = []; k += 1
            while k < len(w) and w[k] not in (";", "+"):
                inner.append(w[k]); k += 1
            if inner:
                res.append(norm_seg(inner))
        k += 1
    return res


def all_segs(c, depth=0):
    out = []
    for w in cmd_segments(c, depth):
        for a, u, ww in [norm_seg(w)] + _find_clauses(w):
            out.append((a, u, ww))
            if depth < 3 and ww:
                b = os.path.basename(ww[0])
                if b in SHELLS:
                    for k in range(1, len(ww) - 1):
                        if re.match(r"-\w*c$", ww[k]):
                            out.extend(all_segs(ww[k + 1], depth + 1)); break
                elif b == "eval":
                    out.extend(all_segs(" ".join(ww[1:]), depth + 1))
    return out


def raw_segs(c, depth=0):
    """The words of every simple command as written (assignments included, values kept), with the commands inside `sh -c` and eval."""
    out = []
    for w in cmd_segments(c, depth):
        out.append(w)
        if depth < 3:
            ww = norm_seg(w)[2]
            if ww:
                b = os.path.basename(ww[0])
                if b in SHELLS:
                    for k in range(1, len(ww) - 1):
                        if re.match(r"-\w*c$", ww[k]):
                            out.extend(raw_segs(ww[k + 1], depth + 1)); break
                elif b == "eval":
                    out.extend(raw_segs(" ".join(ww[1:]), depth + 1))
    return out


def long_segs(c):
    return all_segs(c[:400000]) + (all_segs(c[-100000:]) if len(c) > 500000 else [])


ADMIN_ARGS = re.compile(r"^(sync|switch)$|^agents$|^registry$|^config$|^project$|^standard$|^playbook$|^cr$|^autopilot$|^owner$|^projects$|^hooks$|^skills$")
ADMIN_SUB = {"agents": ("install", "uninstall", "activate", "vendor", "migrate-team"), "registry": ("set", "activate", "forget", "sync", "write"),
             "config": ("set", "unset"), "project": ("migrate-team",), "standard": ("apply",),
             "playbook": ("set", "init", "accept", "asset"), "cr": ("abandon", "advance"),      # P5 T4
             "autopilot": ("charter", "start", "stop", "allow", "resume", "drop", "checkpoint", "admit", "probe"),
             "owner": ("mark-separate-account",), "projects": ("link", "unlink"), "hooks": ("apply",), "skills": ("approve", "ignore", "remove"), "release": ("mark",)}              # P6 T3: only the owner's terminal or panel; `autopilot show` and `autopilot charter show` stay readable
# Owner proof (OP6): a command whose TEXT names `shipm autopilot <verb>` (also inside quotes, a python -c string or a heredoc) is refused when any unrelated program runs it; readers
# of text (git, grep, rg, cat ...) never trigger it, so a commit message or a search over the code stays allowed. Launchers that run code outside the chat's process tree
# (osascript, tmux, screen, launchctl, at, crontab, open) are refused only when the same text names the command shipm or claude: a notification or `tmux ls` stays allowed.
# One definition of the command token `shipm` for every rule below (plan 2026-10-21-sm-rename-plan.md section 5). `shipm` is part of real words (shipment, shipmate,
# midshipman, ...), so it is found by command position and explicit word boundaries, never by a bare substring. Before it: not a word character and not one of
# . - $ @ % + : ~ (so `x.shipm`, `my-shipm`, `$shipm` never match; `/`, `\` and `=` ARE allowed before it: `./shipm`, `bin/shipm`, `\shipm` and `ProxyCommand=shipm` are decoded to the command by Tcl, sh, perl, node, awk, ssh;
# security review F1). The raw-text rules also run on the text with quotes and backslashes removed, and on the NFKC + case-folded text (U+017F long s runs the real file on APFS).
# After it: not a word character and not one of . - / (so `shipment`, `shipm_x`, `shipm.py`, `shipm-watch`, `shipm/` never match). Case-insensitive: APFS runs `SHIPM` as bin/shipm.
SHIPM = r"(?<![\w.\-$@%+:~])(?i:shipm)(?![\w.\-/])"
RAW_ADMIN = re.compile(r"(?:" + SHIPM + r"[\s'\",\[\]()]+(?:[\w=-]+[\s'\",\[\]]+){0,4}(?:autopilot[\s'\",\[\]]+(?:charter[\s'\",\[\]]+(?:set|clear)|start|stop|allow|resume|drop|checkpoint|admit|probe)|hooks[\s'\",\[\]]+apply)(?![\w-]))|shipmiracle[.\s'\",/]*(?:import\s+)?githook_apply(?!\.py\b)")
RAW_SWITCH = re.compile(SHIPM + r"[\s'\",\[\]()]+(?:switch|config[\s'\",\[\]]+set)[\s'\",\[\]]+autopilot\.")
INERT_CMDS = frozenset(("git", "gh", "grep", "egrep", "fgrep", "rg", "ag", "ack", "cat", "head", "tail", "less", "more", "wc", "diff", "man", "ls", "cd", "pwd", "true", "false", "test",
                        "[", "[[", "sort", "uniq", "cut", "tr", "nl", "column", "jq", "basename", "dirname", "realpath", "stat", "file", "date", "which", "type", "mkdir", "touch", "tree", "du", "df"))
HARD_LAUNCHERS = ("osascript", "tmux", "screen", "launchctl", "at", "batch", "crontab", "expect", "wt", "schtasks", "mshta", "wscript", "cscript", "rundll32", "gnome-terminal", "konsole", "xterm",
                  "x-terminal-emulator", "xdotool", "ydotool", "wtype", "systemd-run", "loginctl", "kitten", "wezterm", "shortcuts",
                  "xdg-open", "gnome-open", "kde-open", "kde-open5", "gvfs-open", "secret-tool", "xclip", "xsel", "wl-copy", "wl-paste", "notify-send", "dbus-send", "gdbus", "busctl",
                  "kdialog", "zenity", "gio", "gtk-launch", "kioclient", "kioclient5", "kioclient6", "dex", "exo-open", "qdbus", "qdbus-qt5", "qdbus6", "qdbus-qt6", "dbus-launch",
                  "dbus-update-activation-environment", "gsettings", "dconf", "pkexec", "run0", "flatpak-spawn", "machinectl")      # programs that start or type into code outside this chat's process tree; the second line is Linux: openers, keyring, clipboard, pop-ups, the session bus; the third: launchers, settings that autostart, privilege wrappers (D9 M3)
LAUNCHER_CMDS = frozenset(HARD_LAUNCHERS + ("open", "powershell", "pwsh", "cmd", "wsl"))
LAUNCH_WORDS = re.compile(r"\b(?:Start-Process|Register-ScheduledTask|SendKeys|AppActivate|WScript\.Shell)\b|\bcmd(?:\.exe)?\s+/[ck]\b[^;|&]*\bstart\b", re.I)
ENC_FLAG = re.compile(r"^-(?:e|ec|enc|encodedcommand)$", re.I)
NAMES_SHIPM = re.compile(SHIPM + r"|(?<![\w/.-])claude(?![\w/.-])")          # the command token, or claude
RAW_TEXT = "That text starts an autopilot command from a program. Type `shipm autopilot ...` yourself in Terminal; to mention it in a note, put the note in a file (git commit -F)."
LAUNCH_TEXT = "That command opens another program and names shipm or claude. Run `shipm ...` yourself in Terminal instead."


def _fold(s):
    """A name as the file system sees it: NFKC, zero-width and soft-hyphen characters dropped, case-folded. APFS folds U+017F (long s) to s and U+212A (Kelvin) to k; str.lower() does not
    (security review F2), so every comparison of a command word or script name with `shipm` goes through this."""
    import unicodedata  # SHIPMIRACLE-LAZY
    return unicodedata.normalize("NFKC", s).translate(_ZW).casefold()


def _ansi_c(t):
    """The text with bash $'...' strings decoded (\\xNN, \\NNN octal, \\uNNNN, \\UNNNNNNNN): the shell turns $'\\xc5\\xbfhipm' into a name the file system folds to shipm."""
    def one(m):
        out = re.sub(r"\\x([0-9a-fA-F]{1,2})|\\([0-7]{1,3})|\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})",
                     lambda e: chr(int(e.group(1) or e.group(2) or e.group(3) or e.group(4), 16 if (e.group(1) or e.group(3) or e.group(4)) else 8) % 0x110000), m.group(1))
        if all(ord(c) < 256 for c in out):
            try:
                out = out.encode("latin-1").decode("utf-8")
            except UnicodeError:
                pass
        return out
    return re.sub(r"\$'((?:[^'\\]|\\.)*)'", one, t)


def _cmd_name(w0):
    b = _fold(os.path.basename(w0))
    return b[:-4] if b.endswith(".exe") else b


def _decode_ps(segs):
    """Texts of PowerShell -EncodedCommand arguments (base64 of UTF-16LE), and True when one of them cannot be decoded."""
    import base64
    out, bad = [], False
    for _a, _u, w in segs:
        if not w or _cmd_name(w[0]) not in ("powershell", "pwsh"):
            continue
        for k, x in enumerate(w[1:-1], 1):
            if ENC_FLAG.match(x):
                try:
                    out.append(base64.b64decode(w[k + 1], validate=True).decode("utf-16-le"))
                except Exception:
                    bad = True
    return out, bad


# Owner proof, review round 2: files that decide who counts as the owner, launchers that run payloads outside this chat (unconditional, design 6.3), commands that run text they build.
PROT_NAMES = re.compile(r"throwaway-account|probes\.json|presence\.sha256|shipm-presence|separate-account", re.I)
PROT_READERS = frozenset(("cat", "grep", "egrep", "fgrep", "rg", "ls", "head", "tail", "stat", "wc", "diff", "cd", "pwd", "true", "test", "[", "[[", "git", "gh"))
PROT_REDIR = re.compile(r">>?\s*\S*(?:throwaway-account|probes\.json|presence\.sha256|shipm-presence|separate-account)", re.I)
PROT_TEXT = "Those files decide who counts as the owner (the Touch ID helper and its pin, the separate-account marker, the sandbox record): only you change them, in your own terminal. Looking (cat, ls, grep) is fine."
TERM_APPS = ("terminal", "iterm", "ghostty", "warp", "kitty", "alacritty", "wezterm", "system events", "script editor", "automator", "shortcuts", "hyper", "tabby")
OPEN_EXEC_EXT = (".command", ".terminal", ".tool", ".sh", ".scpt", ".scptd", ".workflow", ".bash", ".zsh", ".py")
OSA_BAD = re.compile(r"do script|keystroke|key code|System Events|do shell script|\bTerminal\b|iTerm|Ghostty|Warp|run script|load script|ObjC|\$\.NS|doShellScript|Application\(", re.I)
LAUNCH_ANY_TEXT = "That command starts another program or types into another window; run it yourself in Terminal instead (looking is fine: `tmux ls`, `launchctl list`, `crontab -l`, an osascript notification)."
DECODE_TEXT = "That command runs text it builds, decodes or expands itself; type the real command instead."
DECODE_PIPE = re.compile(r"(?:base64\s+(?:-d|-D|--decode)|xxd\s+-r|openssl\s+(?:enc|base64)\s+[^|;&]*-d|printf\s+(?:'[^']*\\x[0-9a-fA-F]{2}[^']*'|\"[^\"]*\\x[0-9a-fA-F]{2}[^\"]*\")|echo\s+-e\s+[^|;&]*\\x[0-9a-fA-F]{2})[^|;&]*\|\s*(?:sudo\s+)?(?:env\s+)?(?:/bin/|/usr/bin/)?(?:ba|z|da|k)?sh\b")
EVAL_EXP = re.compile(r"\beval\s+[\"']?(?:\$\(|`|\$\{|\$[A-Za-z_])")
GIT_ALIAS = re.compile(r"\bgit\s+(?:-[A-Za-z]\s+\S+\s+)*-c\s+[\"']?alias\.[\w.-]+=[\"']?!")


def _tmux_sub(r):
    i = 0
    while i < len(r):
        if r[i] in ("-L", "-S", "-f", "-c", "-T") and i + 1 < len(r):
            i += 2
        elif r[i].startswith("-"):
            i += 1
        else:
            return r[i]
    return ""


SYSTEMCTL_RUN = frozenset(("start", "restart", "reload", "reload-or-restart", "try-restart", "try-reload-or-restart", "enable", "reenable", "link", "edit", "set-environment", "import-environment",
                           "unset-environment", "daemon-reload", "daemon-reexec", "preset", "preset-all", "mask", "revert", "add-wants", "add-requires", "isolate", "condrestart", "force-reload",
                           "reload-or-try-restart", "condreload", "kill", "freeze", "thaw", "set-property", "set-default", "switch-root", "reboot", "poweroff", "halt", "suspend", "hibernate",
                           "hybrid-sleep", "suspend-then-hibernate", "kexec", "soft-reboot", "rescue", "emergency"))


KNOWN_DOC_EXT = frozenset((".txt", ".md", ".markdown", ".rst", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tif", ".tiff", ".html", ".htm", ".xhtml", ".csv", ".tsv",
                           ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".log", ".rtf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".epub", ".mp3", ".mp4",
                           ".m4a", ".mov", ".wav", ".flac", ".ogg", ".webm", ".mkv", ".avi", ".zip"))


def _opener_exec_file(x):
    """D9 m3: an existing local file that is executable and not a known document type (extension-less, .bin, `name.txt ` with a trailing space, `name#1`): xdg-open, gio open and open start it as a program.
    Relative names are looked up in the hook's working directory and in CLAUDE_PROJECT_DIR; a `cd` the gate cannot follow, or a handler the desktop runs for a known type, stays a limit."""
    if not x or x.startswith("-") or "://" in x or x.startswith("mailto:"):
        return False
    for cand in dict.fromkeys((x, x.split("#", 1)[0], x.split("?", 1)[0], x.rstrip())):
        if not cand:
            continue
        c = os.path.expanduser(cand)
        for base in ([c] if os.path.isabs(c) else [c, os.path.join(os.environ.get("CLAUDE_PROJECT_DIR") or "", c)]):
            try:
                if os.path.isfile(base) and os.access(base, os.X_OK) and os.path.splitext(cand)[1].lower() not in KNOWN_DOC_EXT:
                    return True
            except (OSError, ValueError):
                pass
    return False


MACHINECTL_RUN = frozenset(("shell", "login", "start", "enable", "reenable", "poweroff", "reboot", "terminate", "kill", "bind", "copy-to", "copy-from", "edit", "clone", "rename", "remove"))


def launcher_deny(segs):
    """True when a segment starts or types into code OUTSIDE this chat's process tree, whatever its text says (design 6.3): open of an executable document or a terminal app,
    osascript with a script file or a terminal / keystroke script, launchctl bootstrap|load|submit|kickstart, crontab with a file or -e, tmux new|send|run, screen -X / -dm,
    a terminal emulator with -e / --, shortcuts run, at / batch, xdotool / ydotool / wtype typing. Harmless forms stay allowed."""
    for _a, _u, w in segs:
        if not w:
            continue
        b = _cmd_name(w[0]); r = w[1:]
        if b in ("gtk-launch", "dex", "dbus-launch", "dbus-update-activation-environment", "pkexec", "run0"):
            return True                                          # D9 M3: start a desktop file / a program with another environment or other rights, whatever the text says
        if b == "systemctl":
            if any(x in SYSTEMCTL_RUN for x in r):
                return True                                      # D9 M1: a unit that is started, enabled, linked, edited or given an environment runs code outside this chat (user or system instance, any options between)
        elif b == "gio":
            if next((x for x in r if not x.startswith("-")), "") == "launch":
                return True
        elif b == "machinectl":
            if any(x in MACHINECTL_RUN or x.startswith(("import-", "pull-")) for x in r):
                return True                                      # a shell or a start inside a container / machine; images that are imported run later
        elif b in ("kioclient", "kioclient5", "kioclient6"):
            if "exec" in r:
                return True
        elif b == "exo-open":
            if any(x.startswith(("--launch", "--working-directory")) for x in r) or any(not re.match(r"^(?:https?|ftp|mailto):", x, re.I) for x in r if not x.startswith("-")):
                return True
        elif b in ("qdbus", "qdbus-qt5", "qdbus6", "qdbus-qt6"):
            if len([x for x in r if not x.startswith("-")]) >= 3:
                return True                                      # service path method: a method call
        elif b == "gsettings":
            if next((x for i_, x in enumerate(r) if not x.startswith("-") and not (i_ and r[i_ - 1] == "--schemadir")), "") in ("set", "reset", "reset-recursively"):
                return True
        elif b == "dconf":
            if next((x for x in r if not x.startswith("-")), "") in ("write", "load", "reset"):
                return True
        elif b == "flatpak-spawn":
            if any(x == "--host" or x.startswith(("--host-env", "--host=")) for x in r):
                return True
        if b == "open":
            if "--args" in r:
                return True
            for i, x in enumerate(r):
                lx = x.lower()
                if lx.endswith(OPEN_EXEC_EXT) or _opener_exec_file(x):
                    return True
                if x in ("-a", "-b") and i + 1 < len(r) and any(t in r[i + 1].lower() for t in TERM_APPS):
                    return True
        elif b == "osascript":
            i = 0
            while i < len(r):
                x = r[i]
                if x == "-e" and i + 1 < len(r):
                    if OSA_BAD.search(r[i + 1]):
                        return True
                    i += 2
                elif x in ("-l", "-s") and i + 1 < len(r):
                    i += 2
                elif x.startswith("-"):
                    i += 1
                else:
                    return True                                  # a script FILE
        elif b == "launchctl":
            sub_ = next((x for x in r if not x.startswith("-")), "")
            if sub_ in ("bootstrap", "load", "submit", "kickstart", "asuser", "start", "enable"):
                return True
        elif b == "crontab":
            if r != ["-l"]:
                return True
        elif b == "tmux":
            if _tmux_sub(r) in ("new-session", "new", "new-window", "neww", "send-keys", "send", "run-shell", "run", "pipe-pane", "pipep", "respawn-pane", "respawnp", "respawn-window", "respawnw",
                                "split-window", "splitw", "source-file", "source", "display-popup", "popup"):
                return True
        elif b == "screen":
            if any(x in ("-X", "-d", "-m") or x.startswith(("-dm", "-DR")) for x in r):
                return True
        elif b in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm", "urxvt", "xfce4-terminal", "mate-terminal", "lxterminal", "tilix", "terminator", "foot", "alacritty", "kitty", "wezterm", "wezterm-gui"):
            if any(x in ("-e", "--", "-x", "--command", "--execute", "-c") or x.startswith("--command=") for x in r) or (b in ("wezterm", "kitty") and r[:1] in (["start"], ["cli"], ["@"])):
                return True
        elif b == "kitten":
            if "@" in r:
                return True
        elif b == "shortcuts":
            if r[:1] == ["run"]:
                return True
        elif b in ("at", "batch"):
            if not any(x in ("-l", "-c") for x in r):
                return True
        elif b == "xdotool":
            if _tmux_sub(r) in ("type", "key", "keydown", "keyup", "click", "mousedown", "mouseup", "mousemove", "windowactivate", "windowfocus", "exec"):
                return True
        elif b in ("ydotool", "wtype", "systemd-run", "secret-tool", "dbus-send"):
            return True                                          # Linux: a transient unit runs code outside this chat; the keyring; the session bus (any message)
        elif b in ("xdg-open", "gnome-open", "kde-open", "kde-open5", "gvfs-open") or (b == "gio" and r[:1] == ["open"]):
            if any(x.lower().endswith(OPEN_EXEC_EXT + (".desktop", ".appimage", ".jar", ".rb", ".pl", ".js", ".deb", ".rpm")) or _opener_exec_file(x) for x in r):
                return True                                      # Linux `open`: an executable document or a launcher file
        elif b in ("gdbus", "busctl"):
            if any(x in ("call", "emit", "set-property") for x in r):
                return True                                      # D9 m2: an option value (--address X, -H host) can no longer hide the verb
        elif b == "zenity":
            if any(x.split("=", 1)[0] in ("--entry", "--password", "--forms") for x in r):
                return True                                      # a dialog that asks the owner to type (a fake prompt)
        elif b == "kdialog":
            if any(x.split("=", 1)[0] in ("--inputbox", "--password", "--newpassword", "--textinputbox") for x in r):
                return True
    return False


# D9 (B): programs that run a command named in an OPTION or an ENVIRONMENT VALUE (git -c core.sshCommand=, GIT_SSH_COMMAND=, rsync -e, ssh -o ProxyCommand=, man -P, less +!...). The value is judged like a
# command of its own (admin command, launcher, launcher that names shipm / claude); an ordinary value (`ssh -i key`, `cat`, `true`) stays allowed. A name built at run time stays an accepted limit.
EXEC_ENV = frozenset(("GIT_SSH_COMMAND", "GIT_SSH", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_ASKPASS", "GIT_PROXY_COMMAND", "SSH_ASKPASS", "SUDO_ASKPASS", "PAGER", "MANPAGER",
                      "EDITOR", "VISUAL", "LESSOPEN", "LESSCLOSE", "BROWSER", "PROMPT_COMMAND", "BASH_ENV"))
EXEC_HINT = re.compile(r"git|rsync|scp|sftp|ssh|\bman\b|\bless\b|\bmore\b|editor|visual|pager|lessopen|lessclose|browser|askpass|prompt_command|bash_env", re.I)
EXEC_PLAIN = frozenset(("echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "ack", "cat", "head", "tail", "wc", "diff", "jq", "sort", "uniq", "tr", "cut", "basename", "dirname", "ls", "stat", "file",
                        "test", "[", "[[", "true", "false", ":"))
GIT_EXEC_KEY = re.compile(r"^(?:alias\.|core\.(?:sshcommand|pager|editor|fsmonitor|askpass|gitproxy|hookspath)|credential\.|diff\.|sequence\.editor|gpg\.|filter\.|merge\.|pager\.|"
                          r"remote\.[^.]+\.(?:uploadpack|receivepack|vcs)|(?:difftool|mergetool|man|browser)\.|web\.browser|help\.browser|.*\.(?:cmd|command|textconv|driver|program|helper|clean|smudge|process)$)")
SSH_EXEC_OPT = ("proxycommand", "localcommand", "knownhostscommand", "remotecommand", "pkcs11provider")


def _val_deny(v, depth):
    """True when the text of an option / environment value is an admin command or a launcher (judged as a command line of its own)."""
    v = v.strip().lstrip("!").strip()
    if not v or depth > 3:
        return False
    segs = all_segs(v[:20000])
    return any(admin_seg(*g_) for g_ in segs) or bool(raw_admin(v, segs, depth + 1))


def _opt_vals(r, short, longs=()):
    """The values of an option written `-S v`, `-Sv`, `--long v` or `--long=v`."""
    out = []
    for i, x in enumerate(r):
        if x == short or x in longs:
            if i + 1 < len(r):
                out.append(r[i + 1])
        elif len(short) == 2 and x.startswith(short) and len(x) > 2 and not x.startswith("--"):
            out.append(x[2:])
        else:
            for l_ in longs:
                if x.startswith(l_ + "="):
                    out.append(x[len(l_) + 1:])
    return out


def _git_cfg_deny(kv, depth):
    if "=" not in kv:
        return False
    k, _, v = kv.partition("=")
    return bool(GIT_EXEC_KEY.match(k.strip().lower())) and _val_deny(v, depth)


def _exec_words_deny(w, depth):
    a_, u_, ww = norm_seg(w)
    b = _cmd_name(ww[0]) if ww else ""
    if b not in EXEC_PLAIN:
        for x in w:
            if "=" in x:
                nm, _, val = x.partition("=")
                if nm in EXEC_ENV and val and _val_deny(val, depth):
                    return True
    if not ww:
        return False
    r = ww[1:]
    if b == "git":
        sub = ""; i = 0
        while i < len(r):
            x = r[i]
            if x in ("-C", "--git-dir", "--work-tree", "--namespace", "-c") and i + 1 < len(r):
                if x == "-c" and _git_cfg_deny(r[i + 1], depth):
                    return True
                i += 2; continue
            if not x.startswith("-"):
                sub = x; break
            i += 1
        rest = r[i + 1:] if sub else r
        for j, x in enumerate(rest):
            nx = rest[j + 1] if j + 1 < len(rest) else ""
            if x.startswith(("--upload-pack=", "--receive-pack=", "--exec=")) and _val_deny(x.split("=", 1)[1], depth):
                return True
            if x in ("--upload-pack", "--receive-pack", "--exec") and _val_deny(nx, depth):
                return True
            if x == "-u" and sub in ("clone", "fetch", "ls-remote", "pull") and _val_deny(nx, depth):
                return True
            if x == "-c" and nx and _git_cfg_deny(nx, depth):
                return True
            if x == "--config" and nx and _git_cfg_deny(nx, depth):
                return True
            if x.startswith("--config=") and _git_cfg_deny(x[9:], depth):
                return True
        if sub == "config":
            pos = [x for x in rest if not x.startswith("-")]
            if len(pos) >= 2 and GIT_EXEC_KEY.match(pos[0].lower()) and _val_deny(pos[1], depth):
                return True
    elif b == "rsync":
        for i, x in enumerate(r):
            v = None
            if x in ("-e", "--rsh", "--rsync-path"):
                v = r[i + 1] if i + 1 < len(r) else ""
            elif x.startswith(("--rsh=", "--rsync-path=")):
                v = x.split("=", 1)[1]
            elif re.match(r"^-[A-Za-z]+e$", x):
                v = r[i + 1] if i + 1 < len(r) else ""
            elif x.startswith("-e") and len(x) > 2:
                v = x[2:]
            if v and _val_deny(v, depth):
                return True
    elif b in ("scp", "sftp", "ssh"):
        if b != "ssh" and any(_val_deny(v, depth) for v in _opt_vals(r, "-S")):
            return True
        for v in _opt_vals(r, "-o"):
            m = re.match(r"\s*(\w+)\s*[=\s]\s*(.*)$", v, re.S)
            if m and m.group(1).lower() in SSH_EXEC_OPT and _val_deny(m.group(2), depth):
                return True
    elif b == "man":
        if any(_val_deny(v, depth) for v in _opt_vals(r, "-P", ("--pager",)) + _opt_vals(r, "-H")):
            return True
    elif b in ("less", "more"):
        if any(x.startswith("+") and "!" in x and _val_deny(x.split("!", 1)[1], depth) for x in r):
            return True
    return False


def exec_value_deny(c, depth=0):
    """D9 (B): True when an execution-capable option or environment value names an admin command or a launcher."""
    if depth > 3 or not EXEC_HINT.search(c[:200000]):
        return False
    return any(_exec_words_deny(w, depth) for w in raw_segs(c[:200000]))


def raw_admin(c, segs, depth=0):
    """'' or the one-sentence deny text of the raw-text rules (see above)."""
    t = c[:200000]
    cmdw0 = [_cmd_name(w[0]) for _a, _u, w in segs if w]
    tn = re.sub(r"[\\'\"`]", "", t)
    tf, tnf = _fold(t), _fold(tn)
    ta = _ansi_c(t)
    texts = (t, tn, tf, tnf, ta, _fold(ta))
    hit = lambda rx: any(rx.search(x) for x in texts)       # the text as written, with quotes and backslashes removed, and folded like the file system folds it
    if (PROT_NAMES.search(t) or PROT_NAMES.search(tn)) and (not all(b in PROT_READERS for b in cmdw0) or PROT_REDIR.search(tn)):
        return PROT_TEXT
    if launcher_deny(segs) or exec_value_deny(c, depth):
        return LAUNCH_ANY_TEXT
    if DECODE_PIPE.search(t) or EVAL_EXP.search(t) or GIT_ALIAS.search(t):
        return DECODE_TEXT
    dec, undecodable = _decode_ps(segs)
    for d_ in dec:
        if RAW_ADMIN.search(d_) or RAW_SWITCH.search(d_) or NAMES_SHIPM.search(d_) or RAW_ADMIN.search(_fold(d_)) or RAW_SWITCH.search(_fold(d_)):
            return RAW_TEXT if (RAW_ADMIN.search(d_) or RAW_SWITCH.search(d_) or RAW_ADMIN.search(_fold(d_)) or RAW_SWITCH.search(_fold(d_))) else LAUNCH_TEXT
    if undecodable:
        return LAUNCH_TEXT
    for _a, _u, w in segs:                                   # D17: `sh FILE` / `python3 FILE` / `source FILE` where the file (written earlier) names the owner-only command
        if w and (_cmd_name(w[0]) in SHELLS or _cmd_name(w[0]) in ("source", ".", "perl", "ruby", "node") or re.match(r"^python[0-9.]*$", _cmd_name(w[0]))):
            for x_ in [x for x in w[1:] if not x.startswith("-")][:1]:
                try:
                    with open(x_, "rb") as f_:
                        body_ = f_.read(100000).decode("utf-8", "replace")
                except (OSError, ValueError):
                    continue
                if RAW_ADMIN.search(body_) or RAW_ADMIN.search(_fold(body_)) or RAW_ADMIN.search(re.sub(r"[\\'\"`]", "", body_)):
                    return RAW_TEXT
    if "shipm" not in tf and "shipm" not in tnf and "shipm" not in texts[5] and "claude" not in t:
        return ""
    cmdw = [_cmd_name(w[0]) for _a, _u, w in segs if w]
    if (any(b in LAUNCHER_CMDS for b in cmdw) or LAUNCH_WORDS.search(t)) and hit(NAMES_SHIPM):
        return LAUNCH_TEXT
    if all(b in INERT_CMDS for b in cmdw):
        return ""
    if hit(RAW_ADMIN) or hit(RAW_SWITCH):
        return RAW_TEXT
    return ""


CLAUDE_CHARTER = re.compile(r"(?:^|[^\w])(?:charter|allow)\s*:", re.I)


def unknown_cmd(c, segs):
    """P3 R2: True when a command word cannot be known: it is built from a variable, a glob, a substitution or find's `{}`."""
    for _, _, w in segs:
        if w and w[0] not in ("[", "[[") and re.search(r"[$`*?]|\{\}|(?<=[\w/.-])\[", w[0]):
            return True
    return bool(re.search(r"(?:^|[;&|(\n])[ \t]*(?:\$\(|`|\$\{|\$[A-Za-z_])", c[:200000]))


def admin_seg(a, u, w, table=None):
    if "CLAUDECODE" in u or any(x.startswith("CLAUDECODE") for x in a):
        return True
    if not w:
        return False
    b = os.path.basename(w[0]); r = w[1:]
    if b == "unset" and "CLAUDECODE" in r:
        return True
    if b in ("export", "declare", "typeset", "readonly", "local") and any(x.startswith("CLAUDECODE") for x in r):
        return True
    if re.match(r"^python[0-9.]*$", b):
        fl = [x for x in r if x.startswith("-")]
        if "-m" in r and r.index("-m") + 1 < len(r) and r[r.index("-m") + 1].split(".")[0] == "shipmiracle":
            return True
        for k, x in enumerate(r):
            if re.match(r"-\w*c$", x) and k + 1 < len(r) and re.search(r"\b(import|from)\s+shipmiracle\b|\bshipmiracle\.(cli|agents|registry|config|githook_apply)\b", r[k + 1]):
                return True
        pos = [x for x in r if not x.startswith("-")]
        if pos and (_fold(os.path.basename(pos[0])) == "shipm" or re.search(r"(^|/)shipmiracle/[\w/]+\.py$", pos[0])):
            b = "shipm"; r = pos[1:]
    pos_ = [x for x in r if not x.startswith("-")][:1]                # the script is the first positional word (`python3 -m mod file` and `python3 -c code` name something else first)
    if _fold(b) == "shipm-migrate" or ((b in SHELLS or b in ("source", ".", "exec", "perl", "ruby", "node") or re.match(r"^python[0-9.]*$", b))
                                      and any(_fold(os.path.basename(x)) == "shipm-migrate" for x in pos_)):
        return True                                              # D9: the one-off migration tool is the owner's (it refuses a chat itself; this is defence in depth)
    if b == "claude" and any(CLAUDE_CHARTER.search(x) for x in r):
        return True                                              # P6 T3 (C7): a nested chat must not type `charter:`/`allow:` as if it were the owner
    if (_fold(b) == "skills-sync" or ((b in SHELLS or re.match(r"^python[0-9.]*$", b)) and any(_fold(os.path.basename(x)) == "skills-sync" for x in r))) \
            and any(x in ("--pin", "--repin", "--from-commit") or x.startswith(("--repin=", "--pin=", "--from-commit=")) for x in r):
        return True                                              # skills-sync --pin/--repin/--from-commit rewrites the trust record (skills.lock.json): the owner's terminal only
    if (_fold(b) == "shipm-guard" or ((b in SHELLS or re.match(r"^python[0-9.]*$", b)) and any(_fold(os.path.basename(x)) == "shipm-guard" for x in r))) \
            and any(x in ("hold", "release") for x in r):
        return True                                              # shipm-guard hold/release keeps the Mac awake or lets it sleep: the owner's terminal only
    if _fold(b) != "shipm":
        return False
    if any(x.startswith("SHIPMIRACLE_") for x in a) or "XARGS" in a:
        return True
    args = [x for x in r if not x.startswith("-")]
    if not args:
        return False
    if "apply" in args and any(x.startswith(("$", "`")) or "$'" in x or '$"' in x for x in args if x != "apply"):
        return True                                              # D17: `a=hooks; shipm $a apply`: a group word built at run time next to `apply`
    for i_, g_ in enumerate(args):                               # P5 sec H1: an option value before the subcommand must not hide it, so every group word counts
        if g_ in ("sync", "switch", "migrate"):
            return True
        subs_ = (table or ADMIN_SUB).get(g_)
        if subs_:
            rest_ = args[i_ + 1:]
            if g_ == "autopilot":
                for k_ in range(len(rest_) - 1):
                    if rest_[k_:k_ + 2] == ["charter", "show"]:
                        rest_ = rest_[:k_] + rest_[k_ + 2:]; break
            elif g_ == "playbook":                                   # D6: `playbook asset list` stays readable; every other asset verb (add, remove, ...) is the owner's
                for k_ in range(len(rest_) - 1):
                    if rest_[k_:k_ + 2] == ["asset", "list"]:
                        rest_ = rest_[:k_] + rest_[k_ + 2:]; break
            if any(y_ in subs_ for y_ in rest_):
                return True
    return False


GIT_SHIPMIRACLE_SUBS = {"checkout", "restore", "reset", "stash", "rm", "mv", "clean", "apply", "am", "cherry-pick", "revert", "merge", "rebase", "pull", "switch"}
SHIPMIRACLE_NAMED = re.compile(r"(?:^|[/:)])\.shipmiracle(?:/|$)")
SHIPMIRACLE_PATCH = re.compile(r"^(?:diff --git a/\.shipmiracle/|\+\+\+ b/\.shipmiracle/|--- a/\.shipmiracle/|rename (?:from|to) \.shipmiracle/)", re.M)


def git_shipmiracle_seg(w, has_pb):
    """P5 sec L1: True for a git command that can rewrite .shipmiracle/**: it names .shipmiracle, or it is a worktree-wide form in a project that has .shipmiracle/playbook.json."""
    if not w or os.path.basename(w[0]) != "git":
        return False
    r = w[1:]; i = 0
    while i < len(r):
        if r[i] in ("-C", "--git-dir", "--work-tree", "-c", "--namespace") and i + 1 < len(r):
            i += 2
        elif r[i].startswith("-"):
            i += 1
        else:
            break
    if i >= len(r) or r[i] not in GIT_SHIPMIRACLE_SUBS:
        return False
    sub = r[i]; rest = r[i + 1:]; pos = [x for x in rest if not x.startswith("-")]; fl = [x for x in rest if x.startswith("-")]
    if any(SHIPMIRACLE_NAMED.search(x) for x in rest):
        return True
    if sub in ("apply", "am"):
        for x in pos[:5]:
            try:
                if SHIPMIRACLE_PATCH.search(open(x, "rb").read(1000000).decode("utf-8", "replace")):
                    return True
            except OSError:
                pass
        return False
    if not has_pb:
        return False
    whole = [".", ":/", ":(top)", "*", "./"]
    if sub == "checkout":
        return any(x in whole for x in pos) or "-f" in fl or "--force" in fl
    if sub == "restore":
        return any(x in whole for x in pos)
    if sub == "reset":
        return "--hard" in fl
    if sub == "stash":
        return pos[:1] not in (["list"], ["show"])
    if sub == "clean":
        return not any(f in ("-n", "--dry-run") or re.match(r"^-[a-zA-Z]*n[a-zA-Z]*$", f) for f in fl)
    if sub in ("rm", "mv"):
        return sub == "rm" and any(x in whole for x in pos)
    return False


GIT_MUT = {"add", "commit", "push", "reset", "checkout", "switch", "restore", "merge", "rebase", "cherry-pick", "revert", "clean", "rm", "mv", "apply", "am",
           "update-ref", "gc", "update-index", "worktree", "notes", "pull", "init", "clone", "prune", "filter-branch"}
NPM_MUT = {"i", "install", "ci", "add", "remove", "uninstall", "rm", "un", "publish", "update", "up", "upgrade", "link", "prune", "dedupe", "rebuild"}


def mut_seg(w, ok):
    if not w:
        return None
    c0 = os.path.basename(w[0]); r = w[1:]
    pos = [x for x in r if not x.startswith("-")]; fl = [x for x in r if x.startswith("-")]
    has = lambda *names: any(f in names or f.split("=")[0] in names for f in fl)
    if any(f_.split("=")[0] in ("--snapshot-update", "--update-snapshots", "--update-snapshot", "--snapshot_update") for f_ in r) or \
            (r and "-u" in r and c0 in ("jest", "vitest", "npm", "pnpm", "yarn", "npx", "bunx", "bun", "uv", "node")):
        return "snapshot update"                                 # P3 R6: rewrites the expected files of the tests
    if c0 in ("npx", "bunx") and pos:
        return mut_seg(r[r.index(pos[0]):], ok)
    if c0 == "git":
        i = 0
        while i < len(r):
            if r[i] in ("-C", "--git-dir", "--work-tree", "-c", "--namespace") and i + 1 < len(r):
                if r[i] == "-c" and r[i + 1].lower().startswith("alias."):
                    return "git -c alias"
                i += 2
            elif r[i].startswith("-"):
                i += 1
            else:
                break
        if i >= len(r):
            return None
        sub = r[i]; rest = r[i + 1:]; rp = [x for x in rest if not x.startswith("-")]; rf = [x for x in rest if x.startswith("-")]
        if sub in GIT_MUT:
            return "git " + sub
        if sub == "stash":
            return None if rp[:1] in (["list"], ["show"]) else "git stash"
        if sub == "tag":
            return None if (not rp or "-l" in rf or "--list" in rf) else "git tag"
        if sub == "branch":
            if any(f in ("-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "-u", "--set-upstream-to", "--unset-upstream") for f in rf):
                return "git branch"
            return "git branch" if rp and not any(f in ("-l", "--list", "--contains", "--merged", "--no-merged", "--points-at") for f in rf) else None
        if sub == "config":
            if any("alias." in x.lower() for x in rest):
                return "git config alias"
            return "git config" if len(rp) >= 2 and not any(f in ("--get", "--get-all", "--list", "-l", "--get-regexp") for f in rf) else None
        if sub == "remote":
            return "git remote" if rp[:1] and rp[0] in ("add", "remove", "rm", "rename", "set-url", "set-head", "prune") else None
        return None
    if c0 == "npm" or c0 == "pnpm":
        return c0 + " " + pos[0] if pos and pos[0] in NPM_MUT else None
    if c0 == "yarn":
        return "yarn" if (not pos and not fl) or pos[:1] and pos[0] in ("install", "add", "remove", "publish", "upgrade", "link", "up") else None
    if c0 in ("pip", "pip3") or re.match(r"^pip3?\.\d+$", c0):
        return "pip " + pos[0] if pos and pos[0] in ("install", "uninstall") else None
    if re.match(r"^python[0-9.]*$", c0) and "-m" in r and r.index("-m") + 2 < len(r) + 1:
        k = r.index("-m")
        if k + 1 < len(r) and r[k + 1] == "pip":
            return "pip install" if any(x in ("install", "uninstall") for x in r[k + 2:]) else None
        return None
    if c0 == "uv":
        return "uv " + " ".join(pos[:2]) if (pos[:2] in (["pip", "install"], ["pip", "uninstall"]) or pos[:1] in (["add"], ["remove"], ["sync"], ["lock"])) else None
    if c0 == "pipx":
        return "pipx" if pos[:1] and pos[0] in ("install", "uninstall", "upgrade") else None
    if c0 == "brew":
        return "brew " + pos[0] if pos and pos[0] in ("install", "uninstall", "upgrade", "reinstall", "remove", "tap", "untap", "link", "unlink") else None
    if c0 == "curl":
        for k, x in enumerate(r):
            if x in ("-o", "--output") and k + 1 < len(r):
                return None if ok(r[k + 1]) else "curl -o"
            if x.startswith("--output="):
                return None if ok(x[9:]) else "curl -o"
            if x in ("-O", "--remote-name", "-J", "-OJ", "--remote-name-all"):
                return "curl -O"
            if re.match(r"^-[A-Za-z]*o.+", x) and not x.startswith("--"):
                return None if ok(x.split("o", 1)[1]) else "curl -o"
        return None
    if c0 == "wget":
        if has("--spider"):
            return None
        for k, x in enumerate(r):
            if x in ("-O", "--output-document") and k + 1 < len(r):
                return None if (r[k + 1] == "-" or ok(r[k + 1])) else "wget -O"
        return "wget"
    if c0 == "tar":
        first = r[0] if r else ""
        flags = first.lstrip("-") if first and not first.startswith("--") else ""
        if "x" in flags or has("--extract", "-x"):
            for k, x in enumerate(r):
                if x in ("-C", "--directory") and k + 1 < len(r):
                    return None if ok(r[k + 1]) else "tar -C"
            return "tar x"
        return None
    if c0 == "unzip":
        if has("-l", "-t", "-p", "-Z", "-v"):
            return None
        for k, x in enumerate(r):
            if x == "-d" and k + 1 < len(r):
                return None if ok(r[k + 1]) else "unzip -d"
        return "unzip"
    if c0 in ("mkdir", "rmdir"):
        return None if pos and all(ok(x) for x in pos) else c0
    if c0 == "eval":
        return "eval"
    if c0 == "prettier":
        return "prettier --write" if has("--write", "-w") else None
    if c0 == "eslint":
        return "eslint --fix" if has("--fix") else None
    if c0 == "ruff":
        if pos[:1] == ["format"]:
            return None if has("--check", "--diff") else "ruff format"
        return "ruff --fix" if has("--fix") else None
    if c0 == "black":
        return None if has("--check", "--diff", "--help", "-h", "--version") else "black"
    if c0 == "gofmt":
        return "gofmt -w" if has("-w") else None
    if c0 == "go":
        return "go fmt" if pos[:1] == ["fmt"] else None
    if c0 == "cargo":
        return "cargo fmt" if pos[:1] == ["fmt"] and not has("--check") else None
    if c0 == "rustfmt":
        return None if has("--check") else "rustfmt"
    if c0 == "swiftformat":
        return None if has("--lint", "--dryrun") else "swiftformat"
    return None


TEST_VERDICTS = ("NOT TESTED", "BLOCKED", "PASS", "FAIL")
REVIEW_VERDICTS = ("REMEDIATE", "ACCEPT WITH FIXES", "ACCEPT")
BAD_QA = ("FAIL", "BLOCKED", "NOT TESTED")
SEVERITY = {"FAIL": 5, "BLOCKED": 4, "NOT TESTED": 3, "REMEDIATE": 5, "ACCEPT WITH FIXES": 3, "PASS": 1, "ACCEPT": 1}
_VLINE = re.compile(r"^[\s*_`#\-]*(?:\w+\s+)?verdict[\s*_`]*(:)?[\s*_`]*(.*)$", re.I)
_LEAD = re.compile(r"^[\s*_`\"'()\[\]~.\-]*")
_ANCHOR = {"NOT TESTED": r"NOT\s+TESTED", "BLOCKED": r"BLOCKED", "PASS": r"PASS(?:ED)?", "FAIL": r"FAIL(?:ED|ING)?",
           "REMEDIATE": r"REMEDIATE", "ACCEPT WITH FIXES": r"ACCEPT\s+WITH\s+\w+", "ACCEPT": r"ACCEPT"}
_QUALIFY = re.compile(r"\b(EXCEPT|BUT|UNLESS|IF|WITHOUT|NOT|PARTIAL|SOME|ONLY)\b|\b[1-9]\d*\s+(FAIL\w*|ERRORS?|BLOCKED)\b")
_ZW = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"))


def _norm(msg):
    import unicodedata  # SHIPMIRACLE-LAZY
    return unicodedata.normalize("NFKC", msg).translate(_ZW)


def _lines(msg):
    """Lines that can carry a report field: not inside ``` / ~~~ fences, not quotes (> ...), not indented code (4+ spaces or a tab)."""
    fence = False
    for ln in msg.splitlines():
        t = ln.strip()
        if t.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence or t.startswith(">") or ln.startswith(("    ", "\t")):
            continue
        yield t


def _field(msg, name):
    val = ""
    for ln in _lines(_norm(msg)):
        m = re.match(r"^[\s*_`#\-]*" + name + r"[\s*_`]*:[\s*_`]*(.*)$", ln, re.I)
        if m:
            val = m.group(1)
    return val


def _one(value, kinds):
    """Judge one Verdict value: a verdict, 'IGNORE' (a template listing several verdicts) or '' (unknown)."""
    v = _LEAD.sub("", re.sub(r"[*_`]", " ", value)).upper()
    v = re.sub(r"\s+", " ", v).strip()
    test = "PASS" in kinds
    for k in kinds:
        m = re.match(_ANCHOR[k] + r"\b", v)
        if not m:
            continue
        rest = v[m.end():]
        if re.match(r"^\s*[|/]", rest) or re.match(r"^\s*OR\s+[A-Z]", rest):
            return "IGNORE"                                       # the template 'PASS | FAIL | ...'
        if k in ("PASS", "ACCEPT") and _QUALIFY.search(rest):
            if k == "PASS":
                return "FAIL" if re.search(r"FAIL", rest) else "NOT TESTED"
            return "ACCEPT WITH FIXES"
        if k == "ACCEPT WITH FIXES":
            return "ACCEPT WITH FIXES"                           # 'ACCEPT WITH MINORS' and the like: the safe reading
        return k
    if test:                                                      # not anchored: 'not PASS - 3 failed', 'would be PASS if', 'PARTIAL PASS'
        if re.search(r"\bFAIL", v):
            return "FAIL"
        if re.search(r"\bBLOCKED\b", v):
            return "BLOCKED"
        if re.search(r"\bPASS", v):
            return "NOT TESTED"
    elif re.search(r"\bREMEDIATE\b", v):
        return "REMEDIATE"
    elif re.search(r"\bACCEPT", v):
        return "ACCEPT WITH FIXES"
    return ""


def parse_verdict(msg, kinds):
    """The report's Verdict. Fenced, quoted and indented lines are ignored; the value must START with a verdict word; when several
    lines remain the most severe wins. Returns (verdict, counts, lens): verdict '' when none; counts = digit counts only ('3 failed, 9 passed')."""
    if not isinstance(msg, str):
        return "", "", ""
    msg = _norm(msg[-20000:])
    lines = list(_lines(msg)); found = []
    for i, ln in enumerate(lines):
        m = _VLINE.match(ln)
        if not m or not (m.group(1) or not m.group(2)):
            continue                                              # 'Verdict ...' without a colon and with text is prose
        val = m.group(2)
        if not val.strip(" *_`"):                                 # heading style: '## Verdict' and the value on the next line
            val = next((x for x in lines[i + 1:i + 4] if x.strip(" *_`")), "")
        j = _one(val, kinds)
        if j and j != "IGNORE":
            found.append(j)
    verdict = max(found, key=lambda k: SEVERITY.get(k, 0)) if found else ""
    ev = _field(msg, "Evidence")
    counts = ", ".join(f"{n} {w.lower()}" for n, w in re.findall(r"\b(\d{1,6})\s+(passed|failed|failing|failures?|errors?|skipped|pass|fail)\b", ev, re.I)[:6])
    lens = re.sub(r"[^A-Za-z0-9 ,/_-]", "", _field(msg, "Lens"))[:60].strip()
    return verdict, counts, lens


def qa_cohort(st):
    """QA runs that count for the last build: the newest run plus every run that overlapped it (parallel agents), only runs
    that stopped at/after the last build. Returns a list of run dicts (oldest first)."""
    runs = [r for r in (st.get("qa_runs") or []) if isinstance(r, dict) and r.get("ts", 0) >= st.get("build_ts", 0)]
    if not runs:
        return []
    known = [r for r in runs if r.get("verdict")]
    runs = known or runs                                         # a verdict-less run never supersedes an earlier known verdict since the last build
    runs.sort(key=lambda r: r["ts"])
    cohort = [runs[-1]]; lo = runs[-1].get("start", runs[-1]["ts"])
    for r in reversed(runs[:-1]):
        if r["ts"] >= lo:
            cohort.insert(0, r); lo = min(lo, r.get("start", r["ts"]))
    return cohort


def qa_eval(st, mode):
    """-> (state, kind, message, extra). state: none | pending | passed | failed | unknown | stale. kind '' when satisfied."""
    hm = lambda t: time.strftime("%H:%M", time.localtime(t))
    bt = st.get("build_ts", 0)
    if not bt:
        return "none", "", "", {}
    cohort = qa_cohort(st)
    legacy_ts = st.get("qa_ts", 0) >= bt and not st.get("qa_runs")      # state written before verdicts existed
    if not cohort and not legacy_ts:
        pend = [t for t in (st.get("qa_pending") or {}).values() if isinstance(t, (int, float)) and t >= bt - 1]
        if pend:
            return "pending", "done_without_qa", (f"{st.get('qa_by') or QA[0]} was started at {hm(max(pend))} but never reported "
                    "(probably cut off by its turn limit, which leaves no verdict): run it again on a narrower scope and wait for its Verdict line."), {}
        return ("stale" if st.get("qa_runs") else "none"), "done_without_qa", (
            f"Agents changed files since the last QA run. Run {QA[0]} on the change (Agent tool) and report its pass/fail counts before finishing."), {}
    vs = [r.get("verdict", "") for r in cohort] or [""]
    bad = [r for r in cohort if r.get("verdict") in BAD_QA]
    if bad:
        r = bad[-1]; v = r["verdict"]; ev_ = re.sub(r"[^0-9A-Za-z ,]", "", str(r.get("evidence") or ""))[:80]   # digit counts only, never free text
        counts = f" ({ev_})" if re.search(r"\d", ev_) else ""
        extra = {"qa_verdict": v, "qa_verdict_ts": int(r["ts"]), "qa_by": r.get("by", "")}
        nxt = {"FAIL": f"rerun the builder ({st.get('built_by') or 'the engineer'}) on the failures, then {r.get('by') or QA[0]} again. Do not report success until QA says PASS.",
               "BLOCKED": f"QA could not run its checks: remove the blocker (missing tool, access or file) or tell the owner what blocks it, then run {QA[0]} again.",
               "NOT TESTED": f"QA ran nothing: run {QA[0]} again with the exact test command to execute."}[v]
        return "failed", "qa_failed", f"QA reported {v} at {hm(r['ts'])}{counts}: {nxt}", extra
    if all(v == "PASS" for v in vs) and cohort:
        return "passed", "", "", {"qa_verdict": "PASS", "qa_verdict_ts": int(cohort[-1]["ts"])}
    last = cohort[-1] if cohort else {"ts": st.get("qa_ts", 0)}
    extra = {"qa_verdict": "unknown", "qa_verdict_ts": int(last["ts"])}
    if mode == "strict":
        return "unknown", "qa_no_verdict", (f"{last.get('by') or st.get('qa_by') or QA[0]} finished at {hm(last['ts'])} without a "
                "'Verdict: PASS|FAIL|BLOCKED|NOT TESTED' line, so the gate cannot tell if the checks passed: ask it for its report in the "
                "Definition-of-Done format (Verdict, Evidence), or run it again."), extra
    return "unknown", "", "", extra                                       # legacy: an older agent file without the DoD: 'ran' counts


# ---- G11 + D11: project isolation layer 1 and the secret-read rule (plan docs/plans/2026-10-23-G11-D11-project-isolation-layer1.md; rules in docs/owner-steps/link-projects.md) ----
# A text-level guard against slips, NOT a security boundary (G12 is): it does not see computed paths, programs that open files themselves, MCP servers or cd chains it cannot follow.
# Same rule for the main chat and agents; level = config/flow.json "isolation" (strict | warn | off); an internal error refuses at strict. Tables = the literals of autopilot/rules.py (tests compare).
SECRET_HOME_DIRS = (".ssh", ".gnupg", ".kube", ".local/share/keyrings", ".gnome2/keyrings", ".config/gcloud", ".azure", "Library/Keychains", "Library/Cookies", "Library/Safari",
                    "Library/Application Support/Google/Chrome", "Library/Application Support/BraveSoftware", "Library/Application Support/Microsoft Edge", "Library/Application Support/Arc",
                    "Library/Application Support/Firefox", ".config/google-chrome", ".config/BraveSoftware", ".config/chromium", ".config/microsoft-edge", ".mozilla", ".password-store", ".oci", "Library/Messages", ".aws/sso")
SECRET_SSH_KEEP = (".pub", "known_hosts", "known_hosts.old", "config")
SECRET_HOME_FILES = (".aws/credentials", ".docker/config.json", ".config/gh/hosts.yml", ".netrc", ".pypirc", ".git-credentials", ".npmrc", ".yarnrc.yml", ".claude/.credentials.json",
                     ".claude.json", ".terraform.d/credentials.tfrc.json", ".config/gcloud/credentials.db", ".pgpass", ".my.cnf", ".s3cfg", ".vault-token", ".boto", ".oci/config", ".m2/settings.xml", ".config/op/config", ".bash_history", ".zsh_history", ".python_history", ".psql_history", ".mysql_history", ".node_repl_history", ".sh_history", ".local/share/fish/fish_history", ".huggingface/token", ".cache/huggingface/token", ".config/anthropic/key", ".openai/key", ".authinfo", "_netrc", ".zshenv", ".viminfo", ".rediscli_history", ".irb_history", ".sqlite_history", ".lesshst", ".config/hub")
SECRET_NAME_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".secret", ".env", ".tfvars", ".tfstate", ".tfstate.backup", ".kdbx", ".p8")
SECRET_NAME_EXACT = (".envrc", ".dev.vars", ".npmrc", ".pypirc", "kubeconfig", ".pgpass", ".my.cnf", ".s3cfg", "state.vscdb", ".netrc", "_netrc", ".git-credentials", ".htpasswd", ".vault-pass", ".vault_pass", ".dockerconfigjson",
                     "wp-config.php", "token.txt", "api_token", ".token", "oauth.json", "settings.local.py", "application-secrets.properties", "secring.gpg", "secring.pgp")
SECRET_NAME_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
SECRET_DATA_NAMES = ("credentials", "secret", "secrets", "creds")
SECRET_DATA_EXT = ("json", "yaml", "yml", "toml", "ini", "txt", "env", "conf", "cfg", "")
ENV_ALLOW_SUFFIXES = ("example", "sample", "template", "dist", "defaults")
KEY_USERS = ("ssh", "scp", "sftp", "ssh-add", "ssh-keygen", "sshpass")
USE_FLAGS = ("--env-file", "--envfile", "--env-file-path")
WS_READ_ALLOW = ("AGENTS.md", "CLAUDE.md", "README.md", "bin", "hooks", "shipmiracle", "templates", "agents", "skills", "memory", "config", "docs/standards", "docs/owner-steps")
CLAUDE_STORES = ("projects", "history.jsonl", "file-history", "shell-snapshots", "todos", "session-env")
ISO_READ_TOOLS = ("Read", "Grep", "Glob", "LS", "NotebookRead")
ISO_FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
ISO = {}
ISO_WD = 8.0
OUTER_WD = 10.0                                                       # legacy only: total wall limit of one PreToolUse call (the v1 dispatcher has its own, see core.py)
EMIT = [__import__("threading").Lock(), False]                        # one lock + flag for everything that writes the answer (main thread, isolation watchdog, outer watchdog): exactly one JSON goes out
ISO_CALL = [None]                                                     # (project, tool) of the PreToolUse call being judged: set before the isolation check
ISO_CRASH = "the isolation check could not finish (an internal error was logged); the call is refused until it can. Ask the owner to run `shipm doctor`."
ISO_W_ALL = frozenset(("rm", "rmdir", "touch", "mkdir", "chmod", "chown", "chgrp", "truncate", "unlink", "shred", "history", "tee", "mkfifo", "chflags", "xattr"))
ISO_DEST = frozenset(("cp", "mv", "install", "ln", "link", "rsync", "scp", "ditto"))
ISO_NOPATH = frozenset(("echo", "printf", "export", "unset", "alias", "type", "which", "whereis", "true", "false", ":", "read", "sleep", "date", "kill", "wait", "exit", "return", "declare",
                        "local", "readonly", "typeset", "set", "shopt", "trap", "ulimit", "umask", "unalias", "hash", "let", "bind", "jobs", "fg", "bg", "popd", "dirs", "pwd", "[", "[["))
ISO_NOSHOW = frozenset(("ls", "stat", "file", "test", "chmod", "chown", "chgrp", "rm", "touch", "mv", "ln", "mkdir", "rmdir", "du", "wc", "realpath", "readlink", "basename", "dirname", "unlink", "shred", "lsof", "shasum", "sha1sum", "sha224sum", "sha256sum", "sha384sum", "sha512sum", "md5sum", "md5", "cksum", "b2sum", "sum"))
ISO_GIT_NOSHOW = frozenset(("add", "check-ignore", "rm", "mv", "reset", "restore", "checkout", "stash", "ls-files", "clean", "update-index", "status", "commit", "switch", "worktree", "init", "clone", "remote", "config"))
ISO_PAT_FIRST = frozenset(("grep", "egrep", "fgrep", "ggrep", "zgrep", "zegrep", "zfgrep", "bsdgrep", "ugrep", "ug", "rg", "ag", "ack", "sed", "awk", "gawk", "mawk"))
ISO_RECURSIVE = frozenset(("find", "tree", "du", "rg", "ag", "ack", "fd", "fdfind", "rsync", "tar", "zip", "ditto", "7z", "7za", "bsdtar", "gtar"))
_ISO_R = re.compile(r"^-[A-Za-z]*[rR]|^--(?:dereference-)?recursive")
_ISO_RU = re.compile(r"^-[A-Za-z]*R|^--recursive")
ISO_RECFLAG = {"grep": _ISO_R, "egrep": _ISO_R, "fgrep": _ISO_R, "ggrep": _ISO_R, "zgrep": _ISO_R, "zegrep": _ISO_R, "zfgrep": _ISO_R, "bsdgrep": _ISO_R, "ugrep": _ISO_R, "ug": _ISO_R, "cp": re.compile(r"^-[A-Za-z]*[rRa]|^--(?:recursive|archive)"), "ls": _ISO_RU, "chmod": _ISO_RU, "chown": _ISO_RU, "scp": re.compile(r"^-[A-Za-z]*r")}
ISO_GREPS = frozenset(("grep", "egrep", "fgrep", "ggrep", "zgrep", "zegrep", "zfgrep", "bsdgrep", "ugrep", "ug"))
ISO_URLCMDS = frozenset(("curl", "wget", "http", "https", "xh", "httpie", "open", "gh", "npm", "pnpm", "yarn", "pip", "pip3", "docker", "ssh", "scp", "rsync", "brew", "go", "cargo", "sftp", "ftp", "nc"))
ISO_CMDSTR = {"npx": ("-c", "--call"), "nix-shell": ("--run", "--command"), "nix": ("--command", "-c"), "script": ("-c", "--command")}
ISO_IOWORD = re.compile(r"open|read|load|dotenv|glob|walk|listdir|scandir|readdir|copy|move|rename|unlink|exec|system|popen|spawn|subprocess|send|post|upload|curl|\bcat\b|sql|attach|source|fetch|stream|Deno|Bun|open3", re.I)
ISO_SHELLS = ("bash", "sh", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "busybox", "mksh", "ash", "rbash", "su")
ISO_WOPT = {"curl": ("-o", "--output"), "wget": ("-O", "-P", "--output-document", "--directory-prefix"), "sort": ("-o", "--output"), "tar": ("-C", "--directory"), "unzip": ("-d",), "patch": ("-d", "--directory"),
            "npm": ("--prefix",), "yarn": ("--cwd",), "pnpm": ("-C", "--dir"), "make": ("-C",), "gmake": ("-C",)}
ISO_SENDOPT = {"curl": ("-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "-F", "--form", "-T", "--upload-file", "--json"), "wget": ("--post-file", "--body-file")}
ISO_CD = frozenset(("tar", "make", "gmake", "patch", "unzip", "npm", "yarn", "pnpm"))
ISO_CURL_USE = ("--cert", "-E", "--key", "--cacert", "--capath", "--proxy-cert", "--proxy-key", "--crlfile")
ISO_VALOPTS = {"rg": ("-g", "--glob", "--iglob", "-t", "-T", "--type", "--type-not", "-e", "--regexp", "-r", "--replace", "--encoding", "-E", "--path-separator", "--sort", "--sortr", "--pre", "--pre-glob", "--type-add", "--colors", "--engine"),
               "grep": ("-e", "--regexp", "--include", "--exclude", "--exclude-dir", "--label"),
               "ag": ("-G", "--file-search-regex", "-g", "--ignore", "--pager", "-W", "--workers"),
               "tar": ("--exclude", "--exclude-tag"), "gitgrep": ("-e", "--threads"), "ack": ("-g", "--ignore-dir", "--noignore-dir", "--type", "-G", "--match", "--pager", "--ignore-directory", "--noignore-directory"),
               "rsync": ("--exclude", "--include", "--filter", "-f", "-e", "--rsh", "--rsync-path", "--port", "--bwlimit", "--timeout", "--log-file", "--partial-dir", "--temp-dir", "-T")}
ISO_NUMOPTS = ("--threads", "--max-depth", "-A", "-B", "-C", "--context", "--after-context", "--before-context", "-m", "--max-count", "-j", "--threads", "-M", "--max-columns", "-d", "--max-depth", "--maxdepth", "--depth", "-W")
ISO_FILEOPTS = {"gitgrep": ("-f", "--file"), "ack": ("--ignore-file",), "rg": ("-f", "--file", "--ignore-file"), "grep": ("-f", "--file", "--exclude-from"), "ag": ("-p", "--path-to-ignore"), "tar": ("-T", "--files-from", "-X", "--exclude-from"), "rsync": ("--exclude-from", "--include-from", "--files-from")}
ISO_WORDS = ("read", "recurse", "skip", "binary", "text", "without-match", "action")
ISO_GIT_META = frozenset(("status", "rev-parse", "branch", "remote", "worktree", "describe", "tag", "config", "init", "fetch", "ls-remote"))
ISO_INTERP = re.compile(r"^(python[0-9.]*|node|nodejs|ruby|perl|php|deno|bun|lua|Rscript|julia|sqlite3|osascript|ts-node|tsx)$")
ISO_TEXT = {
    "project": "That path is inside another project ({o}). A chat works in its own project; the owner can open it in a terminal: `shipm projects link {c} {o}` (read) or `--write`.",
    "secret": "That file holds secrets and would show them in this chat. Use it without showing it (`source .env`, `--env-file`, `ssh -i key`), read .env.example, search with `--exclude=.env*` or in a subfolder, or ask the owner.",
    "ws": "That part of the workspace is not shared with project chats (they read its tools, templates, standards and config; they never write it).",
    "store": "That is another project's Claude data (transcripts, history, scratch files).",
    "search": "That search starts above other projects ({o}) and would read them. Search inside this project.",
    "cwd": "The shell is inside another project ({o}). Only `cd` back into this project is allowed.",
    "import": "That text imports (`@path`) another project, a private workspace path or a secret into a chat instruction file.",
    "error": "Command too large or too complex for the isolation check, or a folder is too big to check in time: narrow the path, exclude the folder (node_modules, vendor ...), split the command, or write the script with the Write tool and run it. (Owner: isolation can be set to warn in config/flow.json.)",
}


def iso_ci(p):
    return sys.platform == "darwin" or _ci_drive(p)


def iso_key(p):
    p = os.path.normcase(p)
    return _fold(p) if iso_ci(p) else p


def iso_level(proj):
    ov = os.environ.get("SHIPMIRACLE_ISOLATION")
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and ov in ("strict", "warn", "off"):
        return ov
    try:
        cfg_ = json.load(open(os.path.join(WS, "config/flow.json")))
        blk_ = cfg_.get("isolation") if isinstance(cfg_, dict) else None
        if not isinstance(blk_, dict):
            return "strict"
        pj_ = blk_.get("projects")
        lv_ = (pj_ if isinstance(pj_, dict) else {}).get(proj, blk_.get("default", "strict"))
        return lv_ if lv_ in ("strict", "warn", "off") else "strict"
    except Exception:
        return "strict"


def iso_pid(path):
    import hashlib  # SHIPMIRACLE-LAZY
    return hashlib.sha256(("shipmiracle-project:" + os.path.realpath(path)).encode("utf-8", "surrogateescape")).hexdigest()[:12]


def iso_init(pd, rpd, unk):
    ISO.clear()
    ents = []
    try:
        names = sorted(os.listdir(DEV))
    except OSError:
        names = []
    for n in names:
        p = os.path.join(DEV, n)
        if not n.startswith(".") and not any(ord(c) < 32 for c in n) and os.path.isdir(p) and os.path.exists(os.path.join(p, ".git")):
            r = os.path.realpath(p)
            ents.append({"name": n, "k": iso_key(n), "path": p, "real": r, "keys": list(dict.fromkeys((iso_key(p), iso_key(r))))})
    cur = next((e for e in ents if not unk and iso_key(rpd) in e["keys"]), None)
    wsk = iso_key(os.path.realpath(WS))
    hub = next((e["k"] for e in ents if iso_key(e["real"]) == wsk), None)
    ISO.update(ents=ents, names={e["k"]: e for e in ents}, devk=iso_key(DEV), pdk=iso_key(pd), cur=cur, curk=cur["k"] if cur else None, wsk=wsk, hub=hub, pd=pd, links=None)
    ISO["is_hub"] = hub is not None and hub == ISO["curk"]


def iso_links():
    if ISO["links"] is not None:
        return ISO["links"]
    res = ISO["links"] = {}
    d = shipmiracle_cfg_dir()
    try:
        raw = open(os.path.join(d, "project-links.json"), "rb").read(65537) if d else None
    except FileNotFoundError:
        return res
    except OSError:
        raw = b"x" * 65537
    if raw is None:
        return res
    try:
        j = json.loads(raw.decode("utf-8")) if len(raw) <= 65536 else None
        for l in j["links"][:200] if j["v"] == 1 else None:
            if isinstance(l, dict) and isinstance(l.get("from"), str) and isinstance(l.get("to"), str) and l.get("mode") in ("read", "write") and res.get((l["from"], l["to"])) != "write":
                res[(l["from"], l["to"])] = l["mode"]
    except Exception:
        res.clear()
        ISO.setdefault("events", []).append(("isolation_links_unreadable", {}))
    return res


def iso_linked(other, write):
    cur_ = ISO["cur"]
    if cur_ is None or other["k"] == ISO["hub"]:
        return False
    m_ = iso_links().get((iso_pid(cur_["real"]), iso_pid(other["real"])))
    return m_ == "write" or (m_ == "read" and not write)


def iso_spell(ap):
    d_, b_ = os.path.dirname(ap), os.path.basename(ap)
    rp_ = ISO.setdefault("rp", {})
    if d_ not in rp_:
        rp_[d_] = os.path.realpath(d_)
    out_ = [os.path.join(rp_[d_], b_) if b_ else rp_[d_]]
    if b_ and os.path.islink(ap):
        out_.insert(0, os.path.realpath(ap))
    n_ = os.path.normpath(os.path.abspath(ap))
    if n_ not in out_:
        out_.append(n_)
    return out_


def iso_homes():
    if "homes" not in ISO:
        h = {HOME, os.path.realpath(HOME)}
        try:
            h.add(pwd.getpwuid(os.getuid()).pw_dir)
        except Exception:
            pass
        ISO["homes"] = h
    return ISO["homes"]


def iso_secret(s):
    b_ = os.path.basename(s); bl_ = b_.casefold()
    ks_ = iso_key(s)
    for h_ in iso_homes():
        hk_ = iso_key(h_).rstrip("/")
        if ks_.startswith(hk_ + "/"):
            rel_ = ks_[len(hk_) + 1:]
            for dd_ in SECRET_HOME_DIRS:
                dk_ = iso_key(dd_)
                if rel_ == dk_ or rel_.startswith(dk_ + "/"):
                    if dd_ == ".ssh" and (rel_ == dk_ or bl_ in SECRET_SSH_KEEP or bl_.endswith(".pub")):
                        return False
                    return True
            if any(rel_ == iso_key(f_) for f_ in SECRET_HOME_FILES):
                return True
    if re.fullmatch(r"/proc/[^/]*/(?:task/[^/]*/)?environ", s):
        return True
    if bl_ in SECRET_NAME_EXACT:
        return True
    if bl_.startswith(".env"):
        return not (bl_.startswith(".env.") and bl_.rsplit(".", 1)[1] in ENV_ALLOW_SUFFIXES)
    if bl_.endswith(SECRET_NAME_SUFFIXES):
        if bl_.endswith(".pem") and os.path.isfile(s) and not ISO.get("nosniff"):
            try:
                if os.path.getsize(s) <= 1048576:
                    d_ = open(s, "rb").read(1048577)
                    left_ = re.sub(rb"-----BEGIN (CERTIFICATE|X509 CRL|TRUSTED CERTIFICATE|PUBLIC KEY|RSA PUBLIC KEY)-----[A-Za-z0-9+/=\r\n \t:,.-]*?-----END \1-----", b"", d_)
                    if left_ != d_ and not left_.strip() and b"PRIVATE" not in d_:
                        return False
            except OSError:
                pass
        return True
    if bl_.startswith(SECRET_NAME_PREFIXES) and not bl_.endswith(".pub"):
        return True
    if bl_.startswith("service-account") and bl_.endswith(".json"):
        return True
    if re.fullmatch(r"(?:firebase-adminsdk|gcp-key|authkey_)[^/]*\.(?:json|p8)|[^/]*-key\.json", bl_) or ks_.endswith(("/.kube/config", "/.docker/config.json")):
        return True
    if bl_.endswith((".crt", ".cer", ".asc", ".gpg", ".der", ".pgp")) and os.path.isfile(s) and not ISO.get("nosniff"):
        try:
            if os.path.getsize(s) <= 1048576 and b"PRIVATE KEY" in open(s, "rb").read(1048577):
                return True
        except OSError:
            pass
    stem_, dot_, ext_ = bl_.rpartition(".")
    if not dot_:
        stem_, ext_ = bl_, ""
    if (stem_ in SECRET_DATA_NAMES or re.search(r"[-_.](?:credentials|secrets?|creds)$", stem_)) and ext_ in SECRET_DATA_EXT and not os.path.isdir(s) and (ext_ != "" or os.path.isfile(s)):
        return True
    return False


def iso_owner(s):
    k_ = iso_key(s)
    dk_ = ISO["devk"]
    if k_.startswith(dk_ + "/"):
        parts_ = k_[len(dk_) + 1:].split("/")
        if parts_[0] == iso_key(".worktrees"):
            if len(parts_) < 2 or not parts_[1]:
                return None
            return parts_[1] if parts_[1] in ISO["names"] else "?"
        if parts_[0] in ISO["names"]:
            return parts_[0]
    for e_ in ISO["ents"]:
        for ek_ in e_["keys"]:
            if k_ == ek_ or k_.startswith(ek_ + "/"):
                return e_["k"]
    return None


def iso_slug(p):
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def iso_slug_owner(slug):
    best_ = (0, None)
    for e_ in ISO["ents"]:
        for p_ in (e_["path"], e_["real"], os.path.join(DEV, ".worktrees", e_["name"])):
            sl_ = iso_key(iso_slug(p_)); slug = iso_key(slug)
            if (slug == sl_ or slug.startswith(sl_ + "-")) and len(sl_) > best_[0]:
                best_ = (len(sl_), e_["k"])
    return best_[1]


def iso_hit(s, write):
    k_ = iso_key(s)
    cur_, curk_ = ISO["cur"], ISO["curk"]
    pdk_ = ISO["pdk"]
    if k_ == pdk_ or k_.startswith(pdk_ + "/"):
        return None
    wsk_ = ISO["wsk"]
    if (k_ == wsk_ or k_.startswith(wsk_ + "/")) and not ISO["is_hub"]:
        rel_ = k_[len(wsk_) + 1:] if k_ != wsk_ else ""
        if write:
            if (rel_ == "" and ISO.get("rmop")) or rel_ in ("config/flow.json", "hooks", "shipmiracle") or rel_.startswith(("hooks/", "shipmiracle/")):
                return None
            return ("ws", "")
        if rel_ and not any(rel_ == iso_key(a_) or rel_.startswith(iso_key(a_) + "/") for a_ in WS_READ_ALLOW):
            return ("ws", "")
        return None
    o_ = iso_owner(s)
    if o_ is not None and o_ != curk_:
        if o_ == "?":
            return ("project", "an unknown worktree")
        oe_ = ISO["names"][o_]
        if ISO["is_hub"] and not write:
            return None
        if o_ == ISO["hub"] and not ISO["is_hub"]:
            return ("ws", "")
        if iso_linked(oe_, write):
            if write:
                rel_ = next((k_[len(ek_) + 1:] for ek_ in oe_["keys"] if k_.startswith(ek_ + "/")), None)
                if rel_ is None:
                    rel_ = "/".join(k_[len(ISO["devk"]) + 1:].split("/")[3:])
                rl_ = rel_.lower()
                if (rl_ in (".mcp.json", ".claude", "claude.md", "claude.local.md", "agents.md") or rl_.startswith((".claude/", ".githooks/", ".husky/", ".git/")) or rl_ in [f_.lower() for f_ in PERSIST_PROJECT_FILES]
                        or rl_.endswith(PERSIST_PROJECT_SUFFIXES)):
                    return ("project", oe_["name"])
            return None
        return ("project", oe_["name"])
    if o_ is None:
        h_ = os.path.realpath(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude"))
        ks_ = iso_key(s)
        for base_ in {h_, os.path.realpath(os.path.join(HOME, ".claude"))} | {os.path.join(x_, ".claude") for x_ in iso_homes()}:
            bk_ = iso_key(base_)
            if ks_ == bk_ or ks_.startswith(bk_ + "/"):
                parts_ = ks_[len(bk_) + 1:].split("/") if ks_ != bk_ else [""]
                if parts_[0] in [iso_key(x_) for x_ in CLAUDE_STORES]:
                    if parts_[0] == "projects":
                        if len(parts_) > 1 and parts_[1]:
                            so_ = iso_slug_owner(parts_[1])
                            if so_ is not None and so_ != curk_:
                                return ("store", "")
                        return None
                    return ("store", "")
        m_ = re.match(r"^(?:/private)?/tmp/claude-\d+/([^/]+)(?:/|$)", s, re.I)
        if m_:
            so_ = iso_slug_owner(m_.group(1))
            if so_ is not None and so_ != curk_:
                return ("store", "")
    return None


def iso_wslink(s):
    try:
        st = os.lstat(s)
    except OSError:
        return False
    if (st.st_mode & 0o170000) != 0o100000 or st.st_nlink < 2:
        return False
    dl = time.process_time() + 0.3
    for dp, dn, fn in os.walk(os.path.realpath(WS)):
        dn[:] = [d for d in dn if d not in (".git", "node_modules")]
        for f in fn:
            try:
                s2 = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            if s2.st_ino == st.st_ino and s2.st_dev == st.st_dev:
                return True
        if time.process_time() > dl:
            return True
    return False


def iso_judge(ap, read=True, write=False, use=False):
    sps_ = iso_spell(ap)
    if read and not use:
        for s_ in sps_:
            if iso_secret(s_):
                return ("secret", "")
    for s_ in sps_:
        r_ = iso_hit(s_, write)
        if r_:
            return r_
    if write and not ISO["is_hub"] and iso_wslink(sps_[0]):
        return ("ws", "")
    return None


def iso_covers(ap):
    if ISO["is_hub"]:
        return ""
    k_ = iso_key(ap).rstrip("/")
    for e_ in ISO["ents"]:
        if e_["k"] == ISO["curk"]:
            continue
        if any(ek_.startswith(k_ + "/") or ek_ == k_ for ek_ in e_["keys"]) and not (e_["k"] != ISO["hub"] and iso_linked(e_, False)):
            return e_["name"]
        wk_ = iso_key(os.path.join(DEV, ".worktrees", e_["name"]))
        if wk_.startswith(k_ + "/") and os.path.isdir(os.path.join(DEV, ".worktrees", e_["name"])) and not (e_["k"] != ISO["hub"] and iso_linked(e_, False)):
            return e_["name"]
    if ISO["hub"] is None and (ISO["wsk"].startswith(k_ + "/") or ISO["wsk"] == k_) and ISO["wsk"] != ISO["pdk"] and not ISO["pdk"].startswith(ISO["wsk"] + "/"):
        return "the workspace"
    return ""


class IsoTimeout(BaseException):
    pass


def iso_tick():
    if time.process_time() > ISO.get("cdl", 1e18) or time.time() > ISO.get("wdl", 1e18):
        raise IsoTimeout()


def iso_expand(w, cwd):
    if w.startswith("file://"):
        w = w[16:] if w.startswith("file://localhost") else w[7:]
    if w.startswith("~"):
        m = re.match(r"~([^/$`]*)", w); nm = m.group(1)
        if ISO.get("homeset") or nm == "-":
            return w, True
        try:
            h = HOME if nm == "" else cwd if nm == "+" else pwd.getpwnam(nm).pw_dir
        except Exception:
            return w, True
        w = h + w[m.end():]
    w = ENVVAR.sub(lambda m: m.group(0) if (ISO.get("homeset") and (m.group(1) or m.group(2)) == "HOME") else {"HOME": HOME, "PWD": cwd, "CLAUDE_PROJECT_DIR": ISO["pd"]}[m.group(1) or m.group(2)], w)
    if "$" in w or "`" in w:
        return w, True
    w = w if os.path.isabs(w) else os.path.join(cwd, w)
    w = re.sub(r"^/proc/(?:self|\d+)/cwd(?=/|$)", lambda m: cwd, w)
    w = re.sub(r"^/proc/(?:self|\d+)/root(?=/|$)|^/System/Volumes/Data(?=/)|^/dev/fd/\d+/\.\.(?=/)", "", w) or "/"
    return os.path.normpath(w), False


def iso_literal(text):
    tl_ = iso_key(text)
    base_ = iso_key(os.path.basename(DEV.rstrip("/")))
    for e_ in ISO["ents"]:
        if e_["k"] == ISO["curk"]:
            continue
        n_ = re.escape(e_["k"])
        if re.search(r"/" + re.escape(base_) + r"/" + n_ + r"(?:/|$)", tl_) or re.search(r"(?:^|[\s'\"=:(<>|;&/])\.\./" + n_ + r"(?:[/\s'\";|&)]|$)", tl_) or re.search(r"/\.worktrees/" + n_ + r"(?:/|$)", tl_):
            if ISO["is_hub"] or iso_linked(e_, False):
                continue
            return ("project", e_["name"])
        if re.search(r"(?:^|[\s'\"=:(<>|;&])\$\w+/" + n_ + r"(?:[/\s'\";|&)]|$)", tl_, re.I) and not (ISO["is_hub"] or iso_linked(e_, False)):
            return ("project", e_["name"])
        if ISO.get("homeset") and re.search(r"(?:^|[\s'\"=:(<>|;&])(?:~|\$HOME|\$\{HOME\})/" + n_ + r"(?:[/\s'\";|&)]|$)", tl_, re.I) and not (ISO["is_hub"] or iso_linked(e_, False)):
            return ("project", e_["name"])
    return None


def iso_secret_root(ap):
    k = iso_key(ap).rstrip("/")
    conts = [iso_key(d) for d in SECRET_HOME_DIRS] + [iso_key(os.path.dirname(f)) for f in SECRET_HOME_FILES if os.path.dirname(f)] + [".claude", ".claude/projects"]
    for h in {iso_key(HOME), iso_key(os.path.realpath(HOME))}:
        h = h.rstrip("/")
        if k == h or h.startswith(k + "/"):
            return True
        if k.startswith(h + "/"):
            rel = k[len(h) + 1:]
            if rel in conts or any(rel.startswith(x + "/") for x in conts if x not in (".claude", ".claude/projects")):
                return True
    return False


ISO_CERTS = ("cacert.pem", "ca-bundle.crt", "ca-certificates.crt", "cert.pem")
ISO_GIT = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]


def iso_git_out(root, args, data=b""):
    """git for the judging code: cached per hook call, at most 12 processes and 3 s of wall time per call (git's CPU time is not in our own CPU budget); beyond that: rc 128 = unknown."""
    import subprocess  # SHIPMIRACLE-LAZY
    key = (root, tuple(args), data)
    gc = ISO.setdefault("gitc", {})
    if key in gc:
        return gc[key]
    if ISO.get("gitn", 0) >= 12 or ISO.get("gitw", 0.0) > 3.0:
        return 128, ""
    ISO["gitn"] = ISO.get("gitn", 0) + 1
    t0 = time.time()
    try:
        r = subprocess.run(ISO_GIT + ["-C", root] + args, input=data, capture_output=True, timeout=0.5)
        res = (r.returncode, r.stdout.decode("utf-8", "replace"))
    except Exception as e:
        res = (128, "")
        if isinstance(e, FileNotFoundError):
            ISO["nogit"] = True
    ISO["gitw"] = ISO.get("gitw", 0.0) + (time.time() - t0)
    gc[key] = res
    return res


ISO_DEPDIRS = frozenset(("node_modules", "vendor", "venv", ".venv", "site-packages", "Pods", "target", "dist", ".next", ".nuxt", "__pycache__", ".gradle", ".cache", "bower_components", "DerivedData"))
ISO_TYPES = {"js": (".js", ".jsx", ".mjs", ".cjs"), "ts": (".ts", ".tsx"), "py": (".py", ".pyi"), "json": (".json",), "md": (".md", ".markdown"), "rust": (".rs",), "go": (".go",), "java": (".java",), "c": (".c", ".h"), "cpp": (".cpp", ".cc", ".hpp", ".h"),
             "yaml": (".yaml", ".yml"), "html": (".html", ".htm"), "css": (".css", ".scss"), "ruby": (".rb",), "sh": (".sh", ".bash"), "txt": (".txt",), "swift": (".swift",), "kotlin": (".kt",), "php": (".php",)}


def iso_cand_name(f):
    fl = f.lower()
    return (fl.startswith((".env", "service-account", "id_")) or fl.endswith(SECRET_NAME_SUFFIXES) or fl in SECRET_NAME_EXACT or fl.rpartition(".")[0] in SECRET_DATA_NAMES or fl in SECRET_DATA_NAMES
            or re.search(r"[-_.](?:credentials|secrets?|creds)(?:\.[a-z]+)?$", fl) is not None or fl.startswith(SECRET_NAME_PREFIXES)
            or fl.endswith((".crt", ".cer", ".asc", ".gpg", ".der", ".pgp", "-key.json")) or fl.startswith(("firebase-adminsdk", "gcp-key", "authkey_")))


def iso_dep_names(path, lim1=60000, lim2=100, lim3=200):
    """File names (and sub/name) of a dependency folder, two levels deep, by counts and not by time: at most lim1 entries at the top, lim2 sub folders, lim3 entries in each."""
    res, subs = [], []
    try:
        with os.scandir(path) as it:
            for i_, e_ in enumerate(it):
                if i_ >= lim1:
                    break
                (subs if e_.is_dir(follow_symlinks=False) else res).append(e_.name)
    except OSError:
        return res
    for sd_ in subs[:lim2]:
        try:
            with os.scandir(os.path.join(path, sd_)) as it:
                for i_, e_ in enumerate(it):
                    if i_ >= lim3:
                        break
                    if not e_.is_dir(follow_symlinks=False):
                        res.append(sd_ + "/" + e_.name)
        except OSError:
            pass
    return res


def iso_tree_secret(root, hidden=True, ignore=False, glob="", git=False, excludes=(), exdirs=(), recurse=False, revs=(), names=(), relprefix="", follow=False, depth=0, pathspec=(), ftype=""):
    """True: a secret-named file would be searched (ISO["offender"] names it); False: clean; None: unknown (cannot say in time) - callers refuse unless the result is False."""
    for rv in revs:
        rc, out = iso_git_out(root, ["ls-tree", "-r", "--name-only", "-z", rv])
        if rc != 0:
            return None
        plain = [p_.rstrip("/") for p_ in pathspec if not p_.startswith(":") and not re.search(r"[*?\[\\]", p_)]
        for f in out.split("\0"):
            if f and (len(plain) != len(pathspec) or not pathspec or any(f == p_ or f.startswith(p_ + "/") for p_ in plain)) and iso_secret(os.path.join(root, f)):
                ISO["offender"] = f
                return True
    gl = glob.rstrip("/").rsplit("/", 1)[-1] if glob else ""
    grx = iso_glob_rx(gl) if gl and not re.search(r"[{}]", gl) else None
    exts = ISO_TYPES.get(ftype)
    nmrx = [iso_glob_rx(g) for g in names]
    exrx = [(iso_glob_rx(g.lstrip("/")), "/" in g) for g in excludes]; edrx = [(iso_glob_rx(g.lstrip("/")), "/" in g) for g in exdirs]

    def want(rel):
        f = rel.rsplit("/", 1)[-1]
        if not hidden and any(c.startswith(".") for c in rel.split("/")):
            return False
        if not iso_cand_name(f):
            return False
        if (grx is not None and not grx.fullmatch(f)) or (exts and not f.lower().endswith(exts)) or (nmrx and not any(rx.fullmatch(f) for rx in nmrx)):
            return False
        if any(rx.fullmatch(relprefix + rel if pf else f) for rx, pf in exrx):
            return False
        return not any(rx.fullmatch(relprefix + c if pf else c) for rx, pf in edrx for c in rel.split("/")[:-1])

    def judge(rels):
        for r in rels:
            if r and want(r) and iso_secret(os.path.join(root, r)):
                ISO["offender"] = r
                return True
        return False
    if git:
        rc, out = iso_git_out(root, ["ls-files", "-z"] + (["--recurse-submodules"] if recurse else []) + (["--"] + list(pathspec) if pathspec else []))
        if rc == 0:
            return judge(out.split("\0"))
    dl = time.process_time() + 0.4; n = 0; cand = []

    def dep(pabs, prel):
        for r_ in iso_dep_names(pabs):
            if iso_cand_name(r_.rsplit("/", 1)[-1]) and want(prel + r_):
                cand.append((prel + r_, os.path.join(pabs, r_)))
    rootdep = os.path.basename(root.rstrip("/")) in ISO_DEPDIRS
    if rootdep:
        dep(root, "")
    for dp, dn, fn in ([] if rootdep else os.walk(root)):
        rel = os.path.relpath(dp, root)
        rel = "" if rel == "." else rel + "/"
        if follow:
            for nm_ in list(dn) + list(fn):
                fp_ = os.path.join(dp, nm_)
                if os.path.islink(fp_):
                    rl_ = os.path.realpath(fp_)
                    if iso_judge(rl_, True, False) or (os.path.isfile(rl_) and iso_secret(rl_)):
                        ISO["offender"] = rel + nm_
                        return True
                    if os.path.isdir(rl_) and depth < 3:
                        sub_ = iso_tree_secret(rl_, hidden, ignore, glob, False, excludes, exdirs, False, (), names, "", True, depth + 1)
                        if sub_ is not False:
                            return sub_
        dn[:] = [d for d in dn if d != ".git" and (hidden or not d.startswith("."))]
        keep_ = []
        for d in dn:
            if d in ISO_DEPDIRS:
                dep(os.path.join(dp, d), rel + d + "/")               # dependency folders (node_modules, vendor, venv ...): a bounded, name-only listing of the first two levels, never a walk (deterministic, no time budget)
            else:
                keep_.append(d)
        dn[:] = keep_
        for f in fn:
            n += 1
            if n % 500 == 0:
                iso_tick()
                if time.process_time() > dl:
                    return None
            if iso_cand_name(f) and want(rel + f):
                cand.append((rel + f, os.path.join(dp, f)))
    if ignore and cand and not follow:
        rc0, _ = iso_git_out(root, ["check-ignore", "-q", "--", "."])
        if rc0 == 1:                                                  # the root itself is searched on its own merits only when it is an ignored folder named on the command line
            rc, out = iso_git_out(root, ["check-ignore", "-z", "--stdin"], "\0".join(r for r, _ in cand).encode("utf-8", "surrogateescape"))
            if rc in (0, 1):
                ign = set(out.split("\0"))
                cand = [(r, f) for r, f in cand if r not in ign]
    for r, f in cand:
        if iso_secret(f):
            ISO["offender"] = r
            return True
    return False


def iso_tree_hit(ap, **kw):
    t = iso_tree_secret(ap, **kw)
    return None if t is False else ("secret" if t is True else "error", "")


def iso_search_mode(cmd, opts):
    """(hidden files searched, .gitignore honoured) for a search command."""
    if cmd == "rg":
        u = sum(o.count("u") for o in opts if re.fullmatch(r"-[A-Za-z.]+", o))
        return u >= 2 or "--hidden" in opts or any(re.fullmatch(r"-[A-Za-z]*\.[A-Za-z]*", o) for o in opts), not (u >= 1 or any(o.startswith("--no-ignore") for o in opts))
    if cmd in ("ugrep", "ug"):                                              # ugrep skips hidden files unless -. / --hidden and reads .gitignore only with --ignore-files
        return any(o == "--hidden" or re.fullmatch(r"-[A-Za-z]*\.[A-Za-z]*", o) for o in opts), any(o == "--ignore-files" or o.startswith("--ignore-files=") for o in opts)
    if cmd == "ag":
        return any(o in ("--hidden", "-u", "--unrestricted") for o in opts), not any(o in ("-U", "--skip-vcs-ignores", "-u", "--unrestricted", "-a", "--all-types") for o in opts)
    return True, False


def iso_check_word(w, cwd, read, write, use, out):
    w = w.replace("\0", "")
    if not w or w == "-":
        return
    if "\x05" in w:
        out.append(("error", ""))
        return
    iso_tick()
    if read and not use and re.search(r"(?:^|/)proc/[^/]*(?:/task/[^/]*)?/environ$", w):
        out.append(("secret", ""))                                    # /proc/self/environ, /proc/$$/environ, /proc/*/environ ...
        return
    if ISO.get("urlcmd") and re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", w) and not w.lower().startswith("file:") and not os.path.lexists(os.path.join(cwd, w.split("/", 1)[0])) and not re.search(r"\b(?:mkdir|ln|cp|mv|install|rsync|tar|unzip)\b", ISO.get("cmds", "")):
        return                                                        # a URL given to a command that parses URLs (and no folder named like the scheme exists) is not a local path
    if (" " in w or "\t" in w or "\n" in w) and "/" not in w and not ISO.get("spaced"):
        return
    if " " in w and w.split(" ", 1)[0] in KEY_USERS:
        use = 1
    ap_, unres_ = iso_expand(w, cwd)
    if unres_:
        if "OLDPWD" in ap_ or ap_.startswith("~-") or (ISO.get("homeset") and (ap_.startswith("~") or "$HOME" in ap_)):
            out.append(("error", ""))
            return
        r_ = iso_literal(ap_)
        if not r_ and read and not use and ("/" in ap_ and ap_.rsplit("/", 1)[-1] in SECRET_DATA_NAMES):
            r_ = ("secret", "")
        if not r_ and read and not use and (iso_secret("/x/" + ap_.rsplit("/", 1)[-1]) or any(h[0] == "secret" for h in iso_text_scan(ap_))):
            r_ = ("secret", "")
        if r_:
            out.append(r_)
        return
    if ap_.startswith(("/dev/", "/proc/self/", "/sys/")) and not iso_secret(ap_):
        return
    if use and read and iso_secret(ap_):
        ISO["used_secret"] = True
    cands_ = [ap_]
    if any(c_ in ap_ for c_ in "*?["):
        kg_ = iso_key(ap_)
        for b_ in {os.path.join(x_, ".claude") for x_ in iso_homes()} | {os.path.realpath(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude"))}:
            bp_ = iso_key(b_) + "/projects/"
            if kg_.startswith(bp_) and re.search(r"[*?\[]", kg_[len(bp_):].split("/")[0]):
                out.append(("store", ""))
                return
        cands_ = []; more_ = 0
        for x_ in glob.iglob(ap_):
            iso_tick()
            if len(cands_) < 60:
                cands_.append(os.path.normpath(x_))
            else:
                more_ += 1
                if read and not use and iso_secret(x_):
                    out.append(("secret", ""))
                    return
                if more_ > 20000:
                    if not any(p_ in ISO_DEPDIRS for p_ in ap_.split("/")):
                        out.append(("error", ""))
                    break                                                 # a glob through node_modules and friends: the first 20000 names were judged, the rest are dependency files
        pre_ = re.split(r"[*?\[]", ap_, 1)[0]
        cands_.append(os.path.normpath(pre_.rstrip("/") or "/") if pre_.endswith("/") else os.path.normpath(os.path.dirname(pre_) or "/"))
    for c_ in cands_:
        r_ = iso_judge(os.path.normpath(c_), read, write, use)
        if r_:
            out.append(r_)
            return


ISO_REDIR = re.compile(r"^(?:\d*|&)(>>?|<)(?!<)(.*)$", re.S)
ISO_LIT = re.compile(r"""(?<=['"])([^'"\s]{1,400})(?=['"])""")


ISO_BRACED = re.compile(r"\$\{(SHELL|BASH|0)\}")
ISO_VARS = re.compile(r"\$\{(HOME|PWD|OLDPWD|CLAUDE_PROJECT_DIR)([^}\sA-Za-z0-9_][^}\s]{0,39})?\}|\$(HOME|PWD|OLDPWD|CLAUDE_PROJECT_DIR)(?![A-Za-z0-9_])")


def iso_var(m):
    name, mod = m.group(1) or m.group(3), m.group(2) or ""
    val = {"HOME": HOME, "CLAUDE_PROJECT_DIR": ISO["pd"]}.get(name)
    if name == "OLDPWD":
        return "\x05" if m.group(2) else "$OLDPWD"
    if m.group(3) is None:
        nxt = m.string[m.end():m.end() + 1]
        if (mod and not re.fullmatch(r"%/|:?-[A-Za-z0-9_./]{0,20}", mod)) or (val is None and (nxt.isalnum() or nxt == "_")):
            return "\x05"
        if mod == "%/" and val:
            val = val.rstrip("/")
    return "$PWD" if val is None else "$HOME" if (name == "HOME" and ISO.get("homeset")) else val.replace(" ", "\\ ")


ISO_SPREAD = re.compile(r"(?<=[^\s<>&|])(?=<(?![<(])|>)")
ISO_DEFAULT = re.compile(r"\$\{[A-Za-z_]\w{0,40}:?[-=]([^}\s]{0,100})\}")
ISO_SUBECHO = re.compile(r"([^\s;|&()<>`]*/)?(?:\$\(|`)\s*(?:echo|printf)\s+([^)`]{1,300})")
ISO_GLUE = re.compile(r"[)`]['\"]?((?:/|\.\./)[^\s;|&()<>`]{0,300}|[\w.~-][^\s;|&()<>`]{0,300})")
ISO_PIPED = re.compile(r"\b(?:echo|printf)\b([^|;&\n]{0,300})\|\s*(?:sudo\s+)?(?:xargs|eval|(?:ba|z|da)?sh|cat|less|head|tail|while)\b|\b(?:xargs|cat|less|head|tail|while\s+read)\b[^|;&\n<]{0,100}<<<\s*('[^']{0,300}'|\"[^\"]{0,300}\"|[^\s|;&]{1,300})|<<<\s*('[^']{0,300}'|\"[^\"]{0,300}\"|[^\s|;&]{1,300})\s*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|(?:source|\.|bash|sh|zsh)\s+<\(\s*(?:echo|printf)\s+([^)]{0,300})\)")
ISO_READERS = frozenset(("cat", "less", "more", "head", "tail", "bat", "nl", "od", "xxd", "strings", "base64", "tac", "sed", "awk", "grep", "egrep", "fgrep", "rg", "wc", "sort", "cut", "jq", "cp", "mv", "scp", "rsync"))
ISO_PATHY = ISO_READERS | ISO_W_ALL | ISO_DEST | frozenset(("find", "tee", "ln", "tar", "zip", "unzip"))
ISO_ASG = re.compile(r"^[A-Za-z_]\w*=(.+)$", re.S)
ISO_HD = re.compile(r"<<-?[ \t]*(['\"]?)(\w{1,40})\1[^\n]*\n")
ISO_WORD = re.compile(r"""(?:'[^']*'|"(?:\\.|[^"\\])*"|[^\s;|&()<>'"])+""")
ISO_QSPLIT = re.compile(r"""('[^']*'|"(?:\\.|[^"\\])*")""")


def iso_braces(c):
    def group(o):
        p = -1
        while True:
            p = o.find("}", p + 1)
            if p < 0:
                return None
            i = o.rfind("{", 0, p)
            if i < 0 or (i > 0 and o[i - 1] == "$"):
                continue
            g = o[i + 1:p]
            if "," in g:
                if g.count(",") >= 64:
                    raise ValueError("brace list too long")
                return i, p, g.split(",")
            ms = re.fullmatch(r"(-?\d{1,9})\.\.(-?\d{1,9})(?:\.\.(-?\d{1,6}))?|([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d{1,6}))?", g)
            if ms:
                num = ms.group(1) is not None
                a_, b_ = (int(ms.group(1)), int(ms.group(2))) if num else (ord(ms.group(4)), ord(ms.group(5)))
                st = abs(int(ms.group(3) or ms.group(6) or 1)) or 1
                seq = range(a_, b_ + 1, st) if b_ >= a_ else range(a_, b_ - 1, -st)
                if len(seq) > 1024:
                    rest = o[:i] + o[p + 1:]
                    if "/" in rest or ".." in rest or re.search(r"\.env|id_|\.pem|\.key|\.p12|\.pfx|\.jks|credential|secret|\.npmrc|\.netrc", rest, re.I):
                        raise ValueError("brace sequence too long next to a path or secret name")
                    pre_, suf_ = o[:i].rsplit("/", 1)[-1], o[p + 1:].split("/", 1)[0]
                    if len(seq) > 20000 and (pre_ or suf_):
                        raise ValueError("brace sequence too long next to a name")
                    for n_, k_ in enumerate(seq):
                        if n_ % 1000 == 0:
                            iso_tick()
                        if iso_secret("/x/" + pre_ + (str(k_) if num else chr(k_)) + suf_):
                            raise ValueError("brace sequence completes a secret name")
                    return i, p, [str(a_) if num else chr(a_)]
                w_ = 0
                if num:
                    e1, e2 = ms.group(1).lstrip("-"), ms.group(2).lstrip("-")
                    if (e1.startswith("0") and len(e1) > 1) or (e2.startswith("0") and len(e2) > 1):
                        w_ = max(len(e1), len(e2))
                return i, p, [("-" if k < 0 else "") + str(abs(k)).zfill(w_) if num else chr(k) for k in seq]

    def expand(w):
        outs = [w]
        for _ in range(12):
            nxt = []; changed = False
            for o in outs:
                gp = group(o)
                if gp is None:
                    nxt.append(o)
                    continue
                changed = True
                nxt.extend(o[:gp[0]] + a + o[gp[1] + 1:] for a in gp[2])
            if len(nxt) > 4096:
                raise ValueError("brace expansion too large")
            outs = nxt
            if not changed:
                return " ".join(outs)
        raise ValueError("brace nesting too deep")

    def one(m):
        w = m.group(0)
        if "{" not in w or ("," not in w and ".." not in w):
            return w
        iso_tick()
        if len(w) > 1000:
            raise ValueError("brace word too long")
        return expand(w)

    def word(m):
        w = m.group(0)
        if "'" not in w and '"' not in w:
            return one(m)
        parts = ISO_QSPLIT.split(w)
        if not any("{" in x and ("," in x or ".." in x) for x in parts[0::2]):
            return w
        iso_tick()
        w2 = "".join(x[1:-1] if n % 2 else x for n, x in enumerate(parts))
        if len(w2) > 1000:
            raise ValueError("brace word too long")
        return expand(w2)

    def plain(piece):
        return ISO_WORD.sub(word, piece)
    spans = []; p = 0
    for _ in range(20):
        m = ISO_HD.search(c, p)
        if not m:
            break
        end = c.find("\n" + m.group(2), m.end() - 1)
        end = len(c) if end < 0 else end
        spans.append((m.end(), end)); p = max(end, m.end())
    res = []; cur = 0
    for a, b in spans + [(len(c), len(c))]:
        res.append(plain(c[cur:a])); res.append(c[a:b]); cur = b
    return "".join(res)


def iso_heredocs(c):
    out, pos = [], 0
    for _ in range(20):
        m = ISO_HD.search(c, pos)
        if not m:
            break
        em = re.compile(r"\n[ \t]*" + re.escape(m.group(2)) + r"(?:[ \t]|\n|$)").search(c, m.end() - 1)
        end = em.start() if em else -1
        out.append(c[m.end():end if end >= 0 else len(c)])
        pos = end if end > 0 else len(c)
    return out


def iso_hd_unquoted(c):
    """Bodies of heredocs whose delimiter is NOT quoted: $(...) and backticks in them run."""
    res, pos = [], 0
    for _ in range(20):
        m = ISO_HD.search(c, pos)
        if not m:
            break
        em = re.compile(r"\n[ \t]*" + re.escape(m.group(2)) + r"(?:[ \t]|\n|$)").search(c, m.end() - 1)
        end = em.start() if em else len(c)
        if not m.group(1):
            res.append(c[m.end():end])
        pos = max(end, m.end())
    return res


def iso_subst_cmds(t):
    """The command texts of $(...) and `...` in t."""
    out, i = [], 0
    while i < len(t) and len(out) < 30:
        if t.startswith("\\", i):
            i += 2
            continue
        if t.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(t) and depth:
                depth += (t[j] == "(") - (t[j] == ")")
                j += 1
            out.append(t[i + 2:j - 1 if depth == 0 else j]); i = j
        elif t[i] == "`":
            j = t.find("`", i + 1)
            if j < 0:
                out.append(t[i + 1:]); break
            out.append(t[i + 1:j]); i = j + 1
        else:
            i += 1
    return out


def iso_curlpath(v, opt):
    m = re.match(r"^[^=@<]*=?\s*[@<](.+)$", v)
    if m:
        return m.group(1).split(";")[0]
    return v if opt in ("-T", "--upload-file", "--post-file", "--body-file", "T", "K") else "-"


def iso_unquoted(c):
    """c with the insides of single-quoted strings and quoted heredoc bodies blanked: a backtick or $( there is text, not a substitution."""
    c = re.sub(r"(<<-?[ \t]*(['\"]?)(\w+)\2[^\n]*\n).*?(\n[ \t]*\3(?:[ \t]|\n|$))", lambda m: m.group(1) + " " + m.group(4), c, flags=re.S)
    out = []; q = ""; i = 0
    while i < len(c):
        ch = c[i]
        if q == "'":
            out.append("_" if ch != "'" else ch)
            if ch == "'":
                q = ""
        elif ch == "\\" and q != "'":
            out.append(c[i:i + 2]); i += 1
        elif ch in "'\"" and not q:
            q = ch; out.append(ch)
        elif ch == q:
            q = ""; out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def iso_bash(c, cwd, depth=0):
    hits = []
    ISO["cmds"] = c[:BIG_CMD]
    cw = [cwd]; unsure = False; oldpwd = False; only_cd = True; interp = False; nw = 0; wsg = [False]; shell = False
    c = _ansi_c(c[:BIG_CMD].replace("\0", ""))
    c = re.sub(r"\$\{IFS\}|\$IFS(?![A-Za-z0-9_])", " ", c.replace('$"', '"'))
    if depth < 3 and "<<" in c and ("$(" in c or "`" in c):
        for hb_ in iso_hd_unquoted(c)[:5]:
            for inner_ in iso_subst_cmds(hb_)[:10]:
                hits.extend(iso_bash(inner_, cwd, depth + 1)[0])
    cs_ = iso_unquoted(c) if ("$(" in c or "`" in c) else c
    if "$(" in cs_ or "`" in cs_:
        for m in ISO_GLUE.finditer(cs_):
            chk0 = []
            iso_check_word("$X" + m.group(1), cwd, 1, 0, 0, chk0)
            hits.extend(chk0)
    if "$(" in cs_ or "`" in cs_:
        for m in ISO_SUBECHO.finditer(cs_):
            for tok in m.group(2).split()[:50]:
                if not tok.startswith("-"):
                    chk0 = []
                    iso_check_word((m.group(1) or "") + tok, cwd, 1, 0, 0, chk0)
                    hits.extend(chk0)
    for m in ISO_PIPED.finditer(c):
        hits.extend(iso_text_scan(next((g for g in m.groups() if g), "")))
    c = re.sub(r"\benv\s+(?:-C\s*|--chdir[= ])(\S+)\s+", r"cd \1 && env ", c)
    ISO["homeset"] = ISO.get("homeset") or bool(re.search(r"(?<![\w$])(?<!\$\{)HOME(?![\w])", c))
    cdpath = bool(re.search(r"(?<![\w$])(?<!\$\{)CDPATH(?![\w])", c)); dumps = False; echovar = False
    c = iso_braces(c)
    c = ISO_BRACED.sub(r"$\1", c)
    c = ISO_VARS.sub(iso_var, c)
    c = ISO_DEFAULT.sub(lambda m: m.group(1), c)
    c = ISO_SPREAD.sub(" ", c)
    sb = [None]
    feeds_ = [bool(re.search(r"xargs|\$\(|`|\bread\b|\bfor\b", c))]
    chk = lambda w, r=1, wr=0, use=0: iso_check_word(w, sb[0] or cw[0], r, wr, use, hits)

    def gitws(v):
        ap, un = iso_expand(v, cw[0])
        k = iso_key(ap)
        if not un and not ISO["is_hub"] and (k == ISO["wsk"] or k.startswith(ISO["wsk"] + "/")):
            wsg[0] = True
    for rw in cmd_segments(c):
        iso_tick()
        mut = any(a in GIT_MUT for a in rw)
        for x in rw:
            m = ISO_ASG.match(x)
            if m:
                v = m.group(1)
                if " " not in v and (v.startswith(("/", "~", ".", "$")) or "/" in v):
                    chk(v, 1, mut and x.startswith("GIT_"))
                    if x.startswith("GIT_"):
                        gitws(v)
            elif os.path.basename(x) not in ("env", "sudo", "command", "nohup", "time", "exec", "nice", "builtin", "export", "declare", "readonly", "local", "typeset") and not x.startswith("-"):
                break
        b0 = [os.path.basename(x) for x in rw]
        for i, x in enumerate(rw):
            nx = rw[i + 1] if i + 1 < len(rw) else None
            if x in ("-a", "--arg-file") and "xargs" in b0[:i] and nx:
                chk(nx)
            elif x.startswith("--arg-file=") and "xargs" in b0[:i]:
                chk(x.split("=", 1)[1])
            elif x in ("-C", "--chdir") and "env" in b0[:i] and nx:
                chk(nx)
            elif x.startswith("--chdir=") and "env" in b0[:i]:
                chk(x.split("=", 1)[1])
        na = [x for x in rw if not ISO_ASG.match(x)]
        if na and (os.path.basename(na[0]) == "printenv" or (os.path.basename(na[0]) == "env" and all(x.startswith("-") for x in na[1:])) or (os.path.basename(na[0]) in ("export", "declare", "typeset") and ("-p" in na or "-x" in na or na == ["export"])) or na == ["set"] or na[:2] == ["compgen", "-e"]):
            dumps = True
        if na and os.path.basename(na[0]) in ("echo", "printf") and any("$" in x for x in na[1:]):
            echovar = True
        fi = next((i for i, x in enumerate(rw[:8]) if os.path.basename(x) in ("find", "gfind")), None)
        if fi is not None:
            for q in range(fi + 1, len(rw) - 1):
                if rw[q] in ("-fprint", "-fprint0", "-fprintf", "-fls"):
                    chk(rw[q + 1], 0, 1)
                if rw[q] in ("-name", "-iname", "-path", "-ipath", "-regex", "-wholename") and iso_pattern_secret(rw[q + 1]) and re.search(r"xargs|\$\(|`|\bread\b|-exec|-ok", c):
                    hits.append(("secret", ""))
            for x in rw[fi + 1:]:
                if x.startswith(("-", "(", "!")):
                    break
                chk(x)
                ap, un = iso_expand(x, cw[0])
                if un and re.search(r"\$\(|`", x):
                    ap, un = cw[0], False                             # "$(pwd)", "$(git rev-parse --show-toplevel)": judged as the folder we are in
                cv = "" if un else iso_covers(ap)
                if cv:
                    hits.append(("search", cv))
                elif not un and any(e in rw for e in ("-exec", "-execdir", "-ok", "-okdir")):
                    nm_ = [rw[q + 1] for q in range(fi + 1, len(rw) - 1) if rw[q] in ("-name", "-iname")]
                    th = ("secret", "") if iso_secret_root(ap) else iso_tree_hit(ap, names=nm_) if os.path.isdir(ap) else None
                    if th:
                        hits.append(th)
    if depth < 3 and "=" in c:
        for rw_ in cmd_segments(c, 0):
            for x_ in rw_[:6]:
                m_ = re.match(r"(?:GIT_PAGER|GIT_EDITOR|GIT_SSH_COMMAND|GIT_SSH|GIT_ASKPASS|GIT_EXTERNAL_DIFF|GIT_PROXY_COMMAND|PAGER|EDITOR|VISUAL|SSH_ASKPASS|BROWSER|PROMPT_COMMAND)=(.+)$", x_, re.S)
                if m_:
                    hits.extend(iso_bash(m_.group(1), cw[0], depth + 1)[0])
                elif not re.match(r"[A-Za-z_]\w*=", x_):
                    break
    for a_, u_, w_ in all_segs(c):
        if not w_:
            continue
        nw += len(w_)
        if nw > 20000:
            raise ValueError("too many words")
        ws = []; j = 0; sb[0] = None
        while j < len(w_):
            x = w_[j]; j += 1
            m = ISO_REDIR.match(x)
            if m and not x.startswith(("<<", "&>&")):
                tgt = m.group(2)
                if not tgt and j < len(w_):
                    tgt = w_[j]; j += 1
                if tgt and not tgt.startswith("&"):
                    if oldpwd and not tgt.startswith(("/", "~")):
                        hits.append(("error", ""))
                    ISO["spaced"] = True
                    chk(tgt, m.group(1) == "<", m.group(1) != "<")
                    ISO["spaced"] = False
                continue
            ws.append(x)
        if not ws:
            continue
        while ws and ws[0] in ("do", "then", "else", "elif", "if", "while", "until", "!", "time"):
            ws.pop(0)
        if not ws:
            continue
        if os.path.basename(ws[0]) == "busybox" and len(ws) > 1:
            ws = ws[1:]
        ISO["urlcmd"] = False
        cmd = "bash" if re.fullmatch(r"\$\{?(?:SHELL|BASH|0)\}?", ws[0]) else os.path.basename(ws[0])
        ISO["urlcmd"] = cmd in ISO_URLCMDS or (cmd == "git" and any(a_ in ws[1:] for a_ in ("clone", "remote", "fetch", "pull", "push", "ls-remote", "submodule")))
        if iso_secret("/x/" + cmd):
            hits.append(("secret", ""))
        if "/" in ws[0]:
            chk(ws[0])
        if cmd not in ("cd", "pushd", "popd", "pwd", ":", "true", "export"):
            only_cd = False
            cr = None if unsure else iso_judge(cw[0], False, False, True)
            if cr and cr[0] == "project":
                hits.append(("cwd", cr[1]))
        if re.match(r"python[0-9.]*$", cmd) and ws[1:3] == ["-m", "dotenv"]:
            cmd = "dotenv"; ws = ws[2:]
        interp = interp or bool(ISO_INTERP.match(cmd))
        shell = shell or cmd in ISO_SHELLS
        args = ws[1:]
        if (cmd in ISO_SHELLS or cmd == "eval") and depth < 3:
            body = " ".join(args) if cmd == "eval" else next((args[n + 1] for n, x in enumerate(args[:-1]) if re.fullmatch(r"-[A-Za-z]*c", x)), None)
            if body:
                hits.extend(iso_bash(body, cw[0], depth + 1)[0])
        if cmd == "ls" and feeds_[0]:
            for a_ in args:
                if not a_.startswith("-") and (iso_pattern_secret(a_) or (a_.startswith(".") and iso_glob_wide(a_))):
                    hits.append(("secret", ""))
        if cmd in ("ex", "vi", "vim", "nvim", "view", "ed", "gvim"):
            for a_ in args:
                m_ = re.match(r"\+?[0-9$%]*\s*(r|read|e|edit|sp|split|vs|vsplit|w|write|badd|so|source)!?\s+([^\s|]+)", a_)
                if m_:
                    chk(m_.group(2), 1 if m_.group(1) in ("r", "read", "e", "edit", "sp", "split", "vs", "vsplit", "badd", "so", "source") else 0, m_.group(1) in ("w", "write"))
        if depth < 3:
            bs_ = [args[n + 1] for n, x in enumerate(args[:-1]) if x in ISO_CMDSTR.get(cmd, ())]
            if cmd == "git":
                for n, x in enumerate(args[:-1]):
                    if x == "-c":
                        key_, _, v_ = args[n + 1].partition("=")
                        if re.search(r"pager|editor|command|external|textconv|helper|fsmonitor|askpass|^alias\.|sshcommand|proxy", key_, re.I):
                            bs_.append(v_[1:] if v_.startswith("!") else v_)
                bs_ += [x.split("=", 1)[1] for x in args if re.match(r"--(?:extcmd|ext-cmd|exec|upload-pack|receive-pack)=", x)]
            for b_ in bs_[:4]:
                hits.extend(iso_bash(b_, cw[0], depth + 1)[0])
        if cmd == "popd" or (cmd == "pushd" and not args):
            unsure = oldpwd = True
            continue
        if cmd in ISO_NOPATH:
            continue
        if oldpwd and cmd not in ("cd", "pushd") and any(not x.startswith(("-", "/", "~")) and (cmd in ISO_PATHY or "/" in x or x.startswith(".")) for x in args):
            hits.append(("error", ""))
        opts = [x for x in args if x.startswith("-") and x != "-"]
        pos = []; k = 0; has_e = False; tdir = False
        wopt = ISO_WOPT.get(cmd, ()); sopt = ISO_SENDOPT.get(cmd, ())
        fam = "gitgrep" if (cmd == "git" and "grep" in args) else "ack" if cmd == "ack" else "rg" if cmd == "rg" else "ag" if cmd == "ag" else "tar" if cmd in ("tar", "gtar", "bsdtar") else "rsync" if cmd == "rsync" else "grep" if cmd in ISO_GREPS else ""
        fopt = ISO_FILEOPTS.get(fam, ())
        while k < len(args):
            x = args[k]; k += 1
            if not (x.startswith("-") and x != "-"):
                pos.append(x)
                continue
            has_e = has_e or x in ("-e", "-f", "--regexp", "--file") or x.startswith(("--regexp=", "--file="))
            name, eq, val = x.partition("=")
            nxt = args[k] if k < len(args) else None
            if name in sopt:
                v = val if eq else nxt
                k += 0 if eq else 1
                if v is not None:
                    chk(iso_curlpath(v, name))
            elif eq and fam and name in ISO_VALOPTS.get(fam, ()) and name not in fopt:
                pass                                                  # --exclude=PAT style values of this tool's own table are patterns, not paths
            elif fam and name in fopt and (val if eq else nxt):
                fv_ = val if eq else nxt
                chk(fv_, 1, 0)
                try:
                    fp_ = os.path.join(sb[0] or cw[0], os.path.expanduser(fv_))
                    if os.path.exists(fp_) and not os.path.isfile(fp_):
                        hits.append(("error", ""))
                except OSError:
                    pass
                k += 0 if eq else 1
            elif fam and not eq and nxt is not None and ((name in ISO_NUMOPTS and (re.fullmatch(r"\d+", nxt) or (cmd in ISO_GREPS and name == "-d" and nxt in ISO_WORDS)))
                                                       or (name in ("--directories", "--devices", "--binary-files") and nxt in ISO_WORDS) or name in ISO_VALOPTS.get(fam, ())):
                k += 1
            elif cmd in ("docker", "podman", "nerdctl") and (x.startswith("-v") and len(x) > 2 or name in ("-v", "--volume", "--mount", "--secret") and (val if eq else nxt)):
                if x.startswith("-v") and len(x) > 2:
                    mv_ = x[2:].split(":")[0]
                else:
                    mv_ = val if eq else nxt
                    k += 0 if eq else 1
                    if name in ("--mount", "--secret"):
                        mv_ = next((a.split("=", 1)[1] for a in mv_.split(",") if a.startswith(("src=", "source="))), "")
                    else:
                        mv_ = mv_.split(":")[0]
                if mv_:
                    chk(mv_, 1, 0, 1 if name == "--secret" else 0)
                    ap_m, un_m = iso_expand(mv_, cw[0])
                    cv_m = "" if un_m else iso_covers(ap_m)
                    if cv_m:
                        hits.append(("search", cv_m))
                    elif not un_m and iso_secret_root(ap_m):
                        hits.append(("secret", ""))
            elif cmd in ISO_DEST and name in ("-t", "--target-directory") and (val if eq else nxt):
                chk(val if eq else nxt, 0, 1)
                tdir = True; k += 0 if eq else 1
            elif cmd == "openssl" and name in ("-out", "-keyout") and nxt is not None:
                chk(nxt, 0, 1); k += 1
            elif cmd == "openssl" and name in ("-key", "-keyfile", "-signkey", "-CAkey", "-cert", "-CAfile") and nxt is not None:
                chk(nxt, 1, 0, 1); k += 1
            elif cmd == "git" and name in ("-m", "--message") and nxt is not None and not eq:
                k += 1
            elif name == "--message":
                pass
            elif cmd == "curl" and name in ISO_CURL_USE and (val if eq else nxt):
                chk(val if eq else nxt, 1, 0, 1)
                k += 0 if eq else 1
            elif cmd == "curl" and len(x) > 2 and x[1] != "-" and any(ch in "dFTKo" for ch in x[1:]):
                q = next(n for n, ch in enumerate(x) if n and ch in "dFTKo")
                v = x[q + 1:]
                if not v and nxt is not None:
                    v = nxt; k += 1
                if x[q] == "o":
                    chk(v, 0, 1)
                else:
                    chk(iso_curlpath(v, x[q]))
            elif cmd in ISO_SENDOPT and len(x) > 2 and x[1] != "-" and x[:2] in sopt:
                v = x[2:]
                chk(v[1:] if v.startswith("@") else v.split("=@", 1)[1] if "=@" in v else v if x[:2] == "-T" else "-")
            elif eq and val and (val.startswith(("/", "~", ".", "$", "file:")) or "/" in val):
                chk(val, 1, cmd in ISO_W_ALL or name in wopt, name in USE_FLAGS)
                if cmd in ISO_CD and name in wopt:
                    sb[0] = iso_expand(val, cw[0])[0]
                if cmd == "git" and name in ("--git-dir", "--work-tree"):
                    gitws(val)
            elif nxt is not None and (name in USE_FLAGS or (cmd == "dotenv" and name in ("-e", "-f", "--file")) or (cmd in KEY_USERS and name in ("-i", "-F") or (cmd == "ssh-keygen" and name == "-f" and ("-l" in opts or "-y" in opts)))):
                chk(nxt, 1, 0, 1); k += 1
            elif nxt is not None and cmd == "ssh-keygen" and name == "-f":
                chk(nxt, 0, 1); k += 1
            elif nxt is not None and name in wopt:
                chk(nxt, 1, 1); k += 1
                if cmd in ISO_CD:
                    sb[0] = iso_expand(nxt, cw[0])[0]
            elif nxt is not None and cmd == "git" and name in ("-C", "--git-dir", "--work-tree"):
                chk(nxt, 1, any(a in GIT_MUT for a in args[k + 1:k + 6] if not a.startswith("-"))); gitws(nxt); k += 1
            elif cmd == "git" and name == "-c":
                k += 1
            elif cmd in ISO_CD and len(x) > 2 and x[1] != "-" and x[:2] in wopt:
                chk(x[2:], 1, 1)
                sb[0] = iso_expand(x[2:], cw[0])[0]
            elif len(x) > 2 and x[1] != "-" and "/" in x and x[2] in "/~.":
                chk(x[2:], 1, x[:2] in [o[:2] for o in wopt])
                if cmd in ISO_CD and x[:2] in wopt:
                    sb[0] = iso_expand(x[2:], cw[0])[0]
        if cmd in ("find", "gfind"):
            pos = []
        gsub = ""
        if cmd == "git" and pos:
            gsub = pos.pop(0)
        if wsg[0] and cmd == "git" and gsub not in ISO_GIT_META:
            hits.append(("ws", ""))
        if cmd in ("docker", "podman", "nerdctl") and any(os.path.basename(x) in ("env", "printenv", "set") for x in pos[2:4]):
            dumps = True
        noshow = (re.match(r"python[0-9.]*$", cmd) is not None and "-m" in args and "venv" in args) or cmd in ISO_NOSHOW or cmd == "ssh-add" or gsub in ISO_GIT_NOSHOW
        if cmd in ("gpg", "gpg2", "gpg1") and any(a_.startswith("--export-secret") for a_ in args):
            hits.append(("secret", ""))
        if cmd == "security" and pos and (pos[0] in ("dump-keychain", "export") or (pos[0].startswith("find-") and any(re.match(r"^-[a-zA-Z]*[wg]", o) for o in opts))):
            hits.append(("secret", ""))
        if cmd in ISO_PAT_FIRST and pos and not has_e:
            pos.pop(0)
        inplace = cmd in ("sed", "perl") and any(re.match(r"^-[a-zA-Z]*i|^--in-place", o) for o in opts)
        if cmd == "git" and gsub == "grep" and pos and not has_e:
            pos.pop(0)
        rf = ISO_RECFLAG.get(cmd)
        rec = (cmd == "git" and gsub == "grep") or cmd in ISO_RECURSIVE or (rf is not None and any(rf.match(o) for o in opts)) or (cmd in ISO_GREPS and ("--directories=recurse" in args or ("-d" in args and "recurse" in args)))
        if cmd in ("cd", "pushd"):
            if pos:
                if pos[0] not in ("$OLDPWD", "-", "~-"):
                    chk(pos[0], 0)
                if cdpath and not pos[0].startswith(("/", ".", "~")) and iso_key(pos[0].split("/")[0]) in ISO["names"] and iso_key(pos[0].split("/")[0]) != ISO["curk"]:
                    hits.append(("project", ISO["names"][iso_key(pos[0].split("/")[0])]["name"]))
                np_, un_ = iso_expand(pos[0], cw[0])
                if un_ or pos[0] == "-":
                    unsure = True
                    oldpwd = oldpwd or pos[0] == "-" or "OLDPWD" in pos[0] or pos[0].startswith("~-")
                else:
                    cw[0] = np_
            elif cmd == "cd":
                cw[0] = os.path.realpath(HOME)
            continue
        if cmd in ("source", ".") and pos:
            chk(pos.pop(0), 1, 0, 1)
        if (cmd in ("mv", "ln") or gsub == "mv") and len(pos) >= 2:
            ex = [iso_expand(x, cw[0]) for x in pos]
            if any(not u and iso_secret(a) for a, u in ex[:-1]) and (ex[-1][1] or not iso_secret(ex[-1][0])):
                hits.append(("secret", ""))
            if cmd == "ln" and any(not u and iso_secret_root(a) for a, u in ex[:-1]):
                hits.append(("secret", ""))
        if cmd == "git" and gsub in ("checkout", "restore", "switch", "reset", "merge", "rebase", "pull", "stash", "cherry-pick", "apply", "am", "revert", "clone"):
            ISO["nosniff"] = True                                    # the working tree changes in this command: file contents seen now are not what will be read
        if (cmd == "gh" and (pos[:2] == ["auth", "token"] or (pos[:2] == ["auth", "status"] and any(o in ("-t", "--show-token") for o in opts)))) or cmd.startswith("git-credential-") or (cmd == "git" and gsub.startswith("credential-")) or (cmd == "git" and gsub == "credential" and pos[:1] in (["fill"], ["get"])):
            hits.append(("secret", ""))
        ISO["spaced"] = cmd in ISO_PATHY or cmd in ("source", ".")
        for idx, x in enumerate(pos):
            mf_ = re.match(r"(?:.*@)?(?:file|link|portal|github|git\+file):(?://)?(.+)", x)
            if mf_ and mf_.group(1).startswith(("/", ".", "~")):
                x = mf_.group(1)
            if re.match(r"[A-Za-z_]+=[^=]", x) and not x.startswith("/"):
                x = x.split("=", 1)[1]
                if cmd == "dd":
                    chk(x, 0 if pos[idx].startswith("of=") else 1, pos[idx].startswith("of="))
                    continue
            if gsub and ":" in x and not x.startswith(("/", "~", ".")) and not noshow:
                x = x.rsplit(":", 1)[1]; ISO["nosniff"] = True
            last = idx == len(pos) - 1 and len(pos) > 1 and not tdir
            ISO["rmop"] = cmd in ("rm", "rmdir", "unlink", "shred") or (cmd == "mv" and not last)
            if cmd in ISO_W_ALL:
                rd, wr = 0, 1
                if cmd in ("chmod", "chown", "chgrp") and idx == 0:
                    continue
            elif cmd in ISO_DEST:
                rd, wr = not last, last or cmd in ("mv", "ln", "link") or (cmd == "cp" and any(o in ("-l", "--link", "-s", "--symbolic-link") or re.fullmatch(r"-[A-Za-z]*[ls][A-Za-z]*", o) for o in opts))
            elif cmd == "git" and gsub in ("clone", "init", "worktree") and idx == len(pos) - 1 and (len(pos) > 1 or gsub == "init"):
                rd, wr = 1, 1
            else:
                rd, wr = 1, inplace
            chk(x, rd, wr, noshow)
        ISO["spaced"] = False; ISO["rmop"] = False
        if rec:
            hidf, ign = iso_search_mode(cmd, opts)
            cont = cmd in ISO_GREPS or cmd in ("cp", "rsync", "scp", "tar", "zip", "ditto", "7z", "bsdtar", "gtar", "rg", "ag", "ack", "git")
            exg = []; exd = []; risky = False; inc_ = []; inc_ok = True; ft_ = ""
            for n_, a_ in enumerate(args):
                nm_, eq_, vl_ = a_.partition("=")
                vv_ = vl_ if eq_ else (args[n_ + 1] if n_ + 1 < len(args) else "")
                if cmd == "rsync" and (nm_ in ("--include", "--include-from", "--filter", "-f", "--relative") or re.fullmatch(r"-[A-Za-z]*[RF][A-Za-z]*", a_)):
                    risky = True                                     # rsync rules other than plain --exclude are not modelled: no exclude counts (fail closed)
                if cmd in ISO_GREPS and nm_ == "--include" and vv_ and iso_pattern_secret(vv_):
                    hits.append(("secret", ""))
                if cmd in ISO_GREPS and nm_ == "--include" and vv_:
                    inc_.append(vv_); inc_ok = inc_ok and "/" not in vv_
                if cmd == "rg" and nm_ in ("-t", "--type") and vv_ and not ft_:
                    ft_ = vv_
                if cmd == "rg" and nm_ in ("-g", "--glob", "--iglob") and vv_ and not vv_.startswith("!"):
                    inc_.append(vv_); inc_ok = inc_ok and "/" not in vv_ and nm_ != "--iglob"
                    if iso_pattern_secret(vv_):
                        hits.append(("secret", ""))
                    elif iso_glob_wide(vv_):
                        hidf, ign = True, False                      # a whitelist glob overrides .gitignore and hidden-file rules for the files it matches
                if nm_ == "--exclude" and cmd != "rsync":
                    pat_ = vv_[2:] if cmd in ("tar", "gtar", "bsdtar") and vv_.startswith("./") else vv_
                    if "/" not in pat_:
                        exg.append(pat_)                             # grep / tar / ag match names only: a pattern with a slash excludes nothing here (fail closed)
                elif nm_ == "--exclude":
                    (exd if vv_.endswith("/") else exg).append(vv_.rstrip("/"))
                elif nm_ == "--exclude-from" and vv_:
                    try:
                        fp_ = os.path.join(sb[0] or cw[0], vv_)
                        if not os.path.isfile(fp_):
                            raise OSError("not a regular file")
                        ls_ = [l.strip() for l in open(fp_, "rb").read(65536).decode("utf-8", "replace").splitlines()[:300] if l.strip() and not l.startswith(("#", ";"))]
                        if cmd == "rsync" and any(l.startswith(("+ ", "- ", ". ", ": ", "!")) for l in ls_):
                            risky = True
                        exg.extend(l for l in ls_ if not l.endswith("/") and not l.startswith(("+ ", "- ", ". ", ": ", "!")) and (cmd == "rsync" or "/" not in l))
                    except OSError:
                        risky = True
                elif nm_ == "--exclude-dir":
                    if "/" not in vv_:
                        exd.append(vv_)
                elif nm_ in ("-g", "--glob") and vv_.startswith("!") and "/" not in vv_:
                    exg.append(vv_[1:])
            if risky:
                exg = []; exd = []
            fol = ((cmd in ISO_GREPS and any(o == "--dereference-recursive" or re.fullmatch(r"-[A-Za-z]*R[A-Za-z]*", o) for o in opts)) or (cmd == "rg" and any(o in ("-L", "--follow") or re.fullmatch(r"-[A-Za-z]*L[A-Za-z]*", o) for o in opts))
                   or (cmd in ("rsync", "cp") and any(o in ("--copy-links", "--dereference") or re.fullmatch(r"-[A-Za-z]*L[A-Za-z]*", o) for o in opts)) or (cmd in ("tar", "gtar", "bsdtar") and any(o == "--dereference" or re.fullmatch(r"-[A-Za-z]*h[A-Za-z]*", o) for o in opts)))
            gitm = cmd == "git"
            ps = []
            if cmd == "rsync":
                ign = False                                          # rsync reads only .gitignore files in the tree: git's view of "ignored" is not trusted
            untr = gitm and any(o in ("--no-index", "--untracked", "--no-exclude-standard") for o in opts)
            after_ = args[args.index("--") + 1:] if "--" in args else []
            revs = [x for x in pos if gitm and x not in after_ and not x.startswith(":") and not re.search(r"[*?\[]", x) and not os.path.exists(os.path.join(cw[0], x))] if gitm else []
            if gitm and not untr:
                ps = [x for x in pos if x not in revs]
            roots = ["."] if (gitm and not untr) else [x for x in pos if x not in revs] or ["."]
            for x in roots:
                ap, un = iso_expand(x, sb[0] or cw[0])
                if un and re.search(r"\$\(|`", x):
                    ap, un = sb[0] or cw[0], False                    # quoted "$(pwd)" / "$(realpath .)": the folder we are in
                if un or (" " in x and not os.path.exists(ap)):
                    continue
                cv = iso_covers(ap) if (os.path.isdir(ap) or not os.path.exists(ap)) else ""
                if cv:
                    hits.append(("search", cv))
                elif cmd not in ("tar", "zip") or pos:
                    th = ("secret", "") if iso_secret_root(ap) else iso_tree_hit(ap, hidden=hidf, ignore=ign, git=gitm and not untr, excludes=exg, exdirs=exd, recurse="--recurse-submodules" in opts, revs=revs, follow=fol, pathspec=ps, names=(inc_ if inc_ok else []), ftype=(ft_ if cmd == "rg" else ""), relprefix=("" if cmd != "rsync" or x.endswith("/") or x in (".", "..") else os.path.basename(x.rstrip("/")) + "/")) if (cont and os.path.isdir(ap)) else None
                    if th:
                        hits.append(th)
    if interp:
        io_ = bool(ISO_IOWORD.search(c[:BIG_CMD]))
        for m in ISO_LIT.finditer(c[:BIG_CMD]):
            if "/" in m.group(1) or "." in m.group(1):
                if io_:
                    chk(m.group(1))
                else:                                                 # no file or process API seen: judge a literal only when it names an EXISTING file
                    t_ = []
                    iso_check_word(m.group(1), sb[0] or cw[0], 1, 0, 0, t_)
                    if t_ and os.path.lexists(iso_expand(m.group(1), sb[0] or cw[0])[0]):
                        hits.extend(h_ for h_ in t_ if h_[0] != "secret")   # os.path.exists('.env') and print('.env') name a secret without reading it
        for pat in CODE_PATTERNS:
            for m in pat.finditer(c[:BIG_CMD]):
                chk(m.group("p"), 0, 1)
    if shell and "<<" in c and depth < 2:
        for body in iso_heredocs(c):
            hits.extend(iso_bash(body, cw[0], depth + 1)[0])
    if not hits and ("$" in c or "`" in c or unsure):
        r = iso_literal(c[:BIG_CMD])
        if not r and re.search(r"(?:^|[\s;&|(])[A-Za-z_]\w*=\.\.?(?:/|[\s;&|)]|$)", c):
            kc = iso_key(c)
            r = next((("project", e["name"]) for e in ISO["ents"] if e["k"] != ISO["curk"] and not (ISO["is_hub"] or iso_linked(e, False)) and re.search(r"[/}]" + re.escape(e["k"]) + r"(?:[/\s;&|)]|$)", kc)), None)
        if r:
            hits.append(r)
    if ISO.get("used_secret") and (dumps or echovar or re.search(r"(?:^|[\s;&|(])(?:set\s+(?:-\w*[xv]|-o\s+(?:xtrace|verbose))|(?:ba|z|da|k)?sh\s+-\w*[xv])", c)):
        hits.append(("secret", ""))
    return hits, only_cd


def iso_text_scan(c):
    c = c[:400000]
    hits = [r for r in [iso_literal(c)] if r]
    if (any(f in c for f in SECRET_HOME_FILES) or any(d + "/" in c for d in SECRET_HOME_DIRS if d != ".ssh") or re.search(r"\.ssh/(?!known_hosts|config|[^\s'\"/]{0,100}\.pub)", c)
            or re.search(r"(?:^|[\s'\"/=<>])\.env(?![\w])(?!\.(?:example|sample|template|dist|defaults)\b)|\.(?:pem|p12|pfx|jks|keystore)\b|\bid_(?:rsa|ed25519|ecdsa|dsa)\b(?!\.pub)", c)):
        hits.append(("secret", ""))
    return hits


ISO_SECRET_SAMPLES = (".env", ".env.local", ".env.production", "prod.env", "x.env", ".envrc", ".dev.vars", "server.pem", "x.key", "id_rsa", "id_ed25519", "credentials.json", "secrets.yml", "secrets.yaml", "secret.json", "secrets.toml",
                      "service-account.json", "x.tfvars", "terraform.tfstate", "kubeconfig", ".npmrc", ".pypirc", ".netrc", ".pgpass", ".my.cnf", ".s3cfg", "x.p12", "x.pfx", "x.jks", "x.keystore", "x.secret", "credentials", "secrets.txt")
ISO_BENIGN_SAMPLES = ("main.py", "index.js", "app.ts", "README.md", "package.json", "config.yml", "data.json", "style.css", "notes.txt", "test.py", "Makefile", "x.json", "x.md")


def iso_glob_rx(g):
    o = ""; i = 0
    while i < len(g):
        ch = g[i]; i += 1
        if ch == "*":
            o += ".*"
        elif ch == "?":
            o += "."
        elif ch == "[" and "]" in g[i:]:
            j = g.index("]", i); o += "[" + g[i:j].replace("\\", "\\\\") + "]"; i = j + 1
        else:
            o += re.escape(ch)
    return re.compile(o)


def iso_glob_wide(pat):
    """True when a positive rg glob can match secret-looking names (so rg would search ignored and hidden files that match it)."""
    last = pat.rstrip("/").rsplit("/", 1)[-1][:300]
    for alt in iso_braces(last).split(" ")[:64]:
        try:
            rx = iso_glob_rx(alt)
        except re.error:
            return True
        if any(rx.fullmatch(n) for n in ISO_SECRET_SAMPLES):
            return True
    return False


def iso_pattern_secret(pat):
    last = pat.rstrip("/").rsplit("/", 1)[-1][:300]
    for alt in iso_braces(last).split(" ")[:64]:
        if alt.startswith(".env") and not alt.startswith((".env.example", ".env.sample", ".env.template", ".env.dist", ".env.defaults")):
            return True
        if iso_secret("/x/" + alt.replace("*", "x").replace("?", "x")) or any(alt.startswith(p) or alt.startswith("*" + p) for p in SECRET_NAME_PREFIXES):
            return True
        try:
            rx = iso_glob_rx(alt)
        except re.error:
            return True
        if any(rx.fullmatch(n) for n in ISO_SECRET_SAMPLES) and not any(rx.fullmatch(n) for n in ISO_BENIGN_SAMPLES):
            return True
    return False


def iso_file_calls(tool, ti, cwd):
    if any(ti.get(k) is not None and not isinstance(ti.get(k), str) for k in ("file_path", "notebook_path", "path", "directory", "dir", "pattern", "glob")):
        return [("error", "")]
    raw = next((sp(ti.get(k)).replace("\0", "") for k in ("file_path", "notebook_path", "path", "directory", "dir") if sp(ti.get(k))), "")
    pat = sp(ti.get("pattern")) if tool == "Glob" else ""
    base = raw or cwd
    if tool == "Glob" and pat.startswith(("/", "~")) and not raw:
        i = min([x for x in (pat.find("*"), pat.find("?"), pat.find("[")) if x >= 0] or [len(pat)])
        base = pat[:i].rsplit("/", 1)[0] or "/"
        pat = pat[len(base):].lstrip("/") if i < len(pat) else ""
    if tool in ISO_FILE_TOOLS and not raw:
        return []
    ap, unres = iso_expand(base, cwd)
    if unres:
        r = iso_literal(ap)
        return [r] if r else []
    ap = os.path.normpath(ap)
    if pat and not pat.startswith(("/", "~")) and ".." in pat.split("/"):
        st = re.split(r"[*?\[{]", pat, 1)[0]
        ap = os.path.normpath(os.path.join(ap, st.rsplit("/", 1)[0] if "/" in st else ""))
    if tool in ISO_FILE_TOOLS:
        r = iso_judge(ap, os.path.lexists(ap), True)
        return [r] if r else iso_import_hits(tool, ti, ap, cwd)
    r = iso_judge(ap, True, False)
    if r:
        return [r]
    hits = []
    if (tool == "Grep" and not os.path.isfile(ap)) or (tool == "Glob" and ("**" in pat or "/" in pat.strip("/"))):
        cv = iso_covers(ap)
        if cv:
            hits.append(("search", cv))
        elif iso_secret_root(ap):
            hits.append(("secret", ""))
        elif tool == "Grep" and os.path.isdir(ap):
            th = iso_tree_hit(ap, hidden=True, ignore=True, glob=sp(ti.get("glob")) if tool == "Grep" else "", ftype=sp(ti.get("type")) if tool == "Grep" else "")
            if th:
                hits.append(th)
    gl = pat if tool == "Glob" else sp(ti.get("glob")) if tool == "Grep" else ""
    if gl and iso_pattern_secret(gl):
        hits.append(("secret", ""))
    if gl and re.search(r"[*?\[{][^/]*/(?:[^/]*/)*\.\.(?:/|$)", gl):
        hits.append(("error", ""))
    if tool == "Grep" and gl and (".." in gl.split("/") or gl.startswith(("/", "~"))):
        st = re.split(r"[*?\[{]", gl, 1)[0]
        e, un = iso_expand(st.rsplit("/", 1)[0] if "/" in st else ".", ap)
        r = iso_literal(e) if un else iso_judge(e, True, False)
        cv = "" if un else iso_covers(e)
        if r:
            hits.append(r)
        elif cv:
            hits.append(("search", cv))
    return hits


ISO_IMPORT = re.compile(r"(?<![\w.@/])@([^\s)\]>\"'`,;]+)")


def iso_import_hits(tool, ti, ap, cwd):
    b = os.path.basename(ap)
    if not (b in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md") or (b.endswith(".md") and "/.claude/" in ap.replace("\\", "/"))):
        return []
    ed = ti.get("edits") if isinstance(ti.get("edits"), list) else []
    texts = {"Write": [ti.get("content")], "Edit": [ti.get("new_string")], "NotebookEdit": [ti.get("new_source")], "MultiEdit": [e.get("new_string") for e in ed if isinstance(e, dict)]}.get(tool, [])
    for t in texts:
        for m in ISO_IMPORT.finditer(sp(t)[:400000]):
            tok = m.group(1).rstrip(".:!?")
            if "/" in tok or tok.startswith(("~", ".")):
                ap2, un = iso_expand(tok, os.path.dirname(ap))
                r = iso_literal(ap2) if un else iso_judge(os.path.normpath(ap2), True, False)
                if r:
                    return [("import", r[1])]
    return []


def wd_fire(msg):
    """A watchdog thread answers: ONE deny on fd 1, then the process ends. Silent when the main thread is already answering."""
    with EMIT[0]:
        if EMIT[1]:
            return
        EMIT[1] = True
        try:
            os.write(1, (json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Project isolation: " + msg}}) + "\n").encode())
        finally:
            os._exit(0)


def gate_drill(ev):
    """Test-only failure injection (SHIPMIRACLE_TEST=1 and SHIPMIRACLE_GATE_DRILL=<kind>): proves the fail-closed paths. Never active in a real run."""
    k_ = os.environ.get("SHIPMIRACLE_GATE_DRILL") if os.environ.get("SHIPMIRACLE_TEST") == "1" else None
    if not k_:
        return
    if k_ == "raise":
        raise RuntimeError("drill")
    if k_ == "exit1":
        sys.exit(1)
    if k_ == "interrupt":
        raise KeyboardInterrupt()
    if k_ == "garbage":
        print("garbage{"); sys.exit(0)
    if k_ == "exit2":
        sys.exit(2)
    if k_ == "twojson":
        print('{"a": 1}'); print('{"b": 2}'); sys.exit(0)
    if k_ == "garbage2":
        print("[1,2"); sys.exit(0)
    if k_ == "hang":
        time.sleep(60)
    if k_ == "kill":
        os.kill(os.getpid(), 9)                                       # "killed by a signal" without a real crash: SIGKILL (a SIGSEGV would pop up the macOS crash dialog)
    if k_ == "exit139":
        os._exit(139)


def iso_outer(proj):
    """Legacy process only: one total wall limit around the whole PreToolUse call (a hang anywhere in the gate), strict only."""
    try:
        if "shipmiracle.hooks.core" in sys.modules or iso_level(proj) != "strict":
            return
        t_ = __import__("threading").Timer(float(os.environ.get("SHIPMIRACLE_GATE_OUTER_WD") or OUTER_WD) if os.environ.get("SHIPMIRACLE_TEST") == "1" else OUTER_WD, wd_fire, [ISO_CRASH]); t_.daemon = True; t_.start()
    except Exception:
        pass


def iso_crash():
    """The gate raised or exited oddly: at strict a PreToolUse for Bash / the file tools is refused (fail closed); everything else stays silent."""
    c_ = ISO_CALL[0]
    if EVENT[0] == "PreToolUse" and c_ and iso_level(c_[0]) == "strict":
        out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Project isolation: " + ISO_CRASH}})


def iso_pre(d, pd, rpd, unk, proj, tool, ti):
    if tool not in ISO_READ_TOOLS and tool not in ISO_FILE_TOOLS and tool != "Bash":
        return
    lv = iso_level(proj)
    if lv == "off":
        return
    cwd = os.path.realpath(sp(d.get("cwd")) or pd)
    hits = []
    over = [False]; done = [False]
    sg = old = oldp = wd = None
    if lv == "strict":
        try:
            wd = __import__("threading").Timer(ISO_WD, wd_fire, [ISO_TEXT["error"]]); wd.daemon = True; wd.start()   # a call stuck in the kernel (hung mount) cannot be interrupted: answer and leave
        except Exception:
            wd = None
    try:
        sg = __import__("signal")

        def alarm(*a):
            if over[0] or done[0]:
                return
            over[0] = True
            raise IsoTimeout()
        old = sg.signal(sg.SIGALRM, alarm); oldp = sg.signal(sg.SIGPROF, alarm)
        sg.setitimer(sg.ITIMER_REAL, 6.0); sg.setitimer(sg.ITIMER_PROF, 1.5)
    except Exception:
        sg = None
    try:
        try:
            try:
                iso_init(pd, rpd, unk)
                ISO["cdl"] = time.process_time() + 1.5; ISO["wdl"] = time.time() + 15
                if tool != "Bash":
                    hits = iso_file_calls(tool, ti, cwd)
                else:
                    c = sp(ti.get("command"))
                    try:
                        hits = [("error", "")] + iso_text_scan(c) if len(c) > BIG_CMD else iso_bash(c, cwd)[0]
                    except (ValueError, Exception) as e:
                        if not isinstance(e, ValueError):
                            log_err()
                        hits = [("error", "")] + iso_text_scan(c)
            except IsoTimeout:
                over[0] = True
            except BaseException:
                log_err()
                hits = [("error", "")]
        finally:
            done[0] = True
            if wd:
                wd.cancel()
            if sg:
                sg.setitimer(sg.ITIMER_PROF, 0); sg.setitimer(sg.ITIMER_REAL, 0)
                sg.signal(sg.SIGALRM, old); sg.signal(sg.SIGPROF, oldp)
    except IsoTimeout:
        over[0] = True
        if sg:
            try:
                sg.setitimer(sg.ITIMER_PROF, 0); sg.setitimer(sg.ITIMER_REAL, 0)
                sg.signal(sg.SIGALRM, old); sg.signal(sg.SIGPROF, oldp)
            except BaseException:
                pass
    if over[0]:
        hits = [("error", "")] + hits
    sid = re.sub(r"[^A-Za-z0-9_-]", "", sp(d.get("session_id")) or "x")

    def log_(kind, **kw):
        try:
            os.makedirs(STATE, exist_ok=True)
            with open(os.path.join(STATE, "flow-events.jsonl"), "a") as f:
                f.write(json.dumps({"ts": int(time.time()), "project": proj, "session": sid, "event": kind, **kw}) + "\n")
        except Exception:
            pass
    for k, kw in ISO.get("events") or []:
        log_(k, **kw)
    if not hits:
        return
    kind, other = hits[0]
    txt = "Project isolation: " + ISO_TEXT.get(kind, ISO_TEXT["project"]).format(o=other or "that project", c=ISO["cur"]["name"] if ISO.get("cur") else proj)
    if kind == "secret" and ISO.get("offender"):
        off_ = str(ISO["offender"])[:120]
        txt = ("Project isolation: this search would show %s, a secret-named file. Add it to .gitignore, search a subfolder, or narrow the search (glob \"*.js\", type)." % off_ if tool == "Grep"
               else "Project isolation: this command would show %s, a secret-named file. Exclude it (--exclude=NAME), search a subfolder, or use `git grep` / `rg` on files git tracks." % off_)
        if tool == "Bash" and re.search(r"--exclude\b|--exclude=|\s-g\s*'?!", sp(ti.get("command"))):
            txt = "Project isolation: this command would still show %s, a secret-named file, that your --exclude does not cover (the check only trusts plain names such as --exclude=.env*; filters, includes and path patterns are not trusted). Name the file in a plain --exclude, search a subfolder, or use `git grep` / `rg`." % off_
    if kind == "secret" and re.search(r"=\$\(\s*cat\s", sp(ti.get("command"))):
        txt = "Project isolation: VAR=$(cat SECRETFILE) cmd would put the secret where this chat can print it. Rails reads config/master.key by itself: start Rails without passing the key (`rails s`); for other tools use --env-file or `source .env`."
    if kind == "error" and ISO.get("nogit"):
        txt = "Project isolation: git is not on PATH, so the check cannot list the files of this search; install git or put it on PATH (or search a folder without .gitignore rules)."
    if tool == "Bash" and re.match(r"\s*zip\b", sp(ti.get("command"))):
        txt = txt.replace("(--exclude=NAME)", "(-x 'NAME')").replace("--exclude=.env*", "-x '.env*'")
    extra = {"agent": sp(d.get("agent_type"))} if d.get("agent_id") else {}
    if lv == "warn":
        log_("isolation_warned", tool=tool, why=kind, other=other, **extra)
        NOTES.append("Isolation (warn): " + txt)
        return
    log_("isolation_refused", tool=tool, why=kind, other=other, **extra)
    out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": txt}})

def log_err():
    """Append the current traceback to flow-errors.log (never raises)."""
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "flow-errors.log"), "a") as f:
            f.write(time.strftime("%F %T ") + traceback.format_exc().replace("\n", " | ")[-800:] + "\n")
    except Exception:
        pass


NOTES = []                                                       # warn-level notes waiting for the next output of this hook call
EVENT = [""]


def out(obj):
    if NOTES and isinstance(obj, dict) and obj.get("decision") != "block" and (obj.get("hookSpecificOutput") or {}).get("permissionDecision") != "deny":
        txt = " ".join(NOTES); del NOTES[:]
        hso = obj.get("hookSpecificOutput")
        if isinstance(hso, dict):
            hso["additionalContext"] = (hso.get("additionalContext") + " " if hso.get("additionalContext") else "") + txt
        else:
            obj["systemMessage"] = (obj.get("systemMessage") + " " if obj.get("systemMessage") else "") + txt
    with EMIT[0]:                                                # one answer only: a watchdog thread that fires at the same moment stays silent
        EMIT[1] = True
        print(json.dumps(obj)); sys.exit(0)


def main():
    global now
    try:
        d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return                                                   # empty or malformed input: nothing to judge, say nothing
    if not isinstance(d, dict):
        return
    ev = sp(d.get("hook_event_name")); EVENT[0] = ev
    if ev == "PreToolUse" and sp(d.get("tool_name")) in ISO_READ_TOOLS + ISO_FILE_TOOLS + ("Bash",):
        ISO_CALL[0] = ("", sp(d.get("tool_name")))                   # known from here on: a crash anywhere below is answered at strict
    pd = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or sp(d.get("cwd")) or "/")
    rpd = pd; wt = None; unk = False                             # rpd: the project whose registry entry and flow level apply (the main checkout for a worktree)
    if fold(os.path.dirname(pd)) != fold(DEV):
        wt = worktree_of(pd)                                     # P6 T3 (F1): <DEV>/.worktrees/<p>/<x> is gated as project <p>; an unverified one at the default level
        if wt is None:
            return                                               # not a project under ~/Developer
        if wt[0] == "ok":
            rpd = wt[1]
        else:
            unk = True
    proj = os.path.basename(rpd) if not unk else ".worktrees/" + os.path.basename(pd)
    if ev != "PreToolUse":
        gate_drill(ev)
    if ev == "PreToolUse":                                       # G11/D11: project isolation and the secret-read rule (before the team-flow activation checks: independent of them)
        tool_i = sp(d.get("tool_name")); ti_i = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
        if tool_i in ISO_READ_TOOLS or tool_i in ISO_FILE_TOOLS or tool_i == "Bash":
            ISO_CALL[0] = (proj, tool_i)
            iso_outer(proj)
        gate_drill(ev)
        iso_pre(d, pd, rpd, unk, proj, tool_i, ti_i)
        if tool_i in ISO_READ_TOOLS:
            return                                               # Read/Grep/Glob/LS/NotebookRead: only the isolation rule applies
    if ev == "PreToolUse" and wt and wt[0] == "ok" and re.fullmatch(r"auto/CR-\d+", wt[2]) and (gate_engine() != "playbook" or cfg_value("hooks.dispatcher") != "v1" or os.environ.get("SHIPMIRACLE_HOOK_FALLBACK") == "1") and autopilot_writes(d, pd):
        try:                                                     # P6 T3 (C6): an autopilot branch is written only under the playbook gate; no cap, no bypass, any level
            os.makedirs(STATE, exist_ok=True)
            with open(os.path.join(STATE, "flow-events.jsonl"), "a") as f_:
                f_.write(json.dumps({"ts": int(time.time()), "project": proj, "session": re.sub(r"[^A-Za-z0-9_-]", "", sp(d.get("session_id")) or "x"), "event": "autopilot_needs_gate", "branch": wt[2], "tool": sp(d.get("tool_name"))}) + "\n")
        except Exception:
            pass
        out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
             "autopilot_needs_gate: this autopilot branch (" + wt[2] + ") may only be written while hooks.dispatcher is v1 and gate.engine is playbook (and the dispatcher itself loads). "
             "Writes are refused until the owner restores both (shipm switch ...)."}})
    agents_dir = os.path.join(pd, ".claude/agents")
    sid = re.sub(r"[^A-Za-z0-9_-]", "", sp(d.get("session_id")) or "x")
    sf = os.path.join(STATE, f"flow.{sid}.json")
    UL[0] = shipmiracle_layout() == "userlevel"
    team_gone = False; gated_reg = unk
    if not os.path.isdir(agents_dir):
        try:
            e_ = reg_entry(rpd)
            gated_reg = gated_reg or (e_ is not None and e_.get("team") != "off")
        except Exception:
            log_err()
        if not gated_reg:
            try:
                try:
                    seen = bool(json.load(open(sf)).get("team_seen"))
                except Exception:
                    seen = False
                if not seen:
                    import subprocess  # SHIPMIRACLE-LAZY
                    seen = bool(subprocess.run(["git", "-C", pd, "ls-files", "--", ".claude/agents"], capture_output=True, timeout=5).stdout.strip()) or \
                        bool(subprocess.run(["git", "-C", pd, "log", "-1", "--format=%H", "--", ".claude/agents"], capture_output=True, timeout=5).stdout.strip())   # P3 R5: a 'team moved' commit shows the team existed (damaged registry must not turn the gate off)
                team_gone = seen
            except Exception:
                team_gone = False
            if not team_gone:
                return
    try:
        cfg = json.load(open(os.path.join(WS, "config/flow.json")))
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    projs = cfg.get("projects")
    level = (projs if isinstance(projs, dict) else {}).get(proj, cfg.get("default", "strict"))
    vmode = os.environ.get("SHIPMIRACLE_FLOW_VERDICT")
    if vmode not in ("strict", "legacy"):
        g_ = cfg.get("gate"); vmode = g_.get("verdict") if isinstance(g_, dict) else None
        if vmode not in ("strict", "legacy"):
            vmode = "legacy"                                     # default: a missing verdict behaves as before (a present FAIL is enforced in both)
    ov = os.environ.get("SHIPMIRACLE_FLOW_LEVEL")
    if ov in ("strict", "warn"):
        level = ov                                               # test override; "off" and anything else is ignored
    cap = os.environ.get("SHIPMIRACLE_FLOW_CAPTURE")
    if cap:
        try:                                                     # raw input of every handled event, redacted; never raises
            roots = [r_ for r_ in {pd, str(d.get("cwd") or ""), os.environ.get("CLAUDE_PROJECT_DIR") or ""} if r_ and r_ != "/"]
            keep = ("hook_event_name", "tool_name", "agent_id", "agent_type", "permission_mode", "file_path", "notebook_path", "replace_all", "edit_mode",
                    "stop_hook_active", "prompt_id", "tool_use_id")
            drop = ("tool_response", "last_assistant_message", "description", "structuredPatch", "originalFile", "lines", "oldString", "newString")      # also every key ending in transcript_path

            def redact(v, key=""):
                if isinstance(v, str):
                    if key not in keep:
                        return "<%d chars>" % len(v)               # allow-list: only these strings are ever captured
                    for r_ in sorted(roots, key=len, reverse=True):
                        v = v.replace(r_ + "/", "PROJECT/")
                        if v == r_:
                            v = "PROJECT"
                    return v.replace(HOME, "~") if HOME and HOME != "/" else v
                if isinstance(v, list):
                    return [redact(x, key) for x in v]
                if isinstance(v, dict):
                    return {k: redact(x, k) for k, x in v.items() if k not in drop and not str(k).endswith("transcript_path")}
                return v
            c = redact({k: v for k, v in d.items() if k not in drop and k not in ("session_id", "cwd") and not str(k).endswith("transcript_path")})
            c["session_id"] = "SESSION"; c["cwd"] = "PROJECT"
            os.makedirs(cap, exist_ok=True)
            fn = os.path.join(cap, "%s-%s.json" % (re.sub(r"[^a-z0-9]", "", ev.lower()) or "event", "agent" if d.get("agent_id") else "main"))
            with open(fn + ".tmp", "w") as f:
                json.dump(c, f, indent=1)
            os.replace(fn + ".tmp", fn)
        except Exception:
            pass
    if level == "off":
        return
    lockf = None                                                 # one hook at a time per session: load to process end (fail open after 3 s)
    try:
        os.makedirs(STATE, exist_ok=True)
        lockf = open(sf + ".lock", "w"); t0 = time.time()
        while True:
            try:
                fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except OSError:
                if time.time() - t0 > 3:
                    break
                time.sleep(0.02)
    except Exception:
        pass
    now = time.time()
    try:
        st = json.load(open(sf))
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    st.setdefault("project", proj)
    agent = d.get("agent_id"); atype = sp(d.get("agent_type"))

    def save():
        os.makedirs(STATE, exist_ok=True)
        st["ts"] = int(now)
        tmp = sf + f".{os.getpid()}.tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, sf)
        except Exception:
            try: os.remove(tmp)
            except OSError: pass
            raise

    def log(kind, **kw):
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "flow-events.jsonl"), "a") as f:
            f.write(json.dumps({"ts": int(now), "project": proj, "session": sid, "event": kind, **kw}) + "\n")

    def role(t):
        if not t or "/" in t or ".." in t:
            return ""                                            # an agent_type is a file name, never a path
        try:
            m = re.search(r"^Flow role:\s*(\w+)", open(os.path.join(agents_dir, t + ".md"), errors="ignore").read(), re.M)
            if m:
                return m.group(1).lower()
        except OSError:
            pass
        return DEFAULT_ROLE.get(ALIASES.get(t, t), "build" if re.search(r"engineer|sre|developer|implement|^builder", t) else "")

    AGM = {}

    def ag_mod():
        if "m" not in AGM:
            AGM["m"] = None
            try:
                import importlib, importlib.util
                root_ = os.path.join(os.path.realpath(WS), "shipmiracle")
                spec_ = importlib.util.spec_from_file_location("shipmiracle", os.path.join(root_, "__init__.py"), submodule_search_locations=[root_])
                pkg_ = importlib.util.module_from_spec(spec_); sys.modules["shipmiracle"] = pkg_; spec_.loader.exec_module(pkg_)
                AG = importlib.import_module("shipmiracle.agents")
                if not os.path.realpath(AG.__file__).startswith(os.path.realpath(root_) + "/"):
                    raise ImportError("shipmiracle.agents is not under the workspace Shipmiracle folder")
                AGM["m"] = AG
            except Exception:
                sys.modules.pop("shipmiracle", None); log_err()
        return AGM["m"]

    def role_info(t):
        c = role(t)
        if not UL[0] or not t or "/" in t or ".." in t:
            return c, c
        AG = ag_mod()
        if AG is None:
            return c, c
        try:
            r_ = AG.resolve(t, pd)
        except Exception:
            log_err()
            return c, c
        if r_ is None:
            if c in PRIV:
                log("role_untrusted", agent=t, claimed=c, effective="support", layer="none")
                return c, "support"
            return c, c
        if r_.claimed in PRIV and r_.effective != r_.claimed:
            log("role_untrusted", agent=t, claimed=r_.claimed, effective=r_.effective, layer=r_.layer)
        return r_.claimed, r_.effective

    def arole_info():
        roles = st.get("roles") if isinstance(st.get("roles"), dict) else {}
        key = sp(agent) + ":" + atype if sp(agent) else ""
        if key and key in roles:
            v_ = roles[key]
            return (str(v_[0]), str(v_[1])) if isinstance(v_, list) and len(v_) == 2 else (sp(v_), sp(v_))
        c_, e_ = role_info(atype)
        if key:
            roles[key] = c_ if c_ == e_ else [c_, e_]; st["roles"] = roles
            for k_ in list(roles)[:-40]:
                del roles[k_]
            try: save()
            except Exception: pass
        return c_, e_

    def arole():
        return arole_info()[1]

    if os.path.isdir(agents_dir) or gated_reg:
        if not st.get("team_seen"):
            st["team_seen"] = True
            try: save()
            except Exception: pass
    elif not st.get("team_missing_logged"):
        st["team_missing_logged"] = True; log("team_missing")
        try: save()
        except Exception: pass
    envs = [k_ for k_ in ("SHIPMIRACLE_FLOW_LEVEL", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "SHIPMIRACLE_WS", "SHIPMIRACLE_FLOW_CAPTURE", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_FLOW_VERDICT") if os.environ.get(k_)]
    if envs and not os.environ.get("SHIPMIRACLE_TEST") and not st.get("env_override_logged"):
        st["env_override_logged"] = True; log("gate_env_override", vars=envs)
        try: save()
        except Exception: pass

    def refuse(kind, msg):
        """Strict: refuse (at most twice per kind per turn). Warn level, or the third time: let it through with a note."""
        n = st.setdefault("refusals", {}).get(kind, 0)
        if level == "warn" or n >= 2:
            log(kind + ("_warned" if level == "warn" else "_capped"))
            st.setdefault("warnings", []).append(kind); save()
            note = f"TEAM FLOW ({'warn-only project' if level == 'warn' else 'third time, let through'}): {msg}"
            out({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": note}})
        st["refusals"][kind] = n + 1; log(kind); save()
        out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}})

    def refuse_many(items, on_done):
        """Stop only: ONE combined block for several kinds [(kind, msg)]. Each kind has its own 2-refusal cap; warn level or all kinds capped: a note."""
        refs = st.setdefault("refusals", {})
        live = [] if level == "warn" else [(k, m) for k, m in items if refs.get(k, 0) < 2]
        capped = [] if level == "warn" else [x for x in items if x not in live]
        for k, _ in items:
            extra = {"files": new_outside[:10]} if k == "outside_team" else (qa_extra if k in ("qa_failed", "qa_no_verdict") else {})
            if (k, _) in live:
                refs[k] = refs.get(k, 0) + 1; log(k, **extra)
            else:
                log(k + ("_warned" if level == "warn" else "_capped"), **extra); st.setdefault("warnings", []).append(k)
        on_done(); save()
        if live:
            reason = " ".join(m for _, m in live)
            if capped:
                reason += " (Note, third time so not enforced: " + " ".join(m for _, m in capped) + ")"
            out({"decision": "block", "reason": reason})
        out({"systemMessage": f"TEAM FLOW ({'warn-only project' if level == 'warn' else 'third time, let through'}): " + " ".join(m for _, m in items)})

    def who_for(r):
        return "builder-frontend" if re.search(r"\.(tsx?|jsx?|css|scss|html|vue|svelte|swift)$", r) else \
               "builder-ops" if re.search(r"(^|/)(\.github|deploy|infra|docker|Dockerfile|.*\.ya?ml$)", r) else \
               "builder" if re.search(r"\.(md|txt|docx)$", r, re.I) and not RECORD.match(r) else "builder-backend"

    def dirty():
        import subprocess  # SHIPMIRACLE-LAZY
        raw = subprocess.run(["git", "-C", pd, "status", "--porcelain", "-z", "-uall"], capture_output=True, timeout=5).stdout
        parts = raw.decode("utf-8", "surrogateescape").split("\0"); res = set(); i = 0
        while i < len(parts):
            e = parts[i]; i += 1
            if len(e) < 4:
                continue
            if e[0] in "RC" or e[1] in "RC":                     # rename/copy: the next NUL field is the old path
                i += 1
            res.add(e[3:])
        return res

    def agent_rule(path, tool, ti):
        path = sp(path)
        if not os.path.isabs(path):
            path = os.path.join(pd, path)
        if tool == "Write":
            text = sp(ti.get("content"))
        else:
            try: text = open(path, errors="ignore").read()
            except OSError: text = ""
            edits = [e for e in (ti.get("edits") or []) if isinstance(e, dict)] if tool == "MultiEdit" else [ti]
            text = apply_edits(text, edits)[0]
        why = []
        m = re.search(r"^model:\s*(\S+)", text, re.M)
        if not m or m.group(1) not in ("opus", "sonnet", "haiku"): why.append("set model: to opus, sonnet or haiku (not inherit)")
        if not re.search(r"^Model reason:\s*\S", text, re.M): why.append("add a 'Model reason: <one line>' line")
        if not re.search(r"^Flow role:\s*(plan|build|test|review|scope|design|route|support|report)\b", text, re.M): why.append("add 'Flow role: plan|build|test|review|scope|design|route|support" + ("|report'" if UL[0] else "'"))
        stem = os.path.basename(path)[:-3]
        t_ = text.lstrip("\ufeff"); m_ = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", t_, re.S); reg_ = m_.group(1) if m_ else t_    # P3 B1: strict name line only
        nl_ = [l_ for l_ in reg_.split("\n") if re.match(r"[ \t]*(?:\?[ \t]*)?['\"]?name['\"]?[ \t]*:", l_)]
        nm_ = re.fullmatch(r"name: (['\"]?)([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\1", nl_[0]) if len(nl_) == 1 else None
        odd_ = text.startswith("\ufeff") or (not m_ and nl_) or re.match(r"\s*\{", reg_) or re.search(r"^<<[ \t]*:", reg_, re.M) or any(c_ in reg_.replace("\r\n", "\n") for c_ in "\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")
        if nl_ and (not nm_ or odd_): why.append("the name line must be exactly one 'name: <kebab-name>' line (no quoted key, 'name :', comment, block scalar, duplicate, tab, CR, BOM)")
        elif nm_ and nm_.group(2) != stem: why.append(f"the file name must equal the frontmatter name (file {stem}, name: {nm_.group(2)})")
        if UL[0] and not os.path.exists(path) and not re.search(r"^overrides:", text, re.M) and (stem in ALIASES or stem in DEFAULT_ROLE or os.path.isfile(os.path.join(shipmiracle_home() or "/nonexistent", ".claude/agents", stem + ".md"))):
            why.append(f"an agent called {stem} already exists (master or user level): choose another name or add 'overrides: {stem}'")
        if why:
            log("agent_rule_refused", file=os.path.basename(path))
            out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
                 "This agent file breaks the model rule (CLAUDE.md, details: docs/standards/team.md): " + "; ".join(why) + ". Opus = decides or judges (design, plans, review, "
                 "security); Sonnet = produces (code, tests, following a plan) and is the default when unsure; Haiku = mechanical lookups only."}})
        log("agent_rule_ok", file=os.path.basename(path))
        if not agent:                                            # a checked agent file written by the main chat is known, not "outside the team"
            af = st.setdefault("agent_files", []); r_ = rel(path)
            if r_ not in af:
                af.append(r_)
            save()

    rel = lambda p: relto(os.path.realpath(p), pd) if p else ""
    inside = lambda r: r and not r.startswith("..") and not os.path.isabs(r)

    def strip_heredocs(c):
        """Cut heredoc bodies (the marker line with its redirect stays). Skipped over 20000 chars; at most 20 markers; linear per marker."""
        if len(c) > 20000:
            return c
        out_ = []; pos = 0; cnt = 0
        for m in re.finditer(r"<<(-?)\s*['\"]?(\w+)['\"]?[^\n]*", c):
            if m.start() < pos:
                continue
            cnt += 1
            if cnt > 20:
                break
            delim = m.group(2); dash = bool(m.group(1)); i_ = c.find("\n", m.end())
            while 0 <= i_ < len(c):
                i_ += 1; e = c.find("\n", i_); e = len(c) if e < 0 else e
                line = c[i_:e]
                if (line.lstrip("\t") if dash else line) == delim:
                    out_.append(c[pos:m.end()]); pos = e; break
                i_ = e if e < len(c) else -1
        out_.append(c[pos:])
        return "".join(out_)

    def bash_regex_hits(c, tam=None):
        c = strip_heredocs(c)                                    # heredoc bodies are data
        c = blank_quotes(c)                                      # so is text in quotes (commit messages)
        hits = re.findall(r"(?:\b(?:sed|perl)\s+-\w*i\S*\s+(?:-e\s+)?(?:'[^']*'|\"[^\"]*\"|\S+)\s+|>>?[!|]?\s*|\btee\s+(?:-a\s+)?)([^\s;&|<>]+)", c)
        res = []
        for h in list(dict.fromkeys(hits))[:500]:                # a huge command: look at the first 500 distinct targets only
            if not h or "$(" in h or "`" in h or h.startswith("&"):
                continue
            if h.startswith("$HOME/") or h.startswith("${HOME}/"):
                h = HOME + h[h.index("/"):]
            if h.startswith("~"):
                h = os.path.expanduser(h)
            if tam:
                if h.startswith("$") or h.startswith("!"):
                    if names_gate(h, (os.path.basename(STATE.rstrip("/")),)):
                        res.append(h)                            # a path we cannot resolve that names a gate folder: refuse
                elif tam(os.path.realpath(h if os.path.isabs(h) else os.path.join(pd, h)), "write"):
                    res.append(h)
                continue
            if h.startswith(("$", "/dev/", "/tmp/", "/private/tmp/", "$TMP")):
                continue
            r_ = rel(os.path.join(pd, h) if not os.path.isabs(h) else h)
            if inside(r_) and not RECORD.match(r_) and r_ != ".git" and not r_.startswith(".git/"):
                res.append(h)
        return res

    gate_files = [os.path.join(WS, "config/flow.json"), os.path.join(HOME, ".claude/settings.json"), os.path.join(HOME, ".claude/settings.local.json"),
                  os.path.join(pd, ".claude/settings.json"), os.path.join(pd, ".claude/settings.local.json"), os.path.join(WS, "bin/shipm-chat"), os.path.join(WS, "hooks/shipm-hook"),
                  os.path.join(pd, ".claude/test-command")]      # P4 M4: the Stop hook runs this file through bash outside the gate
    gate_dirs = [STATE, os.path.join(WS, "hooks"), os.path.join(pd, ".claude/hooks"), os.path.join(HOME, ".claude/hooks"),
                 os.path.join(HOME, ".claude/agents"), os.path.join(HOME, ".config/shipmiracle"), os.path.join(WS, "shipmiracle"),
                 os.path.join(WS, "shipmiracle/hooks"), os.path.join(STATE, "v1/pyc"),
                 os.path.join(HOME, ".local/share/shipmiracle")]    # L4: the engine link folder (FIXED_PREFIX) a hook command may run through; P4 T8: dispatcher modules and the bytecode cache (inside the dirs above, listed so a moved STATE/WS cannot drop them)
    for x_ in (os.path.join(shipmiracle_home(), ".claude/agents") if shipmiracle_home() else "", shipmiracle_cfg_dir()):
        if x_ and x_ not in gate_dirs:
            gate_dirs.append(x_)
    xdg_ = os.environ.get("XDG_CONFIG_HOME") or ""
    for cfg_ in [os.path.join(HOME, ".config")] + ([xdg_] if xdg_.startswith("/") else []):
        for sub_ in ("systemd", "autostart", "environment.d"):     # D9 M1: user units, autostart entries and session environment run code outside this chat (also under an absolute XDG_CONFIG_HOME)
            if os.path.join(cfg_, sub_) not in gate_dirs:
                gate_dirs.append(os.path.join(cfg_, sub_))
    roots_ = [pd] + ([rpd] if rpd != pd else [])                 # P6 T3: a worktree is guarded by its own .claude/.shipmiracle and by the main project's
    if rpd != pd:
        gate_files += [os.path.join(rpd, ".claude/settings.json"), os.path.join(rpd, ".claude/settings.local.json"), os.path.join(rpd, ".claude/test-command")]
        gate_dirs.append(os.path.join(rpd, ".claude/hooks"))
    cc_ = os.environ.get("CLAUDE_CONFIG_DIR") or ""            # D14 #7: a moved Claude settings folder is guarded like ~/.claude
    if cc_.startswith("/") and os.path.realpath(cc_) != os.path.realpath(os.path.join(HOME, ".claude")):
        gate_files += [os.path.join(cc_, "settings.json"), os.path.join(cc_, "settings.local.json")]
        gate_dirs.append(os.path.join(cc_, "hooks"))

    def hp_dirs(root_):
        """The hooks folders of a project: .git/hooks of the common git dir and the folder core.hooksPath names (read from the git config; not section-aware, any hookspath line counts; unreadable -> <root>/hooks)."""
        res_ = []; g_ = os.path.join(root_, ".git"); cfg_ = os.path.join(g_, "config")
        try:
            if os.path.isfile(g_):
                gd_ = open(g_, encoding="utf-8", errors="replace").readline().strip()[7:].strip(); gd_ = gd_ if os.path.isabs(gd_) else os.path.join(root_, gd_)
                cf_ = os.path.join(gd_, "commondir"); cd_ = open(cf_, encoding="utf-8", errors="replace").readline().strip() if os.path.exists(cf_) else "."
                cd_ = cd_ if os.path.isabs(cd_) else os.path.join(gd_, cd_); cfg_ = os.path.join(cd_, "config"); res_.append(os.path.join(cd_, "hooks"))
            if os.path.exists(cfg_):
                m_ = re.search(r"(?mi)^\s*hookspath\s*=\s*(.+?)\s*$", open(cfg_, encoding="utf-8", errors="replace").read())
                if m_:
                    hp_ = os.path.expanduser(m_.group(1).strip().strip('"')); res_.append(hp_ if os.path.isabs(hp_) else os.path.join(root_, hp_))
        except Exception:
            res_.append(os.path.join(root_, "hooks"))
        return res_
    pers_files_ = []
    for pf_ in PERSIST_HOME_FILES:                               # D14 M1/#2: shell start-up files, ~/.gitconfig, ssh config, editor user settings ...: the same table as the hard stop
        pers_files_ += [pfold(os.path.realpath(os.path.join(HOME, pf_))), pfold(os.path.normpath(os.path.join(HOME, pf_)))]
    pers_dirs_ = []
    for pd_ in [os.path.join(HOME, x_) for x_ in PERSIST_HOME_DIRS] + list(PERSIST_ABS_DIRS) + [h_ for r3_ in roots_ for h_ in hp_dirs(r3_)]:
        pers_dirs_ += [pfold(os.path.realpath(pd_)).rstrip("/"), pfold(os.path.normpath(pd_)).rstrip("/")]
    parea_ = [pfold(os.path.realpath(x_)).rstrip("/") for x_ in [DEV] + roots_]       # every project below the projects folder, and this one wherever it is
    pany_ = re.compile(r"(?:^|/)(?:%s)$|(?:^|/)(?:%s)(?:/|$)|(?:%s)$" % ("|".join(re.escape(x_) for x_ in PERSIST_PROJECT_FILES if x_ not in PERSIST_SETTINGS_FILES),
                                                                      "|".join(re.escape(x_) for x_ in PERSIST_PROJECT_DIRS), "|".join(re.escape(x_) for x_ in PERSIST_PROJECT_SUFFIXES)))
    pset_ = re.compile(r"(?:^|/)(?:%s)$" % "|".join(re.escape(x_) for x_ in PERSIST_SETTINGS_FILES))

    SHAD = {}

    def shadow_top(top):
        """True when <WS>/<top> could shadow a standard-library module for the hook: named like one, or not tracked in git (or git unusable)."""
        if "t" not in SHAD:
            names = set(sys.builtin_module_names); tracked = None
            try: names.update(pfold(n_.split(".", 1)[0]) for n_ in os.listdir(os.path.dirname(os.__file__)))
            except OSError: pass
            try:
                import subprocess  # SHIPMIRACLE-LAZY
                r_ = subprocess.run(["git", "-C", WS, "ls-files", "-z"], capture_output=True, timeout=5)
                if r_.returncode == 0: tracked = {pfold(x_.split("/")[0]) for x_ in r_.stdout.decode("utf-8", "replace").split("\0") if x_}
            except Exception: pass
            SHAD["t"] = (names, tracked)
        names, tracked = SHAD["t"]
        return top in names or tracked is None or top not in tracked

    def tamper_path(ap, bash=False, remove=False):
        """True for the files that control the gate (real path, compared without regard to case on macOS). The team folder (<project>/.claude/agents)
        and <project>/.claude are protected too: Edit/Write of an agent .md file is left to the model rule, everything else (Bash, removal) is refused.
        remove=True (rm, rmdir, mv sources): the parent folders of every gate path count as well.
        L4: the path is judged three ways: fully resolved, resolved folder + the entry's own name (a link is judged as a link, not by its target), and as written
        (so a name under a gate folder counts even when a link on the way points elsewhere)."""
        rp_ = os.path.realpath(ap)
        cands_ = [rp_]
        if os.path.basename(ap):
            for c_ in (os.path.join(os.path.realpath(os.path.dirname(ap)), os.path.basename(ap)), os.path.normpath(os.path.abspath(ap))):
                if c_ not in cands_:
                    cands_.append(c_)
        return any(tamper_one(c_, bash, remove) for c_ in cands_)

    SETC = [None]                                                # what the current call writes: ("file", tool, tool_input) or ("bash", command); read by settings_bad
    WHY = [None]                                                 # "persist" when the last refusal came from the persistence table (its own sentence)

    def settings_bad(rp):
        try:
            return settings_bad_(rp)
        except Exception:
            return True                                          # fail closed: a write that cannot be judged is refused

    def settings_bad_(rp):
        """D14 M1/M-1: True when the current call would put a code-running SETTING (by its name: a path, an executable, a shell, a task, an environment, a home ...) into a project's .vscode/settings.json,
        or cannot be judged. Every Bash write is refused (a command can build the content from fragments). A plain editor setting passes; nested values (exclude globs ...) are data."""
        c_ = SETC[0]
        if not c_ or c_[0] != "file":
            return True
        before_ = read_text(rp) if os.path.exists(rp) else ""
        tool_, ti_ = c_[1], c_[2]
        if tool_ == "Write":
            after_ = sp(ti_.get("content"))
        elif tool_ in ("Edit", "MultiEdit") and before_ is not None:
            edits_ = [ti_] if tool_ == "Edit" else [e_ for e_ in (ti_.get("edits") or []) if isinstance(e_, dict)]
            after_, ok_ = apply_edits(before_, edits_)
            if not ok_:
                return True                                      # an edit this exact-match check cannot apply (Claude Code also matches after straightening curly quotes) is not judged: refused
        else:
            return True
        bflat_ = settings_flat(before_) or {}
        aflat_ = settings_flat(after_)
        if aflat_ is None:
            return any(x_ in after_.lower() for x_ in PERSIST_SETTINGS_RISKY)
        return any(settings_risky_key(p_) and bflat_.get(p_) != v_ for p_, v_ in aflat_.items())

    def persist_hit(k, rp, remove):
        """D14: the persistence table (home files and folders, hooks folders, a project's .envrc / tasks.json / .git/config / .githooks ... at any depth below the projects folder, settings by content)."""
        if k in pers_files_ or any(k == d_ or k.startswith(d_ + "/") for d_ in pers_dirs_):
            return True
        if any(k == a_ or k.startswith(a_ + "/") for a_ in parea_):
            if pany_.search(k) or (pset_.search(k) and settings_bad(rp)):
                return True
        return remove and any(g_.startswith(k.rstrip("/") + "/") for g_ in pers_files_ + pers_dirs_)

    def tamper_one(rp, bash=False, remove=False):
        if tamper_gen(rp, bash, remove):
            return True
        if persist_hit(pfold(rp), rp, remove):
            WHY[0] = "persist"
            return True
        return False

    def tamper_gen(rp, bash=False, remove=False):
        k = pfold(rp)
        for root in gate_dirs:
            for rk in {pfold(os.path.realpath(root)).rstrip("/"), pfold(os.path.normpath(root)).rstrip("/")}:     # resolved and as-built (HOME itself may sit behind a link: /var -> /private/var)
                if k == rk or k.startswith(rk + "/"):
                    return True
        gf = [pfold(os.path.realpath(x)) for x in gate_files] + [pfold(os.path.normpath(x)) for x in gate_files]
        if k in gf:
            return True
        wk = pfold(os.path.realpath(WS)).rstrip("/")
        if k.endswith((".py", ".pyc", ".so", ".pth")) and os.path.dirname(k) == wk:
            return True                                          # <WS>/*.py: a top-level module would shadow the standard library for the hook
        if k.startswith(wk + "/") and (k.count("/") > wk.count("/") + 1 or os.path.isdir(k)) and shadow_top(k[len(wk) + 1:].split("/", 1)[0]):
            return True                                          # P3 R4: <WS>/<folder>/ untracked or named like a stdlib module is a package that could shadow it
        if re.match("(?:" + "|".join(re.escape(h_) for h_ in {pfold(HOME), pfold(os.path.realpath(HOME))}) + r")/(library/python/[^/]+/lib/python|\.local/lib/python[^/]*)/site-packages(/|$)", k, re.I):
            WHY[0] = "persist"                                   # D14 m1/m2: said as a persistence file; HOME compared as written AND resolved (a symlinked home)
            return True                                          # the user site-packages (and any *.pth in it) load code into every python start
        ags = []
        for r0_ in roots_:
            cl = pfold(os.path.realpath(os.path.join(r0_, ".claude"))); ag = cl + "/agents"; ags.append(ag)
            if k == cl or k == ag:
                return True
            aw = pfold(os.path.realpath(os.path.join(r0_, ".shipmiracle")))    # P5 T4: the playbook and its rendered record; only the owner's CLI and the engine write them
            if k == aw or k.startswith(aw + "/"):
                return True
            if k.startswith(ag + "/"):
                return bash or remove or not re.match(r"^[^/]+\.md$", k[len(ag) + 1:])
            rp_ = pfold(os.path.realpath(os.path.join(r0_, "docs/reports")))     # P5 sec M3: the reports are written by the engine, never by the team
            if k == rp_ or k.startswith(rp_ + "/"):
                return True
            ags.append(rp_)
        if remove:
            for g in gf + [pfold(os.path.realpath(x)).rstrip("/") for x in gate_dirs] + ags:
                if g.startswith(k.rstrip("/") + "/"):
                    return True
        return False

    def admin_hit(c):
        segs_ = long_segs(c)
        if re.search(r"(?:^|[^\w])(?:charter|allow)\s*:", c[:200000], re.I) and any(w_ and os.path.basename(w_[0]) == "claude" for _a, _u, w_ in segs_):
            return True                                          # P6 T3 (C7): the prompt can arrive on stdin or in a heredoc
        if re.search(r"\bSHIPMIRACLE_(?:TEST|CONFIG|STATE|WS|DEV)\s*=", c[:200000]) and any(admin_seg(list(a_) + ["SHIPMIRACLE_TEST"], u_, w_) for a_, u_, w_ in segs_):
            return True                                          # P5 sec H1: a chat that points Shipmiracle at another config/state (same call, env, export) is not the owner
        return any(admin_seg(*g_) for g_ in segs_) or (bool(re.search(r"(?<![A-Za-z0-9])(?i:shipm)(?![A-Za-z0-9])|shipmiracle|config|agents|registry", c) or re.search(r"(?<![A-Za-z0-9])shipm(?![A-Za-z0-9])|shipmiracle|config|agents|registry", _fold(_ansi_c(c)))) and unknown_cmd(c, segs_))

    RAW = [""]

    def raw_hit(c):
        RAW[0] = raw_admin(c, long_segs(c))
        return bool(RAW[0])

    def tamper_check(agent_rule_on=False):
        """Refuse (any level but off, no bypass, no cap) writes to the files that control the gate. Main chat always; agents too (nobody but the owner
        writes gate files), unless the HOOK process has SHIPMIRACLE_FLOW_TAMPER_OK=1."""
        hit = None; adm = False
        tam = lambda ap, kind="write": tamper_path(ap, True, kind == "remove")
        WHY[0] = None
        SETC[0] = ("file", tool, ti) if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit") else ("bash", sp(ti.get("command")))
        if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
            p_ = sp(ti.get("file_path")) or sp(ti.get("notebook_path"))
            if p_ and tamper_path(p_ if os.path.isabs(p_) else os.path.join(pd, p_)):
                hit = p_
        elif tool == "Bash":
            c = sp(ti.get("command"))
            try:
                if len(c) > BIG_CMD:
                    raise ValueError("command too long for the parsed check")
                bad = bash_targets(c, sp(d.get("cwd")) or pd, pd, tam, (os.path.basename(STATE.rstrip("/")),))
            except Exception:
                try:
                    bad = bash_regex_hits(c, tam)
                except Exception:
                    bad = []
            hit = bad[0] if bad else None
            if not hit and (admin_hit(c) or raw_hit(c)):
                hit = "shipm admin command"; adm = True
            if not hit:
                try:
                    pb_ = any(os.path.isfile(os.path.join(r0_, ".shipmiracle/playbook.json")) for r0_ in roots_)
                    if any(git_shipmiracle_seg(w_, pb_) for _a, _u, w_ in long_segs(c)):
                        hit = ".shipmiracle/playbook.json"
                except Exception:
                    pass
            if not hit:
                try:
                    if git_persist_hit(long_segs(c), tam, sp(d.get("cwd")) or pd):
                        hit = "git config / husky"; WHY[0] = "persist"
                except Exception:
                    if re.search(r"(?i)\bgit\b[^\n;|&]*\bconfig\b[^\n;|&]*(?:hookspath|fsmonitor|sshcommand|core\.pager|core\.editor|askpass|credential\.|insteadof|include\.path)|\bhusky\b", c):
                        hit = "git config / husky"; WHY[0] = "persist"
        parent = bool(hit) and str(hit).endswith(" [PARENT]")
        if parent:
            hit = str(hit)[:-9]
        if hit:
            log("gate_tamper", tool=tool, file=os.path.basename(str(hit)), **({"agent": atype} if agent else {}))
            out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
                 ((RAW[0] or "This command changes the team or the gate settings; the owner runs it in a terminal.") if adm else (PERSIST_TEXT if WHY[0] == "persist" else "These files control the team-flow check; ask the owner to change them."))
                 + (" This would delete .claude, which holds the team-flow check." if parent else "")}})

    def is_test_path(r_):
        try:
            tp = (reg_entry(rpd) or {}).get("test_paths") if UL[0] else None
        except Exception:
            tp = None
        gl_ = [g_ for g_ in tp if isinstance(g_, str)] if isinstance(tp, list) and tp else list(TEST_PATHS_DEFAULT)
        return any(glob_re(g_).match(r_) for g_ in gl_)

    def readonly_check():
        if UL[0]:
            c_, e_ = arole_info()
            ro = c_ in READ_ONLY or e_ in READ_ONLY
        else:
            c_ = e_ = role(atype)                                # no state write on this hot path
            ro = e_ == "review"                                  # legacy layout: only test and review roles are held to their job (write-the-source holes: a QA or reviewer must not fix and then approve its own fix)
        tst = not ro and "test" in (c_, e_)
        if not (ro or tst):
            return
        troots = [fold(os.path.realpath(x_)).rstrip("/") for x_ in ("/tmp", "/private/tmp", os.environ.get("TMPDIR") or "") if x_]
        globs = []
        if tst:
            tp = None
            try:
                tp = (reg_entry(rpd) or {}).get("test_paths") if UL[0] else None
            except Exception:
                tp = None
            globs = [g_ for g_ in tp if isinstance(g_, str)] if isinstance(tp, list) and tp else list(TEST_PATHS_DEFAULT)
            gre = [glob_re(g_) for g_ in globs]

        def allowed(ap, kind="write"):
            k_ = fold(os.path.realpath(ap))
            if k_.startswith("/dev/") or any(k_ == t_ or k_.startswith(t_ + "/") for t_ in troots):
                return True
            r_ = relto(os.path.realpath(ap), pd)
            if inside(r_) and RECORD.match(r_) and (not UL[0] or e_ in ("review", "test")):
                return True                                      # record files (plans, STATUS ...) are written by every role
            if tst:
                return inside(r_) and any(g_.match(r_) for g_ in gre)
            return False

        def refuse_ro(shown, cmd=False):
            if tst:
                msg = f"`{atype}` may not " + (f"run `{shown}`" if cmd else f"change `{shown}`") + f": tests may change only under: `{', '.join(globs)}`. Report it; a builder makes the change."
            elif cmd:
                msg = f"`{atype}` is a read-only role: `{shown}` changes the repository or the installed packages. Report it; a builder makes the change."
            else:
                msg = f"`{atype}` is a read-only role: it may not change `{shown}`. Report it; a builder makes the change."
            if level == "warn":
                log("readonly_refused_warned", agent=atype, tool=tool, file=os.path.basename(str(shown))[:80])
                NOTES.append("TEAM FLOW (warn-only project): " + msg)
                return
            log("readonly_refused", agent=atype, tool=tool, file=os.path.basename(str(shown))[:80])
            out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}})

        if tool == "Bash":
            c = sp(ti.get("command"))
            okp = lambda x_: allowed(x_ if os.path.isabs(x_) else os.path.join(pd, x_))
            if ro and unknown_cmd(c, long_segs(c)):
                return refuse_ro("a command named by a variable, glob or substitution", True)       # P3 R6: `$g commit` hides what runs
            for a_, u_, w_ in long_segs(c):
                m_ = mut_seg(w_, okp)
                if m_:
                    return refuse_ro(m_, True)
            tam = lambda ap, kind="write": not allowed(ap, kind)
            try:
                if len(c) > BIG_CMD:
                    raise ValueError("command too long for the parsed check")
                bad = bash_targets(c, sp(d.get("cwd")) or pd, pd, tam)
            except Exception:
                try:
                    bad = bash_regex_hits(c, tam)
                except Exception:
                    bad = []
            if bad:
                refuse_ro(bad[0])
            return
        p_ = sp(ti.get("file_path")) or sp(ti.get("notebook_path"))
        if p_:
            ap_ = p_ if os.path.isabs(p_) else os.path.join(pd, p_)
            if not allowed(ap_):
                r_ = rel(p_)
                refuse_ro(r_ if inside(r_) else p_)

    def general_purpose_check():
        what = None
        who_ = "general-purpose" if atype == "general-purpose" else f"`{atype}` (role {arole() or 'unknown'})"
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            p_ = sp(ti.get("file_path")) or sp(ti.get("notebook_path"))
            r_ = rel(p_)
            if p_ and inside(r_) and not RECORD.match(r_) and r_ != ".git" and not r_.startswith(".git/"):
                what = r_
        elif tool == "Bash":
            c = sp(ti.get("command"))
            try:
                if len(c) > BIG_CMD:
                    raise ValueError("command too long for the parsed check")
                bad = bash_targets(c, sp(d.get("cwd")) or pd, pd)
            except Exception:
                try:
                    bad = bash_regex_hits(c)
                except Exception:
                    bad = []
            what = bad[0] if bad else None
        if what:
            w_ = who_for(str(what))
            refuse("general_purpose_build", f"Builds go to a named builder: use {w_} (Agent tool, subagent_type {w_}). {who_} may read and research only.")

    # ---- G9 team gate: a build step needs a seat in the project's Team table (docs/SKILLS.md, read by shipmiracle.team); a review verdict from a non-member is not counted.
    # No table = no rule. A table that was fine earlier in this session and is now missing or unreadable, or whose markers are damaged, lets only the master agents work.
    # Verifier and reviewer are always allowed; general-purpose keeps its own refusal; the project's flow level applies; "just do it" lifts it for the turn. A discipline gate, not a boundary against the lead.
    TEAMC = {}
    TEAM_FREE = ("Explore", "Plan", "claude-code-guide", "statusline-setup", "general-purpose")
    TEAM_SUB = {"team": ("add",), "borrow": ("record",)}         # subagent-only table for admin_seg: any later word of the shipm command counts, so option values cannot hide it
    TEAM_NAMES = (fold("docs/SKILLS.md"), fold(".agents/borrowed.json"))
    TEAM_DIRS = (fold("docs"), fold(".agents"))
    TEAM_LABEL = "the command `shipm team add` / `shipm borrow record`"
    class TeamRx:
        """A pattern compiled on first use: the main chat never pays for these."""
        def __init__(self, p, fl=0):
            self.p = p; self.fl = fl
        def search(self, t):
            return re.search(self.p, t, self.fl)

    TEAM_WORD = TeamRx(r"skills\.md|borrowed\.json", re.I)
    TEAM_VERB = TeamRx(r"(?<![\w.-])(?:rm|rmdir|unlink|mv|cp|install|rsync|ln|sed|perl|tee|dd|truncate|shred|chmod|chown|chgrp|chattr|setfacl|xattr|eval|sh|bash|zsh|dash|source|xargs|python[0-9.]*|node|ruby|awk|ed|ex|vi|vim|nano|emacs)(?![\w-])|-delete\b|-exec\b|-fprint|>>?\s*[\"']?\$")
    TEAM_DIRVERB = TeamRx(r"(?<![\w.-])(?:chmod|chown|chgrp|chattr|setfacl|xattr|ln|mv|rm|rmdir|unlink|truncate|shred)(?![\w-])")

    def team_mod():
        """The shipmiracle.team module of the workspace (loaded the way ag_mod loads agents), or None. A load failure is an event and a note, once per session; the rule is then off."""
        if "m" not in TEAMC:
            TEAMC["m"] = None
            try:
                if ag_mod() is not None:
                    import importlib
                    tm_ = importlib.import_module("shipmiracle.team")
                    if not os.path.realpath(tm_.__file__).startswith(os.path.realpath(os.path.join(WS, "shipmiracle")) + "/"):
                        raise ImportError("shipmiracle.team is not under the workspace Shipmiracle folder")
                    TEAMC["m"] = tm_
            except Exception:
                log_err()
            if TEAMC["m"] is None and not st.get("team_reader_logged"):
                st["team_reader_logged"] = True; log("team_reader_unavailable")
                NOTES.append("TEAM FLOW: the Team table could not be read (the Shipmiracle reader did not load), so the team rule is OFF for this session. Run `shipm doctor`.")
        return TEAMC["m"]

    def team_sig():
        """A cheap stamp of docs/ and docs/SKILLS.md (two lstat calls): the key of the parsed-table cache and of the allow decisions. None = no file."""
        if "sg" not in TEAMC:
            try:
                a_ = os.lstat(os.path.join(pd, "docs")); b_ = os.lstat(os.path.join(pd, "docs", "SKILLS.md"))
                TEAMC["sg"] = [a_.st_ino, a_.st_mode, b_.st_ino, b_.st_mode, b_.st_size, b_.st_mtime_ns]
            except FileNotFoundError:
                TEAMC["sg"] = None
            except OSError:
                TEAMC["sg"] = [-1]
        return TEAMC["sg"]

    def team_table():
        """(state, rows) of <checkout>/docs/SKILLS.md: ok | none | damaged | unreadable | unavailable (the reader could not load). The parse is cached in the session by team_sig."""
        if "t" not in TEAMC:
            sig_ = team_sig()
            TEAMC["t"] = ("none", [])
            if sig_ is None:
                return TEAMC["t"]
            c_ = st.get("team_tab")
            if isinstance(c_, dict) and c_.get("sig") == sig_ and sig_ != [-1] and isinstance(c_.get("rows"), list):
                TEAMC["t"] = (str(c_.get("state")), [{"role": str(r_[0]), "agent": str(r_[1])} for r_ in c_["rows"] if isinstance(r_, list) and len(r_) == 2])
                return TEAMC["t"]
            tm_ = team_mod()
            TEAMC["t"] = ("unavailable", [])
            if tm_ is not None:
                try:
                    t_ = tm_.load(pd)
                    TEAMC["t"] = (t_.state, list(t_.rows))
                    if sig_ != [-1]:
                        st["team_tab"] = {"sig": sig_, "state": t_.state, "rows": [[r_["role"], r_["agent"]] for r_ in t_.rows]}
                except Exception:
                    log_err(); TEAMC["t"] = ("unreadable", [])   # fail closed
        return TEAMC["t"]

    def team_head():
        """1 when HEAD's docs/SKILLS.md holds a Team table (a table once existed), 0 when git says there is none; 1 when git cannot say (fail closed). Asked once per session."""
        if "team_head" in st:
            return st["team_head"]
        v_ = 1
        try:
            import subprocess  # SHIPMIRACLE-LAZY
            r_ = subprocess.run(["git", "-C", pd, "show", "HEAD:docs/SKILLS.md"], capture_output=True, timeout=3)
            if r_.returncode == 0:
                txt_ = r_.stdout[:65536].decode("utf-8", "replace")
                tm_ = team_mod()
                v_ = (1 if tm_.parse_text(txt_).state == "ok" else 0) if tm_ is not None else (1 if "<!-- team:begin -->" in txt_ else 0)
            elif re.search(rb"does not exist|exists on disk, but not in|invalid object name|unknown revision|bad revision|not a git repository|ambiguous argument|bad object", r_.stderr):
                v_ = 0
        except Exception:
            v_ = 1
        st["team_head"] = v_
        return v_

    def team_who(rows):
        for r_ in rows:
            if r_.get("role") == "build":
                return r_["agent"]
        return rows[0]["agent"] if rows else "a builder"

    def team_gap(kind):
        """None = this agent may work (build) / its verdict counts (review); else the sentence that refuses it. A member of a readable table is cached per agent id and type,
        valid while docs/SKILLS.md is unchanged (team_sig): a cached call does no table read at all."""
        norm = ALIASES.get(atype, atype)
        if not atype or atype in TEAM_FREE or (norm in ("verifier", "reviewer") and (kind == "review" or arole() in ("test", "review"))):
            return None
        key = (sp(agent) + ":" + atype + ":" + kind) if sp(agent) else ""
        cache = st.get("team") if isinstance(st.get("team"), dict) else {}
        sig_ = team_sig()
        if key and sig_ is not None and cache.get(key) == sig_:
            return None
        state_, rows_ = team_table()
        msg = None; ok_member = False
        if state_ == "ok":
            if not st.get("team_ok"):
                st["team_ok"] = True
            if norm in {r_["agent"] for r_ in rows_}:
                ok_member = True
            else:
                msg = (f"`{atype}` is not on this project's team (docs/SKILLS.md, Team table): only team members build or review here. If it should be, run "
                       f"`shipm team add {atype} --role {'build' if kind == 'build' else 'review'} --why \"...\"` and start it again; otherwise hand the work to {team_who(rows_)}.")
        elif state_ != "unavailable" and (state_ in ("damaged", "unreadable") or st.get("team_ok") or team_head()):
            if norm not in ALIASES and norm not in DEFAULT_ROLE:
                ev_ = "team_table_damaged" if state_ == "damaged" else "team_table_unreadable"
                lg_ = st.get("team_logged") if isinstance(st.get("team_logged"), list) else []
                if ev_ not in lg_:
                    st["team_logged"] = lg_ + [ev_]; log(ev_, state=state_)
                msg = (f"`{atype}` may not {'build' if kind == 'build' else 'review'} here right now: this project's Team table (docs/SKILLS.md) is {'missing' if state_ == 'none' else state_} "
                       "(a table exists in this project), so only the master agents work until the lead repairs it (`shipm team check`).")
        if ok_member and key and sig_ is not None:
            cache[key] = sig_; st["team"] = cache
            for k_ in list(cache)[:-40]:
                del cache[k_]
        return msg

    def team_build_check():
        r_ = arole()
        if r_ not in ("build", ""):                              # every other role is judged like a builder too, except where the read-only rule really holds (user-level layout) and record files
            if UL[0] and (r_ in READ_ONLY or r_ == "test"):
                return                                           # read-only roles cannot write; test roles write only test paths (readonly_check)
            if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and RECORD.match(rel(sp(ti.get("file_path")) or sp(ti.get("notebook_path")))):
                return                                           # record files (plans, STATUS ...) are written by every role
        msg = team_gap("build")
        if msg is None:
            if TEAMC.get("t", ("",))[0] == "none" and not st.get("team_ok") and not st.get("team_note") and atype not in TEAM_FREE and not team_head():
                st["team_note"] = True; log("team_table_missing")
                NOTES.append("TEAM FLOW: No Team table yet: record the team with `shipm team add AGENT --role build --why \"...\"` (docs/SKILLS.md) before the build stage.")
            if "t" in TEAMC:
                try: save()                                      # a fresh decision, parse or note is kept for the next call; a cached call changed nothing
                except Exception: pass
            return
        if st.get("bypass"):
            log("team_bypass", agent=atype); return
        if level == "warn":
            log("team_member_required_warned", agent=atype); NOTES.append("TEAM FLOW (warn-only project): " + msg)
            return
        log("team_member_required", agent=atype)                 # strict means refused: no cap (the message says how to proceed), nothing shared between agents
        try: save()
        except Exception: pass
        out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}})

    def team_review_ignored():
        msg = team_gap("review")
        if msg is None:
            return False
        if st.get("bypass"):
            log("team_bypass", agent=atype); return False
        if level == "warn":
            log("team_review_warned", agent=atype); NOTES.append("TEAM FLOW (warn-only project): the review verdict of " + msg)
            return False
        log("team_review_ignored", agent=atype)
        NOTES.append("TEAM FLOW: the review verdict of `" + atype + "` is not counted: " + msg)
        return True

    def team_rels(ap):
        for c_ in dict.fromkeys((os.path.realpath(ap), os.path.join(os.path.realpath(os.path.dirname(ap)), os.path.basename(ap)), os.path.normpath(os.path.abspath(ap)))):
            yield fold(relto(c_, pd))

    def team_file(ap, kind="write", cmd=""):
        """True for the table and the borrow record (a glob that can match them too), and for the folders docs/ and .agents/ themselves when a command removes, moves,
        links, chmods or copies into them in a way that can reach the table (it names them, uses a glob or a variable, or is a permission/link/move/remove verb)."""
        for r_ in team_rels(ap):
            if r_ in TEAM_NAMES:
                return True
            if re.search(r"[*?\[]", r_) and any(glob_re(r_).fullmatch(n_) for n_ in TEAM_NAMES):
                return True
            if r_ in TEAM_DIRS and cmd and (kind == "remove" or TEAM_DIRVERB.search(cmd) or re.search(r"skills\.md|borrowed\.json|[*?\[$`]", cmd, re.I)):
                return True
        return False

    def team_git(w):
        """A git command that can rewrite the table or the record: it names them (or docs / .agents), is a whole-tree form (checkout ., restore ., reset --hard, stash, clean), or applies a patch naming them."""
        if not w or os.path.basename(w[0]) != "git":
            return False
        r_ = w[1:]; i_ = 0
        while i_ < len(r_):
            if r_[i_] in ("-C", "--git-dir", "--work-tree", "-c", "--namespace") and i_ + 1 < len(r_):
                i_ += 2
            elif r_[i_].startswith("-"):
                i_ += 1
            else:
                break
        if i_ >= len(r_) or r_[i_] not in GIT_SHIPMIRACLE_SUBS:
            return False
        rest_ = r_[i_ + 1:]
        if any(TEAM_WORD.search(x_) or x_.rstrip("/") in ("docs", ".agents") or fold(x_.rstrip("/")) in TEAM_DIRS for x_ in rest_):
            return True
        if r_[i_] in ("apply", "am"):
            for x_ in [x_ for x_ in rest_ if not x_.startswith("-")][:5]:
                try:
                    if re.search(r"docs/SKILLS\.md|\.agents/borrowed\.json", open(x_, "rb").read(1000000).decode("utf-8", "replace"), re.I):
                        return True
                except OSError:
                    pass
        sub_ = r_[i_]; pos_ = [x_ for x_ in rest_ if not x_.startswith("-")]
        if sub_ in ("merge", "pull", "rebase", "cherry-pick", "revert", "am", "apply"):
            return True                                          # rewrites the tree: a subagent does not
        if sub_ in ("checkout", "switch") and "--" not in rest_ and pos_ and not any(x_ in ("-b", "-B", "-c", "-C", "--orphan", "--detach", "-d") for x_ in rest_):
            return True                                          # git checkout BRANCH
        return git_shipmiracle_seg(w, True)

    TEAM_PLUMB = frozenset(("update-index", "checkout-index", "read-tree", "unpack-trees", "filter-branch", "replace", "fast-import", "symbolic-ref"))

    def team_bulk(w):
        """Folder-level overwrites of the project tree: cp -r / rsync -a / ditto into the project or docs / .agents, tar -x and unzip into them; also git plumbing that rewrites the tree."""
        if not w:
            return False
        n_ = _cmd_name(w[0]); a_ = w[1:]; cw_ = sp(d.get("cwd")) or pd
        into = lambda x_: bool(x_) and "$" not in x_ and any(r_ in (".", "") or r_ in TEAM_DIRS for r_ in team_rels(x_ if os.path.isabs(x_) else os.path.join(cw_, x_)))
        if n_ == "git":
            i_ = 0
            while i_ < len(a_):
                if a_[i_] in ("-C", "--git-dir", "--work-tree", "-c", "--namespace") and i_ + 1 < len(a_):
                    i_ += 2
                elif a_[i_].startswith("-"):
                    i_ += 1
                else:
                    break
            return i_ < len(a_) and a_[i_] in TEAM_PLUMB
        pos_ = [x_ for x_ in a_ if not x_.startswith("-")]
        if n_ in ("cp", "rsync", "ditto", "install", "mv"):
            rec_ = any(x_ in ("-r", "-R", "-a", "--recursive", "--archive") or (x_.startswith("-") and not x_.startswith("--") and re.search(r"[rRa]", x_)) for x_ in a_)
            dest_ = pos_[-1] if len(pos_) > 1 else ""
            for k_, x_ in enumerate(a_):
                if x_ in ("-t", "--target-directory") and k_ + 1 < len(a_):
                    dest_ = a_[k_ + 1]
            return (rec_ or n_ in ("install", "mv")) and into(dest_) and (rec_ or any(x_.endswith("/") or x_ == "." for x_ in pos_[:-1]))
        if n_ in ("tar", "bsdtar", "gtar"):
            ext_ = any(x_ in ("--extract", "--get") or (x_.startswith("-") and not x_.startswith("--") and "x" in x_) for x_ in a_) or (pos_ and re.match(r"^[a-zA-Z]*x[a-zA-Z]*$", pos_[0]) is not None and not a_[0].startswith("/"))
            if not ext_:
                return False
            dest_ = ""
            for k_, x_ in enumerate(a_):
                if x_ in ("-C", "--directory") and k_ + 1 < len(a_):
                    dest_ = a_[k_ + 1]
                elif x_.startswith("--directory="):
                    dest_ = x_.split("=", 1)[1]
            return into(dest_ or ".")
        if n_ in ("unzip", "7z", "7za", "jar"):
            if any(re.match(r"^-[a-zA-Z]*[lZtpv][a-zA-Z]*$", x_) for x_ in a_):
                return False                                     # list, test, print: nothing is written
            dest_ = ""
            for k_, x_ in enumerate(a_):
                if x_ == "-d" and k_ + 1 < len(a_):
                    dest_ = a_[k_ + 1]
            return into(dest_ or ".") if n_ == "unzip" else False
        return False

    def team_cmdvar(w):
        """`s=team; shipm $s add x`: a shipm command whose arguments are built at run time cannot be told from team add / borrow record."""
        return bool(w) and _fold(os.path.basename(w[0])) == "shipm" and any(x_.startswith(("$", "`")) or "$'" in x_ or '$"' in x_ for x_ in w[1:])

    TEAM_DIRCMDS = frozenset(("chmod", "chown", "chgrp", "chattr", "setfacl", "xattr", "ln", "mv", "rm", "rmdir", "unlink", "truncate", "shred"))
    TEAM_GITRAW = TeamRx(r"\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree)\s+\S+\s+|-\S+\s+)*(?:checkout|restore|reset|stash|apply|am|cherry-pick|revert|merge|rebase|pull|switch|rm|mv|clean)\b")

    def team_dirverb(w):
        """chmod / chown / chattr / ln / mv / rm / ... aimed at the docs or .agents folder itself, or at the table: makes the table unreadable or replaces it."""
        if not w or _cmd_name(w[0]) not in TEAM_DIRCMDS:
            return False
        cw_ = sp(d.get("cwd")) or pd
        for x_ in w[1:]:
            if not x_ or x_[0] in "-+" or "$" in x_:
                continue
            ap_ = x_ if os.path.isabs(x_) else os.path.join(cw_, x_)
            if any(r_ in TEAM_DIRS or r_ in TEAM_NAMES for r_ in team_rels(ap_)):
                return True
        return False

    def team_text(c, segs):
        """Hidden spellings of a write to the table: the command names it and uses a mutating verb, an interpreter, eval or a redirect to a variable. Pure readers (cat, grep, rg ...) pass."""
        t_ = re.sub(r"[\\'\"`]", "", c[:200000])
        if re.search(r"(?<![\w.$@%+:~-])shipm(?![\w./-])[^\n;|&]*(?:\$\(|`)", c[:200000]):
            return True                                          # shipm with a command substitution in its arguments
        if not TEAM_WORD.search(t_) and not TEAM_WORD.search(c[:200000]):
            return False
        if re.search(r">>?\s*[\"']?\$", c[:200000]):
            return True
        if TEAM_GITRAW.search(t_) or TEAM_GITRAW.search(c[:200000]):
            return True
        names_ = [_cmd_name(w_[0]) for _a, _u, w_ in segs for w_ in (w_,) if w_]
        if names_ and all(n_ in INERT_CMDS for n_ in names_):
            return False
        return bool(TEAM_VERB.search(t_) or TEAM_VERB.search(c[:200000]))

    def team_tamper():
        """A subagent never writes the Team table or the borrow record (the lead or the owner does): no cap, no bypass; warn level notes it. A discipline gate, not a boundary against a hidden command form."""
        hit = None; label = None
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            p_ = sp(ti.get("file_path")) or sp(ti.get("notebook_path"))
            if p_ and team_file(p_ if os.path.isabs(p_) else os.path.join(pd, p_)):
                hit = p_
        elif tool == "Bash":
            c = sp(ti.get("command"))
            tam = lambda ap, kind="write": team_file(ap, kind, c)
            try:
                if len(c) > BIG_CMD:
                    raise ValueError("command too long for the parsed check")
                bad = bash_targets(c, sp(d.get("cwd")) or pd, pd, tam)
            except Exception:
                try:
                    bad = bash_regex_hits(c, tam)
                except Exception:
                    bad = []
            hit = bad[0] if bad else None
            if not hit:
                try:
                    segs_ = [g_ for t_ in dict.fromkeys((c, _ansi_c(c))) for g_ in long_segs(t_)]
                    if any(admin_seg(a_, u_, w_, TEAM_SUB) for a_, u_, w_ in segs_):
                        hit = TEAM_LABEL; label = TEAM_LABEL
                    elif any(team_cmdvar(w_) for _a, _u, w_ in segs_):
                        hit = TEAM_LABEL; label = TEAM_LABEL
                    elif any(team_bulk(w_) for _a, _u, w_ in segs_):
                        hit = "bulk"; label = "a command that overwrites whole folders of the project"
                    elif any(team_git(w_) for _a, _u, w_ in segs_):
                        hit = "git"; label = "this git command"
                    elif any(team_dirverb(w_) for _a, _u, w_ in segs_):
                        hit = "dir"; label = "a command that changes the docs or .agents folder"
                    elif team_text(c, segs_):
                        hit = "text"; label = "a command that writes the table by a spelling this gate cannot follow"
                except Exception:
                    log_err()
        if not hit:
            return
        what = label or ("`" + os.path.basename(str(hit)) + "`")
        msg = f"`{atype}` may not change the project team ({what}): the lead or the owner records the team and the borrow record. Report what is missing; do not edit it."
        if level == "warn":
            log("team_table_write_warned", agent=atype, file=os.path.basename(str(hit))[:80]); NOTES.append("TEAM FLOW (warn-only project): " + msg)
            return
        log("team_table_write", agent=atype, file=os.path.basename(str(hit))[:80])
        out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}})

    # ---- integrity: what can turn the gate off must not change behind the owner's back. Narrow on purpose: only the hooks/disableAllHooks/env part of
    # the four settings files, the workspace hooks/*.sh, config/flow.json, <project>/.claude/hooks/*.sh and whether .claude/agents exists. Model,
    # permissions, .DS_Store and other keys change legitimately all day and are not watched.
    settings_files = [os.path.join(HOME, ".claude/settings.json"), os.path.join(HOME, ".claude/settings.local.json"),
                      os.path.join(pd, ".claude/settings.json"), os.path.join(pd, ".claude/settings.local.json")]
    if rpd != pd:
        settings_files += [os.path.join(rpd, ".claude/settings.json"), os.path.join(rpd, ".claude/settings.local.json")]
    import hashlib  # SHIPMIRACLE-LAZY
    EMPTY = hashlib.sha256(b"{}").hexdigest()

    def settings_digest(p_):
        """sha256 of the canonical JSON of hooks + disableAllHooks + env. A missing file counts like one with none of these keys; unparseable = 'unparseable'."""
        try:
            raw_ = open(p_, "rb").read()
        except OSError:
            return EMPTY
        try:
            j_ = json.loads(raw_.decode("utf-8"))
        except ValueError:
            return "unparseable"
        if not isinstance(j_, dict):
            return "unparseable"
        sub_ = {k_: j_[k_] for k_ in ("hooks", "disableAllHooks", "env") if k_ in j_}
        return hashlib.sha256(json.dumps(sub_, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def file_digest(p_):
        try:
            fd_ = os.open(p_, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)         # a FIFO at a watched path must not hang the hook
            try:
                if (os.fstat(fd_).st_mode & 0o170000) != 0o100000:                    # not a regular file
                    return "nonregular"
                with os.fdopen(fd_, "rb", closefd=False) as f_:
                    return hashlib.sha256(f_.read()).hexdigest()
            finally:
                os.close(fd_)
        except OSError:
            return "absent"

    def integrity_snapshot(only=None):
        if only:                                                 # P6 T3: the agent check watches three items only (cheap, no false positives from file churn)
            s_ = {"gate.engine": gate_engine(), "layout": "userlevel" if UL[0] else "legacy"}
            if UL[0]:
                s_["registry-entry"] = registry_digest()
            return s_
        snap = {}
        for p_ in settings_files:
            snap[p_] = settings_digest(p_)
        snap[os.path.join(WS, "config/flow.json")] = file_digest(os.path.join(WS, "config/flow.json"))
        for folder in [os.path.join(WS, "hooks")] + [os.path.join(r0_, ".claude/hooks") for r0_ in roots_]:
            for p_ in glob.glob(os.path.join(folder, "*.sh")):   # glob skips dotfiles; non-.sh files (.DS_Store, notes) are not watched
                snap[p_] = file_digest(p_)
        snap[os.path.join(WS, "hooks/shipm-hook")] = file_digest(os.path.join(WS, "hooks/shipm-hook"))   # P4 T8: the dispatcher shim and its modules
        for p_ in glob.glob(os.path.join(WS, "shipmiracle/hooks/*.py")) + glob.glob(os.path.join(WS, "shipmiracle/*.py")):   # P4 M2: the package modules on the hook import path too
            snap[p_] = file_digest(p_)
        for r0_ in roots_:
            snap[os.path.join(r0_, ".shipmiracle/playbook.json")] = file_digest(os.path.join(r0_, ".shipmiracle/playbook.json"))   # P5 T4
        snap["gate.engine"] = gate_engine()
        snap["layout"] = "userlevel" if UL[0] else "legacy"
        if UL[0]:
            snap["user-agents"] = user_agents_digest(); snap["manifest"] = file_digest(os.path.join(STATE, "v1/agents.json")); snap["registry-entry"] = registry_digest()
        else:
            snap["agents-dir"] = "present" if os.path.isdir(agents_dir) else "absent"
        return snap

    def user_agents_digest():
        h_ = shipmiracle_home()
        try:
            names = sorted(f for f in os.listdir(os.path.join(h_, ".claude/agents")) if f.endswith(".md") and not f.startswith(".")) if h_ else []
        except OSError:
            return "absent"
        return hashlib.sha256("".join(n + ":" + file_digest(os.path.join(h_, ".claude/agents", n)) + "\n" for n in names).encode("utf-8", "surrogateescape")).hexdigest()

    def registry_digest():
        try:
            e_ = reg_entry(rpd)
        except Exception:
            return "unparseable"
        if e_ is None:
            return "absent"
        sub_ = {k_: e_.get(k_) for k_ in ("team", "test_paths", "agents")}
        return hashlib.sha256(json.dumps(sub_, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def integrity_baseline():
        st["integrity"] = {"v": 2, "items": integrity_snapshot()}
        for k_ in ("integrity_logged", "integrity_stop", "integrity_noted"):
            st.pop(k_, None)

    def integrity_changed(only=None):
        """Watched gate items that differ from the owner's last message. None = no (usable) baseline yet. only=(names): an agent call, which
        compares just those items and never creates the baseline (only the owner's message and the main chat do)."""
        base = st.get("integrity")
        if not isinstance(base, dict) or base.get("v") != 2 or not isinstance(base.get("items"), dict):
            if only:
                return None
            integrity_baseline(); save(); return None            # first call, or a baseline from the older format: accept what is there now
        bi = base["items"]; ni = integrity_snapshot(only); res = []
        for k_ in sorted((set(bi) | set(ni)) & (set(only) if only else (set(bi) | set(ni)))):
            o_ = bi.get(k_, "absent"); n_ = ni.get(k_, "absent")
            if o_ == n_:
                continue
            if n_ == "unparseable" and o_ == "unparseable":
                continue
            if o_ == "unparseable" and n_ == EMPTY:
                continue                                         # a broken settings file that is fixed without hooks/env: nothing new
            res.append(k_)
        if res:
            sig = "|".join(res)
            if st.get("integrity_logged") != sig:
                st["integrity_logged"] = sig; log("gate_tamper_detected", files=[integrity_name(x) for x in res][:10]); save()
        return res

    def integrity_name(p_):
        if p_ == "agents-dir":
            return ".claude/agents"
        if p_ == "layout":
            return "agents.layout"
        if p_ in ("user-agents", "manifest", "registry-entry"):
            return {"user-agents": "~/.claude/agents", "manifest": "agents manifest", "registry-entry": "registry entry of this project"}[p_]
        return "/".join(p_.split("/")[-2:]) if p_.endswith(".json") else os.path.basename(p_)

    def integrity_msg(res):
        return ("A file that controls the team-flow check changed since your last message: " + ", ".join(integrity_name(x) for x in res[:5])
                + ". Tell the owner or revert it.")

    def integrity_note(res):
        """Warn level: say it once per change (delivered with the next output, see NOTES)."""
        sig = "|".join(res)
        if st.get("integrity_noted") != sig:
            st["integrity_noted"] = sig; save()
            NOTES.append("TEAM FLOW (warn-only project): " + integrity_msg(res))

    def qa_started():
        """A test-role agent is running: remember when it started. Without a later SubagentStop (maxTurns) that is no verdict."""
        pend = st.get("qa_pending") if isinstance(st.get("qa_pending"), dict) else {}
        if sp(agent) and sp(agent) not in pend:
            pend[sp(agent)] = now; st["qa_pending"] = pend; st["qa_started_ts"] = now; st["qa_by"] = atype
            for k_ in sorted(pend, key=pend.get)[:-20]:
                del pend[k_]
            save()

    if ev in ("PreToolUse", "PostToolUse") and agent and arole() == "test":
        try:
            qa_started()
        except Exception:
            pass

    if ev == "UserPromptSubmit":
        raw_p = str(d.get("prompt") or "")
        p = raw_p.lower()
        head = p.lstrip()
        head = head.replace("_", "-")                            # P6 sec M1: `<task_notification` is `<task-notification`
        if head.startswith(("<agent-message", "<task-notification", "<teammate-message", "<system-reminder", "[subagent hand-back]")) or "<agent-message from=" in p[:200]:
            log("agent_message"); return                         # a subagent hand-back, not the owner: no bypass, no reset, no baseline
        if head.startswith(("/", "[panel] ")):
            log("panel_prompt"); return                          # a slash command or text the panel typed is not the owner's words: no bypass, no reset, no baseline
        st["refusals"] = {}; st["small"] = {}
        try:
            integrity_baseline()                                 # the owner spoke: whatever changed before is accepted
        except Exception:
            pass
        q = re.sub(r"```.*?(```|$)", " ", p[:300], flags=re.S)   # fenced code and quoted text do not count
        q = re.sub(r"(?<!\w)\"[^\"\n]*\"(?!\w)|(?<!\w)'[^'\n]*'(?!\w)|\u201c[^\u201d\n]*\u201d", " ", q)
        st["bypass"] = bool(re.search(r"\bjust do it\b", q))
        if st["bypass"]:
            log("bypass")
        if "baseline" not in st:                                 # files already changed before this session are not "outside the team"
            try:
                st["baseline"] = sorted(dirty())
            except Exception:
                pass                                             # left unset: the next Stop sets it and flags nothing
        save(); return

    if ev == "SubagentStop":
        r = arole() if agent else role_info(atype)[1]
        if r == "build":                                         # engineers also write through Bash: credit every new dirty file to them
            st["build_ts"] = now; st["built_by"] = atype
            try:
                ed = st.setdefault("agent_edits", []); skip = set(st.get("baseline", [])) | set(st.get("outside") or []) | set(st.get("outside_blocked") or [])
                for f in sorted(dirty()):
                    if f not in skip and not RECORD.match(f) and not ENGINE_OUT.match(f) and f not in ed: ed.append(f)
                del ed[:-300]
            except Exception:
                pass
        elif r == "plan":
            st["arch_ts"] = now; st["planned_by"] = atype
        elif r in ("test", "review") and agent and sp(agent) in (st.get("src_editors") if isinstance(st.get("src_editors"), dict) else {}):
            log("verdict_ignored_self_edit", agent=atype, role=r)
            NOTES.append(f"TEAM FLOW: the verdict of `{atype}` is not counted: it changed source files itself in this run, and the author of a change cannot approve it. Run an independent {QA[0] if r == 'test' else 'reviewer'} on the change.")
        elif r == "test":
            st["qa_ts"] = now; st["qa_by"] = atype
            v_, evd, _l = parse_verdict(d.get("last_assistant_message"), TEST_VERDICTS)   # evd = digit counts only
            pend = st.get("qa_pending") if isinstance(st.get("qa_pending"), dict) else {}
            started = pend.pop(sp(agent), None) if agent else None
            st["qa_pending"] = pend
            st["qa_verdict"] = v_ or "unknown"; st["qa_verdict_ts"] = now; st["qa_evidence"] = evd
            runs = st.setdefault("qa_runs", [])
            runs.append({"ts": now, "start": started if isinstance(started, (int, float)) else now, "verdict": v_, "evidence": evd, "by": atype})
            del runs[:-20]
            log("qa_verdict", agent=atype, qa_verdict=st["qa_verdict"], qa_verdict_ts=int(now), evidence=evd[:120], verdict_mode=vmode)
            if not v_ and vmode == "legacy" and not st.get("verdict_noted"):
                st["verdict_noted"] = True
                NOTES.append(f"TEAM FLOW: {atype} ended without a 'Verdict:' line; counted as 'ran' (legacy mode). Give the agent file the Definition-of-Done report format.")
        elif r == "review" and team_review_ignored():
            pass                                                 # G9: the verdict of a non-member is not counted
        elif r == "review":
            st["review_ts"] = now
            v_, _e, lens = parse_verdict(d.get("last_assistant_message"), REVIEW_VERDICTS)
            st["review_verdict"] = v_ or "unknown"; st["review_lens"] = lens
            log("review_verdict", agent=atype, review_verdict=st["review_verdict"], review_lens=lens)
        save(); return

    if ev == "SubagentStart":                                    # not wired to this hook today (agent-state.sh gets it); first tool call below covers the same
        if agent and arole() == "test":
            qa_started()
        return

    tool = d.get("tool_name", ""); ti = d.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {}

    if ev == "PostToolUse" and agent and tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        r = rel(sp(ti.get("file_path")) or sp(ti.get("notebook_path")))
        if inside(r) and not RECORD.match(r) and not ENGINE_OUT.match(r):   # record files (plans, STATUS) are not a build
            if arole() != "test" or not is_test_path(r):         # a QA agent writing a test file is not a new build: an earlier FAIL must not turn stale; any other source edit is a build
                st["build_ts"] = now; st["built_by"] = atype
                if arole() in ("test", "review") and agent:      # the author of a source change cannot approve it: its own verdict is ignored at its stop
                    se_ = st.get("src_editors") if isinstance(st.get("src_editors"), dict) else {}
                    se_[sp(agent)] = now; st["src_editors"] = dict(list(se_.items())[-40:])
            ed = st.setdefault("agent_edits", []); r not in ed and ed.append(r)
            del ed[:-300]
            save()
        return

    if ev == "PreToolUse" and agent:
        res_ = integrity_changed(("layout", "registry-entry", "gate.engine"))   # P6 T3: a subagent stops when the layout, this project's registry entry or gate.engine changed since the owner's last message
        if res_ and level == "warn":
            integrity_note(res_)
        elif res_:
            out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": integrity_msg(res_)}})
    if ev == "PreToolUse" and agent and os.environ.get("SHIPMIRACLE_FLOW_TAMPER_OK") != "1":
        tamper_check()
    if ev == "PreToolUse" and agent and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"):
        readonly_check()
    if ev == "PreToolUse" and agent and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"):
        team_tamper()
        team_build_check()
    if ev == "PreToolUse" and agent and tool in ("Edit", "Write", "MultiEdit") and re.match(r"^\.claude/agents/[^/]+\.md$", rel(sp(ti.get("file_path"))), re.I):
        return agent_rule(ti.get("file_path"), tool, ti)
    if ev == "PreToolUse" and agent and UL[0] and not st.get("bypass") and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash") and (atype == "general-purpose" or arole() in ("support", "", "route")):
        general_purpose_check()
    if ev == "PreToolUse" and not agent:
        res_ = integrity_changed()
        if res_ and level == "warn":
            integrity_note(res_)
        elif res_:
            out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": integrity_msg(res_)}})
        tamper_check()
        if st.get("bypass") and not re.match(r"^\.claude/agents/", rel(sp(ti.get("file_path"))), re.I):
            if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):   # the owner said "just do it": these paths are known, not "outside the team"
                rb = rel(sp(ti.get("file_path")) or sp(ti.get("notebook_path")))
                bs = st.setdefault("bypass_seen", [])
                if inside(rb) and not RECORD.match(rb) and rb not in bs:
                    bs.append(rb); del bs[:-500]; save()
            return
        if tool == "ExitPlanMode":
            if st.get("arch_ts", 0) <= st.get("plan_ts", 0):
                pl_ = "planner"
                refuse("plan_without_architect", f"Get the plan from {pl_} first (Agent tool, subagent_type {pl_}, with the full request), "
                       "then present its plan. Plans in this project come from the plan-role agent (Opus).")
            st["plan_ts"] = now; log("plan_ok", by=st.get("planned_by", "")); save(); return
        if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
            path = sp(ti.get("file_path")) or sp(ti.get("notebook_path"))
            r = rel(path)
            if re.match(r"^\.claude/agents/[^/]+\.md$", r, re.I):        # a new or changed agent: the model rule applies when it is written (any chat or agent)
                return agent_rule(path, tool, ti)
            if not inside(r) or RECORD.match(r):
                return                                           # outside the project, or a record file the lead keeps
            try:
                n = n_changed(tool, path if os.path.isabs(path) else os.path.join(pd, path), ti)
            except Exception:
                n = BIG
            sm = st.setdefault("small", {})
            if (not sm or r in sm) and sum(sm.values()) + n <= SMALL:
                sm[r] = sm.get(r, 0) + n; log("small_fix", file=r, lines=n)
                ss = st.setdefault("small_seen", [])
                if r not in ss:
                    ss.append(r)
                save(); return
            who = who_for(r)
            if UL[0]:
                refuse("edit_outside_team", f"Source files are changed by the builder agents, not the main chat (only a small fix of one file, <= {SMALL} lines, "
                       f"is allowed here). Hand this change to {who} with the Agent tool (subagent_type {who}), with the exact steps, then review its report.")
            refuse("edit_outside_team", f"Source files are changed by the builder agents, not the main chat (only a small fix of one file, <= {SMALL} lines, "
                   f"is allowed here). Hand this change to {who} with the Agent tool (general-purpose with model sonnet if {who} is not loaded in this chat), with the exact steps, then review its report.")
        if tool == "Bash":
            c = sp(ti.get("command"))
            try:                                                 # parsed check; any failure (unterminated quote, bug) falls back to the regex check
                if len(c) > BIG_CMD:
                    raise ValueError("command too long for the parsed check")
                bad = bash_targets(c, sp(d.get("cwd")) or pd, pd)
            except Exception:
                try:
                    bad = bash_regex_hits(c)
                except Exception:
                    bad = []
            if bad:
                refuse("bash_write_outside_team", f"Do not write project files from the main chat with shell commands ({', '.join(bad[:3])}). "
                       "Hand the change to a builder agent, or use Edit for a small fix.")
        return

    if ev == "Stop" and not agent:
        res_ = integrity_changed()
        if res_ and level == "warn":
            integrity_note(res_)
        elif res_ and not d.get("stop_hook_active") and st.get("integrity_stop") != "|".join(res_):
            st["integrity_stop"] = "|".join(res_); save()        # once per change; the retry (stop_hook_active) passes so a stop never loops
            out({"decision": "block", "reason": integrity_msg(res_)})
        qa_state, qa_kind, qa_msg, qa_extra = "none", "", "", {}
        try:
            qa_state, qa_kind, qa_msg, qa_extra = qa_eval(st, vmode)
        except Exception:
            log_err()                                            # fail open (never block on a bug) but leave the traceback
        if st.get("bypass"):                                     # snapshot: shell writes of a "just do it" turn are known
            if qa_kind == "qa_failed":
                log("bypass_qa_failed", **qa_extra)              # the bypass lifts the refusal for this turn, never the record of a failing QA
            try:
                bs = st.setdefault("bypass_seen", [])
                for f in sorted(dirty()):
                    if not RECORD.match(f) and not ENGINE_OUT.match(f) and not f.endswith("/") and f not in bs:
                        bs.append(f)
                del bs[:-500]; save()
            except Exception:
                pass
            return
        if d.get("stop_hook_active"):
            return
        new_outside = []
        try:                                                     # files changed outside the team (shell writes)
            now_dirty = dirty()
            if "baseline" not in st:                             # no prompt seen yet: everything dirty now predates us
                st["baseline"] = sorted(now_dirty); save()
            else:
                known = set()
                for k in ("agent_edits", "small_seen", "agent_files", "bypass_seen", "baseline"):
                    known |= set(st.get(k) or [])
                known |= set(st.get("small") or {})
                for fn in glob.glob(os.path.join(STATE, "flow.*.json")):   # other sessions of this project (read-only, < 24 h)
                    if os.path.abspath(fn) == os.path.abspath(sf):
                        continue
                    try:
                        o = json.load(open(fn))
                        if o.get("project") != proj or now - o.get("ts", 0) > 86400:
                            continue
                        for k in ("agent_edits", "small_seen", "agent_files", "bypass_seen"):
                            known |= set(o.get(k) or [])
                    except Exception:
                        continue
                st["small_seen"] = sorted(set(st.get("small_seen", [])) | set(st.get("small", {})))
                outside = sorted(f for f in now_dirty if not RECORD.match(f) and not ENGINE_OUT.match(f) and f not in known and not f.endswith("/"))
                st["outside"] = outside
                new_outside = [f for f in outside if f not in set(st.get("outside_blocked") or [])]
        except Exception:
            new_outside = []
        items = []
        if qa_kind:
            items.append((qa_kind, qa_msg))
        if new_outside:
            eng = list(dict.fromkeys(who_for(f) for f in new_outside)); more = len(new_outside) - 6
            items.append(("outside_team", "These files changed outside the team (not by an agent or a logged small fix): " + ", ".join(new_outside[:6])
                          + (f" (+{more} more)" if more > 0 else "") + ". Hand them to " + " or ".join(eng) + " and run " + QA[0] + ", or tell the owner why they changed "
                          "directly (for example generated by a tool, or edited by the owner). The next stop passes."))
        if items:
            def mark():
                ob = st.setdefault("outside_blocked", [])
                ob.extend(f for f in new_outside if f not in ob); del ob[:-500]
            refuse_many(items, mark)
        save()


def run():
    try:
        main()
        if NOTES:                                                    # a warn-level note that no other output carried
            txt_ = " ".join(NOTES); del NOTES[:]                # out() would add them a second time
            out({"hookSpecificOutput": {"hookEventName": EVENT[0], "additionalContext": txt_}} if EVENT[0] == "PreToolUse" else {"systemMessage": txt_})
    except SystemExit as e_:
        if e_.code not in (0, None, 2):
            log_err()
            iso_crash()                                              # an odd exit code from inside the gate: refused at strict for Bash / file tools
        raise
    except (Exception, KeyboardInterrupt):
        log_err()
        iso_crash()
    sys.exit(0)
# --- SHIPMIRACLE GATE SOURCE END ---
# --- adapter (not part of the gate source) ---
from shipmiracle.hooks import core as _core


def quiet_note(ctx):
    """SHIPMIRACLE_QUIET (background probes, unattended runs): no side effects, except that a tool call from a real project is noted once per session
    (flow.<sid>.quiet + one gate_env_override event). Same code as the SHIPMIRACLE_QUIET branch of legacy flow-gate.sh; like there, not under SHIPMIRACLE_TEST."""
    if os.environ.get("SHIPMIRACLE_TEST"):
        return
    fc = (lambda x: x.casefold()) if sys.platform == "darwin" else (lambda x: x)
    try:
        d = json.loads(ctx.raw.decode("utf-8", "replace")); h = os.path.expanduser("~"); pd = os.path.realpath(ctx.env.get("CLAUDE_PROJECT_DIR") or d.get("cwd") or "/")
        if d.get("hook_event_name") == "PreToolUse" and d.get("tool_name") and fc(os.path.dirname(pd)) == fc(os.path.realpath(os.path.join(h, "Developer"))) and os.path.isdir(os.path.join(pd, ".claude/agents")):
            sd = os.path.join(h, ".local/state/shipmiracle"); os.makedirs(sd, exist_ok=True); sid = re.sub(r"[^A-Za-z0-9_-]", "", d.get("session_id") or "x")
            os.close(os.open(os.path.join(sd, "flow." + sid + ".quiet"), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            open(os.path.join(sd, "flow-events.jsonl"), "a").write(json.dumps({"ts": int(time.time()), "project": os.path.basename(pd), "session": sid, "event": "gate_env_override", "vars": ["SHIPMIRACLE_QUIET"]}) + "\n")
    except Exception:
        pass


class _Stdin:
    def __init__(self, raw):
        import io
        self.buffer = io.BytesIO(raw)

    def read(self, *a):
        return self.buffer.read(*a).decode("utf-8", "replace")


def to_result(text, err, code):
    """The gate's answer (captured stdout text, stderr text, exit code) as a core.Result. The gate prints one JSON object or nothing."""
    text = text or ""
    if code not in (0, 2) and EVENT[0] == "PreToolUse":
        raise RuntimeError("the gate exited with code %r" % (code,))      # a crash is not an allow: core.run_module turns it into a refusal at strict
    if code == 2:
        return _core.Result(block=True, reason=(err or text).rstrip("\n"), exit_code=2)
    if not text.strip():
        return None
    try:
        o = json.loads(text)
    except ValueError:
        if EVENT[0] == "PreToolUse":
            raise RuntimeError("the gate printed something that is not JSON")
        return _core.Result(plain_stdout=text)
    if not isinstance(o, dict):
        if EVENT[0] == "PreToolUse":
            raise RuntimeError("the gate printed JSON that is not an object")
        return _core.Result(plain_stdout=text)
    h = o.get("hookSpecificOutput") if isinstance(o.get("hookSpecificOutput"), dict) else {}
    r = _core.Result(additional_context=h.get("additionalContext") or "", system_message=o.get("systemMessage") or "")
    if h.get("permissionDecision") == "deny":
        r.block, r.reason = True, h.get("permissionDecisionReason") or ""
    elif o.get("decision") == "block":
        r.block, r.reason = True, o.get("reason") or ""
    return r


def _invoke(ctx):
    """Run the gate once on ctx.raw. The module globals (now, STATE, NOTES, EVENT, UL, QA) are fresh: see _flow."""
    import io
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = _Stdin(ctx.raw), io.StringIO()
    code = 0
    try:
        run()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except KeyboardInterrupt:
        code = 130
    finally:
        text, sys.stdin, sys.stdout = sys.stdout.getvalue(), old_in, old_out
    return to_result(text, "", code)


def _flow(ctx):
    """The dispatcher slot. The old process ran the gate once; the dispatcher also runs once per call, but a long-lived caller (tests, replay)
    may call twice: from the second call on the module is re-executed first, so no global (now, STATE, DEV, WS, NOTES, EVENT, UL, QA) leaks
    from one call to the next. The gate reads os.environ; a Ctx built with another env gets it for the duration of the call."""
    saved = None
    if ctx.env is not os.environ:
        saved = dict(os.environ); os.environ.clear(); os.environ.update(ctx.env)
    try:
        if ctx.quiet:
            quiet_note(ctx)
            return None
        mod = sys.modules[__name__]
        if _core.__dict__.get("_flow_used") or saved is not None:    # the module was imported before this call's env was in place
            import importlib
            mod = importlib.reload(mod)
        _core._flow_used = True
        return mod._invoke(ctx)
    finally:
        if saved is not None:
            os.environ.clear(); os.environ.update(saved)


for _ev in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop", "Stop"):
    _core.register(_ev, "flow", None, _flow)
