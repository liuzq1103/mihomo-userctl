# First run: prove the path you actually use

Complete [setup](setup.md), [subscription import](subscriptions.md) and your [routing rules](rules.md). Verify four separate layers:

1. Runtime: `mihomoctl status` must report the intended core/config, running state and listener. `mihomoctl logs --lines 50` helps locate startup/config failures.
2. Local authenticated proxy: `mihomoctl health check` verifies local runtime/controller/listener behavior. `mihomoctl env show` is redacted. `mihomoctl exec -- curl --fail --head https://example.com` makes an actual HTTPS request using the generated proxy environment. A successful request may still route DIRECT.
3. Destination route: review the active core `mode`, `rules`, provider order and selected group. A fresh init uses `MATCH,DIRECT`. Select a real node with `mihomoctl groups`, `mihomoctl nodes`, then `mihomoctl select Proxy NODE_NAME`; selection alone does not change a DIRECT matching rule. A target-specific rule must match before fallback and route to that group. NO_PROXY can bypass the proxy entirely.
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
