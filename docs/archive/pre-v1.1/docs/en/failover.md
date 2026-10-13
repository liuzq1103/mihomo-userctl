# Provider policy and automatic failover

Import defaults to `--policy auto`: a YAML document containing only `proxies` merges nodes; other documents use provider policy. Explicit `--policy provider|nodes` wins. Provider mode retains names, types, order, routing and probe settings while protecting host runtime configuration. Missing policy fields become empty; review removals and `probe_overwrites` before saving. Invalid policy never silently falls back to node-only mode.

## Existing automatic paths

Use `mihomoctl groups --json` to inspect `selection_chain`, `automatic_candidates`, `affected_groups` and `warnings`. A Selector pointing to an automatic group can already provide failover. A Selector pinned to a node bypasses that path. Missing references, cycles, unknown selections, missing probe records, observed failures and core-reported fixed selections are distinct states. Historical probe results do not guarantee current application availability.

In the Textual node page, use `: chain`; the numbered node menu presents the same evidence. Follow an existing path one selector at a time, confirm each change and verify readback. Shared-entry impacts are shown before selection. Use your subscription's actual names; no business-specific names are hardcoded. A fixed selection inside an automatic group requires a core-supported reset; choosing the outer group does not clear it.

## Explicit probe settings

```bash
mihomoctl health-check group 'Auto'
mihomoctl health-check group 'Auto' --preset resilient
mihomoctl health-check group 'Auto' --preset resilient --apply
mihomoctl restart
```

No options means inspection; changes preview by default and save only with `--apply`. Options are `--url`, `--expected-status`, `--interval` (seconds), `--timeout` (milliseconds), `--lazy true|false`, and `--tolerance` (milliseconds, url-test only). The optional resilient preset uses HTTPS gstatic, expected 204, interval 120, timeout 5000, lazy false, and url-test tolerance 50. Explicit options override the preset. New URLs must be public HTTPS without credentials, query or fragment; status expressions support values, ranges and combinations such as `200/204/400-405`.

Use `health-check provider NAME` to inspect or explicitly adjust a shared provider. The preset also enables provider checks; other edits preserve the enable setting. Preview lists referencing groups. Group previews show provider settings for `use` members because provider scheduling may control their effective check interval. Only the named object changes; no separate probing daemon is introduced.

Textual supports `: health-check group "Auto" --preset resilient`, followed by `y` to save. The numbered menu exposes the same service. Saves validate with the installed core, detect concurrent edits, create a private backup and commit atomically. Restart separately. Reimporting provider policy can replace local probe adjustments; preview reports the settings being overwritten.

Custom check URLs should require no authentication and return stable status codes. gstatic reachability does not prove that a particular service accepts the exit. A 405 or 451 response alone does not prove application success.

## Incident logs and verification

```bash
mihomoctl logs --since '2026-10-10 21:09:00' --until '2026-10-10 21:14:00' --lines 1000
```

The server journal interprets time expressions. Textual supports `: journal --since "TIME" --until "TIME"`; the numbered menu offers historical logs. Console output remains redacted and bounded, distinguishing query errors from no records in the window. CLI logs retains raw journal output; review private destination information before sharing. Retention, rotation and persistence depend on server configuration; no records does not establish that no failure occurred.

Real-core tests use two local CONNECT proxies and a local target. Disabling the current exit must move new connections to the other exit; disabling both must yield observed-failure diagnostics. Recovery includes probe interval, timeout, candidate count and core caching/scheduling. An interval alone cannot establish a 99.5% availability target or zero failed requests. Failed connections need application retries; restarting the core interrupts connections. Historical attribution still requires contemporaneous evidence.
