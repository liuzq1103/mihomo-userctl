# Updating mihomo-userctl

[中文](../zh-CN/update.md) · [Documentation](README.md) · [Agent update prompt](agent-update-prompt.md)

This updates the **controller and Bash integration only**. It does not upgrade the
Mihomo core, change subscriptions/providers/routing, start or enable services,
configure linger, use sudo, set a system proxy, or stop processes. Existing
service active/enabled states are preserved, including an enabled service.

The updater in the 0.2 source series requires Linux, Bash 5+, Python 3.8+, the
existing controller dependencies and a working systemd user manager. This source
change does not itself publish a GitHub release. Use an actually published stable
`vX.Y.Z` release that contains `release-manifest.json` with update protocol 1;
pre-update releases are incompatible. A latest-release query does not certify
compatibility. Run the dry-run before applying.

## Commands and results

Both Git and ZIP installations use the same installed command. The original
checkout, source archive and `.git` directory are unnecessary after installation.

```bash
mihomoctl update --check
# Set this to the exact published stable tag you have chosen, not main or latest.
UPDATE_TAG='vX.Y.Z'
mihomoctl update --version "$UPDATE_TAG" --dry-run
mihomoctl update --version "$UPDATE_TAG"
rc=$?
printf 'update_rc=%s\n' "$rc"
```

`--check` reads installation metadata and the official latest published release;
it does not modify the active installation. Finding a newer version is a successful
query. `--dry-run` downloads, safely extracts and runs the target's required
validation in a private temporary directory. It reports the exact tag/commit,
archive identity, files, recorded paths, checks and backup/rollback plan, without
replacing active files or changing service state. It may create private temporary
and lock directories. Applying always requires an explicit tag. Prereleases,
drafts, branch names, a moved already-installed tag, and downgrades are refused.

| Exit | Meaning |
| --- | --- |
| 0 | Successful query or dry-run, including an available update |
| 1 | Download, validation, install or final invariant check failed; inspect the separate file/rollback results |
| 2 | Invalid options, unsupported version, unknown/unsafe paths or metadata, or local changes requiring review |
| 3 | Exact release installed (or already installed); end-to-end acceptance still UNVERIFIED/DEFERRED |
| 4 | Another install, update or uninstall holds the operation lock |
| 5 | Files installed and preserved-state checks passed, but the listener acceptance verifier reported FAIL |

Do not treat every nonzero exit as a failed file installation. Do not turn 3 into
“all checks passed.” On 5, inspect the listener/authentication evidence; the updater
does not restart the service or undo a valid file update to conceal network errors.
The one-time migration command below uses the same exit meanings. The standalone
[acceptance script](acceptance.md) has its own documented exit codes.

## Provenance and validation

Only `liuzq1103/mihomo-userctl` on GitHub is used. The updater resolves the published
tag through the GitHub API, peels annotated tags to a full commit, and downloads the
generated source ZIP from `codeload.github.com` using **that commit**. No `curl | bash`
or dependency on a mutable `main` checkout is involved. Non-official redirects,
links/devices, traversal, case-colliding entries, multiple archive roots, encrypted
entries, excessive size/count, damaged ZIPs and incomplete releases are rejected.

The record contains release ID, tag, commit, archive URL and locally calculated
SHA-256. This is a generated source archive, not an uploaded binary release asset.
There is no separate official archive digest or signature used by this flow:
independent digest/signature verification is **UNVERIFIED**. HTTPS and GitHub's
tag-to-commit mapping are the actual source checks; a calculated hash alone is not
publisher authentication. Git-origin first installs record the local HEAD and
dirty state, not a verified official history. Unrecorded ZIP history stays unknown.

Protocol 1 requires matching version markers and the `installation-v1` profile:
Bash syntax; isolated installer/Shell regressions; acceptance verifier regressions;
audit-tool failure regressions; documentation/link checks; configured secret
patterns. These run with a disposable HOME and fake services. This is validation
of trusted official release code, not an operating-system sandbox for hostile code.
Each command has a bounded timeout. Missing tools or failed tests stop the update.
CI separately exercises updater integration, including failures and rollback.

## Paths, local changes and preservation

New installations record the actual HOME, XDG_CONFIG_HOME, XDG_DATA_HOME, executable
and Shell startup file. Absolute, owned paths without symlink components or
group/other-writable target directories are required; startup files stay inside
HOME. Custom XDG paths and `--bashrc` files are supported. Installed launchers use
these recorded paths even if a later terminal does not export XDG variables.
Moving an installation to another HOME/path layout requires a reviewed migration;
the updater does not guess alternate paths or scan other users' installations.

The installer owns locking, transaction backups, replacement and rollback. Each
version lives in an immutable `generations/<id>` directory. Stable launchers pin
one generation per invocation; one atomic `current` symlink publishes all new
modules together, including the updater itself. Old generations remain for running
clients and rollback; there is currently no automatic garbage collection.

