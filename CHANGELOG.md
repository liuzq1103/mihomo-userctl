# Changelog

## [1.4.2] - 2026-10-27

- Render edited policy containers as readable block YAML while preserving types, comments and untouched text.
- Validate in private staging with trusted resource copies; reuse only process-local proofs bound to unchanged inputs. Reject changes before stopping the old core.
- Discover provider nodes and use provider-scoped healthcheck routes, including duplicate-name disambiguation and safe failure categories.
- Show batch latency failures, cancellations and completion counts; replace stale numeric results and support explicit global targets with `--global`.
- Sanitize the complete pinned-core systemd override vocabulary and proxy environment; regenerate existing units with `service install` after upgrading.
- Preserve specific private-path errors and report save/activation/recovery state without raw core diagnostics.
- Strip the known FlClash status marker without widening host-setting permissions. Add explicit `--policy policy` overlays for server routing fragments.
- Keep current-only retention, fixed Mihomo v1.19.32 and all existing two-Ubuntu delivery gates. Production incident root cause and remote business availability remain unverified.

## [1.4.1] - 2026-10-24

- Remove duplicate Python executables and the development libpython alias while retaining the complete offline terminal experience.
- Trim headers, ensurepip, IDLE and their unused wrappers after dependency installation; verify the pinned runtime layout and ELF dependencies before pruning.
- Gate both Ubuntu targets on a real 1.4.0 portable upgrade with a running authenticated core, preserving process identity, configuration and node selection.
- Enforce decimal-byte archive, expanded and first-install budgets and report physical allocation and sampled temporary peaks.
- Avoid uploading the second identical portable artifact; publish only validated main CI outputs through a resumable draft workflow.

## [1.4.0] - 2026-10-23

- Ship a relocatable Linux x86_64 bundle with pinned Python, Textual, dependencies and Mihomo; no target venv or pip setup.
- Open the terminal UI on interactive invocation and provide private subscription URL input, simple node routing and confirmed save/start onboarding.
- Keep only current code/core/configuration. Historical rollback is disabled; recover unfinished transactions automatically and remove temporary recovery data after completion.
- Add network-isolated two-UID and real SSH/PTY acceptance on both supported Ubuntu targets, including Unicode/search/resize, authentication, selection persistence and package/startup/memory measurements.
- Retry conflicts on managed auto-assigned ports without stopping foreign processes. Preserve selected nodes across restarts.
- Refuse manager replacement while another console is open, recover interrupted operations before new work, and retry committed cleanup durably.
- Keep every implicit extraction directory private even with a shared-server umask; publish SSH evidence after restoring the test account home.
- Parse subscription payloads in memory, discard cancelled previews and expire abandoned previews after 24 hours on the next UI/subscription operation.
- Preserve business CLI and JSON envelopes; interactive no-command calls now open the UI. `rollback` remains a compatibility error reporting `historical-rollback-disabled`.
- Update Chinese/English installation, console, subscription, troubleshooting, update and release documentation; distinguish complete bundles from legacy Python kits and historical release records.

This release intentionally removes historical program/core/configuration backups. Temporary recovery material exists only for unfinished operations; recovery failures preserve necessary material and report an error.


## [1.3.0] - 2026-10-22

### Added

- `mihomoctl reset --dry-run | --apply` returns the managed runtime to the
  configuration `init` produces. The core configuration was previously only
  ever generated once, by `init`, which itself refuses to run over an existing
  manager; every later change (subscriptions, rules, probe settings, TUN) was
  a top-level key replacement on top of it, and the only undo was a
  single-level, in-memory `restore()` reachable from the Textual UI alone.
  `reset` previews and applies from one removal list: it stops the runtime,
  backs up and removes the manager configuration, the active core
  configuration, every private credential file and the leftover
  `.before-policy-*` backups and restart receipt, then republishes the same
  default shape with fresh ports and secrets. The Mihomo core binary, the
  subscription previews and the logs are preserved; the replaced credentials
  stay in the `reset-*` transaction journal. `reset --core PATH` re-initializes
  from a different core. Documented in `docs/{en,zh-CN}/setup.md`.
- Textual is now installed privately, in the user's own generation directory,
  like PyYAML already was. `bash install.sh --user --python PYTHON
  --wheelhouse DIR --extras tui` stages `textual==8.2.8` and its transitive
  dependencies into the read-only generation `lib`. No sudo, no system pip,
  no third-party index. `mihomoctl update` and `mihomoctl update --latest`
  accept the same `--extras`/`--no-extras` pair; an upgrade inherits the
  extras recorded by the previous generation.
- An inherited extra that a new wheelhouse cannot resolve is carried forward
  from the previous generation, file by file, only for packages attributed to
  that extra and re-hashed against their recorded digests. Anything that
  cannot be attributed is dropped loudly (`extras-dropped`) instead of
  silently disappearing. Unknown extra names fail closed with
  `unknown-extra`.
- `mihomoctl` with no command, and `mihomoctl --help`, now print a grouped
  command guide with a one-line description per command. The bare invocation
  still exits 2 with the unchanged `usage-error` envelope.
- Health reporting names the group members that are absent from the core
  proxy table (`missing_members`, `missing_member_count`), so a dangling
  subscription reference is visible instead of only inferable. The
  `selected_chain` verdict itself is unchanged.
- `docs/{en,zh-CN}/console.md` expand from a five-line stub into a real guide:
  which front end has a speed test, how to install Textual privately, what
  each delay outcome means, the full key map and the probe syntax.
  `docs/{en,zh-CN}/troubleshooting.md` gain an entry for every node failing
  the delay test.

### Fixed

- `GET /proxies/<name>/delay` returning 404, 503 or 504 all collapsed into one
  opaque `controller-request-failed`, which hid the actual cause: 404 means the
  name is not in the core proxy table at all. They are now `node-not-in-core`,
  `node-unreachable` and `delay-timeout`, with a label in the CLI, plain menu,
  curses and Textual.
- `unknown-node` echoes the exact spelling that was requested, so a flag
  degraded to a country code or a renamed node can be recognised.
- The curses key legend is laid out by display cell and wrapped to the
  terminal width, instead of being clipped at the right edge. It degrades to
  keys-only, and then to a clipped row, rather than raising on a narrow
  terminal. The pane header is bilingual.
