#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PASS=0
FAIL=0

ok() { printf 'ok %d - %s\n' "$((PASS + FAIL + 1))" "$1"; PASS=$((PASS + 1)); }
not_ok() { printf 'not ok %d - %s\n' "$((PASS + FAIL + 1))" "$1"; FAIL=$((FAIL + 1)); }
assert() {
  local name=$1
  shift
  if "$@"; then ok "$name"; else not_ok "$name"; fi
}

TEST_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEST_ROOT"' EXIT
export HOME=$TEST_ROOT/home
export XDG_CONFIG_HOME=$HOME/.config
export XDG_DATA_HOME=$HOME/.local/share
export PATH=$TEST_ROOT/bin:$HOME/.local/bin:/usr/bin:/bin
mkdir -p "$HOME/.local/bin" "$XDG_DATA_HOME/mihomo-userctl" "$XDG_CONFIG_HOME/mihomo" "$TEST_ROOT/bin"
chmod 700 "$XDG_DATA_HOME/mihomo-userctl" "$XDG_CONFIG_HOME/mihomo"
cp "$ROOT/src/common.bash" "$ROOT/src/shell.bash" "$ROOT/completions/mihomoctl.bash" "$XDG_DATA_HOME/mihomo-userctl/"
mv "$XDG_DATA_HOME/mihomo-userctl/mihomoctl.bash" "$XDG_DATA_HOME/mihomo-userctl/completion.bash"
chmod 644 "$XDG_DATA_HOME/mihomo-userctl/common.bash" "$XDG_DATA_HOME/mihomo-userctl/shell.bash" "$XDG_DATA_HOME/mihomo-userctl/completion.bash"
cp "$ROOT/src/mihomoctl" "$HOME/.local/bin/mihomoctl"
chmod 755 "$HOME/.local/bin/mihomoctl"
printf 'active\n' > "$TEST_ROOT/service-state"

cat > "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf" <<'EOF'
MIHOMO_SERVICE=mihomo
MIHOMO_PORT=28443
MIHOMO_READY_URL=https://example.com/
MIHOMO_READY_TIMEOUT=2
MIHOMO_STOP_TIMEOUT=1
EOF
cat > "$XDG_CONFIG_HOME/mihomo/client.env" <<'EOF'
MIHOMO_HTTP_PROXY='http://user:0123456789abcdef@127.0.0.1:28443'
MIHOMO_HTTPS_PROXY='http://user:0123456789abcdef@127.0.0.1:28443'
MIHOMO_ALL_PROXY='socks5h://user:0123456789abcdef@127.0.0.1:28443'
EOF
chmod 600 "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf" "$XDG_CONFIG_HOME/mihomo/client.env"

cat > "$TEST_ROOT/bin/systemctl" <<EOF
#!/usr/bin/env bash
state_file='$TEST_ROOT/service-state'
case "\$*" in
  '--user show-environment') exit 0 ;;
  '--user is-active --quiet mihomo') [[ \$(<"\$state_file") == active ]] ;;
  '--user is-enabled mihomo') printf 'disabled\\n'; exit 1 ;;
  '--user start mihomo'|'--user restart mihomo') printf 'active\\n' > "\$state_file" ;;
  '--user stop mihomo') printf 'inactive\\n' > "\$state_file" ;;
  *) printf 'unexpected systemctl: %s\\n' "\$*" >&2; exit 3 ;;
esac
EOF
cat > "$TEST_ROOT/bin/ss" <<EOF
#!/usr/bin/env bash
[[ \$(<'$TEST_ROOT/service-state') == active ]] || exit 0
case "\$*" in
  *':28443'*) printf 'LISTEN 0 4096 127.0.0.1:28443 0.0.0.0:*\\n' ;;
esac
EOF
cat > "$TEST_ROOT/bin/curl" <<'EOF'
#!/usr/bin/env bash
[[ ${CURL_FAIL:-0} != 1 ]]
EOF
cat > "$TEST_ROOT/bin/journalctl" <<'EOF'
#!/usr/bin/env bash
printf 'journal redacted\n'
EOF
cat > "$TEST_ROOT/bin/mihomo" <<'EOF'
#!/usr/bin/env bash
printf 'Mihomo Meta test\n'
EOF
chmod 755 "$TEST_ROOT/bin/"*

assert 'doctor accepts secure config and disabled service' "$HOME/.local/bin/mihomoctl" doctor
assert 'ready validates the authenticated path' "$HOME/.local/bin/mihomoctl" ready
assert 'status reports active loopback listener' bash -c '[[ $(mihomoctl status) == *"service=up enabled=disabled listener=up endpoint=127.0.0.1:28443"* ]]'

assert 'shell module starts direct and proxy_on exports eight variables' bash -c '
  export http_proxy=old HTTPS_PROXY=old
  source "$XDG_DATA_HOME/mihomo-userctl/shell.bash"
  [[ -z ${http_proxy+x} && -z ${HTTPS_PROXY+x} ]]
  proxy_on || exit
  [[ -n $http_proxy && -n $https_proxy && -n $all_proxy && -n $no_proxy &&
     -n $HTTP_PROXY && -n $HTTPS_PROXY && -n $ALL_PROXY && -n $NO_PROXY ]]
  [[ $(proxy_status) == "shell=proxied service=up endpoint=127.0.0.1:28443" ]]
