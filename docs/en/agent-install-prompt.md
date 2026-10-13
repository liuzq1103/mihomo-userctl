# Agent installation instructions

Read [INSTALL.md](../../INSTALL.md), [setup](setup.md), [security](security.md) and [verification](first-run.md). Begin with a read-only audit of Linux/Python, existing core/configuration, user scope, XDG paths and available network access. Never print private files or put credentials in argv.

Install a verified release and dependencies, then initialize with a trusted core or explicitly install a fixed, digest-checked core. Reuse existing user data. Preview subscriptions and show only redacted summaries, ID and candidate SHA256; apply only within the user's authorized scope, then explicitly restart Mihomo if requested. Add rules using the documented private-file contract and readonly check. Do not revive retired lifecycle commands or shell hooks.

Honor prior user authorization. Ask only for missing input or destructive actions outside scope; do useful reversible preparation first. No implicit sudo, startup edits, third-party service actions or TUN. Export integrations privately. Record PASS/FAIL/UNVERIFIED with actual evidence, a redacted change summary and a rollback path. A successful local proxy test does not prove a real application's remote route. Follow [upgrade instructions](update.md) for existing installations.
