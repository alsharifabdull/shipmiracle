#!/usr/bin/env bash
# Test shim for tests/stage_parity_test.py: stands in for the legacy shell gate (SHIPMIRACLE_TEST_HOOK) and runs the flow slot AND the stage slot of the dispatcher
# (shipmiracle/hooks/core.py) with the interpreter flags of the production hook command. Builtins only: the suites run it with a stripped PATH.
D="${0%/*}"
exec /usr/bin/python3 -I -S -X pycache_prefix="${SHIPMIRACLE_V1_PYC:-${TMPDIR:-/tmp}/shipmiracle-stage-pyc-test}" "$D/launch.py"
