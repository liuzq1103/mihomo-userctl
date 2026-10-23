# First run: prove the path you actually use

Complete [setup](setup.md), [subscription import](subscriptions.md) and your [routing rules](rules.md). Verify four separate layers:

1. Runtime: `mihomoctl status` must report the intended core/config, running state and listener. `mihomoctl logs --lines 50` helps locate startup/config failures.
2. Local authenticated proxy: `mihomoctl health check` verifies local runtime/controller/listener behavior. `mihomoctl env show` is redacted. `mihomoctl exec -- curl --fail --head https://example.com` makes an actual HTTPS request using the generated proxy environment. A successful request may still route DIRECT.
3. Destination route: review the active core `mode`, `rules`, provider order and selected group. Advanced CLI `init` uses `MATCH,DIRECT`; the terminal wizard creates `MATCH,Proxy` for a new simple subscription. Existing custom routing is preserved until explicitly changed. Select a real node with `mihomoctl groups`, `mihomoctl nodes`, then `mihomoctl select Proxy NODE_NAME`; selection alone does not change a DIRECT matching rule. A target-specific rule must match before fallback and route to that group. NO_PROXY can bypass the proxy entirely.
4. Real client: launch Codex through exec, trigger a real request, and correlate its time, destination and controller connection chain. `mihomoctl connections --details` can expose private destinations and matched rules: inspect locally and do not publish raw output. A matching connection with the expected remote chain plus a successful client operation establishes that observed request, not all future traffic.

Codex must already be installed on PATH:

```bash
mihomoctl exec -- codex
mihomoctl exec -- codex --help
mihomoctl exec -- codex "检查当前项目"
mihomoctl direct -- codex
```

`codex --help` tests launch/argument forwarding; it need not access the network. exec is fail-closed when local health is unavailable; it passes child arguments after `--` unchanged and preserves exit/signal semantics. direct clears HTTP_PROXY, HTTPS_PROXY, ALL_PROXY, NO_PROXY and their four lowercase equivalents. It cannot bypass transparent routing, VPNs or a client's own proxy configuration.

```bash
mihomoctl health check --egress-url https://example.com
mihomoctl doctor
```

External probes establish only that probe's result. Do not infer Codex routing from a listening port, selected node, or egress probe alone. If no real Codex request was observed, record **UNVERIFIED**, with the missing evidence. Stop intentionally with `mihomoctl stop`. For systemd/container/CI processes, use [bindings](operations/integrations.md) and restart the application explicitly when ready.


## Install a third-party CLI through the proxy

First initialize Mihomo, explicitly start it and pass local health checks. Configure subscriptions and matching routes if download hosts need a remote node. A missing core cannot bootstrap through its own stopped proxy. This section assumes an explicit request to install Claude Code; installing mihomoctl does not install third-party applications.

`exec` passes proxy variables to its child and descendants; it changes neither the parent shell nor existing daemons. The current shell handles outer `|`, `&&` and `;`. Wrapping only the left-hand curl before piping into an outer Bash leaves the right-hand installer and its downloads outside that environment. Wrap the entire pipeline:

```bash
mihomoctl exec -- bash -o pipefail -c 'curl -fsSL https://claude.ai/install.sh | bash'
```

This fixes environment scope and propagates pipeline failures, but still executes content while it arrives. `curl -f` rejects HTTP error statuses, not HTTP 200 region/login HTML. pipefail cannot undo or prevent execution that already began. Prefer downloading, reviewing and executing separately.

Download to a private directory and reject empty content, obvious HTML and Bash syntax errors. This step does not execute the installer:

```bash
# installer-download
umask 077
installer_dir=$(mktemp -d "$HOME/claude-installer.XXXXXXXX")
mihomoctl exec -- bash -euo pipefail -c '
  curl -fsSL --dump-header "$1/headers" --output "$1/install.sh" https://claude.ai/install.sh
  test -s "$1/install.sh"
  if LC_ALL=C grep -Eiq "<(!doctype[[:space:]]+html|html|head|body)([[:space:]>])" "$1/install.sh"; then
    printf "%s\n" "Refusing an HTML response; inspect network/routing." >&2
    exit 1
  fi
  bash -n "$1/install.sh"
  touch "$1/download-checked"
' bash "$installer_dir"
```

Only after that block succeeds, locally review the final response in `$installer_dir/headers` and the content/source of `$installer_dir/install.sh`. Stop on regional restrictions, login pages or unexpected scripts. Check destination routing, NO_PROXY and connectivity to both script and subsequent asset hosts. Do not blindly switch to direct execution or disable TLS checks. These checks, Content-Type and bash -n do not authenticate scripts or establish remote-node routing.

After reviewing the private file as the expected installer, execute explicitly in the same terminal. Bash and subsequent downloads inherit the proxy:

```bash
# installer-execute-after-review
if test -f "$installer_dir/download-checked"; then
  mihomoctl exec -- bash "$installer_dir/install.sh"
else
  printf '%s\n' 'Download checks did not pass; stop and inspect the previous failure.' >&2
  false
fi
```

`download-checked` records download/format checks only; human review is still required. Retain files for diagnosis and remove this isolated directory when done. Verify installation with `claude --version`; login and real requests are separate checks. Any PATH/file edits by that installer are its own behavior, outside mihomoctl's installer guarantees.

Official references: [installation](https://code.claude.com/docs/en/setup), [proxy and HTML/403 troubleshooting](https://code.claude.com/docs/en/troubleshoot-install). For `Could not resolve host`, inspect proxy inheritance and DNS. `syntax error near unexpected token '<'` commonly indicates an HTML response executed as shell, rather than a Bash version problem.
