# Mihoro inspiration and project boundary

This project studied [spencerwooo/mihoro](https://github.com/spencerwooo/mihoro)
as a design reference. Mihoro is not a dependency, fork, or source-code base.

## Ideas adopted

- a rootless per-user installation under the user's home;
- one consistent CLI for `systemctl --user` lifecycle operations;
- configuration-driven behavior instead of hard-coded users and paths;
- idempotent installation and a clear command-oriented UX;
- status, logs, help, and shell completion as first-class interfaces;
- documentation that covers onboarding and everyday maintenance.

## Deliberate differences

Mihoro has a broader lifecycle-management scope: it can initialize and update
the Mihomo core, remote configuration, geodata, dashboard, cron, and service.
`mihomo-userctl` v0.1 intentionally assumes those already exist.

Mihoro documents `eval $(mihoro proxy export)`. This project does not emit code
for evaluation. A small, owner-checked Bash module changes the parent shell,
while credential files remain non-executable data parsed by a whitelist.

Mihoro's example onboarding enables the service and exposes a dashboard
controller. This project's invariant is a disabled, manually started service,
an authenticated loopback-only Mixed listener, no controller, no dashboard,
and no TUN or routing changes.

Mihoro exports three lower-case proxy variables. This project manages a strict
set of eight upper/lower-case variables and reports partial state as
`inconsistent`.

## Attribution and license

Mihoro is MIT-licensed. `mihomo-userctl` is independently implemented in Bash
and is also MIT-licensed. No Mihoro source code, branding, logo, or assets are
copied into this repository.
