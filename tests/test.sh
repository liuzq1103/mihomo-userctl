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
cp "$ROOT/scripts/acceptance.py" "$ROOT/scripts/diagnostics.py" "$ROOT/scripts/rules.py" \
  "$ROOT/scripts/reporting.py" "$XDG_DATA_HOME/mihomo-userctl/"
mv "$XDG_DATA_HOME/mihomo-userctl/mihomoctl.bash" "$XDG_DATA_HOME/mihomo-userctl/completion.bash"
chmod 644 "$XDG_DATA_HOME/mihomo-userctl/common.bash" "$XDG_DATA_HOME/mihomo-userctl/shell.bash" \
  "$XDG_DATA_HOME/mihomo-userctl/completion.bash" "$XDG_DATA_HOME/mihomo-userctl/acceptance.py" \
  "$XDG_DATA_HOME/mihomo-userctl/diagnostics.py" "$XDG_DATA_HOME/mihomo-userctl/rules.py" \
  "$XDG_DATA_HOME/mihomo-userctl/reporting.py"
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
  '--user is-active mihomo') cat "\$state_file"; [[ \$(<"\$state_file") == active ]] ;;
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
assert 'status and doctor JSON are stable parseable objects' bash -c '
  status=$(mihomoctl status --json) || exit
  doctor=$(mihomoctl doctor --json) || exit
  python3 -c '\''import json,sys; d=json.loads(sys.argv[1]); assert d["schema"] == "mihomo-userctl.diagnostics/v1" and d["overall"] == "PASS"'\'' "$status" || exit
  python3 -c '\''import json,sys; d=json.loads(sys.argv[1]); assert d["command"] == "doctor" and d["overall"] == "PASS"'\'' "$doctor"
'

cat > "$HOME/.local/bin/mihomo" <<'EOF'
#!/usr/bin/env bash
printf 'Mihomo Meta fallback-test\n'
EOF
chmod 755 "$HOME/.local/bin/mihomo"
assert 'version finds a user-local Mihomo outside PATH' bash -c '[[ $(PATH=/usr/bin:/bin "$1" version) == *"mihomo Mihomo Meta fallback-test"* ]]' _ "$HOME/.local/bin/mihomoctl"

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

assert 'mihomoctl exec preserves arguments and exports exactly eight proxy variables' bash -c '
  marker="$1/exec-args"
  mihomoctl exec -- bash -c '\''
    [[ $1 == "argument with spaces" && $2 == "literal;not-shell" ]] || exit 9
    count=0
    for name in http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
      [[ -n ${!name:-} ]] || exit 8
      count=$((count + 1))
    done
    printf "%s" "$count" > "$3"
  '\'' _ "argument with spaces" "literal;not-shell" "$marker" || exit
  [[ $(<"$marker") == 8 ]]
' _ "$TEST_ROOT"

assert 'mihomoctl direct clears proxy variables only for the child' bash -c '
  export http_proxy=parent HTTP_PROXY=parent all_proxy=parent ALL_PROXY=parent
  mihomoctl direct -- bash -c '\''
    for name in http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
      [[ -z ${!name+x} ]] || exit 7
    done
  '\'' || exit
  [[ $http_proxy == parent && $HTTP_PROXY == parent && $all_proxy == parent && $ALL_PROXY == parent ]]
'

assert 'exec and direct require separator and preserve child status' bash -c '
  set +e
  mihomoctl exec bash -c true >/dev/null 2>&1; [[ $? == 2 ]] || exit
  mihomoctl direct -- bash -c "exit 7"; [[ $? == 7 ]]
'

hostile_arguments_are_literal() {
  local marker=$TEST_ROOT/must-not-exist literal first output
  literal="\$(touch $marker)"
  first=$'space \'single\' "double" * ; semicolon'
  output=$(mihomoctl direct -- bash -c 'printf "%s\n%s" "$1" "$2"' _ \
    "$first" "$literal") || return
  [[ $output == "$first"$'\n'"$literal" && ! -e $marker ]]
}
assert 'exec and direct preserve literal hostile-looking arguments' \
  hostile_arguments_are_literal

assert 'direct clears only eight child proxy variables and preserves its parent bytes' bash -c '
  names=(http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY)
  for name in "${names[@]}"; do printf -v "$name" "%s" "parent value $name"; export "$name"; done
  export MIHOMO_HTTP_PROXY=internal-sentinel
  before=$(declare -p "${names[@]}") || exit
  mihomoctl direct -- bash -c '\''
    for name in http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
      [[ -z ${!name+x} ]] || exit 7
    done
    [[ $MIHOMO_HTTP_PROXY == internal-sentinel ]]
  '\'' || exit
  after=$(declare -p "${names[@]}") || exit
  [[ $before == "$after" ]]
