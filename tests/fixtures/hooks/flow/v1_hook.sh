#!/usr/bin/env bash
# Test shim for SHIPMIRACLE_GATE_IMPL=v1 (tests/flow_fixture.py): stands in for the legacy shell gate and runs the flow slot of the dispatcher
# (shipmiracle/hooks/flow.py through shipmiracle.hooks.core.run) with the interpreter flags the production hook command uses. Builtins only: the
# suites run it with a stripped PATH.
D="${0%/*}"
exec /usr/bin/python3 -I -S -X pycache_prefix="${SHIPMIRACLE_V1_PYC:-${TMPDIR:-/tmp}/shipmiracle-v1-pyc-test}" "$D/v1_launch.py"
