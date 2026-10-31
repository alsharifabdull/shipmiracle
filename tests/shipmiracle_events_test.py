#!/usr/bin/env python3
"""shipmiracle/events.py: concurrent appends across rotation, refused keys, size limit, kind regex, retention, tail.
Run: python3 tests/shipmiracle_events_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, subprocess, sys, tempfile, time
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp()).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"))
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, UsageError, config, events, state  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception as e:
        return "wrong exception %r" % e
    return False

if len(sys.argv) > 1 and sys.argv[1] == "worker":
    bad = 0
    for i in range(int(sys.argv[3])):
        try:
            events.append("test.worker", {"p": int(sys.argv[4]), "i": i}, base=sys.argv[2])
        except Exception as e:
            bad += 1; print("worker error", repr(e), file=sys.stderr)
    sys.exit(1 if bad else 0)

def lines(base):
    out = []
    r = pathlib.Path(base) / "v1"
    for n in ("events.jsonl", "events.jsonl.1", "events.jsonl.2", "events.jsonl.3"):
        if (r / n).exists():
            out += [json.loads(l) for l in (r / n).read_text().splitlines()]
    return out

# ---- 12 processes x 200 appends, 64 KB rotation ------------------------------------------------------
base = TMP / "race"
env = dict(os.environ, SHIPMIRACLE_EVENTS_MAX_BYTES="65536")
t0 = time.time()
procs = [subprocess.Popen([sys.executable, __file__, "worker", str(base), "200", str(k)], env=env, stderr=subprocess.PIPE) for k in range(12)]
codes = [p.wait() for p in procs]
print("# concurrency 12x200 appends took %.2fs" % (time.time() - t0))
check("no worker error", codes == [0] * 12, codes)
evs = lines(base)
check("exactly 2400 valid lines across live + rotated files", len(evs) == 2400, len(evs))
check("every (process, i) pair appears once", len({(e["data"]["p"], e["data"]["i"]) for e in evs}) == 2400)
rot = sorted(p.name for p in (base / "v1").glob("events.jsonl*"))
check("rotation happened (live + at least .1 and .2)", {"events.jsonl", "events.jsonl.1", "events.jsonl.2"} <= set(rot), rot)
sizes = [(base / "v1" / n).stat().st_size for n in rot]
check("no file much above the 64 KB limit", max(sizes) <= 65536, sizes)
check("files are 0600, no .tmp", all(oct((base / "v1" / n).stat().st_mode & 0o777) == "0o600" for n in rot))
allv = [e for n in ("events.jsonl.3", "events.jsonl.2", "events.jsonl.1", "events.jsonl") if (base / "v1" / n).exists()
        for e in [json.loads(l) for l in (base / "v1" / n).read_text().splitlines()]]
check("per-process order is preserved across rotated files", all([e["data"]["i"] for e in allv if e["data"]["p"] == k] == list(range(200)) for k in range(12)))

# ---- shape, validation --------------------------------------------------------------------------------
b = TMP / "shape"
e = events.append("proj.opened", {"a": 1, "b": [1, 2]}, project="0123456789ab", src="shipmiracle-test", base=b)
check("line shape", e == json.loads((b / "v1/events.jsonl").read_text()) and set(e) == {"v", "ts", "kind", "project", "src", "data"}
      and e["v"] == 1 and isinstance(e["ts"], int) and e["project"] == "0123456789ab" and e["src"] == "shipmiracle-test")
check("defaults: project null, src Shipmiracle, data {}", (lambda x: x["project"] is None and x["src"] == "shipmiracle" and x["data"] == {})(events.append("a", base=b)))
check("compact one-line JSON", (b / "v1/events.jsonl").read_text().count("\n") == 2 and ", " not in (b / "v1/events.jsonl").read_text().splitlines()[0])
for k in ("", "A.b", "1a", "a b", "a-b", "x" * 65, "a\\n", None, "ünï"):
    r = raises(UsageError, events.append, k, {}, base=b)
    check("bad kind refused: %r" % (k,), r is True, r)
check("kind of 64 chars accepted", events.append("a" + "b" * 63, base=b)["kind"].startswith("ab"))
for bad_key in ("token", "TOKEN", "secret", "access_token", "token-name", "api.secret", "Secret Name"):
    r = raises(UsageError, events.append, "k.x", {bad_key: "v"}, base=b)
    check("refused key %r" % bad_key, r is True, r)
for bad_key in ("tokenName", "To_Ken", "to-ken", "accessToken", "apiKey", "api_key", "password", "Password1", "secretName", "access_key",
                "\uff54\uff4f\uff4b\uff45\uff4e", "to\u200bken", "pass\u200d-word", "SECRET_value", "my.token.x", "client_secret", "passwd"):
    r = raises(UsageError, events.append, "k.x", {bad_key: "v"}, base=b)
    check("refused key (normalised) %r" % bad_key, r is True, r)
check("refused key nested in dict and list", raises(UsageError, events.append, "k", {"a": {"b": [{"token": 1}]}}, base=b) is True)
check("harmless keys accepted (tokens, key)", events.append("k", {"tokens": 5, "key": "x"}, base=b)["data"]["tokens"] == 5)
for ok_key in ("tokens", "tokens_in", "key", "keys", "count", "name", "error", "kind", "i", "p", "tokens_out"):
    check("allowed key %r" % ok_key, events.append("k", {ok_key: 1}, base=b)["data"][ok_key] == 1)
# only keys are checked: values are not inspected (documented)
check("values are not inspected (only keys are checked)", events.append("k", {"note": "a token value"}, base=b)["data"]["note"] == "a token value")
for bad_proj in ("", "XYZ", "0123456789abc", "../etc"):
    check("bad project refused: %r" % bad_proj, raises(UsageError, events.append, "k", {}, bad_proj, base=b) is True)
check("bad src refused", raises(UsageError, events.append, "k", {}, None, "Bad Src", base=b) is True)
check("non-dict data refused", raises(UsageError, events.append, "k", [1], base=b) is True)
check("unserialisable data refused", raises(UsageError, events.append, "k", {"x": object()}, base=b) is True)
n_before = len((b / "v1/events.jsonl").read_text().splitlines())
base_len = len(json.dumps({"v": 1, "ts": int(time.time()), "kind": "k", "project": None, "src": "shipmiracle", "data": {"p": ""}}, separators=(",", ":")))
ok_pad = "x" * (4096 - base_len)
check("a line of exactly 4096 bytes is accepted", len(json.dumps(events.append("k", {"p": ok_pad}, base=b), separators=(",", ":"))) == 4096)
check("a line over 4096 bytes is refused and not written", raises(UsageError, events.append, "k", {"p": ok_pad + "y"}, base=b) is True
      and len((b / "v1/events.jsonl").read_text().splitlines()) == n_before + 1)
check("multibyte data counts bytes, not characters", raises(UsageError, events.append, "k", {"p": "ü" * 2100}, base=b) is True)

# ---- emit, symlink, tail -------------------------------------------------------------------------------
check("emit returns True/False and never raises", events.emit("k", {}, base=b) is True and events.emit("BAD", {}, base=b) is False and events.emit("k", {"token": 1}, base=b) is False)
b2 = TMP / "symev"; state.ensure_root(b2)
os.symlink(TMP / "victim.log", b2 / "v1/events.jsonl")
check("symlinked events.jsonl is refused and nothing is created", raises(SafetyError, events.append, "k", {}, base=b2) is True and not (TMP / "victim.log").exists())
b3 = TMP / "tail"
for i in range(7):
    events.append("t.n", {"i": i}, base=b3)
check("tail(n) returns the last n, oldest first", [e["data"]["i"] for e in events.tail(3, b3)] == [4, 5, 6] and len(events.tail(50, b3)) == 7)
check("tail(0) is empty; missing base is empty", events.tail(0, b3) == [] and events.tail(5, TMP / "none") == [])
with open(b3 / "v1/events.jsonl", "ab") as f:
    f.write(b"garbage\n")
check("tail skips damaged lines", len(events.tail(50, b3)) == 7)
b4 = TMP / "tailrot"; os.environ["SHIPMIRACLE_EVENTS_MAX_BYTES"] = "400"
for i in range(30):
    events.append("t.n", {"i": i}, base=b4)
tl = [e["data"]["i"] for e in events.tail(12, b4)]
check("tail reads across rotated files", tl == list(range(18, 30)), tl)
check("at most .1-.3 are kept", not (b4 / "v1/events.jsonl.4").exists())
del os.environ["SHIPMIRACLE_EVENTS_MAX_BYTES"]

# ---- tail skips an oversized file instead of loading it ----
b6 = TMP / "tailbig"; r6 = state.ensure_root(b6)
events.append("k", {"i": 1}, base=b6)
with open(r6 / "events.jsonl.1", "wb") as f:
    f.truncate(state.MAX_READ + 1)
check("tail skips a rotated file over 8 MiB", [e["data"]["i"] for e in events.tail(50, b6)] == [1])

# ---- retention ----------------------------------------------------------------------------------------
b5 = TMP / "ret"; r = state.ensure_root(b5)
for i in (1, 2, 3):
    (r / ("events.jsonl.%d" % i)).write_text('{"v":1}\n')
old = time.time() - 40 * 86400
os.utime(r / "events.jsonl.2", (old, old)); os.utime(r / "events.jsonl.3", (old, old))
events.append("k", base=b5)
check("default 30 days: rotated files older than that are deleted", (r / "events.jsonl.1").exists() and not (r / "events.jsonl.2").exists() and not (r / "events.jsonl.3").exists())
config.set("logs.retention_days", "1")
two = time.time() - 2 * 86400
os.utime(r / "events.jsonl.1", (two, two))
events.append("k", base=b5)
check("logs.retention_days=1 deletes a 2-day-old rotated file", not (r / "events.jsonl.1").exists())
check("the live file is never expired", (r / "events.jsonl").exists())
os.utime(r / "events.jsonl", (old, old))
events.append("k", base=b5)
check("an old live file is kept", len(lines(b5)) == 3)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
