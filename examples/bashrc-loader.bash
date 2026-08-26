# >>> mihomo-userctl managed loader >>>
unset http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
_muc_shell="${XDG_DATA_HOME:-$HOME/.local/share}/mihomo-userctl/shell.bash"
_muc_shell_dir=${_muc_shell%/*}
_muc_shell_mode=$(stat -c '%a' -- "$_muc_shell" 2>/dev/null || true)
_muc_dir_mode=$(stat -c '%a' -- "$_muc_shell_dir" 2>/dev/null || true)
if [[ -r $_muc_shell && -O $_muc_shell && -O $_muc_shell_dir &&
      $_muc_shell_mode =~ ^[0-7]{3,4}$ && $_muc_dir_mode =~ ^[0-7]{3,4}$ ]] &&
   (( (8#$_muc_shell_mode & 022) == 0 )) && (( (8#$_muc_dir_mode & 022) == 0 )); then
  # shellcheck source=/dev/null
  source "$_muc_shell"
else
  printf 'mihomo-userctl: unsafe or missing Shell module; staying direct\n' >&2
  [[ -z ${CODEX_REMOTE_PAYLOAD:-} ]] || { return 1 2>/dev/null || exit 1; }
fi
unset _muc_shell _muc_shell_dir _muc_shell_mode _muc_dir_mode
# <<< mihomo-userctl managed loader <<<