'

assert 'canonical diagnose commands replace legacy names in help' bash -c '
  help=$(mihomoctl help) || exit
  [[ $help == *"diagnose url"* && $help == *"diagnose process"* && $help == *"diagnose name"* ]] || exit
  [[ $help != *"test-url"* && $help != *"inspect-process"* && $help != *"inspect-name"* ]]
'

diagnostic_command_is_stable() {
  local expected=$1 output rc=0
  shift
  output=$(mihomoctl "$@" --json 2>/dev/null) || rc=$?
  [[ $rc == 2 ]] || return
  python3 -c 'import json,sys; assert json.loads(sys.argv[1])["command"] == sys.argv[2]' \
    "$output" "$expected"
}
diagnostic_names_are_compatible() {
  diagnostic_command_is_stable diagnose-url diagnose url || return
  diagnostic_command_is_stable test-url test-url || return
  diagnostic_command_is_stable diagnose-process diagnose process 0 || return
  diagnostic_command_is_stable inspect-process inspect-process 0 || return
  diagnostic_command_is_stable diagnose-name diagnose name / || return
  diagnostic_command_is_stable inspect-name inspect-name /
}
assert 'canonical diagnostics and v0.2.1 aliases retain versioned JSON names' \
  diagnostic_names_are_compatible

assert 'diagnose reports a JSON argument error when the subcommand is missing' bash -c '
  set +e
  output=$(mihomoctl diagnose --json 2>/dev/null); rc=$?
  [[ $rc == 2 ]] || exit
  python3 -c '\''import json,sys; data=json.loads(sys.argv[1]); assert data["command"] == "diagnose" and data["error"]["code"] == "invalid-options"'\'' "$output"
'

assert 'mihomoctl exec fails before launch when readiness fails' bash -c '
  set +e
  CURL_FAIL=1 mihomoctl exec -- bash -c "exit 0" >/dev/null 2>&1
  [[ $? == 1 ]]
'

cp "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf" "$TEST_ROOT/good.conf"
printf 'EVIL=$(touch /tmp/mihomo-userctl-must-not-run)\n' >> "$XDG_CONFIG_HOME/mihomo/mihomo-shell.conf"
assert 'unknown config syntax is rejected as data' bash -c 'set +e; mihomoctl status >/dev/null 2>&1; [[ $? == 2 && ! -e /tmp/mihomo-userctl-must-not-run ]]'
assert 'JSON mode returns valid redacted data on configuration errors' bash -c '
  set +e
  output=$(mihomoctl status --json 2>/dev/null); rc=$?
  [[ $rc == 2 ]] || exit
  python3 -c '\''import json,sys; d=json.loads(sys.argv[1]); assert d["overall"] == "UNVERIFIED" and d["error"]["code"] == "config-invalid"'\'' "$output"
'
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
assert 'installation metadata hashes every runtime module including reporting' bash -c '
  root="$1/.local/share/mihomo-userctl"
  generation=$(readlink "$root/current") || exit
  python3 -c '\''import json,pathlib,sys; root=pathlib.Path(sys.argv[1]); record=json.loads((root/sys.argv[2]/"installation.json").read_text()); assert "reporting.py" in record["runtime_hashes"] and (root/sys.argv[2]/"reporting.py").is_file()'\'' "$root" "$generation"
' _ "$INSTALL_HOME"

# Ubuntu returns from .bashrc before non-interactive launchers reach content
# appended at the end. The installer must place and, on upgrade, relocate its
# managed loader before that guard without changing unrelated startup content.
UBUNTU_HOME=$TEST_ROOT/ubuntu-home
mkdir -p "$UBUNTU_HOME/.config/mihomo"
chmod 700 "$UBUNTU_HOME/.config/mihomo"
cp "$XDG_CONFIG_HOME/mihomo/client.env" "$UBUNTU_HOME/.config/mihomo/client.env"
chmod 600 "$UBUNTU_HOME/.config/mihomo/client.env"
cat > "$UBUNTU_HOME/.bashrc" <<'EOF'
# Ubuntu-style startup file
case $- in
    *i*) ;;
      *) return;;