- `invalid-health-check-options` now states that a probe target must begin with
  `group` or `provider`.
- `textual-environment-incomplete-use-engine-curses` keeps its error code but
  its remediation now names both real options: `mihomoctl tui --engine curses`
  (standard library, nothing to install) and the private `--extras tui`
  install.

## [1.2.0] - 2026-10-17

### Added

- `release check` observes the official stable release without claiming that an
  installed version is the latest. Optional interactive status/version/doctor/TUI
  notices use a detached five-second worker, a daily attempt limit and persistent
  once-per-version notification state. JSON, pipes, exec and lifecycle commands
  do not trigger checks. Set `MIHOMOCTL_NO_UPDATE_CHECK=1` to disable notices.
- `release fetch --output-dir DIR` obtains reviewed source archives, wheel,
  checksums, build receipt and release gate from the official project channel.
  `--target` obtains either existing Ubuntu offline kit for transfer to another
  machine. Downloads are bounded and verified before atomic publication.
- `update --latest` acquires one fixed release and delegates to the unchanged
  offline transactional installer. `update SOURCE` remains local and offline.
  Explicit network failures return 2 / UNVERIFIED; optional notices never change
  the original command's exit code. No process restarts or core downloads occur.

### Fixed: pathologically nested release JSON crashed instead of returning UNVERIFIED

- Identified in independent cross-model review of this branch and confirmed by
  two models before the fix. Adversarially deep release JSON (metadata, gate,
  receipt, manifest or bundle manifest) raised an uncaught `RecursionError`,
  which is a `RuntimeError`, not a `ValueError`, so it escaped every existing
  error mapping: `mihomoctl release check --json` terminated with a raw
  traceback instead of the contracted 2 / UNVERIFIED envelope, and `release
  fetch` / `install` could crash the same way while validating a hostile
  release tree.
- Both parse boundaries now refuse such documents through the existing codes —
  `release.read_json` maps them to `release-metadata-invalid`,
  `installation.load_manifest` to `release-manifest-unreadable` — and the
  acquisition wrapper reports deep artifact JSON as `release-artifact-invalid`.
  CLI regressions cover the `release check` envelope, acquisition artifacts and
  the manifest gate. No installer engine behavior and no trust decision
  changed; valid documents parse exactly as before.

### Upgrade from older versions

Existing v1.0.0–v1.1.1 binaries cannot acquire this notification feature by
themselves. **Use the verified 1.2.0 installer** from the complete release tree
or offline kit, with a matching wheelhouse and explicit interpreter as needed.
Do not rely on a notification to discover the upgrade, bypass trust/version
checks, or add obsolete Bash version markers. The installer preserves user data
and reports a self-contained private recovery backup.

## [1.1.1] - 2026-10-16

**Fail-closed fix in subscription policy detection.** `mihomoctl subscription preview`
refused to reinterpret a source that carries no routing policy. No command surface,
dependency or configuration key changes; the exit-code definitions are unchanged.

### Fixed: `auto` treated any extra top-level key as routing policy

- `Subscriptions.preview()` detected provider mode with an exact key-set comparison,
  `set(incoming) == {"proxies"}`. Any additional top-level key therefore flipped the
  whole document to `provider`, where `provider_policy()` defaults every
  `POLICY_FIELDS` key the source did not supply. A paste of `proxies: []` plus
  `secret: bad` was accepted as a provider-policy overlay that replaced all five
  routing fields, clearing `proxy-groups`, `rules`, `proxy-providers` and
  `rule-providers` instead of raising an actionable error. An affected preview now
  exits 1 with `subscription-only-node-list-supported`, where it previously exited 0
  after validating a candidate that silently discarded the user's routing policy.
- `auto` now selects provider mode from the presence of routing policy
  (`ROUTING_FIELDS`, every `POLICY_FIELDS` key except `proxies`) rather than from an
  exact key-set match, which is what `docs/{en,zh-CN}/subscriptions.md` has always
  documented. A node list alongside host runtime keys is refused with the existing
  `subscription-only-node-list-supported` vocabulary, and the refusal precedes core
  validation, so the managed configuration is never touched.
- Detection is unchanged for every documented input: a source with real routing
  policy still selects `provider`, a bare node list still selects `nodes`, an explicit
  `--policy provider` is still an honoured operator decision, and host runtime
  settings in an accepted provider source are still excluded and reported in
  `ignored_fields`.

### Fixed: the shipped regression passed in CI for the wrong reason

- `tests/test_console.py::SubscriptionTests::test_full_config_alias_duplicate_and_nonprivate_rejected`
  asserted a bare `ControlError`. In the unit job the core binary does not exist yet,
  so `preview()` reached `validate_candidate()` and raised `mihomo-executable-missing`,
  which satisfied the assertion without exercising the refusal at all. On an installed
  release the core is resolvable and `mihomo -t` succeeds, so the assertion no longer
  held. Reproduced directly against both environments before the fix.
- The regression dates from v0.9.0, when `preview` refused everything that was not
  exactly a node list. Provider-policy import arrived in v0.9.2, but its two entry
  points disagreed: `Subscriptions.preview` still defaulted to `nodes` and so kept
  refusing extra keys, while `ConsoleService.subscription_preview` defaulted to
  `provider`, which left the console and TUI path fail-open from that release. The
  v1.0.0 runtime rebuild (`bcfa5b3`) unified both on `policy="auto"` with the key-set
  comparison, which extended the fail-open to every entry point and also made this
  regression a false pass. v0.9.0 and v0.9.1 were unaffected on every path.
- Each case now asserts its own error code. A new
  `test_auto_refuses_a_source_without_routing_policy` in `tests/test_tasks.py` runs in
  the environment where the defect is visible, with a resolvable core path and
  `subprocess.run` mocked to succeed so candidate validation would pass. It also
  asserts the core is never invoked. Both tests fail against the 1.1.0 detection logic
  and pass against this release.

### Note: previews saved before upgrading

