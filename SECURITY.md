# Security policy

## Supported versions

Security fixes are applied to the latest 0.x release until a 1.0 policy is
published.

## Reporting a vulnerability

Do not open a public issue containing a subscription URL, proxy credential,
private hostname, server address, or complete runtime configuration. Use
GitHub's private vulnerability reporting feature when enabled. If it is not
available, open a redacted issue asking the maintainer for a private channel.

Include the project version, Bash version, Linux distribution, reproduction
steps, and redacted diagnostics from `mihomoctl doctor`. Replace all userinfo in
proxy URLs with `<redacted>`.

## Non-goals

The project does not isolate local users from one another at the Linux network
stack. An authenticated loopback listener reduces accidental use; strict
per-UID enforcement requires administrator-managed firewall policy.