esac
ubuntu_after=yes
EOF
cp -p "$UBUNTU_HOME/.bashrc" "$TEST_ROOT/ubuntu-bashrc.expected"
assert 'installer places loader before Ubuntu non-interactive guard' env HOME="$UBUNTU_HOME" XDG_CONFIG_HOME="$UBUNTU_HOME/.config" XDG_DATA_HOME="$UBUNTU_HOME/.local/share" PATH="$PATH" bash "$ROOT/install.sh" --port 28443 --bashrc "$UBUNTU_HOME/.bashrc"
assert 'Ubuntu non-interactive source reaches Codex hook' env CODEX_REMOTE_PAYLOAD=compat-probe HOME="$UBUNTU_HOME" XDG_CONFIG_HOME="$UBUNTU_HOME/.config" XDG_DATA_HOME="$UBUNTU_HOME/.local/share" PATH="$PATH" bash -c 'source "$1"; [[ $(proxy_status) == "shell=proxied service=up endpoint=127.0.0.1:28443" ]]' _ "$UBUNTU_HOME/.bashrc"
assert 'Ubuntu startup content is byte-preserved outside managed loader' bash -c '
  awk '\''$0 == "# >>> mihomo-userctl managed loader >>>" { skip=1; next }
       skip && $0 == "# <<< mihomo-userctl managed loader <<<" { skip=0; next }
       !skip { print }'\'' "$1/.bashrc" > "$2/ubuntu-bashrc.recovered"
  cmp -s "$2/ubuntu-bashrc.expected" "$2/ubuntu-bashrc.recovered"
' _ "$UBUNTU_HOME" "$TEST_ROOT"
assert 'Ubuntu loader placement remains idempotent' env HOME="$UBUNTU_HOME" XDG_CONFIG_HOME="$UBUNTU_HOME/.config" XDG_DATA_HOME="$UBUNTU_HOME/.local/share" PATH="$PATH" bash "$ROOT/install.sh" --port 28443 --bashrc "$UBUNTU_HOME/.bashrc"
assert 'Ubuntu loader remains unique and before guard' bash -c '
  loader=$(grep -Fnm1 "# >>> mihomo-userctl managed loader >>>" "$1" | cut -d: -f1)
  guard=$(grep -Enm1 "^[[:space:]]*case[[:space:]]+\\\$-[[:space:]]+in" "$1" | cut -d: -f1)
  [[ $(grep -Fxc "# >>> mihomo-userctl managed loader >>>" "$1") == 1 && $loader -lt $guard ]]
' _ "$UBUNTU_HOME/.bashrc"

LEGACY_HOME=$TEST_ROOT/legacy-loader-home
mkdir -p "$LEGACY_HOME/.config/mihomo"
chmod 700 "$LEGACY_HOME/.config/mihomo"
cp "$XDG_CONFIG_HOME/mihomo/client.env" "$LEGACY_HOME/.config/mihomo/client.env"
chmod 600 "$LEGACY_HOME/.config/mihomo/client.env"
cp "$TEST_ROOT/ubuntu-bashrc.expected" "$LEGACY_HOME/.bashrc"
printf '\n' >> "$LEGACY_HOME/.bashrc"
awk '{ print }' "$ROOT/examples/bashrc-loader.bash" >> "$LEGACY_HOME/.bashrc"
assert 'upgrade relocates a legacy loader from below Ubuntu guard' env HOME="$LEGACY_HOME" XDG_CONFIG_HOME="$LEGACY_HOME/.config" XDG_DATA_HOME="$LEGACY_HOME/.local/share" PATH="$PATH" bash "$ROOT/install.sh" --port 28443 --bashrc "$LEGACY_HOME/.bashrc"
assert 'relocated legacy loader runs in a non-interactive Codex shell' env CODEX_REMOTE_PAYLOAD=compat-probe HOME="$LEGACY_HOME" XDG_CONFIG_HOME="$LEGACY_HOME/.config" XDG_DATA_HOME="$LEGACY_HOME/.local/share" PATH="$PATH" bash -c 'source "$1"; [[ $(proxy_status) == "shell=proxied service=up endpoint=127.0.0.1:28443" ]]' _ "$LEGACY_HOME/.bashrc"

assert 'uninstaller removes owned code but preserves credentials and config' env HOME="$INSTALL_HOME" XDG_CONFIG_HOME="$INSTALL_HOME/.config" XDG_DATA_HOME="$INSTALL_HOME/.local/share" PATH="$PATH" bash "$ROOT/uninstall.sh" --bashrc "$INSTALL_HOME/.bashrc"
assert 'configuration survived uninstall' bash -c '[[ -f "$1/.config/mihomo/client.env" && -f "$1/.config/mihomo/mihomo-shell.conf" && ! -e "$1/.local/bin/mihomoctl" ]]' _ "$INSTALL_HOME"