- This fix is prospective. A preview generated by v1.0.0 through v1.1.0 stores its
  resolved `policy`, and `apply()` reads that stored value rather than re-deriving it,
  so an already saved preview can still be applied after upgrading if the active
  configuration digest still matches. Discard saved previews and generate a fresh one
  after upgrading; no configuration or credential is read or changed by doing so.

### Changed: the release-identity gate no longer repeats a version literal

- `test_all_release_stamps_are_checked_against_pyproject` asserted a hard-coded
  `'1.1.0'` while every other stamp is checked against `pyproject.toml`. The bump to
  1.1.1 failed that gate exactly as it would have failed any future bump. It now
  derives the stamp through `version_from_pyproject()`, so the seven drift-detection
  subtests keep their original property without needing an edit per release.

上一版证据不适用于本版。Publication still requires the tagged 1.1.1 commit's own
two-platform CI, offline kits, acceptance reports and `verified: true` release gate.

## [1.1.0] - 2026-10-13

- Separate packaged runtime/controller/recovery from release tools, CI checks and archived Bash/Paseo implementation. Legacy code and source tooling are excluded from wheels.
- Centralize public CLI grammar, configuration-free help, generated completion/reference and drift checks. Remove fictitious core version completion; support rules check JSON and manager-selected core validation.
- Rewrite bilingual homepages and installation/subscription/rules/Codex/verification/integration tutorials. Archive historical guidance and retain navigation redirects.
- Make pyproject.toml the release version authority; validate runtime/manifest/docs/wheel copies and exact-commit build identity. Remove installer/Bash version-marker dependence.
- v1.0.x upgrades require the verified v1.1.0 installer. Private user data and self-contained rollback are preserved; no implicit service actions, privilege escalation or shell hooks.

## [1.0.4] - 2026-10-13

**Runtime behaviour fix.** `mihomoctl select` and the other bridge commands that take positional
values work without a hand-written `--config`, and a managed configuration always persists Selector
choices across a restart.

### Fixed: bridged commands rejected their own positional values

- `run_bridge` synthesized `--config <path>` by splicing it at index 1, between the command name and
  its values. The child parser takes those values as a `nargs="*"` positional, and argparse cannot
  match an optional that precedes such a positional, so `mihomoctl select "Ai+" "节点名称"` arrived as
  `select --config PATH Ai+ 节点名称` and failed as `invalid-options`. Only a caller-written trailing
  `--config` happened to work.
- The synthesized options are now appended, matching the `--json` and `--home-dir` already in the
  same function. `select`, `latency`, `mode`, `controller status` and `subscription apply` are
  restored; `nodes`/`groups`/`connections`/`traffic`/`ui` take no values and were unaffected.
- argv construction is extracted into `mihomoctl.legacy.bridge_forward` so the contract is unit
  tested against the real child parser.

### Fixed: Selector choices reset to the first member on every restart

- `compose_core_config` never emitted a `profile` block, and `controller initialize` returned
  `unchanged` as soon as `external-controller` was present — which the managed configuration always
  sets. `profile.store-selected: true` therefore never reached a standard V1 install, so the core
  discarded every Selector choice on a cold start and the group fell back to its first member (an
  airport `Expire: …` information node in practice).
- `mihomoctl init` and the `--config` import path now write `profile.store-selected: true`,
  preserving any other imported `profile` keys.
- `mihomoctl controller initialize` backfills the key on an already configured controller. **This is
  a one-time write to an existing installation** and reports `restart-required`; the controller
  address and secret are carried over and never regenerated, and a second run is a byte-identical
  no-op. The listener and port-conflict checks still run only while the controller is unconfigured.

### Fixed: the process backend let the core inherit a permissive umask

- The managed systemd unit already runs the core with `UMask=0077`, but the process backend inherited
  the caller's shell umask, leaving `cache.db` and downloaded geodata at `0644`. `start()` now sets
  `0077` around the spawn and restores the previous mask in a `finally`. An existing `cache.db`
  becomes `0600` on the next start; its contents are unaffected.

上一版证据不适用于本版。No 1.0.1/1.0.2/1.0.3 result approves this release. Publication still
requires the tagged 1.0.4 commit's own two-platform CI, offline kits, acceptance reports and
`verified: true` release gate.

## [1.0.3] - 2026-10-12

无运行时行为变更。This patch completes the reviewed source release inventory
and aligns acceptance instructions with the existing V1 checks. The V1 runtime
file set and installation/update/verification/rollback implementations are
unchanged; the five release-version markers advance together to 1.0.3.

- Include the previously referenced `scripts/paseo.py` and `tests/test_paseo.py`
  in Git and the source-only manifest inventory; neither enters the V1 wheel.
- Add a V1 regression requiring legacy installation payload references to be
  declared and present, and validate the complete source inventory with the
  production verifier.
- Replace full historical test discovery in both acceptance pages with the
  existing V1 unit and pinned real-core runners, list prerequisites, and require
  umask 022 for isolated regression.

上一版证据不适用于本版。Publication requires the tagged 1.0.3 commit's own
two-platform CI, offline kits, acceptance reports and `verified: true` release
gate. No 1.0.1/1.0.2 result approves this release.

## [1.0.2] - 2026-10-12

- Check all five source release-version markers before installation or building;
  `install.sh` now carries an explicit VERSION marker.
- Dry-run and installation validate dependency versions, wheel metadata/integrity,
  and compatibility using the selected interpreter. Importing PyYAML 5.4.1 no
  longer incorrectly satisfies the declared PyYAML>=6.0.1 requirement.
- Add complete, target-specific offline control-plane kits with hash-locked
  dependency wheels, nested checksums and commit/target provenance. Both supported
  Ubuntu targets require actual network-isolated kit acceptance before publication.
- Reject bytecode in release archives/wheels and replace historical offline
  instructions with the current V1 flow and independent-provenance requirements.
- No automatic installation of Mihomo, OpenCode, Codex or Node; existing system
  and Conda dependencies, shell startup files and services are preserved.

Publication requires the exact tagged commit's CI release gate, including both
target kits. Historical 1.0.1 evidence does not approve 1.0.2; the release notes
link the actual 1.0.2 acceptance run and artifact digests.

## [1.0.1] - 2026-10-12