'

assert 'with_proxy does not modify its parent shell' bash -c '
  source "$XDG_DATA_HOME/mihomo-userctl/shell.bash"
  with_proxy bash -c "[[ -n \$http_proxy ]]" || exit
  [[ -z ${http_proxy+x} ]]
'

assert 'with_proxy without a command returns 2' bash -c '
  source "$XDG_DATA_HOME/mihomo-userctl/shell.bash"
  set +e; with_proxy >/dev/null 2>&1; rc=$?; [[ $rc == 2 ]]
'

cp "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf" "$TEST_ROOT/good.conf"
printf 'EVIL=$(touch /tmp/mihomo-userctl-must-not-run)\n' >> "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf"
assert 'unknown config syntax is rejected as data' bash -c 'set +e; mihomoctl status >/dev/null 2>&1; [[ $? == 2 && ! -e /tmp/mihomo-userctl-must-not-run ]]'
cp "$TEST_ROOT/good.conf" "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf"
chmod 600 "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf"

chmod 644 "$XDG_CONFIG_HOME/mihomo/client.env"
assert 'credentials wider than mode 600 are rejected' bash -c 'set +e; mihomoctl ready >/dev/null 2>&1; [[ $? == 2 ]]'
chmod 600 "$XDG_CONFIG_HOME/mihomo/client.env"

printf 'inactive\n' > "$TEST_ROOT/service-state"
assert 'start waits for readiness but keeps shell unchanged' "$HOME/.local/bin/mihomoctl" start
assert 'stop releases the configured port without killing anything' "$HOME/.local/bin/mihomoctl" stop

# Installer port selection and idempotency use a second temporary HOME.
INSTALL_HOME=$TEST_ROOT/install-home
mkdir -p "$INSTALL_HOME/.config/mihomo"
chmod 700 "$INSTALL_HOME/.config/mihomo"
cp "$XDG_CONFIG_HOME/mihomo/client.env" "$INSTALL_HOME/.config/mihomo/client.env"
chmod 600 "$INSTALL_HOME/.config/mihomo/client.env"
cat > "$INSTALL_HOME/.bashrc" <<'EOF'
before=yes
after=yes
EOF
printf 'active\n' > "$TEST_ROOT/service-state"
assert 'suggest-port returns a currently unused high candidate' bash -c 'port=$(bash "$1" --suggest-port); [[ $port =~ ^[0-9]+$ && $port -ge 20000 && $port -le 29999 && $port -ne 28443 ]]' _ "$ROOT/install.sh"
assert 'first installation still requires an explicit port' bash -c 'set +e; HOME="$1" XDG_CONFIG_HOME="$1/.config" XDG_DATA_HOME="$1/.local/share" PATH="$2" bash "$3" --dry-run --bashrc "$1/.bashrc" >/dev/null 2>&1; [[ $? == 2 ]]' _ "$INSTALL_HOME" "$PATH" "$ROOT/install.sh"
assert 'installer appends its loader and preserves unrelated bashrc lines' env HOME="$INSTALL_HOME" XDG_CONFIG_HOME="$INSTALL_HOME/.config" XDG_DATA_HOME="$INSTALL_HOME/.local/share" PATH="$PATH" bash "$ROOT/install.sh" --port 28443 --bashrc "$INSTALL_HOME/.bashrc"
assert 'loader markers and unrelated bashrc lines are preserved' bash -c 'grep -Fqx "before=yes" "$1" && grep -Fqx "after=yes" "$1" && [[ $(grep -c "mihomo-userctl managed loader" "$1") == 2 ]]' _ "$INSTALL_HOME/.bashrc"
assert 'installer is idempotent' env HOME="$INSTALL_HOME" XDG_CONFIG_HOME="$INSTALL_HOME/.config" XDG_DATA_HOME="$INSTALL_HOME/.local/share" PATH="$PATH" bash "$ROOT/install.sh" --port 28443 --bashrc "$INSTALL_HOME/.bashrc"
assert 'uninstaller removes owned code but preserves credentials and config' env HOME="$INSTALL_HOME" XDG_CONFIG_HOME="$INSTALL_HOME/.config" XDG_DATA_HOME="$INSTALL_HOME/.local/share" PATH="$PATH" bash "$ROOT/uninstall.sh" --bashrc "$INSTALL_HOME/.bashrc"
assert 'configuration survived uninstall' bash -c '[[ -f "$1/.config/mihomo/client.env" && -f "$1/.config/mihomo/mihomo-shell.conf" && ! -e "$1/.local/bin/mihomoctl" ]]' _ "$INSTALL_HOME"

printf '1..%d\n' "$((PASS + FAIL))"
printf '# pass=%d fail=%d\n' "$PASS" "$FAIL"
(( FAIL == 0 ))