# A failed post-install doctor must restore every active file and prior directory mode.
ROLLBACK_HOME=$TEST_ROOT/rollback-home
mkdir -p "$ROLLBACK_HOME/.local/bin" "$ROLLBACK_HOME/.local/share/mihomo-userctl" "$ROLLBACK_HOME/.config/mihomo"
chmod 755 "$ROLLBACK_HOME/.local/bin" "$ROLLBACK_HOME/.local/share/mihomo-userctl" "$ROLLBACK_HOME/.config/mihomo"
printf 'old-controller\n' > "$ROLLBACK_HOME/.local/bin/mihomoctl"
printf 'old-common\n' > "$ROLLBACK_HOME/.local/share/mihomo-userctl/common.bash"
printf 'old-shell\n' > "$ROLLBACK_HOME/.local/share/mihomo-userctl/shell.bash"
printf 'old-completion\n' > "$ROLLBACK_HOME/.local/share/mihomo-userctl/completion.bash"
cat > "$ROLLBACK_HOME/.config/mihomo/mihomo-shell.conf" <<'EOF'
MIHOMO_SERVICE=mihomo
MIHOMO_PORT=28443
MIHOMO_READY_URL=https://example.com/
MIHOMO_READY_TIMEOUT=2
MIHOMO_STOP_TIMEOUT=1
EOF
cp "$XDG_CONFIG_HOME/mihomo/client.env" "$ROLLBACK_HOME/.config/mihomo/client.env"
chmod 600 "$ROLLBACK_HOME/.config/mihomo/mihomo-shell.conf" "$ROLLBACK_HOME/.config/mihomo/client.env"
printf 'rollback-before=yes\n' > "$ROLLBACK_HOME/.bashrc"
cp -p "$ROLLBACK_HOME/.bashrc" "$TEST_ROOT/rollback-bashrc.expected"
cp -p "$ROLLBACK_HOME/.local/bin/mihomoctl" "$TEST_ROOT/rollback-mihomoctl.expected"
cp -p "$ROLLBACK_HOME/.local/share/mihomo-userctl/common.bash" "$TEST_ROOT/rollback-common.expected"
cp -p "$ROLLBACK_HOME/.local/share/mihomo-userctl/shell.bash" "$TEST_ROOT/rollback-shell.expected"
cp -p "$ROLLBACK_HOME/.local/share/mihomo-userctl/completion.bash" "$TEST_ROOT/rollback-completion.expected"
cp -p "$ROLLBACK_HOME/.config/mihomo/mihomo-shell.conf" "$TEST_ROOT/rollback-config.expected"
assert 'failed doctor triggers transactional installer rollback' bash -c '
  set +e
  CURL_FAIL=1 HOME="$1" XDG_CONFIG_HOME="$1/.config" XDG_DATA_HOME="$1/.local/share" PATH="$2" \
    bash "$3" --port 28443 --bashrc "$1/.bashrc" >/dev/null 2>&1
  [[ $? == 2 ]]
' _ "$ROLLBACK_HOME" "$PATH" "$ROOT/install.sh"
assert 'transactional rollback restores all active files and directory modes' bash -c '
  cmp -s "$1/.bashrc" "$2/rollback-bashrc.expected" &&
  cmp -s "$1/.local/bin/mihomoctl" "$2/rollback-mihomoctl.expected" &&
  cmp -s "$1/.local/share/mihomo-userctl/common.bash" "$2/rollback-common.expected" &&
  cmp -s "$1/.local/share/mihomo-userctl/shell.bash" "$2/rollback-shell.expected" &&
  cmp -s "$1/.local/share/mihomo-userctl/completion.bash" "$2/rollback-completion.expected" &&
  cmp -s "$1/.config/mihomo/mihomo-shell.conf" "$2/rollback-config.expected" &&
  [[ $(stat -c %a "$1/.local/share/mihomo-userctl") == 755 ]] &&
  [[ $(stat -c %a "$1/.config/mihomo") == 755 ]] &&
  backup=$(find "$1/.local/share/mihomo-userctl-backups" -mindepth 1 -maxdepth 1 -type d -print -quit) &&
  [[ -n $backup && $(stat -c %a "$backup") == 700 && $(stat -c %a "$backup/manifest.tsv") == 600 ]]
' _ "$ROLLBACK_HOME" "$TEST_ROOT"

