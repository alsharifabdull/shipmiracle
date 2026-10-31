"""CLI glue for `shipm release-check` and `shipm release denylist` (arguments are parsed in shipmiracle/cli.py). Exit codes: 0 pass, 1 findings,
2 usage, 3 tree missing, 4 unsafe denylist (raised as the matching ShipmiracleError)."""
from __future__ import annotations

import json
import sys

from .. import ShipmiracleError, NotFound, UsageError
from .. import config, paths
from . import check as chk
from . import denylist as dl

PROVIDER = None            # tests inject an object with collect(); None = SystemProvider (git config, gh, scutil, id)


def _out(text=""):
    sys.stdout.write(text + "\n")


def denylist_path():
    return paths.config_dir() / dl.FILENAME


def _tree_for(a):
    if a.tree:
        return a.tree
    try:
        from . import export
    except ImportError:
        raise NotFound("no --tree given and the dry-run export (shipm release export) is not available yet; pass --tree DIR")
    try:
        return export.dry_run_tree()
    except NotFound:
        raise
    except ShipmiracleError as e:
        raise NotFound("no --tree given and the dry-run export could not be built: %s; pass --tree DIR" % e)


def run_check(a) -> int:
    if a.no_denylist and a.require_denylist:
        raise UsageError("--no-denylist and --require-denylist exclude each other")
    tree = _tree_for(a)
    inputs = chk.load_inputs_for_tree(tree, paths.workspace_dir() / "release")
    deny, why = None, None
    if a.no_denylist:
        why = "--no-denylist"
    else:
        deny = dl.load(denylist_path())
        if deny is None:
            why = "no denylist on this machine"
        elif deny.malformed:
            sys.stderr.write("shipm: %d malformed denylist line(s) ignored\n" % deny.malformed)
    binary = chk.gitleaks_binary()
    rep = chk.scan(tree, inputs=inputs, deny=deny, deny_required=bool(a.require_denylist), require_gitleaks=bool(a.require_gitleaks), require_login=bool(getattr(a, "require_login", False)),
                   gitleaks=lambda t: chk.run_gitleaks(t, binary), deny_skip_reason=why)
    rc = 0 if rep.result == "PASS" else 1
    if rep.result == "PASS":
        try:
            chk.write_stamp(rep, {"no_denylist": bool(a.no_denylist), "require_denylist": bool(a.require_denylist),
                                  "require_gitleaks": bool(a.require_gitleaks), "denylist_used": deny is not None})
        except ShipmiracleError as e:
            sys.stderr.write("shipm: PASS stamp not written: %s\n" % e)
            rc = 1
    if a.json:
        _out(json.dumps(rep.as_dict(), sort_keys=True))
    else:
        for line in rep.lines():
            _out(line)
    return rc


def run_release(a) -> int:
    if a.action == "export":
        from . import export
        return export.run(a)
    if a.action != "denylist":
        raise UsageError("unknown release action")
    p = denylist_path()
    if a.refresh:
        paths.require_owner("shipm release denylist --refresh")
        paths.assert_isolated(paths.config_dir())
        res = dl.refresh(p, PROVIDER, include_generic=list(getattr(a, "include_generic", None) or []))
        dl.check_safe(p)
        n = sum(res["counts"].values())
        _out("denylist written: %d entries (%s)" % (n, ", ".join("%s=%d" % kv for kv in sorted(res["counts"].items())) or "none"))
        for note in res["notes"]:
            _out("note: " + note)
        if res.get("skipped"):
            _out("skipped (common word, not added): " + ", ".join(res["skipped"]))
            _out("note: a project name that is a common English word matches the plain word all over a tree; to check for it anyway add --include-generic NAME")
        if res.get("author"):
            try:
                config.set("release.author_name", res["author"][0])
                config.set("release.author_email", res["author"][1])
            except ShipmiracleError:
                _out("note: release.author_* not stored (the config keys do not exist yet)")
    d = dl.load(p)
    if d is None:
        if a.refresh:
            raise NotFound("denylist was not written")
        raise NotFound("no denylist yet; run: shipm release denylist --refresh")
    if a.show_hashes:
        for kind, h in d.hashes():
            _out("%s\t%s" % (kind, h))
    elif not a.refresh:
        counts = {}
        for k, _ in d.entries:
            counts[k] = counts.get(k, 0) + 1
        _out("denylist: %d entries (%s)" % (len(d.entries), ", ".join("%s=%d" % kv for kv in sorted(counts.items())) or "none"))
    return 0


def run_push_check(a) -> int:
    """`shipm push-check REMOTE URL` (called by the pre-push hooks; ref lines on stdin). Exit 1 = refuse. Any unexpected error is a warning
    and exit 0: the guard is a seatbelt, a bug in it must not block every push."""
    from . import pushcheck
    try:
        refs = sys.stdin.read(1 << 20) if not sys.stdin.isatty() else ""
        res = pushcheck.check(a.remote, a.url, refs)
    except Exception as e:      # noqa: BLE001 (documented fail-open)
        sys.stderr.write("shipm push-check: could not decide (%s); push allowed\n" % type(e).__name__)
        return 0
    for line in res.lines:
        sys.stderr.write(line + "\n")
    return 1 if res.refused else 0
