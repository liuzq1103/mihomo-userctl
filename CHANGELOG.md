# Changelog

All notable changes follow a simplified Keep a Changelog format.

## [Unreleased]

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