# A failed first install must remove newly created project files but keep credentials.
FRESH_FAIL_HOME=$TEST_ROOT/fresh-fail-home
mkdir -p "$FRESH_FAIL_HOME/.config/mihomo"
chmod 700 "$FRESH_FAIL_HOME/.config/mihomo"
cp "$XDG_CONFIG_HOME/mihomo/client.env" "$FRESH_FAIL_HOME/.config/mihomo/client.env"
chmod 600 "$FRESH_FAIL_HOME/.config/mihomo/client.env"
printf 'fresh-before=yes\n' > "$FRESH_FAIL_HOME/.bashrc"
assert 'failed first install removes newly created active files' bash -c '
  set +e
  CURL_FAIL=1 HOME="$1" XDG_CONFIG_HOME="$1/.config" XDG_DATA_HOME="$1/.local/share" PATH="$2" \
    bash "$3" --port 28443 --bashrc "$1/.bashrc" >/dev/null 2>&1
  rc=$?
  [[ $rc == 2 && $(<"$1/.bashrc") == fresh-before=yes &&
     -f "$1/.config/mihomo/client.env" &&
     ! -e "$1/.config/mihomo/mihomo-shell.conf" &&
     ! -e "$1/.local/bin/mihomoctl" &&
     ! -e "$1/.local/share/mihomo-userctl/common.bash" ]]
' _ "$FRESH_FAIL_HOME" "$PATH" "$ROOT/install.sh"


# Failure-path evidence is isolated: these stubs cannot stop a live user service.
assert 'with_proxy readiness failure never executes the child or changes its parent' bash -c '
  source "$XDG_DATA_HOME/mihomo-userctl/shell.bash"
  rc=0
  CURL_FAIL=1 with_proxy printf "unexpected-child-command" > "$1/failed-child" 2>/dev/null || rc=$?
  [[ $rc == 1 && ! -s "$1/failed-child" && -z ${https_proxy+x} ]]
' _ "$TEST_ROOT"

assert 'ready-service hook fails closed when the authenticated request fails' bash -c '
  rc=0
  out=$(CURL_FAIL=1 CODEX_REMOTE_PAYLOAD=compat-probe bash -c '\''source "$XDG_DATA_HOME/mihomo-userctl/shell.bash"; printf "unexpected-child-command"'\'' 2>/dev/null) || rc=$?
  [[ $rc == 1 && -z $out && $(<"$1/service-state") == active ]]
' _ "$TEST_ROOT"

printf 'inactive\n' > "$TEST_ROOT/service-state"
assert 'down-service hook exits without executing commands or starting the service' bash -c '
  rc=0
  out=$(CODEX_REMOTE_PAYLOAD=compat-probe bash -c '\''source "$XDG_DATA_HOME/mihomo-userctl/shell.bash"; printf "unexpected-child-command"'\'' 2>/dev/null) || rc=$?
  [[ $rc == 1 && -z $out && $(<"$1/service-state") == inactive ]]
' _ "$TEST_ROOT"
printf 'active\n' > "$TEST_ROOT/service-state"

# Refuse a symbolic-link startup file instead of rewriting an unexpected target.
LINK_HOME=$TEST_ROOT/link-home
mkdir -p "$LINK_HOME"
printf 'link-target-unchanged=yes\n' > "$LINK_HOME/real-bashrc"
ln -s "$LINK_HOME/real-bashrc" "$LINK_HOME/.bashrc"
assert 'installer refuses a symbolic-link bashrc' bash -c 'set +e; HOME="$1" XDG_CONFIG_HOME="$1/.config" XDG_DATA_HOME="$1/.local/share" PATH="$2" bash "$3" --dry-run --port 28443 --bashrc "$1/.bashrc" >/dev/null 2>&1; [[ $? == 2 ]]' _ "$LINK_HOME" "$PATH" "$ROOT/install.sh"
assert 'uninstaller refuses a symbolic-link bashrc without changing its target' bash -c 'set +e; HOME="$1" XDG_CONFIG_HOME="$1/.config" XDG_DATA_HOME="$1/.local/share" PATH="$2" bash "$3" --bashrc "$1/.bashrc" >/dev/null 2>&1; [[ $? == 2 && $(<"$1/real-bashrc") == link-target-unchanged=yes ]]' _ "$LINK_HOME" "$PATH" "$ROOT/uninstall.sh"

printf '1..%d\n' "$((PASS + FAIL))"
printf '# pass=%d fail=%d\n' "$PASS" "$FAIL"
(( FAIL == 0 ))
