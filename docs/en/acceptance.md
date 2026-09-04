# Installation acceptance and evidence

Listener baseline checks and end-to-end usage checks are separate. Installation
success, a successful doctor, and application connectivity are different claims.
Report only what the evidence establishes.

`mihomoctl ready` tests the fixed readiness URL through the authenticated
listener. `mihomoctl diagnose url` adds a caller-selected target and separates
direct, listener, authentication, and target-request observations. Neither one
identifies a selected node. `mihomoctl rules check` is a structural contract
check, not complete routing acceptance.

## 1. Four result states

| State | Meaning |
| --- | --- |
| PASS | The check ran and the observed value satisfies its assertion |
| FAIL | An observed behavior or request failed its assertion |
| UNVERIFIED | Not run, tool failure, missing output, or insufficient evidence |
| DEFERRED | The user explicitly postponed it; record the reason and next action |

Record an unwanted optional feature as "not selected" in the scope, never as a
pass. Do not claim complete acceptance while any required, selected item is
FAIL, UNVERIFIED, or DEFERRED.

## 2. Deterministic listener verifier

Run from the current user's reviewed checkout. Requires Bash, Python 3.8+
(also required for installation and updates), curl, systemctl, ss, and existing mode-600 config/credentials.
Use a pinned version or reviewed commit containing the script. If an older
release lacks it, do not substitute improvised commands and claim equivalent
versioned acceptance.

Manually start your own service first. The example target is public and contains
no credentials:

```bash
acceptance_rc=0
bash scripts/acceptance.sh \
  --url https://www.gstatic.com/generate_204 --expect-status 204 \
  || acceptance_rc=$?
printf 'acceptance_rc=%s\n' "$acceptance_rc"
```

Omitting `--url` uses `MIHOMO_READY_URL`. Omitting `--expect-status` accepts any
actual 2xx response and prints its real status; success is never labeled "204"
without measuring it. URLs cannot contain userinfo, query strings, or fragments.
Never supply subscription, signed-download, or token URLs. The default timeout
is 10 seconds per probe, adjustable with `--timeout` from 1 to 60.

The script reads your config, queries service/listener state, and performs
bounded probes. It does not change config, start/stop/enable services, source
.bashrc, or download large files. The existing allowlist parser validates
credentials before exporting them in the child environment, never argv. Curl
ignores curlrc and inherited proxy bypasses and does not follow redirects. It
uses HEAD requests without downloading response bodies; choose a target that
supports HEAD and select the expected HEAD status. Output excludes raw errors,
response bodies, and authenticated URLs.

Automatic checks cover:

- active service and disabled startup state;
- all TCP listeners on the selected port bound to `127.0.0.1`; this does not
  establish process ownership or the state of other ports;
- actual HTTP status, curl exit code, and listener peer for authenticated HTTP
  CONNECT and SOCKS5H requests;
- unauthenticated HTTP CONNECT must return `407` from the listener. A timeout,
  502, or TLS failure is not evidence of authentication rejection;
- unauthenticated SOCKS5 offers only method `00` and must receive `05 ff`
  (no acceptable authentication methods). Accepting `00` fails the check;
  a disconnect or timeout remains unverified.

Output is `STATE<TAB>CHECK<TAB>EVIDENCE`. Exit 1 means a FAIL exists; 2 means
unverified/deferred work remains or the verifier could not run; 0 means every
reported item passed. Because end-to-end evidence remains pending, even a fully
passing listener baseline normally exits 2. This is not installation failure,
and must not be discarded to claim complete acceptance.

Use `--defer-vscode` only after the user explicitly postpones VS Code validation.
Preserve original script results and attach later independent evidence; never
edit the script output to turn pending rows into PASS.

## 3. End-to-end evidence

| Item | Required evidence and limits |
| --- | --- |
| Proxy egress | Request an approved public target routed to Proxy; correlate time, target, rule, and actual proxy egress. Inspect node details locally; report only whether a proxy node was selected |
| Installed shell | Fresh one-shot ordinary shell is direct; proxy_on/off and with_proxy isolation work; loader precedes the non-interactive guard; ready hook is reachable |
| Failure paths | With approval and no disruption, verify stop, released port, failing hook without auto-start, and successful restart; otherwise run isolated tests and mark live verification pending |
| Downloads | Check each actual axel, S3 client, and large-download task's proxy settings and PID sockets. A small file does not test a large transfer; zero journal delta is supporting evidence only |
| VS Code/remote client | Verify the new PID after reconnect: ownership, variable presence, listener socket, and target routing. Stopping an old PID does not prove its replacement works |
| Logs and checkout | Scan a declared local scope for sensitive values, share counts only, and record tool exit codes. Do not guarantee absence of all leaks |
| Baseline | Compare before/after config, listeners, and service state in the current user's scope. A port set alone does not prove every other user was unaffected |

In the fictional examples, `example.com` and `example.net` may use different
policies. Successful readiness/authentication probes only prove the measured
request through the listener, not proxy-node or application end-to-end connectivity.
Provider/url-test health checks are not application routing evidence either.

Never stop a busy service just to test it. Run isolated regression checks and
distinguish repository tests from live-machine evidence:

```bash
bash tests/test.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tests/audit-test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
git diff --check
```

Preserve every command's exit code. For logging pipelines, use pipefail and
capture `PIPESTATUS` immediately, not the exit status of tail, tee, or a success
message. The repository secret scan covers only configured patterns and
misplaced client.env files, not all live logs, credential files, or Git history.
It does not print matching values or return "clean" after tool failure.

## 4. Reproducible report

Record the source tag/commit (archive SHA256 and approved deviation when using
an archive), pinned Mihomo version and full asset name, official expected and
actual local digests, selected port, active/enabled state, exact changed paths,
pre-install state, and backup inventory. A version string is not provenance.

Every item needs a state, command/tool, exit code, redacted observed value,
scope, and time. Never infer a pass for an unexecuted check. Missing raw output
means unverified; deferred work needs a reason and next action. Keep additional
test evidence separate from original script output. Report "installed, acceptance
pending" or the actual failure until all required selected checks have evidence.

## 5. Rollback order

`uninstall.sh` removes only the controller and loader. It preserves the Mihomo
binary, service, config, credentials, and caches. It is not full uninstallation
or necessarily restoration of the previous controller version.

Distinguish pre-change backups from post-install snapshots such as `after-test`.
Record absent files as absent; restoring an absent state cannot mean copying a
post-install snapshot. Controller transaction backups do not cover separately
installed core binaries, units, or VS Code settings.

Stop your own user service before a full rollback. Restore the previous binary
and config, run `mihomo -t` with the retained binary, restore the unit, and run
`systemctl --user daemon-reload`. To undo a fresh installation, remove only
approved newly created units/config, reload the user manager, then remove the
binary; never delete the binary and subsequently invoke it for validation.
Restore original .bashrc permissions and avoid overwriting unrelated later edits.
Restore pre-change VS Code settings or revert only added keys, reload after
approval, then inspect the new process.

For controller-only updates, preserve the existing active/enabled state; do not
stop/start services for acceptance. Use the generation recovery helper described
in [update and rollback](update.md). Core/full-stack rollback below is a different scope.
