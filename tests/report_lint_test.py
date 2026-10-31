#!/usr/bin/env python3
"""Report lint (shipmiracle/report/lint.py), positive and negative per rule, on literal report texts (no repository needed), including the P5 security rule that a
CR report Summary carries no URL, link or image (M4) and that secret shapes never survive into report facts (M2). Run: python3 tests/report_lint_test.py"""
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shipmiracle.report import lint, safe, secret_free  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    fails += 0 if ok else 1

CR = ("# CR-007 Fix login · DELIVERED · PASS\nSummary: pending\nStages: Do done · Test done\nEvidence: `npm test` -> 214 passed, 0 failed\nFiles: 2 changed\n"
      "Rollback: git revert abc1234\nOwner waits: 1 · Auto-decisions: 0\nCost: 12k tokens\nNot verified: none\n")
ST = ("# CR-007 · Test · PASS  2026-10-20 10:00 · verifier (sonnet)\nVerdict: PASS (214 passed)\nEvidence: `npm test` -> 214 passed\nBy: verifier\n"
      "Next: Review\nNot verified: none\n")

check("positive: a CR report is clean", lint.lint_text(CR) == [], lint.lint_text(CR))
check("positive: a stage report is clean", lint.lint_text(ST) == [], lint.lint_text(ST))

def has(text, word):
    return any(word in p for p in lint.lint_text(text))

check("negative: no header", has("Summary: x\n", "header"))
check("negative: verdict word outside the closed set", has(CR.replace("PASS\n", "MAYBE\n", 1), "header") or has(CR.replace("· PASS", "· MAYBE"), "header"))
check("negative: a field missing (Rollback)", has(CR.replace("Rollback: git revert abc1234\n", ""), "missing field Rollback"))
check("negative: fields out of order", has(CR.replace("Summary: pending\nStages: Do done · Test done\n", "Stages: Do done · Test done\nSummary: pending\n"), "out of order"))
check("negative: Evidence without a backticked command and number", has(CR.replace("`npm test` -> 214 passed, 0 failed", "tests were fine"), "Evidence"))
check("negative: Not verified empty", has(CR.replace("Not verified: none", "Not verified:"), "Not verified is empty"))
check("negative: a hedging word", has(CR.replace("Summary: pending", "Summary: it probably works"), "banned"))
check("negative: over 40 lines", has(CR + "Evidence: `a` -> 1\n" * 40, "lines"))
check("negative: Summary of 4 lines", has(CR.replace("Summary: pending", "Summary: a\n  b\n  c\n  d"), "Summary is 4 lines"))
check("negative: a carriage return", has(CR.replace("\n", "\r\n"), "carriage"))
check("negative: a blank line", has(CR.replace("Stages:", "\nStages:"), "blank"))
check("negative: auto-decisions without Charter and Decisions", has(CR.replace("Auto-decisions: 0", "Auto-decisions: 2"), "Charter"))

for name, line in (("https URL", "Summary: see https://example.org/x"), ("ftp URL", "Summary: ftp://host/file"), ("www host", "Summary: go to www.example.org"),
                   ("markdown link", "Summary: read [this](page)"), ("markdown image", "Summary: ![x](y.png)"), ("html anchor", "Summary: <a href=x>t</a>"),
                   ("bare domain", "Summary: open evil.com"), ("ccTLD link", "Summary: open evil.de/x"), ("host with path", "Summary: see foo-bar.shop/a/b?c=1"), ("data URI", "Summary: data:text/html;base64,QQ==")):
    check("M4 a Summary with a %s is rejected" % name, has(CR.replace("Summary: pending", line), "link"), lint.lint_text(CR.replace("Summary: pending", line)))
for name, line in (("a file name", "Summary: fixed tests/login.ts and README.md"), ("a version", "Summary: bumped to 1.2.3"), ("Arabic", "Summary: تم إصلاح الاتجاه من اليمين إلى اليسار"),
                   ("a code word", "Summary: node.js tests, app.py and index.html were touched"), ("a version and a path", "Summary: v1.2 in src/app.py, e.g. tests")):
    check("M4 control: %s in a Summary is fine" % name, not has(CR.replace("Summary: pending", line), "link"), lint.lint_text(CR.replace("Summary: pending", line)))
check("re-review e: a host name in the title (any report field) is rejected too", any("host name" in x or "link" in x for x in lint.lint_text(CR.replace("Fix login", "Fix login on example.org"))))
for name, frag in (("ideographic full stop", "see evil\u3002de now"), ("fullwidth letters", "see \uff45\uff56\uff49\uff4c\uff0ede now"), ("bare ccTLD host", "see evil.de now"), ("IPv4", "see 10.0.0.5 now"),
                   ("e-mail shape", "write to a@evil.de"), ("host with port", "see evil.de:8080"), ("tk host", "see evil.tk now"), ("ideographic dot with path", "see evil\u3002tk/x now"), ("IPv4 with path", "see 1.2.3.4/x now"), ("e-mail at tk", "x@evil.tk")):
    check("re-review e: %s in a Summary and in an Evidence line is rejected" % name, any("host name" in x for x in lint.lint_text(CR.replace("Summary: pending", "Summary: " + frag))) and
          any("host name" in x for x in lint.lint_text(CR.replace("Evidence: ", "Evidence: " + frag + " ", 1))), lint.lint_text(CR.replace("Summary: pending", "Summary: " + frag)))
for frag in ("Failed: a.test:1, b.test:2", "ok.Next sentence", "Done.Next steps follow", "see tests/login.rtl.test.ts:41 and v2.0.1", "ran npm.cmd twice"):
    check("re-review e: no false positive on %r" % frag, not any("host name" in x for x in lint.lint_text(CR.replace("Summary: pending", "Summary: " + frag))), lint.lint_text(CR.replace("Summary: pending", "Summary: " + frag)))
check("re-review e: code spans, file names and versions stay fine", lint.lint_text(CR.replace("Summary: pending", "Summary: ran `os.path.join` and `a@b`, fixed tests/login.rtl.test.ts and app.py, v1.2.3")) == [], lint.lint_text(CR.replace("Summary: pending", "Summary: ran `os.path.join` and `a@b`, fixed tests/login.rtl.test.ts and app.py, v1.2.3")))

TOK = "ghp" "_abcdefghijklmnopqrstuvwxyz0123456789"
check("M2 secret_free withholds a token, a Bearer header, a password= and a URL with credentials",
      secret_free("curl -H 'Authorization: Bearer %s'" % TOK) == "" and secret_free("password=hunter2") == "" and secret_free("https://u:pw@host/x") == "" and secret_free("key=" + TOK) == "")
check("M2 secret_free keeps normal evidence and safe() applies it", secret_free("`npm test` -> 214 passed") == "`npm test` -> 214 passed" and safe("token " + TOK) == "")

print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