**Documentation and release-tooling patch. No runtime behaviour changes:** the
installed control plane, its command surface, its exit codes and its
`release-manifest.json` inventory are unchanged apart from the version marker.
The installer, the updater, the core-installation gate and every acceptance
suite behave exactly as in 1.0.0.

**Acceptance status: VERIFIED.** The release gates pass on both supported
platforms. On the fully verified tree `505a137`, CI run `38220035037` reported,
identically for Ubuntu 22.04 (Python 3.10) and Ubuntu 24.04 (Python 3.12): unit,
controller and TUI regression 331 passed, 0 failures, 15 environment-gated
skips; real-core regression 59 passed, **0 skipped**; offline install, update and
self-contained recovery of the complete source tarball, zip and wheel 3 passed,
**0 skipped**; real users, systemd and isolated TUN 6 passed, **0 skipped**, with
`real_uids`, `systemd` and `tun` all true. `scripts/verify_release.py` accepted
the exact-commit artifacts and both Ubuntu evidence sets (`verified: true`).
An independent read-only review (MiniMax-M3, with GLM as executor) found no
blocking issues. Publishing is bound to the tagged commit's own CI run and gate
result.

### Fixed: agent installation prompts follow the V1 gates

- `docs/{en,zh-CN}/agent-local-install-prompt.md` now carry the same "archived
  0.9.x steps" banner as `setup.md` / `offline-install.md` / `quick-install.md`,
  and state that INSTALL.md is the single authoritative V1 installation flow and
  that offline-install.md's bundle steps are migration reference only.
- Version checking is now the three cross-checks the V1 installer actually
  performs: `release-manifest.json` ↔ `pyproject.toml`,
  `release-manifest.json` ↔ `mihomoctl/__init__.py`, and the project wheel's
  `Requires-Dist` ↔ `release-manifest.json` `dependencies`. The prompts no longer
  require checking `install.sh`'s `VERSION=` or `src/common.bash`'s
  `MIHOMO_USERCTL_VERSION`: neither file is in the manifest `runtime_files`, V1
  never installs them, and demanding them produced a false "version mismatch"
  missing item.
- `scripts/offline_install.py` keeps its name in both prompts but is now described
  only as a counter-example: `check`/`install` are retired and only print
  `legacy-installation-entry-retired` with exit code 2.
- The prompts document the V1 install flow from INSTALL.md
  (`install.sh --wheelhouse … --dry-run`, the real install, `mihomoctl version`,
  `bootstrap.py verify`), when `--wheelhouse` may be omitted (the selected
  interpreter, `/usr/bin/python3` by default, can already `import yaml`), and that
  dependency wheels must carry a matching platform tag — the Windows/CPython 3.9
  `pyyaml-6.0.3-cp39-cp39-win_amd64.whl` in the local `.tmp-v1-ui-wheels/` is
  rejected by `wheel_compatible_here()` and cannot be used.
- `SHA256SUMS` is a build artifact and not a source-tree file, so it is no longer
  treated as a missing input.

### Fixed: the documentation contract is actually enforced

- `tests/docs-test.sh` and `tests/audit-test.sh` were never executed by the V1 CI
  workflow — only the 0.9.x `scripts/update.py` invoked them — so the assertions
  below their `exec` line were dead code and the documented command surface could
  drift unnoticed.
- Every assertion that still describes the V1 product was migrated into
  `scripts/check_docs_v1.py`, the gate the workflow actually runs: bilingual
  topic-set completeness, the maintainer-specific routing-policy ban, the private
  value ban, README installation entry and language navigation, the generic
  prompt's required markers and product-specific interface ban, the legacy prompt
  pointers, and the ban on pre-expanded bundles.
- The assertions that pinned retired content were removed instead: paseo daemon
  markers, first-use handoff markers V1's rewritten `first-run.md` no longer
  uses, `scripts/offline_install.py`, `--bundle-dir` and the retired `install.sh`
  port-suggestion flag, the 90-line budget for the generic prompt, and the
  assertion that the deleted `CODEX_REMOTE_PAYLOAD` hook is still present in
  `src/shell.bash`.
- A stricter check replaces them: every `install.sh --<flag>` in `docs/**/*.md`
  must exist in `scripts/bootstrap.py`'s argparse (or in `install.sh`'s own
  `-h` / `--help` / `--rollback`). Run against the 1.0.0 tree it reported 15
  occurrences of the retired `--suggest-port`, `--port`, `--with-textual` and
  `--tui-python` flags across five live pages (`docs/architecture-vnext.md` and
  the English/Chinese console and generic installation prompts); those are fixed
  and the gate now reports zero.
- `tests/audit-test.sh` injected a broken `find`/`grep`, which no longer affected
  the Python gates it was auditing. It now injects a failing interpreter, asserts
  that neither wrapper can report success, and runs in the workflow next to the
  other static checks.

### Fixed: one source of truth for the release version

- `scripts/build_release.py` derived artifact names from a hard-coded literal in
  four places. `VERSION` now comes from `release-manifest.json`, the output guard
  matches any `mihomoctl-*` artifact, and the `dist-info` prefix follows
  automatically.
- `scripts/verify_release.py` follows the version recorded in the exact-commit
  build receipt instead of a second hard-coded literal.
- `src/common.bash`'s `MIHOMO_USERCTL_VERSION`, `pyproject.toml`,
  `mihomoctl/__init__.py` and `release-manifest.json` move to `1.0.1`;
  `tests/test_v1_installation.py` and `tests/test_v1_acceptance.py` follow the
  manifest instead of repeating the version.
- Page-level release stamps (`INSTALL.md`, the README set and the documentation
  entry pages) move to `1.0.1`. Historical records — the `[1.0.0]` changelog
  section, `docs/release-review.md`, the accepted ADR and architecture status
  lines, the archived paseo pages and the roadmap — keep `1.0.0`.

## [1.0.0] - 2026-10-12

**Acceptance status: VERIFIED.** The mandatory release gates pass on both
supported platforms. On the last fully verified tree `dee8d0a`, CI run
`38206912788` reported, identically for Ubuntu 22.04 (Python 3.10) and
Ubuntu 24.04 (Python 3.12):

- unit, controller and TUI regression: 331 passed, 0 failures, 15 skipped.
  Every skip is environment-gated and each scenario runs for real inside a
  dedicated suite below.
