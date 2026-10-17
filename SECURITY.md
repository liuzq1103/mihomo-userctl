# Security

No shell startup file writes (.bashrc/.zshrc/profile), no implicit elevation or third-party service actions.

Release acquisition trusts the project's official GitHub HTTPS channel. Tag,
receipt, gate, inventory and checksum cross-checks detect transport corruption
and inconsistent assets; colocated records are not independent publisher
signatures and cannot establish authenticity after an account/channel compromise.
Use an independently trusted digest when your threat model requires it.
Downloads are staged privately and published without overwriting existing paths.
Existing installer trust, ownership, dependency and version gates still apply.

See [English safety boundaries](docs/en/security.md) or [中文安全说明](docs/zh-CN/security.md). Do not publish credentials, subscription URLs, private environment exports or detailed connection traces in issues. Report vulnerabilities privately using GitHub private vulnerability reporting when available; otherwise contact the maintainer without including secret values. Include the affected version, a redacted reproduction and impact.
