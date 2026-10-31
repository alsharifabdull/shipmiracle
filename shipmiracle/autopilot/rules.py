"""Data for the autopilot hard stops (Phase 6 spec section 2): labels, the deny text, the FORBIDDEN literals and the command tables.
Pure data and two small pure functions; no I/O. The logic lives in hardstop.py."""
from __future__ import annotations

import hashlib
import re

class _L:
    """A regex that is compiled on first use (this module defines ~30; a hook call that stops nothing compiles none of them: ~3 ms of import saved)."""
    __slots__ = ("_a", "_r")

    def __init__(self, *a):
        self._a = a
        self._r = None

    def __getattr__(self, name):
        r = self._r
        if r is None:
            r = self._r = re.compile(*self._a)
        return getattr(r, name)


LABELS = {"H1": "H1-delete", "H2": "H2-publish", "H3": "H3-paid", "H4": "H4-production", "H5": "H5-gate",
          "H6": "H6-scope", "H7": "H7-quality", "H8": "H8-limits", "H9": "H9-unclear"}
RULE_IDS = tuple(LABELS)

# Spec section 2, "On a stop": the exact deny text.
DENY = 'Hard stop {label} (id {sid}): "{excerpt}". The autopilot paused. Do not retry or work around it. End your turn with one line for the owner.'

BIG_CMD = 100000                      # H9: a Bash command above this is never parsed
MAX_SPECIAL = 8000                    # H9: operator/quote characters (outside heredoc bodies) above this are too complex to check
MAX_WORDS = 6000                      # H9: words in one call
MAX_SEGS = 2000                       # H9: simple commands in one call
MAX_DEPTH = 2                         # bash -c / eval / script / npm script nesting
EXCERPT_MAX = 200

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read", "Grep", "Glob", "NotebookRead", "LS")
AGENT_TOOLS = ("Agent", "Task")
RECORD_FILES = ("docs/status.md", "docs/decisions.md")        # compared folded, but only where the file system ignores case (hardstop.is_record)
RECORD_EXACT = ("docs/STATUS.md", "docs/DECISIONS.md")        # the exact names on a case-sensitive file system (Linux): DOCS/STATUS.MD is another file there

# The persistence-file table (checklist D14 M1): files and folders that run code later, outside the chat (shell start-up files, launch agents, the git config, a project's editor tasks and
# direnv file). ONE table: the hard stop is built from it, and BOTH copies of the flow gate (shipmiracle/hooks/flow.py and the legacy shell gate) carry the same literal tuples, because the gate
# is stdlib-only and standalone; tests/gate_persist_test.py fails when a copy differs. A change here is made in all three places.
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
PERSIST_HOME_GLOBS = ("Library/Python/*/lib/python/site-packages",)      # hard stop only (the gate has its own pattern): the macOS user site-packages loads *.pth files and usercustomize into every python start

# G11 / D11 (project isolation layer 1 and the secret-read rule): ONE secret table. Both copies of the flow gate carry the same literal tuples (the gate is stdlib-only and standalone);
# tests/gate_secret_read_test.py fails when a copy differs and checks that the hard stop's SENS_KEYS are covered. A change here is made in all three places.
SECRET_HOME_DIRS = (".ssh", ".gnupg", ".kube", ".local/share/keyrings", ".gnome2/keyrings", ".config/gcloud", ".azure", "Library/Keychains", "Library/Cookies", "Library/Safari",
                    "Library/Application Support/Google/Chrome", "Library/Application Support/BraveSoftware", "Library/Application Support/Microsoft Edge", "Library/Application Support/Arc",
                    "Library/Application Support/Firefox", ".config/google-chrome", ".config/BraveSoftware", ".config/chromium", ".config/microsoft-edge", ".mozilla", ".password-store", ".oci", "Library/Messages", ".aws/sso")