- real-core regression: 59 passed, **0 skipped** — authenticated listeners,
  listener separation, port conflicts, invalid configuration, crash reporting
  and explicit restart recovery, and core-update rollback.
- offline install / update / self-contained recovery of the complete source
  tarball, zip and wheel: 3 passed, **0 skipped**.
- real users, systemd and isolated TUN: 6 passed, **0 skipped**, with
  `real_uids`, `systemd` and `tun` all true. This is the suite that exercises two
  genuine UIDs on one VM, the user and system service lifecycle with crash
  recovery, environment inheritance through a loaded `EnvironmentFile=` drop-in,
  and TUN enable / managed restart / `SIGKILL` recovery / status / disable /
  route restoration, plus the refusal to adopt a foreign device and the
  preservation of the active generation when that refusal fires.

`scripts/verify_release.py` accepted those artifacts and evidence for that exact
commit (`verified: true`), confirming the three release assets, their SHA256
digests, `SHA256SUMS`, and that the artifacts actually installed in CI are the
artifacts selected for publication.

Scope of the claim: this establishes the tool's own behaviour and boundaries. It
does **not** establish model end-to-end success, and it is not a claim about any
third-party upstream's signing or reproducibility. Publishing is bound to the
tagged commit's own CI run and gate result — `scripts/verify_release.py` refuses
a dirty worktree, a different commit, a missing Ubuntu acceptance report, any
skipped mandatory suite, or mismatched asset digests.

### Breaking: the automatic shell hook is removed

- The installer no longer writes any startup file. `.bashrc`, `.zshrc`, `profile`,
  managed loaders, aliases and functions are left untouched; `--bashrc` is no longer
  accepted.
- The `CODEX_REMOTE_PAYLOAD` branch is deleted. The fail-closed gate itself is
  retained and is carried by the generic `exec` entry point and `health` check.
- Existing installations must run `mihomoctl migrate --dry-run` and then
  `mihomoctl migrate --apply`. Migration removes only a positively identified project
  loader, preserves every other byte and backs up every file it touches. A customized
  or ambiguously shaped loader is refused.
- The old Shell helper entry is retired and refuses execution when sourced.
  Use explicit `mihomoctl exec`, `direct` and `env show|export` instead.

### Breaking: third-party application lifecycle is retired

- `mihomoctl paseo start|stop|restart|run|install-unit` no longer manage a daemon.
  Old invocations return migration guidance and never start, stop or replace a
  third-party process or unit. Nothing is ever stopped automatically, and a leftover
  managed unit is only detected and reported.
- `mihomoctl codex`, `mihomoctl codex preflight` and the old application-specific
  `diagnose codex` entry are retired. They do not act as compatibility aliases.
  Use `mihomoctl exec -- COMMAND`, `mihomoctl health check` and `mihomoctl doctor`.
- Use `mihomoctl integration install NAME` to write an owned unit drop-in and reload
  its manager. Applying the new environment to a running consumer remains an
  operator-managed action.

### Breaking: new scope and module model

- Default scope is `user`; every system-scoped change requires an explicit `--system`.
  UID 0 is not promoted automatically, and the tool never self-escalates.
- Default user backend is `process`; switching to `systemd` is explicit and only
  applies to a stopped managed runtime. There is no silent backend fallback.
- `mihomoctl start`, `stop`, `restart`, `status` and `logs` remain the first-tier commands
  that manage the Mihomo runtime itself, and they are what the default process backend
  uses. `mihomoctl service install|start|stop|restart|status|uninstall` is offered in
  parallel for the systemd backend; it does not replace the top-level lifecycle verbs.
  Only the third-party `paseo start|restart` is retired.
- `mihomoctl init --core PATH` creates managed configuration, credentials, a default
  profile and one loopback-only authenticated named mixed listener.
- Core installation uses a fixed version and the maintainer pin; unknown versions
  require an explicit `--sha256 DIGEST`. No digest-verification bypass exists.
- TUN is an independent module, disabled by default, enabled only by an administrator
  via `--system tun enable` inside one rollbackable transaction. V1 grants the managed
  service `CAP_NET_ADMIN` only while enabled; administrator-only access is the V1
  permission policy.

### Added

- Runtime status reporting seven facts on every view: core, controller, every
  listener, the active config, the proxy layer, the Mihomo routing mode, TUN and
  errors. A missing fact renders as `unknown` / `UNVERIFIED` rather than as healthy.
- Declarative bindings and adapters for `exec`, `systemd`, `docker`, `kubernetes`,
  `supervisor`, `pm2` and `ci`. Docker/Kubernetes/PM2/Supervisor/CI are export only
  and are never deployed or restarted automatically.
- Proxy profiles resolved from named listeners, with redacted projections and no
  credentials in the template.
- Generic runtime health with per-check evidence levels and fixed boundary statements.
- New console pages: `subscriptions` (the subscription work, previously labelled
  "profiles") and `profile` (proxy profiles, bindings and environment boundaries).
- A dedicated runtime page in both the Textual console and the plain menu showing the
  seven facts.

### Changed

- The console no longer re-enters the Bash CLI in a subprocess; runtime, health,
  profile, lifecycle and journal answers come from the shared application service or
  are reported explicitly UNVERIFIED.
- Without an application service the console reports UNVERIFIED with a reason and
  never returns a guessed success.
- Systemd integration writes a private `proxy.env` and a marked drop-in and reloads
  only its own manager. The written `proxy.env` contains real proxy URLs and
  credentials, so it is a private sensitive file (mode `0600`, owned by the running
  account, never merged with the core config or credential file); `EnvironmentFile=` is
  an integration format, not a secret isolation mechanism.
- Bilingual documentation rewritten around the V1 contract; the Paseo tutorials are
  marked as historical archives.
- Release file selection is allowlist-based and the secret scan covers reviewed and
  packaged files rather than every untracked file in a working tree.

### Retained

- Controller client, node selection, latency, connections, traffic, provider and
  subscription import, policy override preview/apply, the browser dashboard entry
  point, the Textual and plain consoles, generation switching and self-contained
  rollback.
