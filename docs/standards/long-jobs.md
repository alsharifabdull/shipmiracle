# Long jobs (on demand)

Anything over about 10 minutes (benchmarks, builds): run it through `shipm bg <minutes> -- <cmd>` (deadline and a log), write one line in STATUS ("running X, started HH:MM, check Y"), and poll with short checks instead of ending the turn on it. Before a heavy job run `bin/shipm-watch host --heavy-ok`; if the Mac is busy, wait. STATUS is the current state; history goes to `docs/status-archive/`. Run every command to completion; start no background loops.