SECRET_SSH_KEEP = (".pub", "known_hosts", "known_hosts.old", "config")        # inside ~/.ssh: a name ending in .pub or exactly one of these is not secret
SECRET_HOME_FILES = (".aws/credentials", ".docker/config.json", ".config/gh/hosts.yml", ".netrc", ".pypirc", ".git-credentials", ".npmrc", ".yarnrc.yml", ".claude/.credentials.json",
                     ".claude.json", ".terraform.d/credentials.tfrc.json", ".config/gcloud/credentials.db", ".pgpass", ".my.cnf", ".s3cfg", ".vault-token", ".boto", ".oci/config", ".m2/settings.xml", ".config/op/config", ".bash_history", ".zsh_history", ".python_history", ".psql_history", ".mysql_history", ".node_repl_history", ".sh_history", ".local/share/fish/fish_history", ".huggingface/token", ".cache/huggingface/token", ".config/anthropic/key", ".openai/key", ".authinfo", "_netrc", ".zshenv", ".viminfo", ".rediscli_history", ".irb_history", ".sqlite_history", ".lesshst", ".config/hub")
SECRET_NAME_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".secret", ".env", ".tfvars", ".tfstate", ".tfstate.backup", ".kdbx", ".p8")
SECRET_NAME_EXACT = (".envrc", ".dev.vars", ".npmrc", ".pypirc", "kubeconfig", ".pgpass", ".my.cnf", ".s3cfg", "state.vscdb", ".netrc", "_netrc", ".git-credentials", ".htpasswd", ".vault-pass", ".vault_pass", ".dockerconfigjson",
                     "wp-config.php", "token.txt", "api_token", ".token", "oauth.json", "settings.local.py", "application-secrets.properties", "secring.gpg", "secring.pgp")
SECRET_NAME_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")          # not when the name ends in .pub
SECRET_DATA_NAMES = ("credentials", "secret", "secrets", "creds")                       # data files only (see SECRET_DATA_EXT); secrets.ts and the like are code
SECRET_DATA_EXT = ("json", "yaml", "yml", "toml", "ini", "txt", "env", "conf", "cfg", "")
ENV_ALLOW_SUFFIXES = ("example", "sample", "template", "dist", "defaults")     # .env.example ... are not secret
KEY_USERS = ("ssh", "scp", "sftp", "ssh-add", "ssh-keygen", "sshpass")        # commands that USE a key file given with -i / -F / -f without showing it
USE_FLAGS = ("--env-file", "--envfile", "--env-file-path")                    # option values that load a file without showing it
WS_READ_ALLOW = ("AGENTS.md", "CLAUDE.md", "README.md", "bin", "hooks", "shipmiracle", "templates", "agents", "skills", "memory", "config", "docs/standards", "docs/owner-steps")
CLAUDE_STORES = ("projects", "history.jsonl", "file-history", "shell-snapshots", "todos", "session-env")       # under ~/.claude: other projects' transcripts and shared history
ISO_NAMES = ("SECRET_HOME_DIRS", "SECRET_SSH_KEEP", "SECRET_HOME_FILES", "SECRET_NAME_SUFFIXES", "SECRET_NAME_EXACT", "SECRET_NAME_PREFIXES", "SECRET_DATA_NAMES", "SECRET_DATA_EXT", "ENV_ALLOW_SUFFIXES",
             "KEY_USERS", "USE_FLAGS", "WS_READ_ALLOW", "CLAUDE_STORES")
# Always outside the charter whatever the scope globs say (spec 1).
ALWAYS_EXCLUDED = (".shipmiracle/**", ".claude/**", ".githooks/**", ".git/**", ".github/workflows/**", "**/.env*", ".mcp.json",
                   ".co" "dex/**", ".vscode/tasks.json", ".vscode/settings.json", ".envrc", ".husky/**", "CLAUDE.md", "AGENTS.md")