- `mihomoctl rules status|check` is wired into the V1 CLI again. The checker stays
  read-only and fail-closed: it never creates, rewrites or deletes rule files,
  never restarts Mihomo and never uploads policy. The V1 manager supplies the core
  HomeDir and the active config path explicitly, `--home-dir` / `--config` override
  them verbatim, and the checker's own `0`/`1`/`2` result is preserved and
  re-emitted under the `mihomoctl/v1` envelope.
- `mihomoctl config validate` (alias `config check`), `mihomoctl doctor`,
  `mihomoctl direct` and `mihomoctl rollback BACKUP` are part of the documented
  surface; `rollback` requires its backup argument instead of silently choosing the
  most recent generation.

### Fixed

- `service uninstall --dry-run` is a real preview. It evaluates the same
  preconditions as the operation (a running managed runtime and an enabled TUN both
  block it), returns the distinct command `service-uninstall-preview` with
  `data.dry_run: true`, and never removes the unit or rewrites the manager. It
  previously reported the same `PASS` / `removed mihomo.service` payload as a
  completed removal while skipping every precondition.
- Every command published in the README files, the V1 contract and the shell
  completion is now reachable. `mihomoctl rules` had been promised by both READMEs
  and by `completions/mihomoctl.bash` while `dispatch()` had no branch for it, so
  every invocation exited `2` with `unknown-command`.

## [0.9.3] - 2026-10-11

- Add Paseo daemon preflight, per-process exec, idempotent start, complete supervisor stop/start repair and a verified foreground launcher, retaining direct-by-default shells and existing process ownership boundaries.
- Build paired proxy variables from private client.env with mandatory local/relay bypasses and configurable, allowlisted OpenCode baseURL discovery; report OpenAI direct/listener reachability separately from model success.
- Detect long-lived Paseo environment drift in doctor and recognize the validated Paseo bypass environment for its Codex descendants without relaxing independent Codex checks.
- Add an optional credential-free systemd user unit with runtime credential reads, foreground supervision and on-failure restart; installation never enables or starts the unit.
- Freeze v0.9.0-v0.9.2 receipt inventories, include the new adapter in installation/update verification, and add isolated Linux process regression tests and bilingual manual production migration guidance.
- Retain 0.9.2: its Controller/console changes did not cause the historical daemon coverage gap; repository history establishes direct-by-default shells since v0.1.0.

## [0.9.2] - 2026-10-09

- Initialize a private loopback Controller during installation when core/config are present, without dashboard assets or service restart; preserve valid existing settings and expose first-run recovery in the console.
- Automatically select the Chinese Textual task console or a dependency-free numbered menu; expose setup, lifecycle, node search/testing, subscription preview/save/restart and guarded backup recovery.
- Add provider routing-policy import while retaining provider groups, references and rules, protecting host runtime settings, validating paths/references/core config, and preserving node-only CLI/plan compatibility.
- Accept piped subscription YAML with `tui --stdin`, then restore PTY keyboard input for explicit review and saving.
- Reuse existing cores through config/API capability checks; distinguish example package versions from runtime requirements while retaining archive hash checks.
- Preserve core configuration during self-update; require explicit TUI initialization for old installations. Restrict provider caches to dedicated directories and retain pending configuration state for idempotent or in-progress starts.

## [0.9.1] - 2026-10-08

- Fix start/restart rejecting the documented listeners-only configuration: recognize mixed listeners whose integer port matches MIHOMO_PORT without requiring a top-level mixed-port.
- Preserve legacy mixed-port matching, mismatch rejection and the existing runtime ownership, authentication and configuration checks.
- Add regression tests for listener types, multiple listeners, malformed ports, Controller conflicts, configuration drift and mocked start/restart actions; exercise an existing listeners-only configuration in the Shell suite.
- Clarify port matching and legacy precedence in the bilingual setup guides.

## [0.9.0] - 2026-10-08

- Split the existing Controller facade into configuration, API, services, policy, transactions, state and frontend modules; preserve curses/plain and CLI contracts.
- Freeze v0.7/v0.8 runtime receipt sets before adding new generation files.
- Gate start/restart under the user operation lock with before/after socket UID, binding and service ownership checks; never change ports or kill occupants.
- Add an explicitly selected optional Textual console, bounded latency jobs, read-only connections, runtime observations, rule counts, logs, providers and diagnostics.
- Install a private hash-locked UI environment, support offline wheels, reuse it on compatible updates and retain generation rollback.
- Add provider refresh, DNS queries, runtime-only mode changes and node-only private subscription preview/apply with digest, drift, validation, backup and atomic replacement.
- Keep Codex preflight, direct-by-default shells, per-process proxy boundaries and existing security diagnostics unchanged.
- Add live socket/API/PTY, state, optional frontend and offline dependency regression tests; real systemd/multi-UID/SSH acceptance remains a separate gate.

## [0.8.0] - 2026-10-07

### TUI and policy overrides

- Add node search, a compact group sidebar, persistent manual/automatic group status, and latency labels.
- Add explicit automatic-to-manual group preview and validated, backed-up policy writes from CLI and TUI; activation requires a separate restart.
- Run trusted local JavaScript `main(config)` with Node.js; restrict accepted changes to groups, rules and rule providers, preserving server listeners and credentials.
- Add optional FlClash-rules compatibility for existing local provider caches; generated groups reference providers with exact-name filters instead of copying proxy credentials.
- Add opt-in connection destination and matched-rule details for routing diagnosis; default output stays redacted.

### Acceptance fixes

- Distinguish SOCKS5 method 02 (username/password required, although unoffered) from method 00 (anonymous access accepted); retain separate evidence codes and incomplete-handshake uncertainty.
- Filter positively identified non-Codex executables before reading process identity/environment; keep unknown live executables and unreadable Codex candidates UNVERIFIED.
- Preserve published v0.7.0 artifacts and its fixed acceptance contract; these changes apply only to v0.8.0 and later.

## [0.7.0] - 2026-10-06

### Control Plane

