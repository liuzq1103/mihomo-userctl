# Changelog

All notable changes follow a simplified Keep a Changelog format.

## [Unreleased]

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
