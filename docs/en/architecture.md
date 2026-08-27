# Architecture and data flow

## Problem model

```text
ordinary user on a shared server
  -> normal downloads remain on the server direct connection
  -> selected tools explicitly enter the user's local proxy
```

The boundary keeps the proxy endpoint inside the server user account and does
not transparently capture traffic:

```text
ordinary process -> server direct network
opted-in process -> 127.0.0.1:<port> -> user Mihomo -> routing policy
```

## Components

```text
.bashrc managed loader
  -> owner/permission checks
  -> shell.bash: proxy_on/off/status, with_proxy
     -> common.bash: strict config and credential parser

mihomoctl
  -> common.bash
  -> systemctl --user, ss, authenticated curl, journalctl --user

Mihomo
  -> authenticated loopback Mixed listener
  -> user-owned providers, groups, and rules
```

Service state and current-Shell state are independent. `mihomoctl start` moves
the service from down to up; `proxy_on` moves only the current Shell from direct
to proxied. `with_proxy` changes a child process and then disappears.

The controller does not generate Mihomo policy and does not contain desktop
Clash/FlClash rules. That separation prevents server lifecycle code and PC rule
generation from becoming one coupled deployment.

## Trust boundary

The loader validates module ownership and permissions before sourcing code.
Configuration and credentials are parsed as non-executable data with fixed key
whitelists. Unknown or duplicate keys, invalid quoting, wrong endpoints, and
unsafe permissions fail closed.
