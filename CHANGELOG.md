# Changelog

All notable changes follow a simplified Keep a Changelog format.

## [Unreleased]

## [0.1.0] - 2026-08-27

### Changed

- Corrected the project origin: preventing server downloads from consuming a
  metered desktop proxy is the primary motivation; `.bashrc` modularization is
  a later maintainability improvement.
- Split every maintained guide into matching `docs/en` and `docs/zh-CN` trees.
- Expanded setup to begin with a pinned, checksum-verified Mihomo installation.
- Added copyable Codex installation prompts without replacing deterministic
  installers or safety checks.

### Added

- `mihomoctl` lifecycle, status, readiness, diagnostics, logs, and version commands.
- Secure Bash functions for opt-in parent-shell and one-command proxying.
- Strict non-executing parsers for configuration and credential files.
- Idempotent installer, precise legacy `.bashrc` migration, and conservative uninstaller.
- Bash completion, automated tests, secret scan, and bilingual documentation.
- CI coverage for bilingual topic completeness and relative Markdown links.
