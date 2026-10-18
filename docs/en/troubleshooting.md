# Installation and runtime troubleshooting

- Controller installed but Mihomo absent: controller packages do not include a core. For new setup follow [initialization](setup.md), reuse a trusted core or explicitly install the fixed version, then init once. Do not reinitialize existing managers or blindly run core install.
- NAS/wheelhouse permissions rejected: copy all required materials to an owned private directory and verify there. Do not recursively loosen permissions. Check the [two offline layouts](offline-install.md).
- Python/target mismatch: check distribution, architecture and interpreter; do not force another target's kit. Prepare missing strict-offline cores/dependencies beforehand.
- Installer's subsequent download fails DNS: check that the entire installation shell is inside exec; an outer pipeline's right side does not inherit its left side's environment.
- Bash reports HTML or a syntax error involving '<': the response may be a region/login page. curl -f does not reject HTTP 200 HTML. Stop execution and follow [download review and proxy inheritance](first-run.md#install-a-third-party-cli-through-the-proxy); never disable TLS verification.
- init succeeded but exec fails its health gate: initialization leaves the runtime stopped by default. Explicitly start when ready, then check configuration, ports and logs. Do not bootstrap a missing core through its own stopped proxy.
- Local requests work without remote routing: default MATCH,DIRECT requires subscription/rule setup. Check NO_PROXY and actual client connections using [layered verification](first-run.md).

Report controller, core, initialization, runtime and real remote requests separately as PASS/FAIL/UNVERIFIED. Do not publish raw credentials or connection details.
