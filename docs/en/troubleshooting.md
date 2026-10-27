# Installation and runtime troubleshooting

- Complete bundle cannot find its core: keep the entire extracted directory, verify its checksum and permissions, and use the first-run wizard. Source archives, wheels and legacy wheelhouse kits do not include a core. For new setup follow [initialization](setup.md), reuse a trusted core or explicitly install the fixed version, then init once. Do not reinitialize existing managers or blindly run core install.
- NAS/wheelhouse permissions rejected: copy all required materials to an owned private directory and verify there. Do not recursively loosen permissions. Check the [two offline layouts](offline-install.md).
- Python/target mismatch: use the complete Linux x86_64 bundle on supported Ubuntu hosts; source/wheelhouse installations must also check their system interpreter; do not force another target's kit. Prepare missing strict-offline cores/dependencies beforehand.
- Installer's subsequent download fails DNS: check that the entire installation shell is inside exec; an outer pipeline's right side does not inherit its left side's environment.
- Bash reports HTML or a syntax error involving '<': the response may be a region/login page. curl -f does not reject HTTP 200 HTML. Stop execution and follow [download review and proxy inheritance](first-run.md#install-a-third-party-cli-through-the-proxy); never disable TLS verification.
- init succeeded but exec fails its health gate: initialization leaves the runtime stopped by default. Explicitly start when ready, then check configuration, ports and logs. Do not bootstrap a missing core through its own stopped proxy.
- Local requests work without remote routing: advanced CLI init defaults to MATCH,DIRECT; the new-user simple wizard configures Proxy routing. Review the actual active configuration. Check NO_PROXY and actual client connections using [layered verification](first-run.md).

## All nodes fail delay tests / unknown-node / missing references

Run `mihomoctl nodes --json` and compare exact names and provider identities, including spaces and flag emoji (🇺🇸 and US are different). `unknown-node` means the target was absent from the merged directory. Global delay HTTP 404 becomes `node-not-in-core`; a provider 404 refreshes the directory to distinguish `node-disappeared` from `controller-capability-unsupported`. Group results include `missing_member_count` and up to five `missing_members`; numbered-menu guidance and Textual `: chain` explain dangling references. Duplicate sources are reported as ambiguous rather than missing.

Inspect `mihomoctl providers --json`, subscription/provider loading and `mihomoctl logs`. Check upstream renames, readable provider caches and successful loading. Explicitly run `mihomoctl provider refresh NAME` if appropriate, or review and reimport the subscription. After saving configuration, run `mihomoctl restart`, then recheck the core proxy table. A disk configuration or stale UI snapshot does not prove a node is loaded.

503 `node-unreachable` means the node exists but its probe failed; 504 `delay-timeout` means the probe timed out. Check node reachability, outbound networking and access to `https://www.gstatic.com/generate_204`; these are not unsupported-API errors. Successful delay does not verify model requests. The complete bundle includes Textual with individual/batch delay tests; run `mihomoctl` and open Nodes. The numbered menu supports basic selection, while `mihomoctl tui --engine curses` offers the `t` shortcut. See the [terminal guide](console.md). Probe settings require the literal prefix `group "NAME"` or `provider "NAME"`; probe a Selector's underlying provider.

Report controller, core, initialization, runtime and real remote requests separately as PASS/FAIL/UNVERIFIED. Do not publish raw credentials or connection details.

## Update or recovery refuses to continue

`installation-console-open` means another interface for this account is open: close it, then retry; the core can remain running. `operation-committed-cleanup-pending` means the change is already committed but cleanup needs retrying, not that the old version is still active. The next locked operation resumes cleanup. A recovery error or drift warning preserves temporary material to avoid overwriting unrelated edits; inspect the redacted error before retrying. There is no historical rollback command or restore button.

## Validation, provider targets and save recovery (1.4.2)

Use `mihomoctl latency NODE --provider PROVIDER` for a specific provider, or `--global` for the global identity when names collide; these options are mutually exclusive. TUI probes retain the same source identity. Core selection accepts only a name, so selecting an ambiguous name is refused. The latency column distinguishes untested, testing, success, failure with a reason, and cancelled. Batch completion reports success/failure/cancellation counts; a failed new attempt replaces any old numeric result.

After upgrading an existing systemd installation to 1.4.2, run `mihomoctl service install` (with `--system` for system scope) to regenerate the managed unit before starting it; restart an already running service to apply the new environment. Only the exact known prior generated definition is migrated; arbitrary edits are refused. The unit clears proxy variables and the complete override vocabulary of pinned Mihomo v1.19.32. The process backend needs no unit refresh.

If startup cannot establish the attempted process identity or confirm its termination, recovery remains **unverified**. The configuration may still contain the candidate and the unfinished recovery journal is retained. Inspect the managed runtime before retrying; do not delete the journal or treat a missing PID receipt as proof that no core is running. Successful operations remove temporary recovery data and retain no historical backup.

`core-timeout` reports a safe stage, elapsed milliseconds and copied-cache count. The default remains 60 seconds. Trusted geodata and explicitly referenced provider resources are copied into isolation; `cache.db` is not reused. Missing resources may still require network access. Check resource completeness and trust before attributing the incident to downloads. Never paste raw core logs or subscription URLs into a report.

`nodes --json` now includes provider identities. Use `mihomoctl latency "NODE" --provider "PROVIDER"` for duplicate names. `ambiguous-node`, `node-disappeared`, `controller-capability-unsupported`, `node-unreachable` and `delay-timeout` describe different failures. Refresh the directory after provider updates. A successful generic probe does not verify a business API.

A rejected 664 script needs private ownership/mode (600), safe ancestors and no symlink; changing the file alone does not fix an unsafe parent. Saving/activation failures report the actual stage and whether original configuration was restored and the core is running, stopped or unverified. A successful preview or a still-running old core does not prove new policy activation. See [override tutorial](overrides.md).
