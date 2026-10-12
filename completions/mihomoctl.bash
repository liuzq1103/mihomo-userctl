#!/usr/bin/env bash
# Scope flags precede the command. Bindings are names from manager.yaml.
_mihomoctl_complete() {
  local current=${COMP_WORDS[COMP_CWORD]} previous=${COMP_WORDS[COMP_CWORD-1]}
  local command_index=1 index command action words=''
  local commands='init start stop restart status logs config profile env exec direct integration service tun core health doctor migrate rollback update controller nodes groups select latency connections traffic subscription tui version help rules'
  local globals='--user --system --json --help'
  COMPREPLY=()
  for ((index=1; index<COMP_CWORD; index++)); do
    [[ ${COMP_WORDS[index]} == -- ]] && return
  done
  while [[ ${COMP_WORDS[command_index]} == --user || ${COMP_WORDS[command_index]} == --system || ${COMP_WORDS[command_index]} == --json ]]; do
    ((command_index++))
  done
  if ((COMP_CWORD == command_index)); then
    mapfile -t COMPREPLY < <(compgen -W "$commands $globals" -- "$current")
    return
  fi
  command=${COMP_WORDS[command_index]}
  action=${COMP_WORDS[command_index+1]}
  case "$previous" in
    --core|--config|--file|--output|--output-dir|--path|--wheelhouse|--python) mapfile -t COMPREPLY < <(compgen -f -- "$current"); return ;;
    --profile|--binding|--version|--sha256|--port|--allow-non-loopback|--egress-url|--lines) return ;;
  esac
  case "$command" in
    init) words='--core --config --port --allow-non-loopback --json --help' ;;
    start|stop|restart|status) words='--json --help' ;;
    logs) words='--lines --follow --json --help' ;;
    config)
      if ((COMP_CWORD == command_index+1)); then words='validate check'; else words='--file --profile --json --help'; fi ;;
    profile)
      if ((COMP_CWORD == command_index+1)); then words='list show validate set-default'; else words='--json --help'; fi ;;
    env)
      if ((COMP_CWORD == command_index+1)); then words='show export'
      elif [[ $action == show ]]; then words='--profile --binding --reveal --json --help'
      else words='--profile --binding --output --reveal --json --help'; fi ;;
    exec) words='--profile --binding --json --help --' ;;
    direct) words='--help --' ;;
    integration)
      if ((COMP_CWORD == command_index+1)); then words='list show check export install remove'
      elif [[ $action == export ]]; then words='--output-dir --reveal --json --help'
      else words='--json --help'; fi ;;
    service)
      if ((COMP_CWORD == command_index+1)); then words='install start stop restart status uninstall'
      elif [[ $action == uninstall ]]; then words='--dry-run --json --help'
      else words='--json --help'; fi ;;
    tun) words='status enable disable --json --help' ;;
    core)
      if ((COMP_CWORD == command_index+1)); then words='install update version'
      else words='--version --sha256 --dry-run --json --help'; fi ;;
    health) words='check --profile --binding --egress-url --json --help' ;;
    doctor) words='--json --help' ;;
    migrate) words='--dry-run --apply --json --remove-loader --no-import --help' ;;
    update) words='--dry-run --allow-same-version --allow-downgrade --wheelhouse --python --json --help' ;;
    rollback) words='--json --help' ;;
    controller) words='initialize setup status token --port --archive --sha256 --json --help' ;;
    subscription) words='preview apply --policy auto nodes provider --source-file --url-file --stdin --sha256 --json --help' ;;
    tui) words='--plain --engine textual plain --theme dark light --ascii --details --stdin --policy auto provider nodes --help' ;;
    rules) words='status check --json --help' ;;
    nodes|groups|connections|traffic|select|latency|version) words='--json --help' ;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$words" -- "$current")
}
complete -F _mihomoctl_complete mihomoctl
