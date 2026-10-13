# systemd, containers and CI

Edit only the `bindings` mapping of your initialized private manager.yaml (merge existing bindings). This complete example uses the existing default profile. Choose addresses/targets for your own host:

```yaml
bindings:
  worker:
    profile: default
    adapter: systemd
    target: worker.service
    connect_host: 127.0.0.1
  container:
    profile: default
    adapter: docker
    connect_host: 172.17.0.1
  pipeline:
    profile: default
    adapter: ci
```

```bash
mihomoctl config validate
mihomoctl integration check worker
mihomoctl integration install worker
```

The systemd adapter writes a marked drop-in plus private proxy.env under the managed integration directory, and reloads the user unit manager. Inspect `mihomoctl integration show worker`. It does not enable/start/stop/restart worker.service. Explicitly restart your own service when ready; existing processes retain their inherited environment. `integration remove worker` removes owned integration artifacts without deleting a pre-existing user's unit.

For the Mihomo runtime itself, `mihomoctl service install` followed by explicit `mihomoctl service start` selects user systemd management. This is separate from third-party application bindings. No automatic linger or enable.

## Containers

172.17.0.1 is only an example reachable host address. Loopback inside a container refers to the container itself. A connect_host changes exported URLs but does not create a listener or firewall rule. Explicitly configure a reachable authenticated listener and authorize that non-loopback address in manager.allow_non_loopback; restrict network access. Export privately:

```bash
umask 077
mihomoctl integration export container --output-dir "$HOME/private/container-proxy"
```

The output includes docker.env and a compose fragment. The compose fragment references the accompanying docker.env; merge it into your own compose configuration after review. Alternatively use the exported docker.env with your own `docker run --env-file` command. The tool does not deploy/restart containers. Kubernetes also requires connect_host and exports a Secret; its base64 data is still sensitive.

## CI

```bash
umask 077
mihomoctl integration export pipeline --output-dir "$HOME/private/ci-proxy"
. "$HOME/private/ci-proxy/ci-env.sh"
```

Use in a trusted runner's explicit step, with command tracing disabled and secrets masked. Never upload exports as artifacts or print them. Environment changes apply to subsequent processes in that shell; the tool does not start the pipeline. A separate runner needs a reachable listener and secure transfer of its private environment. Export-only adapters also support supervisor and pm2.