- Add authenticated loopback Controller API commands for groups, nodes, selection, latency, traffic and redacted connection chains.
- Add a terminal selector, bundled browser panel and SHA256-pinned local MetaCubeXD static archive installation.
- Back up and validate controller configuration with Mihomo before replacement; never restart a service automatically.
- Add a standalone release bootstrap, preserving the existing control-layer-only installer contract.
- Controller commands require PyYAML; existing proxy and Codex commands keep their dependencies and behavior.
- Preserve pre-v0.7 installation receipts during upgrades.


### Codex Reliability (includes previously unreleased v0.6 work)

- Add `mihomoctl codex preflight [--json]` with shared diagnostics/v1 output and
  SAFE_TO_LAUNCH (0), BLOCKED (1), UNVERIFIED (2) policy decisions.
- Change `mihomoctl codex` from warning-only to a fail-closed gate: mismatched
  candidates or incomplete inspection never launch the child. No processes are stopped.
- Reuse listener and authentication probes; reject anonymous HTTP/SOCKS access and
  measure authenticated HTTP egress without implying model or remote transport success.
- Retain offline diagnosis and legacy websocket field; distinguish DIRECT_EXPECTED
  local transport from unverified remote transport and model requests.
- Document four evidence levels and deterministic post-install handoff; installer
  agent connectivity and disk changes cannot prove an existing app-server's route.
- Make Chinese the default README, add English overview and retain the old Chinese link.
- Preserve ordinary status, generic exec/direct/shell hooks and service lifecycle behavior.

## [0.5.0] - 2026-09-28

### Added

- `mihomoctl codex [-- ARGS...]` checks HTTP proxy readiness before launching the PATH
  executable and warns about old-process environments without stopping active sessions.
- Offline `mihomoctl diagnose codex [--json]` provides redacted same-user process
  snapshots and actionable recovery guidance; model/WebSocket results remain UNVERIFIED.
- Bilingual first-use guidance distinguishes terminal, Remote hook and VS Code entrypoints,
  WebSocket failure layers, safe client reconnects and separate installation/network/model milestones.

### Changed

- Installation now prints concrete next steps; agent prompts and acceptance require an
  entry-specific handoff instead of treating plain Codex or a wrapper as universal.

## [0.4.0] - 2026-09-28

### Changed

- Corrected local agent installation to copy a pinned source ZIP from a flat public
  archive directory into a private workspace, then use its bundled installer and manifest.
- Removed mandatory pre-expanded bundle layouts and external SOURCE.txt files; documented
  safe ZIP extraction, source provenance and transfer-checksum limits.
- Made personal installation with existing-tool reuse the default; administrator-shared
  Node/npm/Codex is optional and never inferred from package storage location.
- Preserved offline acquisition, subscription handoff, private credentials and persistent
  process routing checks. Runtime behavior and dependency pins are unchanged.

## [0.3.4] - 2026-09-25

### Changed

- Explained when a verified Remote hook makes an extra with_proxy wrapper unnecessary,
  while retaining explicit terminal entry and persistent-server verification boundaries.
- Required a final subscription handoff in both installation prompts: actual absolute
  configuration path/provider key, safe local entry, preserved existing/file providers,
  truthful partial-completion status and authorized post-entry validation.
- Runtime behavior and dependency pins are unchanged.

## [0.3.3] - 2026-09-24

### Changed

- Clarified ordinary-shell, explicit terminal and verified Remote-hook proxy entry paths.
- Documented both directions of persistent app-server reuse, with separate CLI/bridge/server
  environments, Unix-socket linkage and correlated outbound evidence.
- Corrected README implications that new-child proxy variables determine all Codex traffic;
  retained compatibility-hook limits, redaction and user-coordinated reconnect boundaries.
- Runtime behavior and diagnostic output schemas are unchanged; Unix peer correlation remains
  a deployment audit, not a new automatic diagnostic capability.

## [0.3.2] - 2026-09-24

### Changed

- Documented administrator-shared Node/npm/Codex with private per-user identity,
  Mihomo and controller state, without changing runtime installation behavior.
- Updated both acquisition prompts and offline examples to avoid duplicate Node/Codex
  installs in shared mode; missing shared dependencies remain administrator actions.
- Added PATH/interpreter and private CODEX_HOME audits, explicit NVM migration boundaries,
  preservation of personal credentials/sessions and scoped shared-runtime acceptance.

## [0.3.1] - 2026-09-24

### Changed

- Added shared bilingual deployment parameters and delivery contracts for online
  and local installation prompts, including existing-tool reuse and bounded authorization.
- Distinguished install-only behavior from explicitly authorized service startup,
  redacted audit output, and separate executable/process/routing/model-request evidence.
- Clarified secret handoff, scoped isolation claims and UNVERIFIED versus explicitly
  DEFERRED checks. Runtime installation behavior and dependency pins are unchanged.

## [0.3.0] - 2026-09-24

### Added

- Optional local-only installer for pre-downloaded Mihomo, Node.js, Codex CLI and
  OpenCode archives, with pinned per-architecture checksums and private per-user installs.
- Bilingual shared-directory setup, official download links, and a separate local
  installation prompt; public online installation and update prompts remain distinct.

## [0.2.2] - 2026-09-04

### Changed

- Consolidated public diagnostics under `mihomoctl diagnose url|process|name`;
  the v0.2.1 top-level names remain hidden compatibility aliases.
- Centralized proxy-variable preparation, service/listener state normalization,
  process redaction, and public JSON serialization while reusing the existing
  acceptance probes and transactional installer.
- Reduced duplicated bilingual guidance and added an explicit responsibility
  matrix for mihomo-userctl, Mihomo, systemd, and the user.

### Security

- Limited `direct` to clearing the eight documented child proxy variables,
  removed parent-process names from diagnostics, suppressed raw readiness-tool
  errors, and rejected additional unsupported custom-rule YAML forms.

### Fixed

- Preserved the exact v0.2.1 runtime receipt set so an installed v0.2.1 can be
  verified and deterministically upgraded when the new reporting module is added.

## [0.2.1] - 2026-09-04

### Added

- Added `mihomoctl exec --` and `mihomoctl direct --` as explicit child-process
  boundaries that reuse the existing authenticated proxy activation path.
- Added stable JSON for status/readiness/doctor, redacted URL probes, and
  same-user process environment/socket classification.
- Added a documented three-file private rule contract with read-only status,
  structural checks, Mihomo configuration testing, and fictional examples.