The effective changed scope is project code, provenance and the current pointer.
The shared installer snapshots/replaces the stable launchers and managed startup
block; protocol 1 rejects a change to their layout. It preserves the exact existing
`mihomo-shell.conf`, `client.env`, port, unit name and non-managed startup content.
The Mihomo binary, config.yaml, subscription/provider/node/routing files and unit
are never installation targets. Final checks compare configuration bytes/modes,
startup content outside the block and service state. Normalized or symlinked paths,
unsafe permissions, edited installed code, edited managed loader, or a recorded
dirty source installation stop automatic updating. Keep private settings in the
configuration files. Review/rebase code customizations separately; do not delete
hashes or rewrite metadata to bypass the check.

## One-time migration for older Git or ZIP installs

An old `mihomoctl` may have no `update` command or origin record. Report its historical
source as **unknown** unless separately evidenced. Do not invent a historical commit.
Obtain and inspect an official source release containing `scripts/migrate.py`; the
original installation directory may already be deleted. For a Git copy, check out
the chosen published tag, inspect the resolved commit and verify the tree is clean.
For a ZIP copy, use the official release source, inspect archive paths before
extracting, and review the extracted helper/installer. Do not execute unreviewed
downloads or pipe a network response into a shell. The helper then independently
fetches the chosen published release by immutable commit using the same safe
downloader/validator as `update`.

From that inspected source directory, provide all original paths explicitly:

```bash
# Examples only: replace these with paths established from the existing install.
CONFIG_HOME="$HOME/.config"
DATA_HOME="$HOME/.local/share"
STARTUP_FILE="$HOME/.bashrc"
UPDATE_TAG='vX.Y.Z'
python3 scripts/migrate.py --version "$UPDATE_TAG" \
  --config-home "$CONFIG_HOME" --data-home "$DATA_HOME" \
  --bashrc "$STARTUP_FILE" --dry-run
python3 scripts/migrate.py --version "$UPDATE_TAG" \
  --config-home "$CONFIG_HOME" --data-home "$DATA_HOME" \
  --bashrc "$STARTUP_FILE"
```

Review existing managed code for local customizations before applying: old installs
have no trustworthy hashes to distinguish customization automatically. Migration
replaces that managed code. No port argument is needed: the existing configuration
and credentials must validate. The helper uses the same installer transaction,
preserves service state and records the newly installed release's provenance; it
does not retroactively establish the old source. It requires a recognizable old
version and flat installation at the explicit paths. A generation installation
with missing/corrupt metadata must first restore its matching backup; it is not a
flat legacy migration. If paths or version cannot be established, resolve those
specific diagnostics locally before writing anything.

## Failure recovery and rollback

Network/API rate limit, TLS, archive or validation failure leaves active files
untouched. Retry the same explicit target later; there is no automatic downgrade,
mirror fallback or switch to main. Repeating the exact installed release is a
no-op after integrity and provenance checks, with acceptance still pending.

Every application reports a private backup under the recorded
`XDG_DATA_HOME/mihomo-userctl-backups/install-...`. It contains `manifest.tsv`,
the original managed files, `transaction.json`, `result.json` when available,
and the installer's self-contained recovery helper. Backups may contain private
startup settings: keep the directory private and do not paste or upload it.

Use the **exact command printed for this transaction**, for example:

```bash
BACKUP='/absolute/path/from-the-update-report/install-...'
python3 "$BACKUP/restore.py" rollback "$BACKUP"
```

This needs neither the old source directory nor a working `mihomoctl` or systemd
manager. It acquires the same operation lock, restores original managed files and
the prior generation, and leaves the core/service untouched. Repeating a completed
rollback is a no-op. A stale backup cannot replace a later generation. Changes to
snapshotted files after the update cause rollback to refuse rather than overwrite
new personal edits; privately compare/merge them before recovery. Do not restore
only a controller or individual module from a different generation.

Ordinary install failure triggers installer rollback. SIGKILL/power loss can leave
`pending-install.json`; subsequent changes are blocked until its recorded backup
is recovered. During a normal generation update the stable launcher sees either
the old or new complete generation. A legacy migration interrupted while replacing
flat launchers may need the backup helper before `mihomoctl` works again. A
rollback itself can fail on disk/permission errors: report **UNVERIFIED**, inspect
the private backup, and repair the filesystem; do not claim restoration succeeded.

## Acceptance and reconnecting

Reports keep these claims separate:

| Item | Evidence and normal status |
| --- | --- |
| Files installed | Actual installed version/commit and installed file hashes: PASS only after final checks |
| Preserved environment | Before/after configuration and active/enabled comparison |
| Listener/authentication | Existing acceptance probes only if service was already active; otherwise UNVERIFIED |
| Actual target uses a proxy node | UNVERIFIED until target rule and selected-node/egress evidence; reaching a local listener is insufficient |
| Fresh Shell loads new code | DEFERRED until user opens a new terminal and checks version/functions/hook |
| Long-lived Codex/VS Code | DEFERRED until own client reconnects, gets a new process and is verified |

The updater never starts a stopped service for acceptance. It never stops a service
for lifecycle testing. Open a new terminal after update or rollback; already loaded
Bash functions keep the old code. Reconnect only your own long-lived remote clients
at a suitable time. The updater does not kill them. Follow the
[acceptance evidence guide](acceptance.md) for target routing and client checks,
without printing credentials, full proxy URLs or subscription URLs.