# Tools an autopilot run may call at all (C2: default deny). mcp__* tools additionally need autopilot.mcp_allow. Everything else (Monitor, CronCreate/Delete/List,
# ScheduleWakeup, RemoteTrigger, Skill, SlashCommand, EnterWorktree, PushNotification, KillShell ...) is H9 "tool not allowed in an autopilot run".
ALLOWED_TOOLS = ("Read", "Grep", "Glob", "LS", "NotebookRead", "Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "BashOutput", "Agent", "Task", "TodoWrite",
                 "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "WebSearch", "WebFetch", "ExitPlanMode", "AskUserQuestion")
# git subcommands that run hooks (C1): H5 when a hooks folder differs from base or is untracked
HOOK_RUNNING_SUBS = ("commit", "merge", "pull", "rebase", "cherry-pick", "revert", "am", "switch", "checkout", "push", "stash", "gc", "worktree")
HOOK_DIRS = (".githooks", ".husky")
EXTRA_GATE_NAMES = ("claude.md", "agents.md")             # at any depth (folded)

# --- FORBIDDEN literals (spec 2). (name, regex, rule the hit belongs to) ---------------------------------------------------------------------
_LOCAL_URL = r"(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?![\w.-])"
FORBIDDEN = [
    ("git push", _L(r"""\bgit\s+(?:\S+\s+){0,6}?push\b|['"]git['"]\s*,\s*(?:['"][^'"]*['"]\s*,\s*){0,6}?['"]push['"]"""), "H2"),
    ("--force", _L(r"--force\b"), "H1"),
    ("publish", _L(r"\bpublish\b"), "H2"),
    ("rm -rf", _L(r"\brm\s+-[a-zA-Z]*(?:rf|fr)[a-zA-Z]*\b|\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+-[a-zA-Z]*f"), "H1"),
    ("curl ", _L(r"\bcurl\s"), "H3"),
    ("wget ", _L(r"\bwget\s"), "H3"),
    ("http(s)://", _L(r"""\bhttps?://(?!""" + _LOCAL_URL + r""")[^\s'")]+"""), "H3"),
    ("ssh ", _L(r"\bssh\s"), "H4"),
    (".shipmiracle", _L(r"\.shipmiracle\b"), "H5"),
    (".claude", _L(r"\.claude\b"), "H5"),
    (".githooks", _L(r"\.githooks\b"), "H5"),
    # `security ` narrowed to the keychain tool's sub-commands: the bare word is ordinary English in test names (deviation, see STATUS)
    ("security ", _L(r"\bsecurity\s+(?:find-\w+|add-\w+|delete-\w+|dump-keychain|list-keychains|unlock-keychain|set-\w+|create-\w+|import|export|cms|authorize)\b"), "H5"),
    ("SHIPMIRACLE_", _L(r"\bSHIPMIRACLE_"), "H5"),
    ("CLAUDECODE", _L(r"CLAUDECODE"), "H5"),
    ("launchctl", _L(r"\blaunchctl\b"), "H5"),
    ("crontab", _L(r"\bcrontab\b"), "H5"),
    ("systemd-run", _L(r"\bsystemd-run\b"), "H5"),                   # Linux twins of launchctl / security: a transient unit outside this chat, the keyring
    ("secret-tool", _L(r"\bsecret-tool\b"), "H5"),
    ("subprocess push/publish", _L(r"subprocess[\s\S]{0,200}?(?:push|publish)"), "H2"),
    ("import shipmiracle", _L(r"\bimport\s+shipmiracle\b"), "H5"),
    ("from shipmiracle", _L(r"\bfrom\s+shipmiracle\b"), "H5"),
]
# Files whose added lines are never scanned (URLs and generated text are normal there).
SCAN_SKIP = _L(r"(?:\.(?:md|markdown|txt|rst|svg|png|jpe?g|gif|ico|pdf|lock|sum|snap|map|min\.js)|-lock\.json|\.lock\.json|package-lock\.json)$", re.I)

# Inline code that executes dynamic text: unclear execution (H9), whatever its literals.
DYNAMIC_CODE = _L(r"""\b(?:exec|eval|compile|__import__|b64decode|marshal|ctypes|getattr)\s*\(|\bFunction\s*\(|\bos\.(?:system|popen)\b|\bbase64\b|\bchild_process\b"""
                          r"""|\bopen\(\s*(?!['"])[^,)]+,\s*['"][wax+]|\bsystem\s*\(|\bexecSync\b""")

# --- command tables ----------------------------------------------------------------------------------------------------------------------------
SHELLS = ("bash", "sh", "zsh", "dash", "ksh", "fish")
INTERP_RE = _L(r"^(python[0-9.]*|node|nodejs|ruby|perl|php|lua|deno|bun|tclsh|Rscript|julia|swift|osascript)$")
INLINE_FLAGS = {"python": ("-c",), "node": ("-e", "--eval", "-p", "--print"), "ruby": ("-e",), "perl": ("-e", "-E"), "php": ("-r",), "lua": ("-e",),
                "swift": ("-e",), "deno": ("eval",), "bun": ("-e", "--eval"), "julia": ("-e",), "Rscript": ("-e",)}
SQL_CLIENTS = ("psql", "mysql", "sqlite3", "mongosh", "mongo", "mariadb", "clickhouse-client", "redis-cli", "cockroach", "sqlcmd", "usql")
# sqlite3 dot-commands that run programs, read scripts or write files (".shell id", ".read x.sql", ".load ext", ".output f")
SQLITE_DOT = _L(r"(?:^|[\n;\"'])\s*\.(?:shell|system|read|load|output|once|excel|log|backup|save)\b", re.I)
SQL_BAD = _L(r"\b(?:DROP|TRUNCATE)\b|\bdropDatabase\b|\bdropCollection\b|\.drop\s*\(|\bFLUSH(?:ALL|DB)\b", re.I)

EXTRA_WRAPPERS = ("timeout", "stdbuf", "caffeinate", "arch", "unbuffer", "xargs", "watch", "ionice", "chrt", "gtimeout", "setpriv")
PERSIST_CMDS = ("launchctl", "crontab", "at", "atq", "atrm", "batch", "osascript", "security", "disown", "setsid", "screen", "tmux", "nohup", "sudo", "doas",
                "claude", "systemctl", "ssh-add", "ssh-agent", "ssh-keygen", "ssh-keyscan", "op", "alias", "unalias", "su", "login", "pbcopy", "pbpaste",
                "systemd-run", "secret-tool", "xclip", "xsel", "wl-copy", "wl-paste",      # the six above: Linux twins of launchctl, security, pbcopy, pbpaste
                "gio", "gtk-launch", "kioclient", "kioclient5", "kioclient6", "dex", "exo-open", "qdbus", "qdbus-qt5", "qdbus6", "qdbus-qt6", "dbus-launch", "dbus-update-activation-environment",
                "gsettings", "dconf", "pkexec", "run0", "flatpak-spawn", "machinectl")      # D9 M3: desktop launchers, session settings that autostart, privilege wrappers (the hard stop refuses them in any form)
LEAD_PERSIST = ("sudo", "doas", "nohup", "setsid")
ENV_CODE_VARS = ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV", "ENV", "PYTHONPATH", "PYTHONSTARTUP", "NODE_OPTIONS", "NODE_PATH", "RUBYOPT", "RUBYLIB", "PERL5OPT",
                 "PERL5LIB", "IFS", "SHELLOPTS", "PROMPT_COMMAND", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_EXEC_PATH", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
                 "GIT_CONFIG_COUNT", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR", "GIT_PROXY_COMMAND", "GIT_TEMPLATE_DIR", "EDITOR", "VISUAL", "PAGER", "HOME", "XDG_CONFIG_HOME")
ENV_CODE_PREFIX = ("DYLD_", "SHIPMIRACLE_", "CLAUDE", "GIT_CONFIG_KEY", "GIT_CONFIG_VALUE", "NPM_CONFIG_", "npm_config_")
GIT_SCOPE_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")
SENSITIVE_CONFIG_KEYS = _L(r"^(?:alias\.|core\.(?:hookspath|sshcommand|fsmonitor|editor|pager|askpass|gitproxy)|credential\.|url\.|http\.|include|diff\.external|gpg\.program|"
                                   r"filter\.|protocol\.|submodule\.|remote\.[^.]+\.(?:url|pushurl|receivepack|uploadpack)|.*\.(?:cmd|command|textconv)$|pager\.|sequence\.editor|merge\..*driver)", re.I)

CLOUD_CLIS = ("aws", "gcloud", "gsutil", "bq", "az", "stripe", "doctl", "heroku", "openai", "anthropic", "ibmcloud", "linode-cli", "vultr-cli", "railway", "ngrok",
              "cloudflared", "lt", "localtunnel", "twilio", "sentry-cli", "pscale", "turso", "neonctl", "render", "oci", "aliyun", "hcloud", "scw", "s3cmd", "rclone",
              "co" + "dex", "gemini")
NET_RAW = ("curl", "wget", "http", "https", "xh", "httpie", "nc", "ncat", "netcat", "telnet", "socat", "ftp", "tftp", "lftp", "aria2c", "axel", "lynx", "w3m",
           "dig", "nslookup", "host", "ping", "ping6", "traceroute", "traceroute6", "mtr", "whois", "nmap", "tcpdump")
# value-taking options of the diagnostic network tools (their values are not hosts)
NET_TOOL_VALUE = {"ping": {"-W", "-s", "-S", "-p", "-l", "-M", "-Q", "-m", "-I", "-z", "-k", "-G", "-g", "-h", "-T"}, "traceroute": {"-m", "-q", "-w", "-p", "-s", "-f", "-g", "-i", "-t", "-z", "-M"},
                  "dig": {"-p", "-b", "-c", "-f", "-k", "-m", "-q", "-t", "-x"}, "nmap": {"-p", "-e", "-g", "-S", "-D", "--top-ports", "-oN", "-oX", "-oG", "-iL", "--max-retries"}}
NET_TOOL_VALUE["ping6"] = NET_TOOL_VALUE["ping"]; NET_TOOL_VALUE["traceroute6"] = NET_TOOL_VALUE["traceroute"]; NET_TOOL_VALUE["mtr"] = NET_TOOL_VALUE["traceroute"]
LOCAL_HOST_RE = _L(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/\s]*@)?(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)(?::\d+)?(?:[/?#].*)?$", re.I)
URL_RE = _L(r"^[a-z][a-z0-9+.-]*://", re.I)
# value-taking options of curl/wget/httpie (their values are not hosts)
NET_VALUE_OPTS = {"-o", "-O", "-H", "-d", "-X", "-u", "-A", "-e", "-b", "-c", "-F", "-T", "-m", "-w", "-K", "-E", "-x", "-U", "-r", "-C", "-Y", "-y", "-t", "-P", "-i", "-a", "-B", "-I",
                  "--output", "--header", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--request", "--user", "--user-agent", "--referer", "--cookie", "--cookie-jar",
                  "--form", "--upload-file", "--max-time", "--write-out", "--config", "--cert", "--key", "--proxy", "--output-document", "--post-data", "--post-file", "--tries",
                  "--timeout", "--directory-prefix", "--header", "--limit-rate", "--connect-timeout", "--retry", "--cacert", "--resolve", "--connect-to", "--proxy-user", "--json"}

TF_TOOLS = ("terraform", "tofu", "pulumi", "terragrunt", "cdktf", "cdk", "sam", "serverless", "sls", "kubectl", "kubectx", "k9s", "kustomize", "oc", "eksctl", "kops",
            "ansible", "ansible-playbook", "ansible-pull", "salt", "salt-call", "chef", "knife", "puppet", "nomad", "consul", "vagrant")
REMOTE_SHELLS = ("ssh", "scp", "sftp", "mosh", "ssh-copy-id", "rsh", "rcp", "telnetd")
PUBLISH_SIMPLE = {  # command -> subcommands that publish (None = any use)
    "twine": ("upload",), "cargo": ("publish", "yank", "login", "owner"), "gem": ("push", "yank", "owner", "signin"), "pod": ("push",),
    "fastlane": ("deliver", "pilot", "supply", "upload_to_app_store", "upload_to_testflight", "release", "beta", "deploy", "submit_build", "upload_to_play_store"),
    "vercel": None, "netlify": ("deploy",), "fly": ("deploy", "launch"), "flyctl": ("deploy", "launch"), "firebase": ("deploy", "hosting:channel:deploy"),
    "wrangler": ("deploy", "publish", "pages"), "surge": None, "semantic-release": None, "gh-pages": None, "hub": ("release", "create", "pull-request"),
    "transporter": None, "appcenter": ("distribute",), "eas": ("submit", "build", "update"), "expo": ("publish", "upload"), "npm_publish": None,
    "composer": ("publish",), "poetry": ("publish",), "flit": ("publish",), "hatch": ("publish",), "dotnet": ("nuget",), "nuget": ("push",),
    "mvn": ("deploy",), "gradle": ("publish",), "gradlew": ("publish",), 
}
JS_PM = ("npm", "yarn", "pnpm", "bun")
JS_PUBLISH_SUB = ("publish", "unpublish", "deprecate", "dist-tag", "owner", "access", "team", "star", "hook", "pack_upload")
JS_INSTALL_SUB = ("install", "i", "add", "update", "up", "upgrade", "ci", "link", "dedupe", "rebuild", "remove", "uninstall", "rm", "un", "isntall", "in", "insall", "ic", "install-test", "it", "uninstall")
GH_READ_VERBS = ("list", "view", "status", "diff", "checks", "download", "watch", "ls", "version", "help", "--version", "--help", "show", "search", "browse_local", "completion")
GH_CRED_GROUPS = ("auth", "secret", "ssh-key", "gpg-key", "variable", "codespace", "config", "alias", "extension", "attestation", "ruleset", "cache", "label")
GH_DELETE = {("repo", "delete"), ("release", "delete"), ("release", "delete-asset"), ("gist", "delete"), ("issue", "delete"), ("run", "delete"), ("workflow", "disable"),
             ("label", "delete"), ("variable", "delete"), ("secret", "delete"), ("cache", "delete"), ("ssh-key", "delete"), ("gpg-key", "delete"), ("codespace", "delete"),
             ("pr", "delete"), ("repo", "archive"), ("repo", "rename")}
TEST_RUNNERS = ("pytest", "py.test", "jest", "vitest", "mocha", "rspec", "phpunit", "ctest", "tox", "nox", "ava", "karma", "jasmine", "playwright", "cypress", "prove", "busted")
TEST_PAIRS = (("go", "test"), ("swift", "test"), ("cargo", "test"), ("mvn", "test"), ("gradle", "test"), ("gradlew", "test"), ("deno", "test"), ("bun", "test"), ("dotnet", "test"),
              ("bundle", "exec"), ("xcodebuild", "test"), ("flutter", "test"), ("dart", "test"), ("mix", "test"), ("rake", "test"), ("make", "test"), ("make", "check"))
SYSTEM_DIRS = ("/usr/", "/bin/", "/sbin/", "/opt/homebrew/", "/System/", "/Library/Developer/", "/Applications/", "/opt/local/", "/Library/Frameworks/")
SECRET_RES = [
    (_L(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}"), "***"),
    (_L(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "***"),
    (_L(r"\bAKIA[0-9A-Z]{12,}"), "***"),
    (_L(r"\bxox[abprs]-[A-Za-z0-9-]{8,}"), "***"),
    (_L(r"(?i)\b((?:[\w-]*(?:token|secret|passw(?:or)?d|passwd|api[_-]?key|apikey|authorization|bearer|credential)[\w-]*)\s*[=:]\s*)\S+"), r"\1***"),
    (_L(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),
    (_L(r"(://[^/\s:@]+:)[^/\s@]+@"), r"\1***@"),
    (_L(r"[A-Za-z0-9+/_=-]{40,}"), "***"),
]


def redact(s: str) -> str:
    for rx, rep in SECRET_RES:
        s = rx.sub(rep, s)
    return s


def excerpt(s: str) -> str:
    """One line, secrets redacted, no double quote, at most EXCERPT_MAX characters."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", s if isinstance(s, str) else str(s))
    s = redact(" ".join(s.split())).replace('"', "'")
    return s if len(s) <= EXCERPT_MAX else s[:EXCERPT_MAX - 3] + "..."


def new_stop_id() -> str:
    """A random stop id (H4): not derivable from the command, so a model cannot predict the id it would be asked to quote. Stored in the run state."""
    import secrets
    return "H-" + secrets.token_hex(3)


def stop_id(rule: str, subject: str) -> str:
    """Derived id (kept for tests and the engine's cmd_sha); hard stops use new_stop_id()."""
    return "H-" + hashlib.sha256((rule + "\0" + subject).encode("utf-8", "surrogateescape")).hexdigest()[:6]


def scan_literals(text: str, limit: int = 2000000):
    """FORBIDDEN literals found in text: list of (name, rule). Linear regexes only; text is cut at `limit` characters."""
    if not isinstance(text, str):
        return []
    text = text[:limit]
    out = []
    for name, rx, rule in FORBIDDEN:
        if rx.search(text):
            out.append((name, rule))
    return out


# --- Phase 6 hardening tables (red-team K01..K23), compiled on first use --------------------------------------------------------------------------
# inline code that deletes: (regex that ends right after the function name, all arguments are targets, the target is the object the method is called on)
DEL_RES = {
    "python": [(_L(r"\brmtree\s*\("), False, False), (_L(r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*\("), False, False), (_L(r"(?<!os)\.(?:unlink|rmdir)\s*\("), False, True)],
    "node": [(_L(r"\b(?:rmSync|unlinkSync|rmdirSync|rimraf|rimrafSync)\s*\("), False, False), (_L(r"\.(?:rm|unlink|rmdir)\s*\("), False, False)],
    "ruby": [(_L(r"\b(?:FileUtils|Dir|File|IO|Pathname)\.(?:rm_rf|rm_r|rm_f|rm|remove_dir|remove_entry_secure|remove_entry|remove_file|rmtree|rmdir|delete|unlink)\b"), True, False),
             (_L(r"\.(?:rmtree|unlink)\b"), False, True)],
    "perl": [(_L(r"\b(?:unlink|rmtree|remove_tree|rmdir)\b"), True, False)],
    "php": [(_L(r"\b(?:unlink|rmdir)\s*\("), False, False)],
}
# inline code that writes a file (perl, ruby, awk; python and node are read by flow's parser): (regex with the path in group 1, kind)
WRITE_RES = {
    "perl": [(_L(r"""\bopen\s*\(?[^,;()]*,\s*['"]\s*\+?(?:>>?|\+>)[:\w]*\s*['"]\s*,\s*['"]([^'"]+)['"]"""), "perl"),
             (_L(r"""\bopen\s*\(?[^,;()]*,\s*['"]\s*\+?>>?\s*([^'"]+)['"]"""), "perl")],
    "ruby": [(_L(r"""\b(?:File|IO)\.(?:write|binwrite)\s*\(?\s*['"]([^'"]+)['"]"""), "ruby"),
             (_L(r"""\bFile\.(?:open|new)\s*\(?\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]*)['"]"""), "ruby-open")],
    "awk": [(_L(r"""\bprintf?\b[^;}\n]*?>>?\s*"([^"]+)\""""), "awk")],
}
ARCHIVE_TOOLS = ("tar", "bsdtar", "gtar", "unzip", "cpio", "ditto", "7z", "7za", "7zr", "7zz", "7zA")
READERS = ("cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "cp", "tar", "xxd", "od", "strings", "base64", "awk", "sed", "bat", "nl", "tac", "cut", "sort", "zip", "rsync", "gzip", "bzip2", "xz", "openssl")
LISTEN_PKGS = {"http-server": ("-a", "--address", "--host"), "live-server": ("--host",), "serve": ("-l", "--listen"), "browser-sync": ("--host", "--listen")}
LISTEN_LOCAL = _L(r"^(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)(?::\d+)?$", re.I)
# a package whose command name differs from the package that declares it
BIN_ALIAS = {"tsc": "typescript", "tsserver": "typescript", "ng": "@angular/cli", "playwright": "@playwright/test", "vue-cli-service": "@vue/cli-service", "nuxi": "nuxt", "svelte-kit": "@sveltejs/kit"}