### Changed

- Installed diagnostics and rule-check modules are now hashed into immutable
  generations and validated by version-pinned updates.
- Expanded isolated regression, documentation, and secret-scan coverage for
  the new commands without changing service state or private Mihomo data.

## [0.2.0] - 2026-09-03

### Added

- Version-pinned official self-updates, check/dry-run modes, explicit-path legacy
  migration, local source provenance and defined partial-acceptance exit codes.
- Immutable installed generations, shared installer/update/uninstall locking,
  transaction recovery helpers, and isolated update/rollback regressions.
- Bilingual update guides and evidence-based update prompts.

- Added a non-disruptive listener acceptance verifier with measured HTTP status,
  explicit HTTP/SOCKS authentication rejection checks, and four evidence states.
- Added bilingual acceptance/rollback guidance and regression tests for verifier
  failures, audit-tool failures, redaction, and fail-closed shell paths.

### Fixed

- Documentation and repository secret scans now fail when enumeration/search
  tools fail; the secret scan no longer prints matching sensitive values.

### Changed

- Installation now requires Python 3.8+, records original XDG/startup paths, and
  publishes controller modules together via an atomic generation pointer.

- Installation prompts require scoped evidence, original exit codes, immutable
  source provenance, and explicit pending results instead of blanket success.
- Setup guides use a reviewed source ref, distinguish readiness from proxy
  routing, and avoid printing pre-existing proxy environment values.

## [0.1.6] - 2026-09-02

### Changed

- Removed a maintainer-specific dataset-domain routing rule and associated
  policy-group names from the public setup example and architecture guide.
- Replaced them with a neutral `Proxy` group and generic GitHub/ChatGPT examples.
  User-specific dataset, research, provider, and routing policy remains entirely
  outside the generic control-layer project.
- Added a documentation regression check that rejects those private policy
  identifiers if they are reintroduced into tracked public Markdown files.

## [0.1.5] - 2026-09-02

### Fixed

- Installed and upgraded the managed loader before Ubuntu's standard
  non-interactive `.bashrc` return guard. This lets an explicitly supplied
  `CODEX_REMOTE_PAYLOAD` reach the fail-closed compatibility hook.
- Added regression coverage for fresh installs, upgrades from a loader below
  that guard, non-interactive hook execution, idempotency, and preservation of
  unrelated startup-file content.

### Added

- Added matching English and Chinese VS Code Remote guides for the optional
  remote Machine `http.proxy` integration, secure file permissions, process
  restart, traffic verification, impact scope, and rollback.
- Documented two separate long-lived-process failures found during real-world
  acceptance: a stale Codex App Server retaining its original direct
  environment, and the VS Code Extension Host starting Codex without the Shell
  hook or proxy variables.
- Extended the coding-agent installation protocol to discover and explicitly
  approve optional VS Code Remote integration and to validate the resulting
  process and socket path without exposing credentials.

### Security

- Kept VS Code proxy credentials out of chat, command arguments, logs, diffs,
  and Git; remote Machine Settings containing an authenticated URL must be
  current-user-owned and mode `600`.
- Restart instructions are limited to the current user's client connection and
  processes. They never authorize server-wide process-name kills or changes to
  another user.

## [0.1.4] - 2026-09-02

### Fixed

- Restored the complete installation task in the agent-neutral prompts,
  including the CODEX_REMOTE_PAYLOAD opt-in and fail-closed acceptance path.
- Restored explicit protection for the out-of-scope loopback port, active
  downloads and SSH sessions, current proxy state, and existing user policy.
- Narrowed the product-specific test ban to installation interfaces only;
  runtime compatibility requirements must now be present in both languages.

## [0.1.3] - 2026-09-02

### Changed

- Replaced the primary product-specific installation prompt with matching
  English and Chinese, tool-agnostic coding-agent protocols.
- Added explicit capability detection, a read-only planning phase, ordinary
  conversational choices, sensitive-information boundaries, approval gates,
  rollback, and final acceptance requirements.
- Kept the former prompt paths as short compatibility pages while preserving
  the existing remote-runtime compatibility hook and usage documentation.
- Bumped the packaged controller version to `0.1.3`; this release does not
  change proxy behavior, credentials, routing policy, or service lifecycle.

## [0.1.2] - 2026-08-27

### Changed

- Made installation transactional: a failed final diagnostic restores every
  managed active file and prior managed-directory permissions.
- Refused symbolic-link `.bashrc` targets in both install and uninstall paths.
- Detected a user-owned `~/.local/bin/mihomo` in `mihomoctl version` even when a
  non-interactive session omits that directory from `PATH`.
- Corrected the Codex prompt order so a verified project checkout exists before
  any project script runs.
- Standardized Chinese security terminology: `敏感信息` is the umbrella
  term and `凭据` is reserved for authentication material; `密钥` is not used as
  a misleading replacement for passwords, tokens, or subscription URLs.

## [0.1.1] - 2026-08-27

### Changed

- Removed the project-specific legacy `.bashrc` migration path and guide; new
  users receive only the managed loader owned by this project.
- Reframed the public problem statement around per-user, opt-in proxying on a
  shared server rather than one developer's migration history.
- Replaced the personal example port with explicit user selection and a
  read-only `--suggest-port` helper for the `20000-29999` range.
- Updated Codex prompts to recommend Plan mode and interactive collection of
  non-secret user choices.

## [0.1.0] - 2026-08-27

### Changed

- Established direct-by-default, per-user proxy control as the public project
  model for shared servers.
- Split every maintained guide into matching `docs/en` and `docs/zh-CN` trees.
- Expanded setup to begin with a pinned, checksum-verified Mihomo installation.
- Added copyable Codex installation prompts without replacing deterministic
  installers or safety checks.

### Added

- `mihomoctl` lifecycle, status, readiness, diagnostics, logs, and version commands.
- Secure Bash functions for opt-in parent-shell and one-command proxying.
- Strict non-executing parsers for configuration and credential files.
- Idempotent installer, precise managed-loader updates, and conservative uninstaller.
- Bash completion, automated tests, secret scan, and bilingual documentation.
- CI coverage for bilingual topic completeness and relative Markdown links.
