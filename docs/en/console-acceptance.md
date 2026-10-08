# Console acceptance and rollback

## Local verification record (2026-10-08)

- Ubuntu 22.04 / Python 3.10: 185 Python regressions, 181 passed and 4 skipped; 52 Shell tests and 6 audit regressions passed.
- The skips were three Node cases and one optional user-script case. Windows / Python 3.9 passed seven policy cases, including the Node cases; the optional user script was not supplied.
- Textual 8.2.8 Pilot, real PTY q/Ctrl+C/resize restoration, real Mihomo v1.19.32 and offline venv installation/reuse/bad-hash rollback passed. Page-switch/exit interaction passed three additional repetitions.
- Bash syntax, ShellCheck, Python 3.8 syntax, bilingual links and the release-source snapshot secret scan passed. Private notes are excluded from that source scan.
- Actual user systemd, two real UIDs and remote SSH/tmux/screen acceptance remain unverified. Optional UI CI for Python 3.9/3.12 is configured; consult the workflow for the exact commit's remote results.

Automated tests use fictional credentials, disposable HOME directories, real loopback HTTP/sockets, PTYs and Textual Pilot. Installation/update fixtures replace systemd. Passing them does not establish real user-service, multiple-UID or SSH acceptance.

Run the existing Linux checks: `bash tests/test.sh`, `python3 -m unittest discover -s tests -p 'test_*.py' -v`, `bash tests/audit-test.sh`, `bash tests/docs-test.sh`, `bash tests/secret-scan.sh` and `git diff --check`.

Optional UI tests require the locked dependencies. A prepared private wheelhouse in test-only `MIHOMO_TEST_WHEELHOUSE` enables real offline venv installation, reuse and hash-failure rollback tests. This variable is consumed only by tests; production has no gate bypass. CI separates base checks and Python 3.9/3.12 optional UI checks.

On a dedicated Linux host, have its administrator prepare two ordinary accounts in advance. The product never creates accounts or elevates privileges. Give each account its own private config, credentials, user service and mixed/controller ports.

1. Verify authenticated loopback-only listeners, disabled anonymous access and independent operation without enabling/linger changes.
2. Have A occupy B's intended port, including wildcard and IPv6 cases. B's start/restart must block before touching its service. A's process, B's config/port and parent-shell environment remain unchanged. An unrelated same-UID listener must also block.
3. Verify idempotent start for the target service and post-restart MainPID/cgroup ownership. Unavailable ownership, user manager or authentication evidence cannot pass.
4. Check cross-UID private-file denial and current-UID-only diagnostics; no foreign environment/argv reads.
5. Exercise real Mihomo selection, latency, providers, rules, traffic, logs and DNS. Automatic groups remain read-only and existing connections remain open. Core failure shows stale data; recovery reconnects without replaying writes.
6. Stage subscriptions, then inject source/candidate drift, bad hashes, core validation, disk and lock failures. Active bytes must remain unchanged. Successful writes produce 0600 backups and preserve every non-proxies field, with separate restart.
7. Exercise SSH PTYs, tmux/screen, 60×14/80×24/large sizes, resize, Ctrl+C, q and exceptional exit. Terminal settings restore, SSH disconnect does not stop the user service, and reentry works.
8. Compare all eight parent proxy variables byte-for-byte around TUI, node, mode and lifecycle actions. Recheck exec/direct child status, Codex preflight 0/1/2 and credential-free argv/exports.

Do fault/interruption tests only on the dedicated host, never real workloads. Record unexecuted scenarios as unverified.

For UI rollback choose `--engine curses` or `--plain`. Use the installer's private backup/restore command for code rollback, preserving subsequent config edits. Restore a configuration backup only after explicit selection, Mihomo validation and drift checking, then atomically replace; restart separately. Failed subscription downloads/applies retain the active config. Raw/candidate files contain sensitive material and must remain private and outside Git. An incomplete rollback must identify remaining resources and recovery paths, never claim success.
