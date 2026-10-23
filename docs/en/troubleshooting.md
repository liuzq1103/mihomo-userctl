# Installation and runtime troubleshooting

- Complete bundle cannot find its core: keep the entire extracted directory, verify its checksum and permissions, and use the first-run wizard. Source archives, wheels and legacy wheelhouse kits do not include a core. For new setup follow [initialization](setup.md), reuse a trusted core or explicitly install the fixed version, then init once. Do not reinitialize existing managers or blindly run core install.
- NAS/wheelhouse permissions rejected: copy all required materials to an owned private directory and verify there. Do not recursively loosen permissions. Check the [two offline layouts](offline-install.md).
- Python/target mismatch: use the complete Linux x86_64 bundle on supported Ubuntu hosts; source/wheelhouse installations must also check their system interpreter; do not force another target's kit. Prepare missing strict-offline cores/dependencies beforehand.
- Installer's subsequent download fails DNS: check that the entire installation shell is inside exec; an outer pipeline's right side does not inherit its left side's environment.
- Bash reports HTML or a syntax error involving '<': the response may be a region/login page. curl -f does not reject HTTP 200 HTML. Stop execution and follow [download review and proxy inheritance](first-run.md#install-a-third-party-cli-through-the-proxy); never disable TLS verification.
- init succeeded but exec fails its health gate: initialization leaves the runtime stopped by default. Explicitly start when ready, then check configuration, ports and logs. Do not bootstrap a missing core through its own stopped proxy.
- Local requests work without remote routing: advanced CLI init defaults to MATCH,DIRECT; the new-user simple wizard configures Proxy routing. Review the actual active configuration. Check NO_PROXY and actual client connections using [layered verification](first-run.md).

## All nodes fail delay tests / unknown-node / missing references

Run `mihomoctl nodes --json` and compare the core's exact node names with the requested name printed in the error, including spaces and flag emoji (🇺🇸 and US are different). `unknown-node` means the name was absent at the pre-check; delay HTTP 404 becomes `node-not-in-core`, meaning it is absent when the probe runs. Group results include `missing_member_count` and up to five `missing_members`; numbered-menu guidance and Textual `: chain` explain dangling references.

Inspect `mihomoctl providers --json`, subscription/provider loading and `mihomoctl logs`. Check upstream renames, readable provider caches and successful loading. Explicitly run `mihomoctl provider refresh NAME` if appropriate, or review and reimport the subscription. After saving configuration, run `mihomoctl restart`, then recheck the core proxy table. A disk configuration or stale UI snapshot does not prove a node is loaded.

503 `node-unreachable` means the node exists but its probe failed; 504 `delay-timeout` means the probe timed out. Check node reachability, outbound networking and access to `https://www.gstatic.com/generate_204`; these are not unsupported-API errors. Successful delay does not verify model requests. The complete bundle includes Textual with individual/batch delay tests; run `mihomoctl` and open Nodes. The numbered menu supports basic selection, while `mihomoctl tui --engine curses` offers the `t` shortcut. See the [terminal guide](console.md). Probe settings require the literal prefix `group "NAME"` or `provider "NAME"`; probe a Selector's underlying provider.

Report controller, core, initialization, runtime and real remote requests separately as PASS/FAIL/UNVERIFIED. Do not publish raw credentials or connection details.

## Update or recovery refuses to continue

`installation-console-open` means another interface for this account is open: close it, then retry; the core can remain running. `operation-committed-cleanup-pending` means the change is already committed but cleanup needs retrying, not that the old version is still active. The next locked operation resumes cleanup. A recovery error or drift warning preserves temporary material to avoid overwriting unrelated edits; inspect the redacted error before retrying. There is no historical rollback command or restore button.
